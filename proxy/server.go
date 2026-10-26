// Package proxy supplies transport adapters for the independent Reflow core.
package proxy

import (
	"bytes"
	"compress/gzip"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/chatwithgod/reflow/core"
	"github.com/chatwithgod/reflow/internal/version"
	"github.com/klauspost/compress/zstd"
)

const MaxRequestBytes = 16 << 20

var errForwardedUpstream = errors.New("upstream error forwarded")

type Config struct {
	Upstream string
	Fold     core.Config
	Client   *http.Client
	// FullReplay uses known complete history instead of a parent response ID.
	// Embedded hosts may open a fresh upstream WebSocket for every HTTP round.
	FullReplay    bool
	EnableMetrics bool
}

type Server struct {
	upstream  *url.URL
	config    Config
	client    *http.Client
	cache     *ReplayCache
	heartbeat time.Duration
	metrics   *metricsStore
}

func New(config Config) (*Server, error) {
	u, err := url.Parse(config.Upstream)
	if err != nil || u.Host == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" {
		return nil, errors.New("invalid upstream URL")
	}
	if u.Scheme != "https" && (u.Scheme != "http" || !loopbackHost(u.Hostname())) {
		return nil, errors.New("upstream requires HTTPS or loopback HTTP")
	}
	if err := config.Fold.Validate(); err != nil {
		return nil, err
	}
	client := config.Client
	if client == nil {
		client = &http.Client{Transport: &http.Transport{Proxy: http.ProxyFromEnvironment, ForceAttemptHTTP2: true, ResponseHeaderTimeout: 60 * time.Second, IdleConnTimeout: 90 * time.Second}}
	}
	copyClient := *client
	copyClient.CheckRedirect = func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
	server := &Server{upstream: u, config: config, client: &copyClient, cache: NewReplayCache(), heartbeat: 15 * time.Second}
	if config.EnableMetrics {
		server.metrics = &metricsStore{}
	}
	return server, nil
}

func loopbackHost(host string) bool {
	return host == "localhost" || (net.ParseIP(host) != nil && net.ParseIP(host).IsLoopback())
}

func (s *Server) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil || !loopbackHost(host) {
		http.Error(w, "loopback clients only", http.StatusForbidden)
		return
	}
	if r.Header.Get("Origin") != "" {
		http.Error(w, "browser origins are not accepted", http.StatusForbidden)
		return
	}
	if r.URL.Path == "/healthz" && r.Method == http.MethodGet {
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]any{"service": "reflow", "status": "ready", "version": version.String, "max_continue": s.config.Fold.MaxContinue})
		return
	}
	if r.URL.Path == "/metrics" && r.Method == http.MethodGet {
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(s.metrics.snapshot())
		return
	}
	if r.Header.Get("Authorization") == "" {
		http.Error(w, "client authorization required", http.StatusUnauthorized)
		return
	}
	if strings.EqualFold(r.Header.Get("Upgrade"), "websocket") && strings.HasSuffix(r.URL.Path, "/responses") {
		s.websocket(w, r)
		return
	}
	if r.Method != http.MethodPost || !strings.HasSuffix(r.URL.Path, "/responses") || s.config.Fold.MaxContinue == 0 {
		s.passthrough(w, r)
		return
	}
	raw, err := io.ReadAll(io.LimitReader(r.Body, MaxRequestBytes+1))
	r.Body.Close()
	if err != nil || len(raw) > MaxRequestBytes {
		http.Error(w, "request body limit exceeded", http.StatusRequestEntityTooLarge)
		return
	}
	r.Body = io.NopCloser(bytes.NewReader(raw))
	decoded := raw
	switch r.Header.Get("Content-Encoding") {
	case "", "identity":
	case "gzip":
		reader, e := gzip.NewReader(bytes.NewReader(raw))
		if e != nil {
			http.Error(w, "invalid compressed body", 400)
			return
		}
		decoded, e = io.ReadAll(io.LimitReader(reader, MaxRequestBytes+1))
		reader.Close()
		if e != nil || len(decoded) > MaxRequestBytes {
			http.Error(w, "request body limit exceeded", 413)
			return
		}
	case "zstd":
		reader, e := zstd.NewReader(bytes.NewReader(raw), zstd.WithDecoderConcurrency(1), zstd.WithDecoderMaxMemory(64<<20), zstd.WithDecoderMaxWindow(32<<20))
		if e != nil {
			http.Error(w, "invalid compressed body", 400)
			return
		}
		decoded, e = io.ReadAll(io.LimitReader(reader, MaxRequestBytes+1))
		reader.Close()
		if e != nil || len(decoded) > MaxRequestBytes {
			http.Error(w, "invalid or oversized compressed body", 400)
			return
		}
	default:
		s.passthrough(w, r)
		return
	}
	var body core.Object
	if json.Unmarshal(decoded, &body) != nil || body["stream"] != true || !core.Eligible(body) {
		s.passthrough(w, r)
		return
	}
	scope := credentialScope(r.Header)
	wire, replay := s.cache.Resolve(scope, body)
	if s.config.FullReplay && replay != nil {
		wire = replay
	}
	prepare(wire)
	if replay != nil {
		prepare(replay)
	}
	fold, err := core.New(s.config.Fold, wire, replay)
	if err != nil {
		http.Error(w, "invalid Reflow request", 400)
		return
	}
	s.foldHTTP(w, r, scope, wire, fold)
}

