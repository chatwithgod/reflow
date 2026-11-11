package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"strings"
)

const maxStreamBufferSize = 8 * 1024 * 1024

// eventDecoder accepts the host's raw WebSocket JSON events and SSE data:
// payloads (with or without trailing newlines). JSON boundaries, not searching
// for "data:" within arbitrary bytes, delimit events. Its incremental scanner
// avoids rescanning a large JSON string after every fragmented host read.
type eventDecoder struct {
	buffer       []byte
	awaitingData bool
	jsonStarted  bool
	scanPos      int
	depth        int
	inString     bool
	escaped      bool
}

func (d *eventDecoder) feed(payload []byte) error {
	// CPA's HTTP Codex executor uses bufio.Scanner: an event:/id:/retry:/
	// comment line and the following data: line arrive in separate callbacks,
	// WITHOUT their newlines. Preserve that logical boundary when the next
	// callback starts another SSE field. Never inspect a JSON string for data:,
	// nor insert separators into a partially decoded JSON payload.
	separator := !d.jsonStarted && !d.awaitingData &&
		len(d.buffer) > 0 && isSSEControl(d.buffer) &&
		bytes.IndexByte(d.buffer, '\n') < 0 && startsSSEField(payload)
	extra := 0
	if separator {
		extra = 1
	}
	// Check before allocating, and never include response content in errors.
	if len(payload) > maxStreamBufferSize-len(d.buffer)-extra {
		return fmt.Errorf("stream event buffer exceeded %d bytes", maxStreamBufferSize)
	}
	if separator {
		d.buffer = append(d.buffer, '\n')
	}
	d.buffer = append(d.buffer, payload...)
	return nil
}

func startsSSEField(b []byte) bool {
	b = bytes.TrimLeft(b, " \t\r\n")
	return len(b) > 0 && (bytes.HasPrefix(b, []byte("data:")) || isSSEControl(b))
}

func (d *eventDecoder) next() (map[string]any, bool, error) {
	for {
		if !d.jsonStarted {
			d.buffer = bytes.TrimLeft(d.buffer, " \t\r\n")
			if len(d.buffer) == 0 {
				return nil, false, nil
			}
			if bytes.HasPrefix(d.buffer, []byte("data:")) && !d.awaitingData {
				d.buffer = d.buffer[5:]
				d.awaitingData = true
				continue
			}
			if bytes.HasPrefix(d.buffer, []byte("[DONE]")) {
				d.buffer = d.buffer[6:]
				d.awaitingData = false
				continue // not a substitute for a response terminal event
			}
			if d.buffer[0] != '{' {
				if !d.awaitingData && isSSEControl(d.buffer) {
					if newline := bytes.IndexByte(d.buffer, '\n'); newline >= 0 {
						d.buffer = d.buffer[newline+1:]
						continue
					}
					return nil, false, nil
				}
				if isPartialFramePrefix(d.buffer, d.awaitingData) {
					return nil, false, nil
				}
				return nil, false, fmt.Errorf("invalid stream event framing")
			}
			d.jsonStarted = true
			d.scanPos, d.depth = 0, 0
			d.inString, d.escaped = false, false
		}

		for d.scanPos < len(d.buffer) {
			c := d.buffer[d.scanPos]
			d.scanPos++
			if d.inString {
				if d.escaped {
					d.escaped = false
				} else if c == '\\' {
					d.escaped = true
				} else if c == '"' {
					d.inString = false
				}
				continue
			}
			switch c {
			case '"':
				d.inString = true
			case '{':
				d.depth++
			case '}':
				d.depth--
				if d.depth != 0 {
					continue
				}
				var event map[string]any
				if err := json.Unmarshal(d.buffer[:d.scanPos], &event); err != nil {
					return nil, false, fmt.Errorf("invalid JSON stream event")
				}
				eventType, _ := event["type"].(string)
				if strings.TrimSpace(eventType) == "" {
					return nil, false, fmt.Errorf("stream event is missing its type")
				}
				d.buffer = d.buffer[d.scanPos:]
				d.awaitingData, d.jsonStarted = false, false
				d.scanPos, d.depth = 0, 0
				d.inString, d.escaped = false, false
				return event, true, nil
			}
		}
		return nil, false, nil
	}
}

func isSSEControl(b []byte) bool {
	return b[0] == ':' || bytes.HasPrefix(b, []byte("event:")) ||
		bytes.HasPrefix(b, []byte("id:")) || bytes.HasPrefix(b, []byte("retry:"))
}

func isPartialFramePrefix(b []byte, awaitingData bool) bool {
	prefixes := []string{"[DONE]"}
	if !awaitingData {
		prefixes = append(prefixes, "data:", "event:", "id:", "retry:")
	}
	for _, prefix := range prefixes {
		if len(b) < len(prefix) && bytes.HasPrefix([]byte(prefix), b) {
			return true
		}
	}
	return false
}

func (d *eventDecoder) finish() error {
	if d.awaitingData || d.jsonStarted || len(bytes.TrimSpace(d.buffer)) != 0 {
		return fmt.Errorf("upstream stream ended with an incomplete event")
	}
	return nil
}
