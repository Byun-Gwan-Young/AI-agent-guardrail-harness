"""scenario-v2 dialogue (T1) runs (C-17-4): docs/design/demo-runner-extension.md 2-4, decision 015, DM-16..DM-39.

One step is one role's turn with at most max_llm_calls_per_step model calls, as in the artifact path (protocol v10
step mechanics, unchanged). What differs:
- the session starts with the scenario's registration (DM-26, DM-29, DM-35); no registration, no run
- every turn's final report is output-contract-v3; the closed lists (status, handoff_to, deliverable enums) are sent
  to the provider only with --closed-list-check provider_strict, else checked after receipt (DM-20)
- the observation is built from the verified report's structured fields only (no narrative extraction, no reasoning)
- a value outside a closed list is a vocabulary violation (D-17): the step fails, the value is not observed and the
  violation stays out of the consecutive strict-failure stop; a shape error still counts there
- turn order: fixed, or the router (DM-19, CS only) that follows the verified report's handoff_to
- after each step the scenario judge reads the latest verified report and the tool call records
- a handoff_to naming the reporting role itself is a vocabulary violation (DM-44): counted, kept out of the
  observation; the report's other fields stay valid and the router falls back to the fixed order
- ends with success (DM-45: the declarer's own report is in the completion status, declares completion and passes the
  judge; a failed claim is recorded and the run goes on), escalated (the one terminal status, DM-18, DM-46),
  max_steps, guardrail_stop (block mode), strict_output_failures or runner_error

Tools are handed on through experiments/dialogue_tools.py; their implementations are C-17-6 (decision 018).
The artifact path (scenario-v1 and its requests) is untouched: experiments/run_scenario.py dispatches here only for
scenario-v2 dialogue tasks.
"""
import asyncio
import copy
import hashlib
import importlib.util
import json
import os
import shutil
import uuid
from importlib.metadata import version

import httpx

from experiments import cs_tools, dialogue_tools, search_tools
from experiments import run_scenario as common
from experiments.dialogue_contract import V3, VOCABULARY_VIOLATIONS_V3, for_dialogue_scenario
from experiments.observation_collection import INDEPENDENT, collection_metadata, select_sources
from experiments.step_execution import (NO_OUTPUT_PLACEHOLDER, PROTOCOL_V10, StrictFailureStreak, harness_facts,
                                        make_client, perform_step)
from progress_schema import Conversation, Observation
from scenario_schema import ESCALATED, registration_for

FLOW_VERSION = 'dialogue-flow-v1'
# DM-47: the name of what the next role receives from a turn (SHARED_FIELDS below), recorded with the run.
RECENT_MESSAGES_RULE = 't1-handoff-v1'
# DM-44: a well-formed handoff_to that names the reporting role itself. Only the runner knows the reporting role, so
# this vocabulary violation is found here, not by the contract (which checks the closed list of role IDs).
HANDOFF_TO_SELF = 'handoff_to_self'
# The judge and inputs_dir are repository paths; offline tests point this at their fixtures.
SCENARIO_ROOT = common.ROOT
CLOSED_LIST_CHECKS = ('after_receipt', 'provider_strict')
# DM-20: gateway strict-schema support with enums is not probed yet, so values are checked after receipt.
DEFAULT_CLOSED_LIST_CHECK = 'after_receipt'
JUDGE_RESULTS = ('resolved', 'escalated', 'unfinished')
# The verified report's state fields the next roles see with its narrative (recent_messages, kept by v10).
SHARED_FIELDS = ('status', 'handoff_to', 'adopted_items', 'deliverable')
OBSERVED_FIELDS = ('open_issue_ids', 'info_items', 'status', 'adopted_items', 'handoff_to')
STOP_DECISIONS = ('deadlock', 'termination_failure')
# DM-52 ④: printed by the pre-run check of a run with academic_search and kept in its record.
LR_ONE_AT_A_TIME = ('academic_search keeps the arXiv request interval inside this runner process only: '
                    'run one academic_search (LR) session at a time (DM-52)')


canonical_sha256 = common.canonical_sha256


