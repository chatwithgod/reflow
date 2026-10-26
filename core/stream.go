package core

import (
	"io"
)

// Reader incrementally decodes SSE or raw JSON frames. It owns no transport.
type Reader struct {
	r       io.Reader
	d       eventDecoder
	pending error
	buf     [32768]byte
}

func NewReader(r io.Reader) *Reader { return &Reader{r: r} }

// Decoder accepts arbitrary chunks without owning or buffering a transport.
// It has the same bounded framing rules as Reader.
type Decoder struct{ d eventDecoder }

func (d *Decoder) Push(chunk []byte) ([]Object, error) {
	if err := d.d.feed(chunk); err != nil {
		return nil, err
	}
	var events []Object
	for {
		event, ready, err := d.d.next()
		if err != nil {
			return events, err
		}
		if !ready {
			return events, nil
		}
		events = append(events, event)
	}
}

func (d *Decoder) Finish() error { return d.d.finish() }

func (r *Reader) Next() (Object, error) {
	for {
		event, ready, err := r.d.next()
		if err != nil {
			return nil, err
		}
		if ready {
			return event, nil
		}
		if r.pending != nil {
			if err := r.d.finish(); err != nil {
				return nil, err
			}
			return nil, r.pending
		}
		n, err := r.r.Read(r.buf[:])
		if n > 0 {
			if e := r.d.feed(r.buf[:n]); e != nil {
				return nil, e
			}
		}
		if err != nil {
			r.pending = err
		}
	}
}
