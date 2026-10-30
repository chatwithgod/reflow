//go:build reflow_external_probe

package gateway

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/coder/websocket"
	"github.com/yetone/magpie/internal/proc"
	"github.com/yetone/magpie/internal/provider"
)

var externalReflowBinary = flag.String("reflow-probe-bin", "", "absolute path to the standalone Reflow fixture binary")
var externalDropPin = flag.Bool("reflow-probe-drop-pin", false, "break the account pin on the hidden request as a negative control")
var externalStandardProfile = flag.Bool("reflow-probe-standard-profile", false, "use the standard upstream profile as a compatibility control")

type externalObject = map[string]any

// These are synthetic Responses records, using the same shape as Reflow's
// internal/testfixture. No real model, encrypted reasoning or credential is used.
func externalRound(id string, reasoning int, tool bool) []externalObject {
	reason := externalObject{"type": "reasoning", "id": "rs_" + id, "summary": []any{}, "encrypted_content": "synthetic-" + id}
	item := externalObject{"type": "message", "id": "msg_" + id, "role": "assistant", "status": "completed", "phase": "final_answer", "content": []any{externalObject{"type": "output_text", "text": "synthetic answer"}}}
	if tool {
		item = externalObject{"type": "function_call", "id": "fc_" + id, "call_id": "call_" + id, "name": "inspect", "arguments": "{}", "status": "completed"}
	}
	return []externalObject{
		{"type": "response.created", "response": externalObject{"id": "resp_" + id, "status": "in_progress", "output": []any{}}},
		{"type": "response.output_item.added", "output_index": 0, "item": externalObject{"type": "reasoning", "id": "rs_" + id, "summary": []any{}}},
		{"type": "response.output_item.done", "output_index": 0, "item": reason},
		{"type": "response.output_item.added", "output_index": 1, "item": item},
		{"type": "response.output_item.done", "output_index": 1, "item": item},
		{"type": "response.completed", "response": externalObject{"id": "resp_" + id, "status": "completed", "output": []any{reason, item}, "usage": externalObject{"input_tokens": 100, "output_tokens": reasoning + 10, "total_tokens": reasoning + 110, "output_tokens_details": externalObject{"reasoning_tokens": reasoning}}}},
	}
}

func externalSSE(w http.ResponseWriter, events []externalObject) {
	w.Header().Set("Content-Type", "text/event-stream")
	for _, event := range events {
		raw, _ := json.Marshal(event)
		fmt.Fprintf(w, "data: %s\n\n", raw)
		http.NewResponseController(w).Flush()
	}
}

func externalProcess(t *testing.T, upstream string) string {
	t.Helper()
	if !filepath.IsAbs(*externalReflowBinary) {
		t.Fatal("reflow_binary_must_be_absolute")
	}
	if info, err := os.Stat(*externalReflowBinary); err != nil || !info.Mode().IsRegular() {
		t.Fatal("reflow_binary_missing")
	}
	profile := "magpie"
	if *externalStandardProfile {
		profile = "standard"
	}
	command := proc.Command(*externalReflowBinary, "--listen", "127.0.0.1:0", "--upstream", upstream, "--upstream-profile", profile, "--max-continue", "1", "--metrics")
	command.Stdout = io.Discard
	stderr, err := command.StderrPipe()
	if err != nil {
		t.Fatal("reflow_stderr_pipe_failed")
	}
	tree, err := proc.StartTree(command)
	if err != nil {
		t.Fatal("reflow_start_failed")
	}
	done, scanned := make(chan struct{}), make(chan struct{})
	var raceDetected atomic.Bool
	ready := make(chan string, 1)
	go func() { _ = tree.Wait(); close(done) }()
	go func() {
		defer close(scanned)
		scanner := bufio.NewScanner(stderr)
		address := regexp.MustCompile(`listening on (127\.0\.0\.1:[0-9]+);`)
		for scanner.Scan() {
			if strings.Contains(scanner.Text(), "WARNING: DATA RACE") {
				raceDetected.Store(true)
			}
			if match := address.FindStringSubmatch(scanner.Text()); len(match) == 2 {
				select {
				case ready <- "http://" + match[1]:
				default:
				}
			}
		}
	}()
	t.Cleanup(func() {
		<-tree.Stop(time.Second)
		select {
		case <-done:
		case <-time.After(5 * time.Second):
			t.Error("reflow_process_did_not_exit")
		}
		select {
		case <-scanned:
		case <-time.After(5 * time.Second):
			t.Error("reflow_stderr_reader_did_not_exit")
		}
		if raceDetected.Load() {
			t.Error("reflow_child_data_race")
		}
	})
	select {
	case url := <-ready:
		return url
	case <-done:
		t.Fatal("reflow_exited_before_ready")
	case <-time.After(10 * time.Second):
		t.Fatal("reflow_ready_timeout")
	}
	return ""
}

