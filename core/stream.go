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
