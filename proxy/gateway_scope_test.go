package proxy

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"strings"
	"sync"
	"testing"

	"github.com/chatwithgod/reflow/core"
	"github.com/chatwithgod/reflow/internal/testfixture"
)

// A gateway key can select several upstream accounts. Changing that selection
// must not recover another account's cached conversation for a continuation.
func TestGatewayAccountPinSeparatesHTTPReplay(t *testing.T) {
	for _, tc := range []struct {
		name, firstPin, nextPin, nextAuth, nextAccount string
		canReplay                                      bool
	}{
		{name: "same_pin", firstPin: "account-a", nextPin: "account-a", canReplay: true},
		{name: "changed_pin", firstPin: "account-a", nextPin: "account-b"},
		{name: "pin_removed", firstPin: "account-a"},
		{name: "pin_added", nextPin: "account-a"},
		{name: "bearer_changed", firstPin: "account-a", nextPin: "account-a", nextAuth: "Bearer synthetic-other"},
		{name: "native_account_changed", firstPin: "account-a", nextPin: "account-a", nextAccount: "native-other"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			var mu sync.Mutex
			var seen []core.Object
			var pins []string
			url, _ := harness(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				var body core.Object
				if json.NewDecoder(r.Body).Decode(&body) != nil {
					t.Error("invalid synthetic request")
					return
				}
				if r.Header.Get("Session_id") != "synthetic-session" {
					t.Error("continuation lost the client session header")
				}
				mu.Lock()
				seen = append(seen, body)
				pins = append(pins, r.Header.Get("X-Magpie-Account"))
				n := len(seen)
				mu.Unlock()
				switch n {
				case 1:
					testfixture.WriteSSE(w, testfixture.Round("origin", 20, true))
				case 2:
					testfixture.WriteSSE(w, testfixture.Round("candidate", 516, true))
				case 3:
					testfixture.WriteSSE(w, testfixture.Round("final", 20, false))
				default:
					t.Error("unexpected upstream request")
				}
			}))
			ask := func(pin, auth, account string, body core.Object) {
				t.Helper()
				if auth == "" {
					auth = "Bearer synthetic-gateway"
				}
				if account == "" {
					account = "native-account"
				}
				raw, _ := json.Marshal(body)
				req, err := http.NewRequestWithContext(context.Background(), http.MethodPost, url+"/responses", bytes.NewReader(raw))
				if err != nil {
					t.Fatal(err)
				}
				req.Header.Set("Authorization", auth)
				req.Header.Set("ChatGPT-Account-ID", account)
				req.Header.Set("X-Magpie-Account", pin)
				req.Header.Set("Session_id", "synthetic-session")
				req.Header.Set("Content-Type", "application/json")
				response, err := http.DefaultClient.Do(req)
				if err != nil {
					t.Fatal(err)
				}
				if response.StatusCode != http.StatusOK {
					response.Body.Close()
					t.Fatalf("unexpected HTTP status %d", response.StatusCode)
				}
				events := drain(t, response)
				if len(events) == 0 || events[len(events)-1]["type"] != "response.completed" {
					t.Fatal("synthetic response did not complete")
				}
			}
			ask(tc.firstPin, "", "", core.Object{
				"model": "gpt-6.1-sol", "stream": true,
				"input": []any{core.Object{"role": "user", "content": "cached-account-a-input"}},
			})
			ask(tc.nextPin, tc.nextAuth, tc.nextAccount, core.Object{
				"model": "gpt-6.1-sol", "stream": true, "previous_response_id": "origin",
				"input": []any{core.Object{"type": "function_call_output", "call_id": "origin-call", "output": "synthetic tool result"}},
			})
			mu.Lock()
			defer mu.Unlock()
			want := 2
			if tc.canReplay {
				want = 3
			}
			if len(seen) != want {
				var cachedHistory bool
				if len(seen) > 2 {
					replay, _ := json.Marshal(seen[2]["input"])
					cachedHistory = strings.Contains(string(replay), "cached-account-a-input")
				}
				t.Fatalf("upstream requests=%d want=%d cached_history_replayed=%t", len(seen), want, cachedHistory)
			}
			if pins[0] != tc.firstPin || pins[1] != tc.nextPin || (tc.canReplay && pins[2] != tc.nextPin) {
				t.Fatal("account pin was not preserved on upstream requests")
			}
			if tc.canReplay {
				replay, _ := json.Marshal(seen[2]["input"])
				if seen[2]["previous_response_id"] != nil || !strings.Contains(string(replay), "cached-account-a-input") {
					t.Fatal("same-account replay lost its complete conversation")
				}
			}
		})
	}
}
