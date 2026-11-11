package proxy

import (
	"context"
	"encoding/json"
	"net/http"
	"reflect"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/chatwithgod/reflow/core"
	"github.com/chatwithgod/reflow/internal/testfixture"
	"github.com/coder/websocket"
)

// Public synthetic declarations reused from the CPA v0.1.3 regression fixture.
// This checks preservation, not real model acceptance of a synthetic schema.
func schemaDeclarations(body core.Object) []any {
	out := []any{body["tools"]}
	for _, raw := range body["input"].([]any) {
		if item, ok := raw.(map[string]any); ok && item["type"] == "additional_tools" {
			out = append(out, item)
		}
	}
	return out
}

func TestToolSchemasAcrossContinuation(t *testing.T) {
	for _, transport := range []string{"http", "websocket"} {
		for _, placement := range []string{"root", "additional", "both"} {
			t.Run(transport+"/"+placement, func(t *testing.T) {
				var body core.Object
				if err := json.Unmarshal([]byte(toolSchemaFixture), &body); err != nil {
					t.Fatal(err)
				}
				if placement == "additional" {
					delete(body, "tools")
				}
				if placement == "root" {
					body["input"] = body["input"].([]any)[2:]
				}
				want := schemaDeclarations(body)
				var calls atomic.Int32
				check := func(got core.Object) []core.Object {
					n := calls.Add(1)
					if !reflect.DeepEqual(schemaDeclarations(got), want) {
						t.Errorf("declarations changed on upstream request %d", n)
					}
					if n == 1 {
						return testfixture.Round("first", 516, true)
					}
					if n > 2 {
						t.Errorf("unexpected request %d", n)
					}
					return testfixture.Round("last", 20, true)
				}
				url, server := harness(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
					if transport == "http" {
						var got core.Object
						if err := json.NewDecoder(r.Body).Decode(&got); err != nil {
							t.Error(err)
							return
						}
						testfixture.WriteSSE(w, check(got))
						return
					}
					c, err := websocket.Accept(w, r, nil)
					if err != nil {
						t.Error(err)
						return
					}
					defer c.CloseNow()
					ctx, cancel := context.WithTimeout(context.Background(), 8*time.Second)
					defer cancel()
					for {
						_, raw, err := c.Read(ctx)
						if err != nil {
							return
						}
						var got core.Object
						if err := json.Unmarshal(raw, &got); err != nil {
							t.Error(err)
							return
						}
						for _, ev := range check(got) {
							raw, _ := json.Marshal(ev)
							if err := c.Write(ctx, websocket.MessageText, raw); err != nil {
								return
							}
						}
					}
				}))
				server.config.Fold.MaxContinue = 1
				ctx, cancel := context.WithTimeout(context.Background(), 8*time.Second)
				defer cancel()
				var terminal core.Object
				if transport == "http" {
					events := drain(t, request(t, ctx, url+"/responses", body))
					if len(events) == 0 {
						t.Fatal("no events")
					}
					terminal = events[len(events)-1]
				} else {
					c, _, err := websocket.Dial(ctx, "ws"+strings.TrimPrefix(url, "http")+"/responses", &websocket.DialOptions{HTTPHeader: http.Header{"Authorization": []string{"Bearer synthetic-only"}}})
					if err != nil {
						t.Fatal(err)
					}
					defer c.CloseNow()
					body["type"] = "response.create"
					wsSend(t, ctx, c, body)
					for {
						terminal = wsRead(t, ctx, c)
						if terminal["type"] == "response.completed" {
							break
						}
					}
				}
				if terminal["type"] != "response.completed" || calls.Load() != 2 {
					t.Fatalf("completion=%v requests=%d", terminal["type"], calls.Load())
				}
			})
		}
	}
}
