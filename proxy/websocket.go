package proxy

import (
	"context"
	"encoding/json"
	"net/http"
	"strings"

	"github.com/chatwithgod/reflow/core"
	"github.com/coder/websocket"
)

type packet struct {
	kind websocket.MessageType
	data []byte
	err  error
}
type lane struct {
	fold       *core.Session
	request    core.Object
	replayable bool
	active     bool
	broken     bool
	canceled   bool
	currentID  string
	pending    []packet
	metrics    *metricRound
}

func (s *Server) websocket(w http.ResponseWriter, r *http.Request) {
	target := s.target(r)
	if target.Scheme == "https" {
		target.Scheme = "wss"
	} else {
		target.Scheme = "ws"
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	headers := cleanHeaders(r.Header)
	for k := range headers {
		if strings.HasPrefix(strings.ToLower(k), "sec-websocket-") {
			headers.Del(k)
		}
	}
	// The incoming HTTP context cancels an abandoned handshake; after upgrade,
	// the connection read pumps own cancellation for the long-lived stream.
	up, resp, err := websocket.Dial(r.Context(), target.String(), &websocket.DialOptions{HTTPClient: s.client, HTTPHeader: headers})
	if err != nil {
		if resp != nil {
			copyResponse(w, resp)
		} else {
			http.Error(w, "upstream websocket unavailable", 502)
		}
		return
	}
	defer up.CloseNow()
	for k, v := range cleanHeaders(resp.Header) {
		if !strings.HasPrefix(strings.ToLower(k), "sec-websocket-") {
			w.Header()[k] = v
		}
	}
	down, err := websocket.Accept(w, r, nil)
	if err != nil {
		return
	}
	defer down.CloseNow()
	up.SetReadLimit(MaxRequestBytes)
	down.SetReadLimit(MaxRequestBytes)
	fromClient, fromUpstream := make(chan packet, 16), make(chan packet, 16)
	read := func(conn *websocket.Conn, ch chan<- packet) {
		for {
			kind, data, err := conn.Read(ctx)
			select {
			case ch <- packet{kind: kind, data: data, err: err}:
			case <-ctx.Done():
				return
			}
			if err != nil {
				return
			}
		}
	}
	go read(down, fromClient)
	go read(up, fromUpstream)
	lanes := map[string]*lane{}
	defer func() {
		for _, lane := range lanes {
			lane.metrics.failed()
		}
	}()
	cache := NewReplayCache()
	scope := credentialScope(r.Header)
	write := func(conn *websocket.Conn, event core.Object) error {
		b, err := json.Marshal(event)
		if err != nil {
			return err
		}
		return conn.Write(ctx, websocket.MessageText, b)
	}
	emit := func(id string, ev core.Object) error {
		if id != "" {
			ev["stream_id"] = id
		}
		return write(down, ev)
	}
	var begin func(string, *lane, packet) bool
	begin = func(id string, l *lane, p packet) bool {
		var body core.Object
		if json.Unmarshal(p.data, &body) != nil {
			return false
		}
		wire, replay := cache.Resolve(scope, body)
		full := replay
		if full == nil {
			full, _ = core.Clone(wire)
		}
		l.request = full
		parent, _ := wire["previous_response_id"].(string)
		l.replayable = parent == "" || replay != nil
		l.active, l.broken, l.canceled, l.currentID = true, false, false, ""
		l.fold = nil
		if s.config.Fold.MaxContinue > 0 && core.Eligible(wire) {
			prepare(wire)
			if replay != nil {
				prepare(replay)
			}
			fold, err := core.New(s.config.Fold, wire, replay)
			if err != nil {
				return false
			}
			l.fold = fold
		}
		delete(wire, "stream")
		s.metrics.toolResults(scope, body)
		l.metrics = s.metrics.begin(false, wire["generate"] == false)
		return write(up, wire) == nil
	}
	advance := func(id string, l *lane) bool {
		l.active = false
		l.fold = nil
		if len(l.pending) == 0 {
			return true
		}
		p := l.pending[0]
		l.pending = l.pending[1:]
		return begin(id, l, p)
	}
	for {
		select {
		case p := <-fromClient:
			if p.err != nil {
				return
			}
			var body core.Object
			if json.Unmarshal(p.data, &body) != nil {
				if up.Write(ctx, p.kind, p.data) != nil {
					return
				}
				continue
			}
			id, _ := body["stream_id"].(string)
			l := lanes[id]
			typ, _ := body["type"].(string)
			if typ != "response.create" {
				if typ == "response.cancel" && l != nil && l.active {
					l.canceled = true
					if _, ok := body["response_id"]; ok && l.currentID != "" {
						body["response_id"] = l.currentID
						p.data, _ = json.Marshal(body)
					}
				}
				if up.Write(ctx, p.kind, p.data) != nil {
					return
				}
				continue
			}
			if l == nil {
				if len(lanes) >= 64 {
					_ = down.Close(websocket.StatusPolicyViolation, "too many response streams")
					return
				}
				l = &lane{}
				lanes[id] = l
			}
			if l.active {
				if len(l.pending) >= 8 {
					_ = down.Close(websocket.StatusPolicyViolation, "too many queued requests")
					return
				}
				l.pending = append(l.pending, p)
				continue
			}
			if !begin(id, l, p) {
				return
			}
		case p := <-fromUpstream:
			if p.err != nil {
				for id, l := range lanes {
					if l.active && l.fold != nil && !l.broken {
						_ = emit(id, l.fold.Abort("upstream_eof"))
					}
				}
				return
			}
			var ev core.Object
			if json.Unmarshal(p.data, &ev) != nil {
				if down.Write(ctx, p.kind, p.data) != nil {
					return
				}
				continue
			}
			id, _ := ev["stream_id"].(string)
			l := lanes[id]
			if l == nil || !l.active {
				if down.Write(ctx, p.kind, p.data) != nil {
					return
				}
				continue
			}
			typ, _ := ev["type"].(string)
			l.metrics.event(ev)
			terminal := typ == "response.completed" || typ == "response.done" || typ == "response.failed" || typ == "response.incomplete" || typ == "error"
			if response, ok := ev["response"].(map[string]any); ok {
				if rid, _ := response["id"].(string); rid != "" {
					l.currentID = rid
				}
			}
			if l.broken {
				if terminal && !advance(id, l) {
					return
				}
				continue
			}
			if l.fold == nil {
				rollback := func() {}
				if terminal && l.replayable {
					response, _ := ev["response"].(map[string]any)
					if typ == "response.completed" || typ == "response.done" {
						full, _ := core.Clone(l.request)
						items := inputItems(full["input"])
						if output, ok := response["output"].([]any); ok {
							items = append(items, output...)
						}
						full["input"] = items
						rollback = cache.Remember(scope, core.Result{VisibleID: l.currentID, UpstreamID: l.currentID, ReplayRequest: full})
					}
				}
				if down.Write(ctx, p.kind, p.data) != nil {
					rollback()
					return
				}
				if terminal && !advance(id, l) {
					return
				}
				continue
			}
			if l.canceled && terminal {
				if emit(id, l.fold.Abort("canceled")) != nil {
					return
				}
				if !advance(id, l) {
					return
				}
				continue
			}
			if typ == "error" && l.fold.Rounds() == 1 {
				// The client needs the original code to rebuild context after an
				// uncached parent (and to distinguish auth/quota failures).
				if down.Write(ctx, p.kind, p.data) != nil {
					return
				}
				if !advance(id, l) {
					return
				}
				continue
			}
			out, err := l.fold.Push(ev)
			if err != nil {
				if emit(id, l.fold.Abort("upstream_error")) != nil {
					return
				}
				l.broken = true
				if terminal && !advance(id, l) {
					return
				}
				continue
			}
			for _, event := range out {
				if emit(id, event) != nil {
					return
				}
			}
			if !l.fold.HasTerminal() {
				continue
			}
			d, err := l.fold.Finish()
			if err != nil {
				return
			}
			if d.Next != nil {
				d.Next["type"] = "response.create"
				delete(d.Next, "stream")
				if id != "" {
					d.Next["stream_id"] = id
				}
				l.metrics = s.metrics.begin(true, false)
				if write(up, d.Next) != nil {
					return
				}
				continue
			}
			rollback := cache.Remember(scope, d.Result)
			model, _ := l.request["model"].(string)
			finishTools := s.metrics.prepareTools(scope, model, d.Result, d.Events)
			for _, event := range d.Events {
				if emit(id, event) != nil {
					rollback()
					finishTools(false)
					return
				}
			}
			finishTools(true)
			if !advance(id, l) {
				return
			}
		case <-ctx.Done():
			return
		}
	}
}
