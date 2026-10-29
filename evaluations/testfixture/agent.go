//go:build ignore

// A process fixture for the evaluation runner, not a model or quality result.
package main

import (
	"bufio"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"time"
)

func preflight(home string) {
	if _, err := os.Stat(filepath.Join(home, "auth.json")); !os.IsNotExist(err) {
		os.Exit(3)
	}
	for _, arg := range os.Args[1:] {
		if arg == "--help" {
			return
		}
	}
	profile := filepath.Dir(home)
	work := filepath.Join(profile, "workspace")
	if len(os.Args) > 1 && os.Args[1] == "exec-server" {
		scanner := bufio.NewScanner(os.Stdin)
		for scanner.Scan() {
			var req struct {
				ID     any            `json:"id"`
				Method string         `json:"method"`
				Params map[string]any `json:"params"`
			}
			if json.Unmarshal(scanner.Bytes(), &req) != nil || req.ID == nil {
				continue
			}
			response := map[string]any{"id": req.ID, "result": map[string]any{}}
			if req.Method == "initialize" {
				response["result"] = map[string]any{"sessionId": "synthetic-preflight"}
			} else if req.Method == "fs/writeFile" {
				if strings.Contains(filepath.Base(os.Args[0]), "missing-systemroot") {
					delete(response, "result")
					response["error"] = map[string]any{"code": -32603, "message": "missing required SYSTEMROOT SYNTHETIC_PRIVATE_SENTINEL"}
				} else {
					path, _ := req.Params["path"].(string)
					uri, err := url.Parse(path)
					if err != nil || uri.Scheme != "file" || uri.Host != "" {
						os.Exit(3)
					}
					filename := filepath.FromSlash(uri.Path)
					if runtime.GOOS == "windows" && len(filename) > 2 && filename[2] == ':' {
						filename = filename[1:]
					}
					allowed := filename == filepath.Join(work, "native-probe.txt")
					if strings.Contains(filepath.Base(os.Args[0]), "unsafe-filesystem") && filename == filepath.Join(profile, "blocked-probe.txt") {
						allowed = true
					}
					if allowed {
						encoded, _ := req.Params["dataBase64"].(string)
						data, err := base64.StdEncoding.DecodeString(encoded)
						if err != nil || string(data) != "REFLOW_NATIVE_PREFLIGHT_OK\n" || os.WriteFile(filename, data, 0600) != nil {
							os.Exit(3)
						}
					} else {
						delete(response, "result")
						response["error"] = map[string]any{"code": -32600, "message": "synthetic denied write SYNTHETIC_PRIVATE_SENTINEL"}
					}
				}
			}
			json.NewEncoder(os.Stdout).Encode(response)
		}
		return
	}
	for _, arg := range os.Args[1:] {
		if arg == "sandbox" {
			if os.WriteFile(filepath.Join(work, "probe.txt"), []byte("REFLOW_SANDBOX_OK\n"), 0600) != nil {
				os.Exit(3)
			}
			return
		}
	}
	os.Exit(3)
}

func main() {
	home := os.Getenv("CODEX_HOME")
	if strings.Contains(home, "preflight-") {
		preflight(home)
		return
	}
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
	if strings.Contains(prompt, "SYNTHETIC_TOOL_ERRORS") {
		fmt.Println(`{"type":"item.started","item":{"id":"SYNTHETIC_PRIVATE_SENTINEL","type":"command_execution","status":"in_progress","command":"SYNTHETIC_PRIVATE_SENTINEL"}}`)
		fmt.Println(`{"type":"item.completed","item":{"id":"SYNTHETIC_PRIVATE_SENTINEL","type":"command_execution","status":"failed","exit_code":1,"aggregated_output":"AssertionError: SYNTHETIC_PRIVATE_SENTINEL"}}`)
	}
	task := ""
	for id, name := range map[string]string{"intervals": "merge_intervals", "topo": "topological_order", "ndjson": "parse_chunks", "lru": "LRUCache", "ledger": "reconcile", "scheduler": "schedule_builds"} {
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
	if strings.Contains(prompt, "SYNTHETIC_MUTATE_CHECKER") {
		if err := os.WriteFile(filepath.Join(work, "verify_fixture.py"), []byte("# changed synthetic checker\n"), 0600); err != nil {
			os.Exit(2)
		}
	}
	fmt.Println(`{"type":"item.completed","item":{"type":"agent_message","text":"SYNTHETIC_PRIVATE_SENTINEL"}}`)
	fmt.Printf("{\"type\":\"turn.completed\",\"usage\":{\"input_tokens\":10,\"cached_input_tokens\":2,\"output_tokens\":%d,\"reasoning_output_tokens\":1}}\n", 5+health.MaxContinue)
}
