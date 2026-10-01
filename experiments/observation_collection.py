"""Versioned input collection only; does not change progress or criteria policy."""
import copy
from experiments.output_contract import parse_output

LEGACY = 'legacy-failed-step-v1'
INDEPENDENT = 'independent-sources-v1'
DEFAULT_POLICY = INDEPENDENT
PROTOCOLS = {LEGACY: 'tool-capable-step-v5-strict',
             INDEPENDENT: 'tool-capable-step-v6-independent-observations'}


def unavailable(reason, status='unmeasured', source_turn=None):
    return {'status': status, 'source_turn': source_turn, 'value': None, 'reason': reason}


def validate_final_response(*, request, response, status_code, turn, step_turns, contract=None):
    """Require evidence of a linked, complete, tool-free strict final report."""
    if type(turn) is not int or turn not in step_turns:
        return unavailable('final response not linked to this step')
    if not isinstance(request, dict) or not isinstance(response, dict):
        return unavailable('request/response body unavailable', source_turn=turn)
    fmt = request.get('response_format') or {}
    if (not isinstance(fmt, dict) or fmt.get('type') != 'json_schema'
            or not isinstance(fmt.get('json_schema'), dict)
            or fmt['json_schema'].get('strict') is not True or request.get('tools')):
        return unavailable('not a tool-free strict final request', source_turn=turn)
    if type(status_code) is not int or not 200 <= status_code < 300:
        return unavailable('final HTTP response unsuccessful', source_turn=turn)
    choices = response.get('choices')
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        return unavailable('ambiguous or missing final choice', 'invalid', turn)
    choice = choices[0]; message = choice.get('message') or {}
    if (choice.get('finish_reason') != 'stop' or not isinstance(message, dict)
            or message.get('role') != 'assistant' or message.get('tool_calls')
            or message.get('function_call') or not isinstance(message.get('content'), str)):
        return unavailable('incomplete final response or tool result', 'invalid', turn)
    try:
        value = (contract.parse if contract is not None else parse_output)(message['content'])
    except (ValueError, TypeError) as exc:
        code = getattr(exc, 'code', None)
        return unavailable('final output contract violation' + (': ' + code if code else ''), 'invalid', turn)
    return {'status': 'valid', 'source_turn': turn, 'value': value, 'reason': None}


def select_sources(policy, *, failed, legacy_parsed, final_report, artifact):
    if policy not in PROTOCOLS:
        raise ValueError('Unsupported collection policy')
    if policy == LEGACY:
        return legacy_parsed, None if failed else artifact
    parsed = (copy.deepcopy(final_report['value'])
              if final_report and final_report.get('status') == 'valid' else None)
    return parsed, artifact


def collection_metadata(policy, receipt, parsed, artifact, progress_source, metrics):
    """Raw selected-field coverage; not a progress verdict or task-success flag."""
    states, reasons = {}, {}
    sources = ('conversation', 'artifact') if progress_source == 'both' else (progress_source,)
    fields = {'proposal_value_delta':'proposal_values', 'open_issues_count':'open_issue_ids',
              'new_info_ratio':'info_items', 'files_changed':'file_hashes',
              'test_pass_count':'test_pass_count', 'build_status':'build_status',
              # T1 metrics (output-contract-v3 fields, C-17-4); the same field names progress-v3 reads.
              'status_advance':'status', 'adopted_items':'adopted_items', 'new_issue_ids':'open_issue_ids'}
    for source in sources:
        values = parsed if source == 'conversation' else artifact
        for metric in metrics.get(source, []):
            key = source + '.' + metric
            value = (values or {}).get(fields[metric])
            measured = value is not None and value != 'not_run'
            states[key] = 'measured' if measured else 'unmeasured'
            if not measured:
                reasons[key] = ((values or {}).get('reasons', {}).get(fields[metric])
                                or 'selected field not measured')
    measured = [v == 'measured' for v in states.values()]
    aggregate = 'observed' if measured and all(measured) else 'partial' if any(measured) else 'unmeasured'
    return {'policy': policy, 'final_output_status': receipt['status'],
            'final_output_reason': receipt['reason'], 'source_turn': receipt['source_turn'],
            'measurement_status': aggregate, 'metric_status': states, 'reasons': reasons}
