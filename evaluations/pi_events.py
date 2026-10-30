"""Pi event observations: fixed labels, counters and exact-fixture booleans only."""
import time

from event_diagnostics import EventDiagnostics


class PiEvents:
    def __init__(self, expected, read_metrics, started, stop, clock=time.monotonic):
        self.expected = expected
        self.started, self.clock, self.stop = started, clock, stop
        self.tools = EventDiagnostics(read_metrics, started, clock)
        self.trace = []
        self.usage = dict.fromkeys(('input', 'output', 'cacheRead', 'cacheWrite', 'reasoning'), 0)
        self.counts = dict.fromkeys(('agent_ends', 'assistant_messages', 'usage_reports', 'invalid_usage_reports',
            'tool_starts', 'tool_ends', 'tool_failures', 'unexpected_tools', 'error_events', 'guard_reports'), 0)
        self.guard = {'allowed': 0, 'blocked': 0}
        self.guard_valid = True
        self.rate_limited = False
        self.read_matched = self.final_matched = False
        self.final_stop = 'missing'
        self.trace_truncated = False

    @staticmethod
    def text(content):
        if not isinstance(content, list):
            return ''
        return ''.join(item.get('text', '') for item in content if isinstance(item, dict)
                       and item.get('type') == 'text' and isinstance(item.get('text'), str))

    def observe(self, event):
        kind = event.get('type')
        if kind == 'agent_end':
            self.counts['agent_ends'] += 1
        elif kind == 'reflow_probe_guard':
            self.counts['guard_reports'] += 1
            valid = type(event.get('version')) is int and event['version'] == 1 and all(type(event.get(k)) is int and self.guard[k] <= event[k] <= 16
                                                   for k in ('allowed', 'blocked'))
            self.guard_valid = self.guard_valid and valid
            if valid:
                self.guard = {key: event[key] for key in self.guard}
                if self.guard['blocked']:
                    self.stop()
        elif kind == 'message_end' and isinstance(event.get('message'), dict):
            message = event['message']
            if message.get('role') != 'assistant':
                return
            self.counts['assistant_messages'] += 1
            reason = message.get('stopReason')
            self.final_stop = reason if reason in ('stop', 'toolUse', 'length', 'error', 'aborted') else 'unknown'
            self.final_matched = self.text(message.get('content')).strip() == self.expected
            usage = message.get('usage', {})
            if all(type(usage.get(key)) is int and usage[key] >= 0 for key in self.usage):
                self.counts['usage_reports'] += 1
                for key in self.usage:
                    self.usage[key] += usage[key]
            else:
                self.counts['invalid_usage_reports'] += 1
            if reason in ('error', 'aborted', 'length'):
                self.counts['error_events'] += 1
                raw = message.get('errorMessage', '')
                if isinstance(raw, str):
                    self.rate_limited |= any(marker in raw.lower() for marker in
                        ('429', 'rate_limit', 'rate limit', 'too many requests', 'usage_limit_exceeded'))
                self.stop()
        elif kind in ('tool_execution_start', 'tool_execution_end'):
            started = kind == 'tool_execution_start'
            self.counts['tool_starts' if started else 'tool_ends'] += 1
            if event.get('toolName') != 'read':
                self.counts['unexpected_tools'] += 1
            failed = not started and event.get('isError') is not False
            if failed:
                self.counts['tool_failures'] += 1
            if not started and not failed:
                result = event.get('result', {})
                text = self.text(result.get('content')) if isinstance(result, dict) else ''
                self.read_matched |= self.expected in text
            normalized = {'type': 'mcp_tool_call', 'id': event.get('toolCallId'),
                          'status': 'in_progress' if started else 'failed' if failed else 'completed'}
            extra = self.tools.observe('item.started' if started else 'item.completed', normalized, capture=len(self.trace) < 20)
            if len(self.trace) < 20:
                self.trace.append({'at_seconds': round(self.clock() - self.started, 3),
                    'event': 'started' if started else 'completed', 'kind': 'read' if event.get('toolName') == 'read' else 'other',
                    'failed': failed, **extra})
            else:
                self.trace_truncated = True
            if failed or self.counts['unexpected_tools'] or self.counts['tool_starts'] > 1:
                self.stop()

    def summary(self):
        return {**self.counts, 'rate_limit_detected': self.rate_limited, 'final_stop_reason': self.final_stop,
            'fixture_read_matched': self.read_matched, 'final_fixture_matched': self.final_matched,
            'client_reported_usage': dict(self.usage), 'guard': dict(self.guard),
            'guard_observations_valid': self.guard_valid and self.counts['guard_reports'] > 0,
            'event_trace': list(self.trace), 'event_trace_truncated': self.trace_truncated,
            'event_diagnostics': self.tools.summary()}
