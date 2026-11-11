package main

import "github.com/chatwithgod/reflow/core"

const maxStreamBufferSize = core.MaxStreamBufferSize

type eventDecoder struct{ core.EventDecoder }

func (d *eventDecoder) feed(payload []byte) error           { return d.Feed(payload) }
func (d *eventDecoder) next() (map[string]any, bool, error) { return d.Next() }
func (d *eventDecoder) finish() error                       { return d.Finish() }