type externalProbe struct {
	t                        *testing.T
	url, model, pin          string
	mu                       sync.Mutex
	requests                 []externalObject
	accounts, auths          []string
	frontRequests, sideCalls int
	started, canceled        chan struct{}
	socket                   *websocket.Conn
}

func externalSetup(t *testing.T, managed, socket, cancelHidden, refuseHidden bool) *externalProbe {
	t.Helper()
	codexSignedIn(t, "spare@example.com")
	for _, who := range []string{"me@example.com", "spare@example.com"} {
		if err := provider.SetCodexAutoReset(who, false); err != nil {
			t.Fatal("synthetic_reset_configuration_failed")
		}
	}
	if err := provider.SetRouting("codex", provider.Ordered); err != nil {
		t.Fatal("synthetic_routing_configuration_failed")
	}
	wasSocket := codexSocketOff.Swap(true)
	t.Cleanup(func() { codexSocketOff.Store(wasSocket) })
	p := &externalProbe{t: t, model: "gpt-5.5", pin: "spare@example.com", started: make(chan struct{}), canceled: make(chan struct{})}
	up := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/backend-api/codex/responses" {
			p.mu.Lock()
			p.sideCalls++
			p.mu.Unlock()
			http.Error(w, "synthetic_unexpected_route", http.StatusNotFound)
			return
		}
		reader, err := decodedBody(r)
		if err != nil {
			t.Error("upstream_body_decode_failed")
			return
		}
		defer reader.Close()
		var body externalObject
		if json.NewDecoder(reader).Decode(&body) != nil {
			t.Error("upstream_json_decode_failed")
			return
		}
		p.mu.Lock()
		p.requests = append(p.requests, body)
		p.accounts = append(p.accounts, r.Header.Get("Chatgpt-Account-Id"))
		p.auths = append(p.auths, r.Header.Get("Authorization"))
		n := len(p.requests)
		p.mu.Unlock()
		if r.Header.Get("Chatgpt-Account-Id") != "acct-2" {
			t.Error("upstream_account_changed")
		}
		if body["model"] != "gpt-5.5" {
			t.Error("upstream_model_changed")
		}
		if r.Header.Get(AccountHeader) != "" {
			t.Error("account_selector_reached_vendor")
		}
		if cancelHidden && n == 2 {
			externalSSE(w, externalRound("chosen", 20, true)[:2])
			close(p.started)
			<-r.Context().Done()
			close(p.canceled)
			return
		}
		switch n {
		case 1:
			externalSSE(w, externalRound("discarded", 516, true))
		case 2:
			externalSSE(w, externalRound("chosen", 20, true))
		case 3:
			externalSSE(w, externalRound("final", 20, false))
		default:
			t.Error("unexpected_upstream_request")
			http.Error(w, "synthetic_request_limit", 500)
		}
	}))
	t.Cleanup(up.Close)
	was := provider.CodexBase
	provider.CodexBase = up.URL + "/backend-api/codex"
	t.Cleanup(func() { provider.CodexBase = was })
	s := New()
	front := s.Front()
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		p.mu.Lock()
		p.frontRequests++
		n := p.frontRequests
		p.mu.Unlock()
		if n == 2 && (refuseHidden || *externalDropPin) {
			restingUntil.Lock()
			restingUntil.m["codex@spare@example.com"] = time.Now().Add(time.Hour)
			restingUntil.note["codex@spare@example.com"] = Rest{Why: failQuota}
			restingUntil.Unlock()
			if *externalDropPin {
				r.Header.Del(AccountHeader)
			}
		}
		front.ServeHTTP(w, r)
	}))
	t.Cleanup(server.Close)
	t.Cleanup(func() {
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		s.sockets.drain(ctx)
	})
	base := server.URL + CodexPath
	if managed {
		base, p.model = server.URL+"/v1", "codex/gpt-5.5"
	}
	p.url = externalProcess(t, base)
	if socket {
		ctx, cancel := context.WithTimeout(t.Context(), 10*time.Second)
		defer cancel()
		connection, _, err := websocket.Dial(ctx, "ws"+strings.TrimPrefix(p.url, "http")+"/responses", &websocket.DialOptions{HTTPHeader: p.headers()})
		if err != nil {
			t.Fatal("external_socket_dial_failed")
		}
		p.socket = connection
		p.socket.SetReadLimit(4 << 20)
		t.Cleanup(func() { p.socket.CloseNow() })
	}
	return p
}

