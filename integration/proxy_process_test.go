package integration

import (
	"bufio"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"strings"
	"testing"
	"time"

	"github.com/chatwithgod/reflow/core"
	"github.com/chatwithgod/reflow/proxy"
)

// An explicit binary path makes the same client tests verify a packaged artifact.
func startProxy(t *testing.T, upstream string) string {
	t.Helper()
	bin := os.Getenv("REFLOW_PROXY_BIN")
	if bin == "" {
		handler, err := proxy.New(proxy.Config{Upstream: upstream, Fold: core.DefaultConfig(), EnableMetrics: true})
		if err != nil {
			t.Fatal(err)
		}
		server := httptest.NewServer(handler)
		t.Cleanup(server.Close)
		return server.URL
	}
	ctx, cancel := context.WithCancel(context.Background())
	cmd := exec.CommandContext(ctx, bin, "-listen", "127.0.0.1:0", "-upstream", upstream, "-metrics")
	stderr, err := cmd.StderrPipe()
	if err != nil {
		cancel()
		t.Fatal(err)
	}
	if err := cmd.Start(); err != nil {
		cancel()
		t.Fatal(err)
	}
	t.Cleanup(func() { cancel(); _ = cmd.Wait() })
	address := make(chan string, 1)
	go func() {
		scanner := bufio.NewScanner(stderr)
		for scanner.Scan() {
			line := scanner.Text()
			if _, tail, ok := strings.Cut(line, " listening on "); ok {
				if at, _, ok := strings.Cut(tail, ";"); ok {
					select {
					case address <- "http://" + at:
					default:
					}
				}
			}
		}
	}()
	select {
	case url := <-address:
		return url
	case <-time.After(10 * time.Second):
		t.Fatal("packaged Reflow did not report a listening address")
		return ""
	}
}

func proxyMetrics(t *testing.T, url string) proxy.Metrics {
	t.Helper()
	client := &http.Client{Timeout: 3 * time.Second}
	res, err := client.Get(url + "/metrics")
	if err != nil {
		t.Fatal(err)
	}
	defer res.Body.Close()
	var stats proxy.Metrics
	if json.NewDecoder(res.Body).Decode(&stats) != nil || !stats.Enabled {
		t.Fatal("packaged proxy did not expose enabled metrics")
	}
	return stats
}
