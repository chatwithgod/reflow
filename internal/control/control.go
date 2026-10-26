// Package control exposes local diagnostics and narrow, reversible Codex setup.
package control

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"time"

	"github.com/chatwithgod/reflow/internal/codexconfig"
)

type Controller struct {
	Home     string
	Endpoint string
	Client   *http.Client
}

type Status struct {
	Endpoint    string               `json:"endpoint"`
	Ready       bool                 `json:"ready"`
	Version     string               `json:"version,omitempty"`
	MaxContinue int                  `json:"max_continue,omitempty"`
	Reason      string               `json:"reason,omitempty"`
	Routing     *codexconfig.Preview `json:"routing,omitempty"`
}

func DefaultHome() (string, error) {
	for _, key := range []string{"REFLOW_CODEX_HOME", "CODEX_HOME"} {
		if value := os.Getenv(key); value != "" {
			return filepath.Abs(value)
		}
	}
	// Codex filters CODEX_HOME from stdio MCP environments. Its portable plugin
	// loader does provide PLUGIN_ROOT, rooted in the owning profile's cache.
	// Never fall back to a different user profile when this layout is unknown.
	if root := os.Getenv("PLUGIN_ROOT"); root != "" {
		if !filepath.IsAbs(root) {
			return "", errors.New("plugin root must be absolute; set --codex-home explicitly")
		}
		root, err := filepath.EvalSymlinks(root)
		if err != nil {
			return "", errors.New("cannot resolve installed plugin root; set --codex-home explicitly")
		}
		plugin := filepath.Dir(root)
		market := filepath.Dir(plugin)
		cache := filepath.Dir(market)
		plugins := filepath.Dir(cache)
		if filepath.Base(plugin) != "reflow" || filepath.Base(cache) != "cache" || filepath.Base(plugins) != "plugins" {
			return "", errors.New("cannot identify the Codex home owning this plugin; set --codex-home explicitly")
		}
		return filepath.Dir(plugins), nil
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return "", errors.New("cannot determine Codex home")
	}
	return filepath.Join(home, ".codex"), nil
}

func (c Controller) target(value string) (string, error) {
	if value == "" {
		value = c.Endpoint
	}
	if value == "" {
		value = "http://127.0.0.1:18516"
	}
	return codexconfig.Endpoint(value)
}

func (c Controller) Status(ctx context.Context, endpoint string) (Status, error) {
	endpoint, err := c.target(endpoint)
	if err != nil {
		return Status{}, err
	}
	status := Status{Endpoint: endpoint}
	if preview, err := codexconfig.Inspect(c.Home, endpoint); err == nil {
		status.Routing = &preview
	}
	client := &http.Client{Timeout: 2 * time.Second}
	if c.Client != nil {
		copy := *c.Client
		client = &copy
	}
	client.CheckRedirect = func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
	req, _ := http.NewRequestWithContext(ctx, "GET", endpoint+"/healthz", nil)
	resp, err := client.Do(req)
	if err != nil {
		status.Reason = "local_service_unavailable"
		return status, nil
	}
	defer resp.Body.Close()
	var health struct {
		Service, Status, Version string
		MaxContinue              int `json:"max_continue"`
	}
	if resp.StatusCode != 200 || json.NewDecoder(io.LimitReader(resp.Body, 8192)).Decode(&health) != nil || health.Service != "reflow" || health.Status != "ready" {
		status.Reason = "endpoint_is_not_ready_reflow"
		return status, nil
	}
	status.Ready, status.Version, status.MaxContinue = true, health.Version, health.MaxContinue
	return status, nil
}

func (c Controller) Preview(endpoint string) (codexconfig.Preview, error) {
	endpoint, err := c.target(endpoint)
	if err != nil {
		return codexconfig.Preview{}, err
	}
	return codexconfig.Inspect(c.Home, endpoint)
}

func (c Controller) Connect(ctx context.Context, endpoint string) (codexconfig.Preview, error) {
	status, err := c.Status(ctx, endpoint)
	if err != nil {
		return codexconfig.Preview{}, err
	}
	if !status.Ready {
		return codexconfig.Preview{}, errors.New("start the local Reflow service before connecting Codex")
	}
	return codexconfig.Connect(c.Home, status.Endpoint)
}

func (c Controller) Restore() (bool, error) { return codexconfig.RestoreChanged(c.Home) }