func (p *externalProbe) headers() http.Header {
	return http.Header{"Authorization": {"Bearer synthetic-client"}, "Chatgpt-Account-Id": {"client-account"},
		AccountHeader: {p.pin}, "Session_id": {"external-synthetic-session"}, "Content-Type": {"application/json"}}
}

func (p *externalProbe) body(parent string) externalObject {
	body := externalObject{"model": p.model, "stream": true, "store": false, "input": []any{externalObject{"role": "user", "content": "external-fixture-task"}}}
	if parent != "" {
		body["previous_response_id"] = parent
		body["input"] = []any{externalObject{"type": "function_call_output", "call_id": "call_chosen", "output": "synthetic-tool-result"}}
	}
	return body
}

func externalTerminal(event externalObject) bool {
	return event["type"] == "response.completed" || event["type"] == "response.incomplete" || event["type"] == "response.failed" || event["type"] == "error"
}

func (p *externalProbe) socketSend(body externalObject) {
	p.t.Helper()
	ctx, cancel := context.WithTimeout(p.t.Context(), 10*time.Second)
	defer cancel()
	raw, _ := json.Marshal(body)
	if p.socket.Write(ctx, websocket.MessageText, raw) != nil {
		p.t.Fatal("external_socket_write_failed")
	}
}

func (p *externalProbe) socketRead() []externalObject {
	return p.socketReadUntil(externalTerminal)
}

func (p *externalProbe) socketReadUntil(stop func(externalObject) bool) []externalObject {
	p.t.Helper()
	ctx, cancel := context.WithTimeout(p.t.Context(), 10*time.Second)
	defer cancel()
	var events []externalObject
	for {
		_, raw, err := p.socket.Read(ctx)
		if err != nil {
			p.t.Fatal("external_socket_read_failed")
		}
		var event externalObject
		if json.Unmarshal(raw, &event) != nil {
			p.t.Fatal("external_socket_json_failed")
		}
		events = append(events, event)
		if stop(event) || externalTerminal(event) {
			return events
		}
	}
}

func (p *externalProbe) ask(ctx context.Context, body externalObject) (int, []externalObject) {
	p.t.Helper()
	if p.socket != nil {
		body["type"] = "response.create"
		p.socketSend(body)
		return 200, p.socketRead()
	}
	raw, _ := json.Marshal(body)
	req, _ := http.NewRequestWithContext(ctx, http.MethodPost, p.url+"/responses", bytes.NewReader(raw))
	req.Header = p.headers()
	response, err := http.DefaultClient.Do(req)
	if err != nil {
		return 0, nil
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		var failure externalObject
		_ = json.NewDecoder(response.Body).Decode(&failure)
		encoded, _ := json.Marshal(failure)
		p.t.Logf("REFLOW_EXTERNAL_HTTP_ERROR status=%d missing_parent=%t", response.StatusCode, strings.Contains(string(encoded), "previous_response_not_found"))
		return response.StatusCode, nil
	}
	var events []externalObject
	scanner := bufio.NewScanner(response.Body)
	scanner.Buffer(make([]byte, 4096), 4<<20)
	for scanner.Scan() {
		line := strings.TrimSpace(strings.TrimPrefix(scanner.Text(), "data:"))
		if !strings.HasPrefix(line, "{") {
			continue
		}
		var event externalObject
		if json.Unmarshal([]byte(line), &event) == nil {
			events = append(events, event)
		}
	}
	return response.StatusCode, events
}

func (p *externalProbe) metrics() map[string]int64 {
	p.t.Helper()
	response, err := http.Get(p.url + "/metrics")
	if err != nil {
		p.t.Fatal("reflow_metrics_failed")
	}
	defer response.Body.Close()
	var raw map[string]json.RawMessage
	if json.NewDecoder(response.Body).Decode(&raw) != nil {
		p.t.Fatal("reflow_metrics_json_failed")
	}
	values := map[string]int64{}
	for _, key := range []string{"requests", "continuations", "continued_tool_calls", "continued_tool_results", "warmups"} {
		var v int64
		json.Unmarshal(raw[key], &v)
		values[key] = v
	}
	return values
}

