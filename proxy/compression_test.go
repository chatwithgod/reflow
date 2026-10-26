package proxy

import (
	"bytes"
	"compress/gzip"
	"context"
	"encoding/json"
	"net/http"
	"sync/atomic"
	"testing"

	"github.com/chatwithgod/reflow/core"
	"github.com/chatwithgod/reflow/internal/testfixture"
	"github.com/klauspost/compress/zstd"
)

func TestCompressedNativeRequestsStillFold(t *testing.T) {
	for _, encoding := range []string{"gzip", "zstd"} {
		t.Run(encoding, func(t *testing.T) {
			var calls atomic.Int32
			url, _ := harness(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if r.Header.Get("Content-Encoding") != "" {
					t.Error("rewritten request still marked compressed")
				}
				var body core.Object
				if json.NewDecoder(r.Body).Decode(&body) != nil {
					t.Error("invalid upstream JSON")
					return
				}
				n := calls.Add(1)
				tokens := 20
				if n == 1 {
					tokens = 516
				}
				testfixture.WriteSSE(w, testfixture.Round("r", tokens, false))
			}))
			raw := []byte(`{"model":"gpt-6.1-sol","stream":true,"input":[]}`)
			var compressed []byte
			if encoding == "gzip" {
				var b bytes.Buffer
				writer := gzip.NewWriter(&b)
				writer.Write(raw)
				writer.Close()
				compressed = b.Bytes()
			} else {
				writer, err := zstd.NewWriter(nil, zstd.WithEncoderConcurrency(1))
				if err != nil {
					t.Fatal(err)
				}
				compressed = writer.EncodeAll(raw, nil)
				writer.Close()
			}
			req, _ := http.NewRequestWithContext(context.Background(), "POST", url+"/responses", bytes.NewReader(compressed))
			req.Header.Set("Content-Encoding", encoding)
			req.Header.Set("Authorization", "Bearer synthetic-only")
			resp, err := http.DefaultClient.Do(req)
			if err != nil {
				t.Fatal(err)
			}
			out := drain(t, resp)
			if calls.Load() != 2 || out[len(out)-1]["type"] != "response.completed" {
				t.Fatal("compressed request bypassed Reflow")
			}
		})
	}
}
