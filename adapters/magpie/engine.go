// Package magpie embeds Reflow's tested HTTP pipeline behind a host-owned send
// callback. It opens no listener and receives no account credentials.
package magpie

import (
	"bytes"
	"context"
	"errors"
	"io"
	"net/http"
	"sync"

	"github.com/chatwithgod/reflow/core"
	"github.com/chatwithgod/reflow/proxy"
)

// Send executes a round on the host's already selected account and endpoint.
// It must honor cancellation and return a body that Close unblocks.
type Send func(context.Context, []byte) (*http.Response, error)
type sendKey struct{}
type transport struct{}

func (transport) RoundTrip(r *http.Request) (*http.Response, error) {
	send, ok := r.Context().Value(sendKey{}).(Send)
	if !ok {
		return nil, errors.New("missing host execution callback")
	}
	body, err := io.ReadAll(io.LimitReader(r.Body, proxy.MaxRequestBytes+1))
	r.Body.Close()
	if err != nil || len(body) > proxy.MaxRequestBytes {
		return nil, errors.New("host request body limit exceeded")
	}
	return send(r.Context(), body)
}

type Engine struct{ handler *proxy.Server }

func New(config core.Config) (*Engine, error) {
	if config.MaxContinue > 7 {
		return nil, errors.New("Magpie execution permits at most seven additional rounds")
	}
	handler, err := proxy.New(proxy.Config{Upstream: "http://127.0.0.1", Fold: config, Client: &http.Client{Transport: transport{}}, FullReplay: true})
	if err != nil {
		return nil, err
	}
	return &Engine{handler: handler}, nil
}

// Execute holds the same bounded replay cache and event handling as the
// standalone service. Scope must separate accounts and endpoints; only opaque
// hashes belong here, never a token. Closing the returned body joins its worker.
func (e *Engine) Execute(parent context.Context, scope string, body []byte, send Send) (*http.Response, error) {
	if scope == "" || len(scope) > 256 || send == nil {
		return nil, errors.New("host scope and execution callback are required")
	}
	if len(body) > proxy.MaxRequestBytes {
		return send(parent, body)
	}
	ctx, cancel := context.WithCancel(context.WithValue(parent, sendKey{}, send))
	r, _ := http.NewRequestWithContext(ctx, http.MethodPost, "http://127.0.0.1/responses", bytes.NewReader(body))
	r.RemoteAddr = "127.0.0.1:1"
	r.Header.Set("Authorization", "Bearer "+scope)
	r.Header.Set("Content-Type", "application/json")
	reader, writer := io.Pipe()
	done := make(chan struct{})
	responseBody := &joinedBody{reader: reader, cancel: cancel, done: done}
	out := &responseWriter{header: make(http.Header), ready: make(chan *http.Response, 1), writer: writer, body: responseBody, ctx: ctx}
	go func() {
		defer close(done)
		defer func() {
			if recover() != nil {
				out.WriteHeader(http.StatusInternalServerError)
				writer.CloseWithError(errors.New("Reflow execution failed"))
			} else {
				out.WriteHeader(http.StatusOK)
				writer.Close()
			}
		}()
		e.handler.ServeHTTP(out, r)
	}()
	select {
	case res := <-out.ready:
		return res, nil
	case <-ctx.Done():
		responseBody.Close()
		return nil, ctx.Err()
	}
}

type responseWriter struct {
	header http.Header
	ready  chan *http.Response
	writer *io.PipeWriter
	body   io.ReadCloser
	ctx    context.Context
	wrote  bool
}

func (w *responseWriter) Header() http.Header { return w.header }
func (w *responseWriter) WriteHeader(code int) {
	if w.wrote {
		return
	}
	w.wrote = true
	w.ready <- &http.Response{StatusCode: code, Status: http.StatusText(code), Proto: "HTTP/1.1", ProtoMajor: 1, ProtoMinor: 1, Header: w.header.Clone(), Body: w.body, ContentLength: -1}
}
func (w *responseWriter) Write(b []byte) (int, error) {
	w.WriteHeader(http.StatusOK)
	return w.writer.Write(b)
}
func (w *responseWriter) FlushError() error { w.WriteHeader(http.StatusOK); return w.ctx.Err() }

type joinedBody struct {
	reader *io.PipeReader
	cancel context.CancelFunc
	done   <-chan struct{}
	once   sync.Once
	err    error
}

func (b *joinedBody) Read(p []byte) (int, error) { return b.reader.Read(p) }
func (b *joinedBody) Close() error {
	b.once.Do(func() { b.cancel(); b.err = b.reader.Close(); <-b.done })
	return b.err
}