func prepare(body core.Object) {
	include, _ := body["include"].([]any)
	for _, v := range include {
		if v == "reasoning.encrypted_content" {
			return
		}
	}
	body["include"] = append(include, "reasoning.encrypted_content")
}

func (s *Server) target(r *http.Request) *url.URL {
	u := *s.upstream
	path := r.URL.Path
	for _, prefix := range []string{"/backend-api/codex", "/v1"} {
		if strings.HasPrefix(path, prefix+"/") {
			path = strings.TrimPrefix(path, prefix)
			break
		}
	}
	u.Path = strings.TrimRight(u.Path, "/") + "/" + strings.TrimLeft(path, "/")
	u.RawPath = ""
	u.RawQuery = r.URL.RawQuery
	return &u
}

func cleanHeaders(h http.Header) http.Header {
	out := h.Clone()
	for _, name := range strings.Split(out.Get("Connection"), ",") {
		out.Del(strings.TrimSpace(name))
	}
	for _, name := range []string{"Connection", "Proxy-Connection", "Keep-Alive", "TE", "Trailer", "Transfer-Encoding", "Upgrade", "Proxy-Authorization", "Forwarded", "X-Forwarded-For", "X-Forwarded-Host", "X-Forwarded-Proto"} {
		out.Del(name)
	}
	return out
}

func (s *Server) upstreamRequest(ctx context.Context, r *http.Request, body io.Reader, rewritten, continuation bool) (*http.Response, error) {
	req, err := http.NewRequestWithContext(ctx, r.Method, s.target(r).String(), body)
	if err != nil {
		return nil, err
	}
	req.Header = cleanHeaders(r.Header)
	if rewritten {
		req.Header.Del("Content-Encoding")
		req.Header.Del("Content-Length")
		req.Header.Set("Content-Type", "application/json")
	}
	req.Header.Set("Accept-Encoding", "identity")
	var observed *metricRound
	if r.Method == http.MethodPost && strings.HasSuffix(r.URL.Path, "/responses") {
		observed = s.metrics.begin(continuation, false)
	}
	resp, err := s.client.Do(req)
	if observed == nil {
		return resp, err
	}
	if err != nil {
		observed.failed()
		return resp, err
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		observed.failed()
		return resp, nil
	}
	if !strings.Contains(resp.Header.Get("Content-Type"), "text/event-stream") || (resp.Header.Get("Content-Encoding") != "" && resp.Header.Get("Content-Encoding") != "identity") {
		observed.unsupported()
		return resp, nil
	}
	resp.Body = &meteredBody{ReadCloser: resp.Body, round: observed}
	return resp, nil
}

func copyResponse(w http.ResponseWriter, resp *http.Response) {
	for k, values := range cleanHeaders(resp.Header) {
		w.Header()[k] = values
	}
	w.WriteHeader(resp.StatusCode)
	defer resp.Body.Close()
	io.Copy(w, resp.Body)
}