def without_enums(schema):
    """The schema with every enum keyword removed; property names are kept even when one is called enum."""
    if isinstance(schema, list):
        return [without_enums(s) for s in schema]
    if not isinstance(schema, dict):
        return schema
    result = {}
    for key, value in schema.items():
        if key == 'enum':
            continue
        result[key] = ({name: without_enums(sub) for name, sub in value.items()}
                       if key in ('properties', '$defs') and isinstance(value, dict) else without_enums(value))
    return result


class SentContract:
    """output-contract-v3 as requested from the provider (DM-20). provider_strict sends the v3 strict schema as is;
    after_receipt sends the same strict shape without its enums. Parsing, instructions and reports are the
    contract's own in both modes, so a value outside a closed list is always caught after receipt."""

    def __init__(self, contract, mode):
        if mode not in CLOSED_LIST_CHECKS:
            raise ValueError('Unsupported closed-list check: ' + str(mode))
        self.contract, self.mode = contract, mode

    def __getattr__(self, name):
        return getattr(self.contract, name)

    def response_format(self):
        sent = self.contract.response_format()
        if self.mode == 'after_receipt':
            sent['json_schema']['schema'] = without_enums(sent['json_schema']['schema'])
        return sent


def load_judge(scenario, root):
    """The scenario's completion judge: judge(report, *, tool_records, inputs_dir) -> gate."""
    path = common.safe_path(root, scenario.judge)
    if not path.is_file():
        raise ValueError('Judge not found: ' + scenario.judge)
    spec = importlib.util.spec_from_file_location('scenario_judge_' + path.stem.replace('-', '_'), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not callable(getattr(module, 'judge', None)):
        raise ValueError('Judge module must define judge(report, *, tool_records, inputs_dir)')
    return module.judge, {'path': scenario.judge, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def checked_gate(gate):
    """demo-runner-extension.md 2: {machine_success, result: resolved|escalated|unfinished, missing}."""
    if (not isinstance(gate, dict) or set(gate) != {'machine_success', 'result', 'missing'}
            or type(gate['machine_success']) is not bool or gate['result'] not in JUDGE_RESULTS
            or not isinstance(gate['missing'], list) or not all(isinstance(m, str) for m in gate['missing'])
            or gate['machine_success'] != (gate['result'] == 'resolved')):
        raise ValueError('Judge must return {machine_success, result, missing} with machine_success only for resolved')
    return gate


def next_turn(scenario, current, report, failure=None):
    """(index of the next role, how it was chosen). Fixed order: the next role in the scenario list. Router (DM-19):
    the verified final report's handoff_to; without a usable one (no report, null, the same role) the fixed order.
    No model call and no model reasoning (demo-runner-extension.md 3)."""
    ids = [a.id for a in scenario.agents]
    fallback = (current + 1) % len(ids)
    handoff = (report or {}).get('handoff_to')
    route = {'turn_order': scenario.turn_order, 'from_agent': ids[current], 'handoff_to': handoff,
             'basis': 'verified_final_report' if report is not None else None}
    if scenario.turn_order == 'fixed':
        return fallback, {**route, 'next_agent': ids[fallback], 'rule': 'fixed_order', 'fallback_reason': None}
    if report is None:
        # A handoff_to outside the roles never yields a verified report (handoff_to_not_allowed).
        reason = failure or 'no_verified_final_report'
    elif handoff is None:
        reason = 'no_handoff'
    elif handoff == ids[current]:
        reason = 'self_handoff'
    elif handoff not in ids:
        reason = 'handoff_to_not_allowed'
    else:
        return ids.index(handoff), {**route, 'next_agent': handoff, 'rule': 'handoff_to', 'fallback_reason': None}
    return fallback, {**route, 'next_agent': ids[fallback], 'rule': 'fixed_order_fallback', 'fallback_reason': reason}


def system_message(agent, tool_names, scenario, schema_text):
    """Facts only: role text, its tools, the v8 harness facts (no writable files, call budget) and the contract."""
    return (agent.system_message + '\n' + dialogue_tools.tool_instructions(tool_names)
            + harness_facts(agent.writable_paths, scenario.termination.max_llm_calls_per_step)
            + "Final response must be one JSON object matching this schema. Report the full shared state, "
              "not only this role's issues.\n" + schema_text)


def shared_entry(agent, report):
    if report is None:
        return {'agent': agent, 'narrative': NO_OUTPUT_PLACEHOLDER}
    return {'agent': agent, 'narrative': report['narrative'], **{k: report[k] for k in SHARED_FIELDS}}


def step_context(scenario, tools, feedback, recent):
    return json.dumps({'task': scenario.task, 'registered_tools': tools, 'tool_feedback': feedback,
                       'initial_issue_ids': scenario.initial_issue_ids, 'recent_messages': recent}, ensure_ascii=False)


def observation(step, agent, turns, scenario, report, collection, termination, contract):
    """T1 observation from the verified report's structured fields only. Without one (a vocabulary violation, a
    shape error) every field is unobserved, so a violating value is neither an advance nor a retreat."""
    fields = ({k: report[k] for k in OBSERVED_FIELDS} if report is not None else
              {'open_issue_ids': None, 'info_items': None,
               'reasons': {'output': 'invalid or missing structured output'}})
    return Observation(step_id=step, agent_id=agent, llm_turns=turns, progress_source=scenario.progress_source,
                       progress_metric=scenario.progress_metric.model_dump(),
                       conversation=Conversation(source_kind='structured', **fields).model_dump(), artifact=None,
                       termination_context=termination, collection=collection,
                       issue_report=contract.report(report)).model_dump()


def completion_claim(scenario, agent, report, gate):
    """DM-45: a report claiming completion (the completion status, or completion_declared). It ends the run only when
    it is the declarer's own report, in the completion status, declared (when the scenario requires it) and passes
    the judge on that same report. No declaration carries over from an earlier step."""
    declarer = scenario.termination_context_collection.declarer_agent
    reasons = (['not_declarer'] * (agent != declarer)
               + ['status_not_completion'] * (report['status'] != scenario.status_values[-1].id)
               + ['not_declared'] * (scenario.termination.require_completion_declaration
                                     and report['completion_declared'] is not True)
               + ([] if gate['machine_success'] else ['judge_' + gate['result']]))
    return {'agent': agent, 'declarer': declarer, 'status': report['status'],
            'completion_declared': report['completion_declared'], 'gate': gate, 'accepted': not reasons,
            'reasons': reasons}


def ending(report, claim):
    """Termination reason after a non-failed step, or None to continue. DM-46: escalated is the only terminal status;
    any role's escalated report ends the run (DM-18: continuing would spend tokens after the task was declared
    defective), while success needs the declarer's own accepted claim (DM-45)."""
    if report['status'] == ESCALATED:
        return 'escalated'
    if claim is not None and claim['accepted']:
        return 'success'
    return None


def check_arguments(args, scenario):
    """Everything refused before a run folder exists."""
    if getattr(args, 'collection_policy', INDEPENDENT) != INDEPENDENT:
        raise ValueError('A dialogue task uses the independent collection policy')
    if getattr(args, 'output_contract', None) != V3:
        raise ValueError('A scenario-v2 dialogue task needs --output-contract ' + V3)
    if getattr(args, 'runner_protocol', None) != PROTOCOL_V10:
        raise ValueError('A scenario-v2 dialogue task runs with --runner-protocol ' + PROTOCOL_V10)
    if scenario.reasoning_effort is None:
        raise ValueError('runner protocol v10 requires scenario reasoning_effort')
    mode = getattr(args, 'closed_list_check', None) or DEFAULT_CLOSED_LIST_CHECK
    if mode not in CLOSED_LIST_CHECKS:
        raise ValueError('Unsupported closed-list check')
    evidence = scenario.reasoning_effort_evidence
    if evidence is not None and not common.safe_path(common.ROOT, evidence).is_file():
        raise ValueError('reasoning_effort_evidence file not found: ' + evidence)
    if args.run_index < 1 or (args.temperature is not None and not 0 <= args.temperature <= 2):
        raise ValueError('Invalid run index or temperature')
    return mode


def tool_preflight(scenario, root, environ):
    """C-17-6 part 3, before any external call and before a run folder exists: every tool of every role has an
    implementation, every key a used tool needs is in the environment (presence only; no value is read out or
    printed), and inputs_dir holds what the used tools read. Returns the record kept in conditions.json; raises
    ValueError naming every problem."""
    used = sorted({t for a in scenario.agents for t in a.tools})
    missing = dialogue_tools.missing_implementations(scenario)
    keys = {env: 'present' if environ.get(env) else 'missing'
            for env in sorted({search_tools.KEY_ENVS[t] for t in used if t in search_tools.KEY_ENVS})}
    inputs_dir = common.safe_path(root, scenario.inputs_dir)
    inputs = {t: cs_tools.input_problems(t, inputs_dir) for t in used if t in cs_tools.TOOLS}
    problems = (['Tools without an implementation: ' + ', '.join(missing)] * bool(missing)
                + ['Key environment variable not set: ' + env for env, state in keys.items() if state == 'missing']
                + ([] if inputs_dir.is_dir() else ['inputs_dir not found: ' + scenario.inputs_dir])
                + [f'{tool} input: {problem}' for tool, found in inputs.items() for problem in found
                   if problem != 'inputs_dir not found'])
    if problems:
        raise ValueError('Pre-run check failed: ' + '; '.join(problems))
    record = {'check': 'dialogue-tool-preflight-v1', 'tools_implemented': used, 'keys': keys,
              'inputs_dir': scenario.inputs_dir, 'input_problems': inputs}
    if 'academic_search' in used:
        # DM-52 ④: the arXiv interval is kept per runner process (decision 018); no lock between processes.
        record['notices'] = [LR_ONE_AT_A_TIME]
    return record


async def run_dialogue(args, scenario, scenario_path):
    from autogen_agentchat.agents import AssistantAgent

    mode = check_arguments(args, scenario)
    model_name, model_record = common.run_model(scenario, args)
    preflight = tool_preflight(scenario, SCENARIO_ROOT, os.environ)
    for notice in preflight.get('notices', []):
        print('notice:', notice, flush=True)
    key_env = getattr(args, 'api_key_env', None) or 'GROQ_API_KEY'
    key = os.environ.get(key_env)
    if not key:
        raise ValueError(key_env + ' is required')
    judge, judge_record = load_judge(scenario, SCENARIO_ROOT)
    inputs_dir = common.safe_path(SCENARIO_ROOT, scenario.inputs_dir)
    contract = for_dialogue_scenario(scenario)
    sent = SentContract(contract, mode)
    registration = registration_for(scenario)
    repository_state = common.git_state()
    dataset_run = bool(getattr(args, 'dataset_run', False))
    phase = getattr(args, 'phase', None)
    # deadlock-v0.3 judges only demo sessions (DM-10): a scenario-v2 run is never on the dataset path (DM-2).
    common.enforce_demo_track(dataset_run, phase)
    output_root = common.output_root_for(phase, getattr(args, 'output_root', None))
    session_id = scenario.scenario_id + '-' + uuid.uuid4().hex
    out = output_root / session_id
    out.mkdir(parents=True, exist_ok=False)
    temperature = scenario.temperature if args.temperature is None else args.temperature
    buffer_messages = (None if args.no_context_buffer else args.context_buffer_messages
                       if args.context_buffer_messages is not None else scenario.context_buffer_messages)
    if buffer_messages is not None and buffer_messages < 1:
        raise ValueError('Context buffer must be positive')
    if args.seed_probe is not None and scenario.seed_support != 'unverified':
        raise ValueError('--seed-probe is only for unverified support')
    versions = {p: version(p) for p in ('autogen-agentchat', 'autogen-core', 'autogen-ext', 'openai')}
    # C-17-6: search tools store every response in the run folder; their settings are the scenario's (decision 018).
    tool_settings = scenario.tool_settings.model_dump(exclude_none=True) if scenario.tool_settings else {}
    search = search_tools.SearchSession(tool_settings, out) if tool_settings else None
    dispatch = dialogue_tools.ToolDispatch(dialogue_tools.IMPLEMENTATIONS, inputs_dir,
                                           {'search': search} if search is not None else None)
    evidence = scenario.reasoning_effort_evidence
    effective = {
        'scenario': scenario.model_dump(), 'model': model_record, 'temperature': temperature, 'versions': versions,
        'actual_outcome': None,
        'seed_support': scenario.seed_support, 'session_id': session_id, 'run_index': args.run_index,
        'context_buffer_messages': buffer_messages, 'seed_probe': args.seed_probe,
        'requested_seed': args.seed_probe if args.seed_probe is not None else scenario.seed,
        'runner_protocol': PROTOCOL_V10, 'collection_policy': INDEPENDENT, 'output_contract': V3,
        'output_contract_version': V3, 'allowed_issues_sha256': contract.sha256,
        'contract_sha256': contract.contract_sha256,
        'closed_list_check': {'mode': mode, 'decision': 'DM-20', 'enums_sent_to_provider': mode == 'provider_strict',
                              'basis': ('default until a gateway strict probe (DM-20)' if mode == DEFAULT_CLOSED_LIST_CHECK
                                        else 'run condition')},
        'strict_support': 'unverified', 'strict_probe': None,
        'strict_failure_policy': 'fail step; abort after two consecutive strict-failed steps; vocabulary violations '
                                 '(issue IDs, status, handoff_to) fail the step, are not observed, are excluded from '
                                 'that streak and counted separately; no automatic B fallback',
        'task_kind': 'dialogue', 'turn_order': scenario.turn_order, 'dialogue_flow': FLOW_VERSION,
        'recent_messages_rule': RECENT_MESSAGES_RULE,
        'routing_policy': ('router: next role = handoff_to of the verified final report; fixed order when there is '
                           'none, it is null or the same role (DM-19)' if scenario.turn_order == 'router'
                           else 'fixed order; handoff_to recorded only'),
        'recent_messages_policy': 'narrative plus status, handoff_to, adopted_items, deliverable of the parsed or '
                                  'verified final report; placeholder narrative only without one; no raw tool results',
        'harness_facts_policy': 'system message states writable files (none) and the per-step call limit; each '
                                'non-final call carries its call number and remaining calls (G0-14)',
        'reasoning_effort': {'requested': scenario.reasoning_effort, 'sent_on': 'all_calls',
                             'applied': 'probe_indicated' if evidence else 'unverified', 'evidence': evidence},
        'registration': registration, 'registration_sha256': canonical_sha256(registration),
        'judge': judge_record, 'inputs_dir': scenario.inputs_dir,
        'tools': {a.id: list(a.tools) for a in scenario.agents}, 'tool_implementations': dispatch.identity(),
        'tool_settings': tool_settings or None, 'tool_preflight': preflight,
        'search': search_tools.conditions_record(tool_settings) if tool_settings else None,
        'dataset_run': dataset_run, 'phase': phase, **repository_state}
    conditions_path = out / 'conditions.json'
    common.save(conditions_path, effective)
    print('session_id:', session_id, 'run_directory:', out, flush=True)
    shutil.copy2(scenario_path, out / 'scenario.yaml')
    headers = {'X-Guardrail-Session': session_id, 'X-Guardrail-Scenario': scenario.scenario_id,
               'X-Guardrail-Run-Index': str(args.run_index),
               'X-Guardrail-Framework-Version': 'autogen-agentchat/' + versions['autogen-agentchat'],
               'X-Guardrail-Context-Buffer-Messages': str(buffer_messages) if buffer_messages is not None else 'none',
               'X-Guardrail-Phase': phase}
    budget = common.CallBudget(scenario.termination.max_llm_calls_per_step, sent, scenario.reasoning_effort,
                               final_report_allowlist=True)
    base = args.proxy_url.rstrip('/').removesuffix('/v1')
    model_http = httpx.AsyncClient(event_hooks={'response': [budget.capture]})
    options = dict(model=model_name, api_key=key, base_url=base + '/v1', default_headers=headers,
                   http_client=model_http, max_retries=0, temperature=temperature, max_tokens=scenario.max_tokens,
                   model_info={'vision': False, 'function_calling': True, 'json_output': True,
                               'structured_output': True, 'family': 'unknown'})
    if scenario.seed_support == 'supported':
        options['seed'] = scenario.seed
    elif args.seed_probe is not None:
        options['seed'] = args.seed_probe
    model = make_client(options, budget)
    schema_text = json.dumps(contract.schema(), ensure_ascii=False) + '\n' + contract.instructions()
    role_names = [list(a.tools) for a in scenario.agents]
    common.save(out / 'registered-tools.json', dict(zip([a.id for a in scenario.agents], role_names)))
    agents = [AssistantAgent(a.id, model_client=model, tools=dispatch.tools(role_names[i]),
                             model_context=common.make_model_context(buffer_messages),
                             reflect_on_tool_use=False, model_client_stream=False,
                             system_message=system_message(a, role_names[i], scenario, schema_text))
              for i, a in enumerate(scenario.agents)]
    declarer = scenario.termination_context_collection.declarer_agent
    steps, missing, observation_first, claims = [], [], None, []
    reason, error, session, started = 'max_steps', None, None, False
    guardrail_block, escalated_by, latest_report, gate = None, None, None, None
    history, cursors, pending_feedback = [], [0] * len(agents), [None] * len(agents)
    strict_streak = StrictFailureStreak()
    vocabulary_streak, vocabulary_total = StrictFailureStreak(), 0
    index = 0
    async with httpx.AsyncClient(base_url=base, headers=headers, timeout=60) as client:
        try:
            # Registered once, with the session (DM-35). A scenario-v2 session never runs unregistered.
            response = await client.post('/sessions', json={'registration': registration})
            if response.is_error:
                raise ValueError(f'Proxy refused the session ({response.status_code}): {response.text[:300]}')
            started = True
            if response.json().get('registered') is not True:
                raise ValueError('The proxy did not register the session')
            pin_response = await client.get('/log')
            pin_response.raise_for_status()
            meta = pin_response.json()['meta']
            if meta.get('criteria_version') != scenario.criteria_version:
                raise ValueError('Proxy criteria version differs from scenario')
            if meta.get('registration') != registration:
                raise ValueError('The proxy stored a different registration')
            common.ensure_key_env(meta.get('upstream'), key_env)
            effective.update(api_key_env=key_env, upstream=meta.get('upstream'),
                             guardrail_mode=meta.get('guardrail_mode'))
            common.save(conditions_path, effective)
            common.enforce_observe_proxy(dataset_run, meta.get('guardrail_mode'))
            for step in range(1, scenario.termination.max_steps + 1):
                name = agents[index].name
                budget.reset()
                dispatch.step_id, dispatch.agent_id = step, name
                text, parsed, call_error = '', None, None
                context = step_context(scenario, role_names[index], pending_feedback[index], history[cursors[index]:])
                outcome = await perform_step(agents[index], context, budget, role_names[index], budget_notes=True,
                                             tool_text=dialogue_tools.tool_instructions,
                                             correct=dialogue_tools.correction)
                if outcome['blocked'] is not None:
                    # Block mode refused this step's request after a STOP (DM-7, DM-23); no output, no observation.
                    guardrail_block = {**outcome['blocked'], 'blocked_step': step}
                    steps.append({'step_id': step, 'agent': name, 'text': '', 'llm_calls': budget.used,
                                  'llm_turns': sorted(set(budget.turns)), 'completion_gate': None, 'call_error': None,
                                  'step_status': 'blocked', 'measurement_status': 'unmeasured',
                                  'tool_errors': outcome['tool_errors'], 'tool_executions': outcome['tool_executions'],
                                  'final_output': False, 'failure_reasons': outcome['failure_reasons'],
                                  'guardrail_stop': guardrail_block})
                    common.save(out / 'steps.json', steps)
                    reason = 'guardrail_stop'
                    break
                vocabulary = outcome['strict_failure'] if outcome['strict_failure'] in VOCABULARY_VIOLATIONS_V3 else None
                # D-17: a vocabulary violation is not a strict failure for the stop streak.
                stop_for_strict = strict_streak.observe(outcome['strict_failure'] if vocabulary is None else None)
                text, call_error = outcome['text'], outcome['error']
                pending_feedback[index] = outcome['feedback']
                if not outcome['failed']:
                    try:
                        parsed = contract.parse(text)
                        parsed.update(agent_id=name, step_id=step)
                    except (ValueError, TypeError) as exc:
                        outcome['failed'] = True
                        outcome['final_output'] = False
                        outcome['failure_reasons'].append(getattr(exc, 'code', 'no_final_output'))
                        outcome['feedback'] = '최종 구조화 JSON이 유효하지 않다. 다음 차례에는 지정된 스키마로 응답하라.'
                        pending_feedback[index] = outcome['feedback']
                        call_error = 'invalid_final_output: ' + type(exc).__name__
                receipt = outcome['observation_report']
                shared, shared_source = parsed, 'parsed' if parsed else 'placeholder'
                if shared is None and receipt['status'] == 'valid':
                    # G0-13: a verified final report of a failed step is shared, not hidden.
                    shared, shared_source = receipt['value'], 'verified_final_report'
                history.append(shared_entry(name, shared))
                cursors[index] = len(history)
                observed, _ = select_sources(INDEPENDENT, failed=outcome['failed'], legacy_parsed=parsed,
                                             final_report=receipt, artifact=None)
                if observed is not None:
                    observed.update(agent_id=name, step_id=step)
                    latest_report = observed
                # DM-44: a contract vocabulary violation leaves no verified report, so the two never meet.
                self_handoff = observed is not None and observed['handoff_to'] == name
                if self_handoff:
                    vocabulary = HANDOFF_TO_SELF
                vocabulary_streak.observe(vocabulary)
                vocabulary_total += vocabulary is not None
                # Observation declaration must not alter execution success/stop control.
                observation_first, termination = common.termination_context(observation_first, observed, step,
                                                                             declarer)
                gate = checked_gate(judge(copy.deepcopy(latest_report), tool_records=copy.deepcopy(dispatch.records),
                                          inputs_dir=inputs_dir))
                metadata = collection_metadata(INDEPENDENT, receipt, observed, None, scenario.progress_source,
                                               scenario.progress_metric.model_dump())
                next_index, route = next_turn(scenario, index, observed, outcome['strict_failure'])
                tool_execution_error = any(e['is_error'] for e in outcome['tool_executions'])
                record = {'step_id': step, 'agent': name, 'text': text, 'llm_calls': budget.used,
                          'llm_turns': sorted(set(budget.turns)), 'completion_gate': gate, 'call_error': call_error,
                          'step_status': 'failed' if outcome['failed'] or tool_execution_error else 'completed',
                          'tool_errors': outcome['tool_errors'], 'tool_feedback': outcome['feedback'],
                          'tool_executions': outcome['tool_executions'],
                          'tool_dispatch_seq': [r['seq'] for r in dispatch.records_for(step)],
                          'final_output': outcome['final_output'],
                          'failure_reasons': outcome['failure_reasons'] + ['tool_execution_error'] * tool_execution_error,
                          'strict_used': outcome['strict_used'], 'strict_failure': outcome['strict_failure'],
                          'consecutive_strict_failures': strict_streak.count, 'shared_narrative_source': shared_source,
                          'vocabulary_violation': vocabulary,
                          'consecutive_vocabulary_violations': vocabulary_streak.count,
                          'vocabulary_violations_total': vocabulary_total, 'collection': metadata,
                          'observed_final_report': observed, 'measurement_status': metadata['measurement_status'],
                          'route': route}
                claim = None
                if not outcome['failed'] and (parsed['status'] == scenario.status_values[-1].id
                                              or parsed['completion_declared']):
                    # DM-45: judged on this report itself, not on an earlier one or another role's.
                    claim = completion_claim(scenario, name, parsed, checked_gate(judge(
                        copy.deepcopy(parsed), tool_records=copy.deepcopy(dispatch.records), inputs_dir=inputs_dir)))
                    claims.append({'step_id': step, **claim})
                    record['completion_claim'] = claim
                steps.append(record)
                common.save(out / 'steps.json', steps)
                common.save(out / 'tool-dispatch.json', dispatch.records)
                if not budget.turns:
                    missing.append(step)
                    raise RuntimeError('No proxy turn ID; cannot submit a linked observation')
                # DM-44: the self-naming handoff_to is left out of the observation; the other fields are observed.
                payload = observation(step, name, record['llm_turns'], scenario,
                                      {**observed, 'handoff_to': None} if self_handoff else observed, metadata,
                                      termination, contract)
                common.save(out / 'observations' / f'{step}.pending.json', payload)
                try:
                    ack = await common.deliver(client, session_id, payload)
                except Exception:
                    missing.append(step)
                    raise
                common.save(out / 'observations' / f'{step}.ack.json', ack)
                record['observation'] = ack['observation']
                try:
                    log_response = await client.get('/log')
                    log_response.raise_for_status()
                    trace = common.prompt_trace(steps, log_response.json())
                    record['prompt_tokens'] = trace[-1]
                    common.save(out / 'prompt-trend.json', trace)
                    print(json.dumps({'step_id': step, 'agent': name, 'next_agent': route['next_agent'],
                                      'prompt_tokens_sum': trace[-1]['prompt_tokens_sum']}, ensure_ascii=False),
                          flush=True)
                except (httpx.HTTPError, ValueError, KeyError) as exc:
                    record['prompt_trace_error'] = type(exc).__name__
                common.save(out / 'steps.json', steps)
                if stop_for_strict:
                    reason, error = 'strict_output_failures', 'two_consecutive_strict_failed_steps'
                    break
                if outcome['abort']:
                    raise RuntimeError(call_error or 'step_aborted')
                index = next_index
                if outcome['failed']:
                    continue
                ended = ending(parsed, claim)
                if ended is not None:
                    reason = ended
                    escalated_by = name if ended == 'escalated' else None
                    break
        except asyncio.CancelledError:
            reason, error = 'user_interrupted', 'Cancelled by user'
        except Exception as exc:
            reason, error = 'runner_error', type(exc).__name__ + ': ' + str(exc)
        finally:
            cleanup_errors = []
            if started:
                for attempt in range(3):
                    try:
                        response = await client.post('/sessions/end', json={'termination_reason': reason})
                        response.raise_for_status()
                        break
                    except httpx.HTTPError as exc:
                        if attempt == 2:
                            cleanup_errors.append('end: ' + str(exc))
                try:
                    response = await client.get('/log')
                    response.raise_for_status()
                    session = response.json()
                    common.save(out / 'session.json', session)
                    common.save(out / 'prompt-trend.json', common.prompt_trace(steps, session))
                except httpx.HTTPError as exc:
                    cleanup_errors.append('log: ' + str(exc))
            await model.close()
            await model_http.aclose()
            turns = session.get('turns', []) if session else []
            values = [t.get('tokens') for t in turns]
            criteria = [s['observation']['criteria'] for s in steps if 'observation' in s]
            summary = {
                'session_id': session_id, 'steps': len(steps), 'termination_reason': reason,
                'total_tokens': sum(values) if session is not None and
                    len(turns) == sum(s['llm_calls'] for s in steps) and all(v is not None for v in values) else None,
                'known_tokens_subtotal': sum(v for v in values if v is not None),
                'criteria_latest': criteria[-1] if criteria else {'decision': 'unmeasured'},
                'criteria_alerts': [c for c in criteria if c.get('decision') in STOP_DECISIONS],
                'missing_observation_steps': missing, 'missing_observation_count': len(missing), 'error': error,
                'cleanup_errors': cleanup_errors, 'actual_outcome': None, 'context_buffer_messages': buffer_messages,
                'task_kind': 'dialogue', 'turn_order': scenario.turn_order, 'output_contract_version': V3,
                'registration_sha256': effective['registration_sha256'],
                'vocabulary_violation_steps': [s['step_id'] for s in steps if s.get('vocabulary_violation')],
                'vocabulary_violations_total': vocabulary_total,
                'failed_steps': [{'step_id': s['step_id'], 'reasons': s.get('failure_reasons', [])}
                                 for s in steps if s.get('step_status') == 'failed'],
                'final_status': (latest_report or {}).get('status'), 'escalated_by': escalated_by,
                'completion_gate': gate,
                'completion_claims': [{k: c[k] for k in ('step_id', 'agent', 'status', 'completion_declared',
                                                         'accepted', 'reasons')} for c in claims],
                'recent_messages_rule': RECENT_MESSAGES_RULE,
                'route_fallbacks': [{'step_id': s['step_id'], 'reason': s['route']['fallback_reason']}
                                    for s in steps if (s.get('route') or {}).get('fallback_reason')],
                'search': search.summary() if search is not None else None}
            if guardrail_block is not None:
                summary['guardrail_stop'] = guardrail_block
            common.save(out / 'summary.json', summary)
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            print('run_directory:', out)
    return 1 if error or cleanup_errors else 0
