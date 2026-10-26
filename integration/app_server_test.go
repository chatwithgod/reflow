package integration

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/chatwithgod/reflow/core"
	"github.com/chatwithgod/reflow/internal/control"
)

// This exercises Desktop's backend protocol, not the Desktop/dot UI. The two
// app-server processes run serially in one disposable synthetic account home.
func TestCodexAppServerOffline(t *testing.T) {
	if os.Getenv("REFLOW_CODEX_BIN") == "" {
		t.Skip("set REFLOW_CODEX_BIN for isolated native app-server checks")
	}
	for _, paginated := range []bool{false, true} {
		name := "legacy"
		if paginated {
			name = "paginated"
		}
		t.Run(name, func(t *testing.T) {
			verifyNativeLoginOffline(t, nativeLoginMode{codeMode: true, appServer: true, paginated: paginated})
		})
	}
}

type fixtureRPC struct {
	ctx     context.Context
	cancel  context.CancelFunc
	cmd     *exec.Cmd
	input   io.WriteCloser
	packets chan core.Object
	readErr chan error
	readEnd chan struct{}
	done    chan error
	pending []core.Object
	nextID  int
	close   sync.Once
	stopErr error
}

func newFixtureRPC(parent context.Context, template *exec.Cmd) (*fixtureRPC, error) {
	ctx, cancel := context.WithCancel(parent)
	cmd := exec.CommandContext(ctx, template.Path, "app-server", "--listen", "stdio://")
	cmd.Dir, cmd.Env = template.Dir, template.Env
	cmd.Stderr = io.Discard
	cmd.WaitDelay = 3 * time.Second
	input, err := cmd.StdinPipe()
	if err != nil {
		cancel()
		return nil, err
	}
	output, err := cmd.StdoutPipe()
	if err != nil {
		input.Close()
		cancel()
		return nil, err
	}
	if err := cmd.Start(); err != nil {
		input.Close()
		output.Close()
		cancel()
		return nil, err
	}
	rpc := &fixtureRPC{ctx: ctx, cancel: cancel, cmd: cmd, input: input, packets: make(chan core.Object, 256), readErr: make(chan error, 1), readEnd: make(chan struct{}), done: make(chan error, 1)}
	go func() {
		var readFailure error
		defer func() {
			rpc.readErr <- readFailure
			close(rpc.readErr)
			close(rpc.packets)
			close(rpc.readEnd)
		}()
		scanner := bufio.NewScanner(output)
		scanner.Buffer(make([]byte, 4096), 16<<20)
		for scanner.Scan() {
			var packet core.Object
			if json.Unmarshal(scanner.Bytes(), &packet) != nil {
				readFailure = errors.New("app-server emitted invalid JSON")
				return
			}
			select {
			case rpc.packets <- packet:
			case <-ctx.Done():
				readFailure = ctx.Err()
				return
			}
		}
		readFailure = scanner.Err()
	}()
	go func() { rpc.done <- cmd.Wait() }()
	return rpc, nil
}

func (r *fixtureRPC) stop() error {
	r.close.Do(func() {
		_ = r.input.Close()
		select {
		case r.stopErr = <-r.done:
		case <-time.After(3 * time.Second):
			_ = r.cmd.Process.Kill()
			<-r.done
			r.stopErr = errors.New("app-server did not stop after stdin closed")
		}
		r.cancel()
		<-r.readEnd
	})
	return r.stopErr
}

func (r *fixtureRPC) receive() (core.Object, error) {
	select {
	case packet, ok := <-r.packets:
		if !ok {
			if err := <-r.readErr; err != nil {
				return nil, err
			}
			return nil, errors.New("app-server closed its output")
		}
		if packet["method"] != nil && packet["id"] != nil {
			return nil, errors.New("app-server unexpectedly requested client approval or credentials")
		}
		return packet, nil
	case <-r.ctx.Done():
		return nil, r.ctx.Err()
	}
}

func (r *fixtureRPC) request(method string, params core.Object) (core.Object, error) {
	r.nextID++
	if err := json.NewEncoder(r.input).Encode(core.Object{"id": r.nextID, "method": method, "params": params}); err != nil {
		return nil, err
	}
	for {
		packet, err := r.receive()
		if err != nil {
			return nil, fmt.Errorf("%s: %w", method, err)
		}
		if packet["id"] == float64(r.nextID) {
			if failure, ok := packet["error"].(map[string]any); ok {
				return nil, fmt.Errorf("%s failed with RPC code %v", method, failure["code"])
			}
			result, ok := packet["result"].(map[string]any)
			if !ok {
				return nil, fmt.Errorf("%s returned no result object", method)
			}
			return result, nil
		}
		if len(r.pending) >= 256 {
			return nil, errors.New("too many pending app-server notifications")
		}
		r.pending = append(r.pending, packet)
	}
}

func (r *fixtureRPC) initialize(home, work string) error {
	init, err := r.request("initialize", core.Object{"clientInfo": core.Object{"name": "reflow_offline_fixture", "title": "Reflow offline fixture", "version": "0.1.0"}, "capabilities": core.Object{"experimentalApi": true}})
	if err != nil {
		return err
	}
	gotHome, _ := init["codexHome"].(string)
	wantInfo, wantErr := os.Stat(home)
	gotInfo, gotErr := os.Stat(gotHome)
	if wantErr != nil || gotErr != nil || !os.SameFile(wantInfo, gotInfo) {
		return errors.New("app-server selected a different configuration home")
	}
	if err := json.NewEncoder(r.input).Encode(core.Object{"method": "initialized"}); err != nil {
		return err
	}
	account, err := r.request("account/read", core.Object{"refreshToken": false})
	if err != nil {
		return err
	}
	identity, _ := account["account"].(map[string]any)
	if identity["type"] != "chatgpt" || account["requiresOpenaiAuth"] != true {
		return errors.New("app-server did not retain native ChatGPT auth identity")
	}
	config, err := r.request("config/read", core.Object{"cwd": work})
	if err != nil {
		return err
	}
	settings, _ := config["config"].(map[string]any)
	if settings["model_provider"] != "openai" || settings["model"] != "gpt-6.1-sol" {
		return errors.New("app-server did not load the native provider and model from the test profile")
	}
	return nil
}

