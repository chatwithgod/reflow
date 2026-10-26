package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"os"

	"github.com/chatwithgod/reflow/internal/control"
)

func controlCommand(command string, args []string) error {
	flags := flag.NewFlagSet(command, flag.ContinueOnError)
	home := flags.String("codex-home", "", "Codex home whose routing may be managed")
	defaultEndpoint := os.Getenv("REFLOW_URL")
	if defaultEndpoint == "" {
		defaultEndpoint = "http://127.0.0.1:18516"
	}
	endpoint := flags.String("endpoint", defaultEndpoint, "local Reflow HTTP origin")
	action := flags.String("action", "preview", "config action: preview, connect or restore")
	if err := flags.Parse(args); err != nil {
		return err
	}
	var err error
	if *home == "" {
		*home, err = control.DefaultHome()
		if err != nil {
			return err
		}
	}
	c := control.Controller{Home: *home, Endpoint: *endpoint}
	if command == "mcp" {
		return c.ServeMCP(context.Background(), os.Stdin, os.Stdout)
	}
	var value any
	switch *action {
	case "preview":
		value, err = c.Preview("")
	case "connect":
		value, err = c.Connect(context.Background(), "")
	case "restore":
		var changed bool
		changed, err = c.Restore()
		value = map[string]any{"restored": true, "changed": changed, "restart_required": changed}
	default:
		return fmt.Errorf("unknown config action")
	}
	if err != nil {
		return err
	}
	return json.NewEncoder(os.Stdout).Encode(value)
}