func (p *externalProbe) complete(events []externalObject) externalObject {
	p.t.Helper()
	if len(events) == 0 || events[len(events)-1]["type"] != "response.completed" {
		p.mu.Lock()
		backend, front := len(p.requests), p.frontRequests
		p.mu.Unlock()
		encoded, _ := json.Marshal(events)
		p.t.Fatalf("external_turn_not_completed events=%d backend=%d gateway=%d missing_parent=%t incomplete=%t error=%t", len(events), backend, front,
			strings.Contains(string(encoded), "previous_response_not_found"), strings.Contains(string(encoded), "response.incomplete"), strings.Contains(string(encoded), `"error"`))
	}
	response, ok := events[len(events)-1]["response"].(map[string]any)
	if !ok {
		p.t.Fatal("external_terminal_missing_response")
	}
	return response
}

func TestExternalReflowMagpie(t *testing.T) {
	for _, mode := range []string{"native_http", "managed_http", "native_ws"} {
		t.Run(mode, func(t *testing.T) {
			p := externalSetup(t, mode == "managed_http", mode == "native_ws", false, false)
			if p.socket != nil {
				warm := p.body("")
				warm["generate"] = false
				_, events := p.ask(t.Context(), warm)
				p.complete(events)
				p.mu.Lock()
				n := len(p.requests)
				p.mu.Unlock()
				if n != 0 {
					t.Fatal("warmup_reached_model")
				}
			}
			code, events := p.ask(t.Context(), p.body(""))
			if code != 200 {
				t.Fatalf("external_first_status=%d", code)
			}
			response := p.complete(events)
			raw, _ := json.Marshal(events)
			if strings.Contains(string(raw), "call_discarded") {
				t.Fatal("discarded_tool_reached_client")
			}
			calls := 0
			for _, value := range response["output"].([]any) {
				item := value.(map[string]any)
				if item["type"] == "function_call" {
					if item["call_id"] != "call_chosen" || item["name"] != "inspect" {
						t.Fatal("unexpected_visible_tool")
					}
					// Execute the fixture's one local tool before returning its result.
					file := filepath.Join(t.TempDir(), "tool-result")
					if os.WriteFile(file, []byte("synthetic-tool-result"), 0o600) != nil {
						t.Fatal("fixture_tool_failed")
					}
					result, err := os.ReadFile(file)
					if err != nil || string(result) != "synthetic-tool-result" {
						t.Fatal("fixture_tool_result_failed")
					}
					calls++
				}
			}
			if calls != 1 {
				t.Fatalf("visible_tool_executions=%d", calls)
			}
			_, next := p.ask(t.Context(), p.body(response["id"].(string)))
			p.complete(next)
			p.mu.Lock()
			defer p.mu.Unlock()
			if len(p.requests) != 3 || p.sideCalls != 0 {
				t.Fatalf("backend_requests=%d side_calls=%d", len(p.requests), p.sideCalls)
			}
			for i := range p.requests {
				if p.accounts[i] != "acct-2" || p.auths[i] == "" || p.auths[i] != p.auths[0] {
					t.Fatal("continuation_identity_changed")
				}
			}
			var chosen, results, users, discarded int
			for _, value := range p.requests[2]["input"].([]any) {
				item := value.(map[string]any)
				if item["type"] == "function_call" && item["call_id"] == "call_chosen" {
					chosen++
				}
				if item["type"] == "function_call_output" && item["call_id"] == "call_chosen" && item["output"] == "synthetic-tool-result" {
					results++
				}
				if item["role"] == "user" {
					b, _ := json.Marshal(item)
					if strings.Contains(string(b), "external-fixture-task") {
						users++
					}
				}
				if item["call_id"] == "call_discarded" {
					discarded++
				}
			}
			if chosen != 1 || results != 1 || users != 1 || discarded != 0 {
				t.Fatalf("history_calls=%d results=%d users=%d discarded=%d", chosen, results, users, discarded)
			}
			metrics := p.metrics()
			if metrics["requests"] != 3 || metrics["continuations"] != 1 || metrics["continued_tool_calls"] != 1 || metrics["continued_tool_results"] != 1 {
				t.Fatalf("unexpected_numeric_metrics requests=%d continuations=%d calls=%d results=%d", metrics["requests"], metrics["continuations"], metrics["continued_tool_calls"], metrics["continued_tool_results"])
			}
			t.Logf("REFLOW_EXTERNAL_COUNTS requests=3 continuation=1 tool_executions=1 tool_results=1 account_changes=0")
		})
	}

	t.Run("unknown_account", func(t *testing.T) {
		p := externalSetup(t, false, false, false, false)
		p.pin = "nobody@example.com"
		code, _ := p.ask(t.Context(), p.body(""))
		p.mu.Lock()
		defer p.mu.Unlock()
		if code != 404 || len(p.requests) != 0 {
			t.Fatalf("unknown_account_status=%d backend_requests=%d", code, len(p.requests))
		}
	})
	t.Run("account_unavailable_during_continuation", func(t *testing.T) {
		p := externalSetup(t, false, false, false, true)
		_, events := p.ask(t.Context(), p.body(""))
		if len(events) == 0 || events[len(events)-1]["type"] != "response.incomplete" {
			t.Fatal("account_failure_not_stopped")
		}
		raw, _ := json.Marshal(events)
		if strings.Contains(string(raw), "call_discarded") {
			t.Fatal("failed_turn_exposed_discarded_tool")
		}
		p.mu.Lock()
		defer p.mu.Unlock()
		if len(p.requests) != 1 || p.frontRequests != 2 {
			t.Fatalf("refused_pin_backend=%d gateway_requests=%d", len(p.requests), p.frontRequests)
		}
	})
	for _, socket := range []bool{false, true} {
		name := "cancel_http"
		if socket {
			name = "cancel_ws"
		}
		t.Run(name, func(t *testing.T) {
			p := externalSetup(t, false, socket, true, false)
			ctx, cancel := context.WithCancel(t.Context())
			defer cancel()
			done := make(chan []externalObject, 1)
			if socket {
				body := p.body("")
				body["type"] = "response.create"
				p.socketSend(body)
			} else {
				go func() { _, events := p.ask(ctx, p.body("")); done <- events }()
			}
			select {
			case <-p.started:
			case <-time.After(10 * time.Second):
				t.Fatal("hidden_round_did_not_start")
			}
			var events []externalObject
			if socket {
				// Wait until the hidden round's first event crossed Reflow before
				// targeting the original response ID, as a native client would.
				events = p.socketReadUntil(func(event externalObject) bool {
					item, _ := event["item"].(map[string]any)
					return item["id"] == "rs_chosen"
				})
				if externalTerminal(events[len(events)-1]) {
					t.Fatal("hidden_socket_round_ended_before_interrupt")
				}
				p.socketSend(externalObject{"type": "response.interrupt", "response_id": "resp_discarded", "mode": "discard_partial_items"})
				events = append(events, p.socketRead()...)
				if events[len(events)-1]["type"] != "response.incomplete" {
					t.Fatal("socket_cancel_terminal_missing")
				}
				accepted := false
				for _, event := range events {
					if event["type"] == "response.interrupt.accepted" && event["response_id"] == "resp_discarded" {
						accepted = true
					}
				}
				response, _ := events[len(events)-1]["response"].(map[string]any)
				details, _ := response["incomplete_details"].(map[string]any)
				output, _ := response["output"].([]any)
				if !accepted || response["id"] != "resp_discarded" || details["reason"] != "interrupted" || len(output) != 0 {
					t.Fatal("socket_interrupt_contract_failed")
				}
			} else {
				cancel()
				select {
				case events = <-done:
				case <-time.After(5 * time.Second):
					t.Fatal("http_client_cancel_did_not_end")
				}
			}
			select {
			case <-p.canceled:
			case <-time.After(5 * time.Second):
				t.Fatal("hidden_upstream_was_not_canceled")
			}
			raw, _ := json.Marshal(events)
			if strings.Contains(string(raw), "call_discarded") || strings.Contains(string(raw), "call_chosen") {
				t.Fatal("canceled_turn_exposed_tool")
			}
			_, next := p.ask(t.Context(), p.body(""))
			p.complete(next)
			p.mu.Lock()
			defer p.mu.Unlock()
			if len(p.requests) != 3 {
				t.Fatalf("cancel_and_recovery_requests=%d", len(p.requests))
			}
		})
	}
}
