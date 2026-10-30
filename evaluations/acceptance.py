"""Conservative early-stop checks for bounded native continuation sampling."""


def clean_trial(result):
    """Only fully observed successful fixed-workspace trials may continue sampling."""
    try:
        metrics = result['upstream_metrics']
        diagnostic = result['event_diagnostics']
        fixture = result['workspace_fixture']
        if not (result['mode'] == 'live' and result['status'] == 'finished' and result['exit_code'] == 0
                and result['completed_turns'] > 0 and result['artifact_changed'] and result['model_evidence_valid']
                and result['score'] == {'status': 'scored', 'total': 18, 'passed': 18, 'failed': []}
                and result['tool_failure_events'] == result['error_events'] == 0
                and not result['rate_limit_detected'] and not result['event_trace_truncated']
                and fixture['unchanged'] and fixture['reader_unchanged']
                and metrics['fold_diagnostics_valid'] and metrics['diagnostics_version'] == 1
                and metrics['usage_complete'] and metrics['requests'] > 0
                and metrics['requests'] == metrics['completed'] == metrics['usage_reports']
                and all(metrics[name] == 0 for name in ('failed', 'parse_errors', 'unsupported_responses', 'tool_tracking_drops'))
                and diagnostic['counter_probes'] > 0 and not diagnostic['counter_probes_disabled']
                and all(diagnostic[name] == 0 for name in ('counter_probe_errors', 'tool_id_tracking_drops', 'unfinished_tracked_tools'))):
            return False
        client = result['client_reported_usage']
        mapping = {'input_tokens': 'input_tokens', 'cached_input_tokens': 'cached_tokens',
                   'output_tokens': 'output_tokens', 'reasoning_output_tokens': 'reasoning_tokens'}
        if not all(0 <= client[left] <= metrics[right] for left, right in mapping.items()):
            return False
        if client['reasoning_output_tokens'] != metrics['reasoning_tokens']:
            return False
        active = 0
        for event in result['event_trace']:
            if event['kind'] not in ('command_execution', 'file_change', 'mcp_tool_call'):
                continue
            if event['event'] == 'item.started':
                active += 1
            elif event['event'] == 'item.completed':
                active -= 1
                if event.get('status') == 'failed' or event.get('exit_code', 0) != 0:
                    return False
            if not 0 <= active <= 1:
                return False
        return active == 0
    except (KeyError, TypeError, ValueError):
        return False


def stop_reason(result):
    if not clean_trial(result):
        return 'non_clean_trial'
    metrics = result['upstream_metrics']
    if all(metrics.get(name, 0) > 0 for name in
           ('continuations', 'continued_tool_responses', 'continued_tool_calls', 'continued_tool_results')):
        return 'continuation_acceptance_observed'
    return None