func (s *Server) passthrough(w http.ResponseWriter, r *http.Request) {
	resp, err := s.upstreamRequest(r.Context(), r, r.Body, false, false)
	if err != nil {
		http.Error(w, "upstream connection failed", 502)
		return
	}
	copyResponse(w, resp)
}

func (s *Server) foldHTTP(w http.ResponseWriter, r *http.Request, scope string, wire core.Object, fold *core.Session) {
	started := false
	emit := func(event core.Object) error {
		b, err := json.Marshal(event)
		if err != nil {
			return err
		}
		if _, err = w.Write(append(append([]byte("data: "), b...), '\n', '\n')); err != nil {
			return err
		}
		return http.NewResponseController(w).Flush()
	}
	for {
		data, err := json.Marshal(wire)
		if err != nil {
			return
		}
		resp, err := s.upstreamRequest(r.Context(), r, bytes.NewReader(data), true, fold.Rounds() > 1)
		if err != nil {
			if !started {
				http.Error(w, "upstream connection failed", 502)
			} else if r.Context().Err() == nil {
				_ = emit(fold.Abort("upstream_error"))
			}
			return
		}
		if resp.StatusCode < 200 || resp.StatusCode >= 300 || !strings.Contains(resp.Header.Get("Content-Type"), "text/event-stream") {
			if !started {
				copyResponse(w, resp)
			} else {
				resp.Body.Close()
				_ = emit(fold.Abort("upstream_error"))
			}
			return
		}
		if !started {
			for k, v := range cleanHeaders(resp.Header) {
				w.Header()[k] = v
			}
			w.Header().Del("Content-Length")
			w.Header().Del("Content-Encoding")
			w.Header().Set("Content-Type", "text/event-stream")
			w.Header().Set("Cache-Control", "no-cache")
			w.WriteHeader(resp.StatusCode)
			started = true
		}
		if err := s.consumeHTTP(r.Context(), resp.Body, w, fold, emit); err != nil {
			if errors.Is(err, errForwardedUpstream) {
				return
			}
			if r.Context().Err() == nil {
				reason := "upstream_error"
				if errors.Is(err, io.EOF) {
					reason = "upstream_eof"
				}
				_ = emit(fold.Abort(reason))
			}
			return
		}
		decision, err := fold.Finish()
		if err != nil {
			_ = emit(fold.Abort("upstream_error"))
			return
		}
		if decision.Next != nil {
			wire = decision.Next
			continue
		}
		rollback := s.cache.Remember(scope, decision.Result)
		for _, event := range decision.Events {
			if emit(event) != nil {
				rollback()
				return
			}
		}
		_, _ = io.WriteString(w, "data: [DONE]\n\n")
		_ = http.NewResponseController(w).Flush()
		return
	}
}

func (s *Server) consumeHTTP(ctx context.Context, body io.ReadCloser, w http.ResponseWriter, fold *core.Session, emit func(core.Object) error) error {
	ctx, cancel := context.WithCancel(ctx)
	defer cancel()
	defer body.Close()
	type decoded struct {
		event core.Object
		err   error
	}
	events := make(chan decoded, 1)
	go func() {
		reader := core.NewReader(body)
		for {
			ev, err := reader.Next()
			select {
			case events <- decoded{ev, err}:
			case <-ctx.Done():
				return
			}
			if err != nil {
				return
			}
		}
	}()
	tick := time.NewTicker(s.heartbeat)
	defer tick.Stop()
	for !fold.HasTerminal() {
		select {
		case item := <-events:
			if item.err != nil {
				return item.err
			}
			// Preserve native retry/refresh codes such as previous_response_not_found.
			// A hidden continuation attempt cannot be exposed as a new client error.
			if item.event["type"] == "error" && fold.Rounds() == 1 {
				if err := emit(item.event); err != nil {
					return err
				}
				return errForwardedUpstream
			}
			out, err := fold.Push(item.event)
			if err != nil {
				return err
			}
			for _, ev := range out {
				if err := emit(ev); err != nil {
					return err
				}
			}
		case <-tick.C:
			if _, err := io.WriteString(w, ": reflow keepalive\n\n"); err != nil {
				return err
			}
			if err := http.NewResponseController(w).Flush(); err != nil {
				return err
			}
		case <-ctx.Done():
			return ctx.Err()
		}
	}
	return nil
}