func (r *fixtureRPC) turn(thread, prompt, marker string) error {
	started, err := r.request("turn/start", core.Object{"threadId": thread, "input": []any{core.Object{"type": "text", "text": prompt}}})
	if err != nil {
		return err
	}
	turn, _ := started["turn"].(map[string]any)
	id, _ := turn["id"].(string)
	if id == "" {
		return errors.New("app-server returned no turn identifier")
	}
	foundMarker := false
	for {
		var packet core.Object
		if len(r.pending) > 0 {
			packet, r.pending = r.pending[0], r.pending[1:]
		} else if packet, err = r.receive(); err != nil {
			return err
		}
		params, _ := packet["params"].(map[string]any)
		if params["threadId"] != thread {
			continue
		}
		if packet["method"] == "item/completed" {
			item, _ := json.Marshal(params["item"])
			foundMarker = foundMarker || strings.Contains(string(item), marker)
		}
		if packet["method"] == "turn/completed" {
			finished, _ := params["turn"].(map[string]any)
			if finished["id"] == id {
				if finished["status"] != "completed" || finished["error"] != nil || !foundMarker {
					return errors.New("app-server did not complete the expected synthetic turn")
				}
				return nil
			}
		}
	}
}

func runAppServerLifecycle(t *testing.T, ctx context.Context, template *exec.Cmd, home, work, endpoint, prompt string, paginated bool) ([]byte, error) {
	t.Helper()
	var settings []string
	for index, value := range template.Args {
		if value == "-c" && index+1 < len(template.Args) && !strings.HasPrefix(template.Args[index+1], "openai_base_url=") {
			settings = append(settings, template.Args[index+1])
		}
	}
	settings = append(settings, `model="gpt-6.1-sol"`, `model_provider="openai"`, `approval_policy="never"`, `sandbox_mode="read-only"`)
	original := []byte(strings.Join(settings, "\n") + "\n")
	configPath := filepath.Join(home, "config.toml")
	if err := os.WriteFile(configPath, original, 0600); err != nil {
		return nil, err
	}
	controller := control.Controller{Home: home, Endpoint: endpoint}
	if _, err := controller.Connect(ctx, endpoint); err != nil {
		return nil, err
	}
	defer func() {
		if _, err := controller.Restore(); err != nil {
			t.Errorf("temporary app-server configuration cleanup failed: %v", err)
		}
	}()
	// Any unconfigured external HTTP(S) destination is rejected locally.
	deny := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "offline fixture denies external destinations", http.StatusForbidden)
	}))
	defer deny.Close()
	template.Env = append(template.Env, "HTTP_PROXY="+deny.URL, "HTTPS_PROXY="+deny.URL, "ALL_PROXY="+deny.URL)
	first, err := newFixtureRPC(ctx, template)
	if err != nil {
		return nil, err
	}
	defer first.stop()
	if err := first.initialize(home, work); err != nil {
		return nil, err
	}
	historyMode := "legacy"
	if paginated {
		historyMode = "paginated"
	}
	started, err := first.request("thread/start", core.Object{"cwd": work, "approvalPolicy": "never", "sandbox": "read-only", "ephemeral": false, "historyMode": historyMode})
	if err != nil {
		return nil, err
	}
	thread, _ := started["thread"].(map[string]any)
	threadID, _ := thread["id"].(string)
	if threadID == "" || started["modelProvider"] != "openai" || thread["historyMode"] != historyMode {
		return nil, errors.New("app-server thread did not retain native provider identity")
	}
	if err := first.turn(threadID, prompt, "REFLOW_NATIVE_OK"); err != nil {
		return nil, err
	}
	if err := first.stop(); err != nil {
		return nil, err
	}
	second, err := newFixtureRPC(ctx, template)
	if err != nil {
		return nil, err
	}
	defer second.stop()
	if err := second.initialize(home, work); err != nil {
		return nil, err
	}
	resumed, err := second.request("thread/resume", core.Object{"threadId": threadID})
	if err != nil {
		return nil, err
	}
	resumedThread, _ := resumed["thread"].(map[string]any)
	if resumed["modelProvider"] != "openai" || resumedThread["historyMode"] != historyMode {
		return nil, errors.New("app-server resume changed provider identity or history mode")
	}
	if err := second.turn(threadID, "Continue this synthetic session without another tool invocation.", "REFLOW_NATIVE_RESUMED"); err != nil {
		return nil, err
	}
	if err := second.stop(); err != nil {
		return nil, err
	}
	changed, err := controller.Restore()
	if err != nil || !changed {
		return nil, errors.New("app-server test configuration did not restore")
	}
	restored, err := os.ReadFile(configPath)
	if err != nil || !bytes.Equal(restored, original) {
		return nil, errors.New("app-server test configuration did not restore exactly")
	}
	t.Log("app-server: native ChatGPT/openai identity, cold process resume, two completed turns and exact configuration restore; synthetic upstream only, UI untested")
	return []byte("REFLOW_NATIVE_OK REFLOW_NATIVE_RESUMED"), nil
}
