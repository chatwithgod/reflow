//go:build ignore

// A process fixture for the evaluation runner, not a model or quality result.
package main

import (
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"time"
)

func main() {
	home := os.Getenv("CODEX_HOME")
	if !strings.Contains(home, "trial-") {
		os.Exit(2)
	}
	auth, err := os.ReadFile(filepath.Join(home, "auth.json"))
	if err != nil || !strings.Contains(string(auth), "synthetic-evaluation-token") {
		os.Exit(2)
	}
	var work, endpoint string
	for i, arg := range os.Args[1:] {
		if arg == "-C" {
			work = os.Args[i+2]
		}
		if strings.HasPrefix(arg, "openai_base_url=") {
			endpoint = strings.Trim(strings.TrimPrefix(arg, "openai_base_url="), "\"")
		}
	}
	u, err := url.Parse(endpoint)
	if err != nil || u.Scheme != "http" || net.ParseIP(u.Hostname()) == nil || !net.ParseIP(u.Hostname()).IsLoopback() {
		os.Exit(2)
	}
	client := &http.Client{Timeout: 2 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	res, err := client.Get(endpoint + "/healthz")
	if err != nil {
		os.Exit(2)
	}
	var health struct {
		Service     string
		MaxContinue int `json:"max_continue"`
	}
	err = json.NewDecoder(res.Body).Decode(&health)
	res.Body.Close()
	if err != nil || health.Service != "reflow" {
		os.Exit(2)
	}
	prompt := os.Args[len(os.Args)-1]
	if strings.Contains(prompt, "SYNTHETIC_AGENT_TIMEOUT") {
		time.Sleep(10 * time.Second)
	}
	if strings.Contains(prompt, "SYNTHETIC_AGENT_FAILURE") {
		fmt.Println(`{"type":"turn.failed","error":{"message":"SYNTHETIC_PRIVATE_SENTINEL"}}`)
		os.Exit(1)
	}
	if strings.Contains(prompt, "SYNTHETIC_AGENT_RATE_LIMIT") {
		fmt.Println(`{"type":"error","message":"429 rate_limit SYNTHETIC_PRIVATE_SENTINEL"}`)
		time.Sleep(10 * time.Second)
		os.Exit(1)
	}
	task := ""
	for id, name := range map[string]string{"intervals": "merge_intervals", "topo": "topological_order", "ndjson": "parse_chunks", "lru": "LRUCache"} {
		if strings.Contains(prompt, name) {
			task = id
		}
	}
	exe, _ := os.Executable()
	raw, err := os.ReadFile(filepath.Join(filepath.Dir(exe), "oracles.json"))
	if err != nil {
		os.Exit(2)
	}
	var oracles map[string]string
	if json.Unmarshal(raw, &oracles) != nil || oracles[task] == "" {
		os.Exit(2)
	}
	if err := os.WriteFile(filepath.Join(work, "solution.py"), []byte(oracles[task]), 0600); err != nil {
		os.Exit(2)
	}
	fmt.Println(`{"type":"item.completed","item":{"type":"agent_message","text":"SYNTHETIC_PRIVATE_SENTINEL"}}`)
	fmt.Printf("{\"type\":\"turn.completed\",\"usage\":{\"input_tokens\":10,\"cached_input_tokens\":2,\"output_tokens\":%d,\"reasoning_output_tokens\":1}}\n", 5+health.MaxContinue)
}
