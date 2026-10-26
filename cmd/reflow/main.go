package main

import (
	"context"
	"flag"
	"fmt"
	"net"
	"net/http"
	"os"
	"os/signal"
	"time"

	"github.com/chatwithgod/reflow/core"
	"github.com/chatwithgod/reflow/internal/version"
	"github.com/chatwithgod/reflow/proxy"
)

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func run() error {
	if len(os.Args) > 1 && (os.Args[1] == "mcp" || os.Args[1] == "codex-config") {
		return controlCommand(os.Args[1], os.Args[2:])
	}
	listen := flag.String("listen", "127.0.0.1:18516", "loopback listen address")
	upstream := flag.String("upstream", "https://chatgpt.com/backend-api/codex", "fixed upstream base URL")
	maxContinue := flag.Int("max-continue", 3, "maximum extra model requests (0 disables folding)")
	showVersion := flag.Bool("version", false, "print version")
	flag.Parse()
	if *showVersion {
		fmt.Println(version.String)
		return nil
	}
	host, _, err := net.SplitHostPort(*listen)
	if err != nil || net.ParseIP(host) == nil || !net.ParseIP(host).IsLoopback() {
		return fmt.Errorf("listen must use a numeric loopback address")
	}
	cfg := core.DefaultConfig()
	cfg.MaxContinue = *maxContinue
	handler, err := proxy.New(proxy.Config{Upstream: *upstream, Fold: cfg})
	if err != nil {
		return err
	}
	listener, err := net.Listen("tcp", *listen)
	if err != nil {
		return err
	}
	server := &http.Server{Handler: handler, ReadHeaderTimeout: 10 * time.Second, IdleTimeout: 2 * time.Minute, MaxHeaderBytes: 64 << 10}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt)
	defer stop()
	go func() {
		<-ctx.Done()
		shutdown, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = server.Shutdown(shutdown)
	}()
	fmt.Fprintf(os.Stderr, "Reflow %s listening on %s; credentials stay with the client\n", version.String, listener.Addr())
	err = server.Serve(listener)
	if err == http.ErrServerClosed {
		return nil
	}
	return err
}
