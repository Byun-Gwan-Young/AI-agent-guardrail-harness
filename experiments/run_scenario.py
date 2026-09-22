"""Explicit single-run CLI. Importing this module never starts an experiment."""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid
from importlib.metadata import version

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import httpx
from pydantic import BaseModel, ConfigDict
from progress_schema import Conversation
from artifact_hook import capture_artifact, make_observation, submit_observation
from scenario_schema import load_scenario
from scenario_checks import check_acceptance
from suite_identity import compute_test_suite_id
from experiments.step_execution import (FINAL_REASONING_EFFORT, NO_OUTPUT_PLACEHOLDER, PROTOCOL_V7, PROTOCOL_V8,
                                        PROTOCOL_V9, PROTOCOL_V10, edit_instructions, harness_facts, make_client, perform_step,
                                        tool_instructions)
from experiments.output_contract import AgentOutput, parse_output
from experiments.issue_contract import (IssueContract, V1, V2, VERSIONS, PROTOCOL_V2, VOCABULARY_VIOLATIONS,
                                        for_scenario)
from experiments.step_execution import StrictFailureStreak
from experiments.observation_collection import (DEFAULT_POLICY, INDEPENDENT, LEGACY, PROTOCOLS,
    unavailable, validate_final_response, select_sources, collection_metadata)


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def fingerprint(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*')) if p.is_file()
            and '__pycache__' not in p.parts and p.suffix != '.pyc'}


def git_state(root=ROOT):
    """Record the exact checkout used by a run; missing Git data stays explicitly unmeasured."""
    try:
        commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root, check=True,
                                capture_output=True, text=True).stdout.strip()
        status = subprocess.run(['git', 'status', '--porcelain', '--untracked-files=all'], cwd=root,
                                check=True, capture_output=True, text=True).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        return {'git_commit': None, 'git_dirty': None, 'git_state_status': 'unmeasured',
                'git_state_reason': type(exc).__name__}
    return {'git_commit': commit, 'git_dirty': bool(status.strip()), 'git_state_status': 'measured',
            'git_state_reason': None}


def enforce_dataset_clean(dataset_run, state):
    # S-7: a dataset session must prove its code, so an unknown checkout is refused like a dirty one.
    if dataset_run and state['git_dirty'] is not False:
        raise ValueError('--dataset-run requires a clean Git working tree'
                         + (' (Git state unmeasured)' if state['git_dirty'] is None else ''))


def safe_path(root, relative):
    p = Path(relative)
    target = (root / p).resolve()
    if p.is_absolute() or '..' in p.parts or not target.is_relative_to(root.resolve()):
        raise ValueError('Path must stay within the copied workspace')
    return target


def make_model_context(buffer_messages):
    from autogen_core.model_context import BufferedChatCompletionContext, UnboundedChatCompletionContext
    return (UnboundedChatCompletionContext() if buffer_messages is None else
            BufferedChatCompletionContext(buffer_size=buffer_messages))


def prompt_trace(steps, session):
    turns = {t['turn']: t for t in session.get('turns', [])}
    rows = []
    for step in steps:
        linked = [turns.get(n, {}) for n in step['llm_turns']]
        values = [t.get('prompt_tokens') for t in linked]
        complete = len(values) == step['llm_calls'] and all(v is not None for v in values)
        rows.append({'step_id': step['step_id'], 'agent': step['agent'],
            'llm_turns': step['llm_turns'], 'prompt_tokens_per_call': values,
            'prompt_tokens_sum': sum(values) if complete else None,
            'known_prompt_tokens_subtotal': sum(v for v in values if v is not None),
            'seed_audit': [t.get('seed_audit') for t in linked]})
    return rows


class CallBudget:
    def __init__(self, limit, contract=None, all_calls_reasoning_effort=None, final_report_allowlist=False):
        self.contract = contract if contract is not None else IssueContract(V1)
        self.all_calls_reasoning_effort = all_calls_reasoning_effort
        self.final_report_allowlist = final_report_allowlist
        self.limit, self.used, self.turns = limit, 0, []
        self.final_next, self.strict_used = False, False
        self.final_report = unavailable("no verified final report")
        self.response_evidence = None

    def reset(self):
        self.used, self.turns = 0, []
        self.final_next, self.strict_used = False, False
        self.final_report = unavailable("no verified final report")
        self.response_evidence = None

    def consume(self):
        if self.used >= self.limit:
            raise RuntimeError('max_llm_calls_per_step reached')
        self.used += 1
        self.final_report = unavailable("no verified final report")
        self.response_evidence = None

    async def capture(self, response):
        turn = response.headers.get('X-Guardrail-Turn')
        if turn is not None:
            self.turns.append(int(turn))
        # Read the same response body once; no extra request. Never log credentials.
        try:
            await response.aread()
            self.response_evidence = dict(request=json.loads(response.request.content),
                response=response.json(), status_code=response.status_code,
                turn=int(turn) if turn is not None else None)
        except (ValueError, RuntimeError, TypeError):
            self.response_evidence = None

    def confirm_final_report(self, content):
        if self.response_evidence is None:
            self.final_report = unavailable('final HTTP evidence unavailable')
            return
        receipt = validate_final_response(**self.response_evidence, step_turns=self.turns, contract=self.contract)
        if receipt['status'] == 'valid' and receipt['value'] != self.contract.parse(content):
            receipt = unavailable('SDK and HTTP output mismatch', 'invalid', receipt['source_turn'])
        self.final_report = receipt

    def observation_report(self):
        if self.final_report['status'] == 'valid':
            return self.final_report
        if self.response_evidence is not None:
            receipt = validate_final_response(**self.response_evidence, step_turns=self.turns, contract=self.contract)
            if receipt['status'] != 'valid':
                return receipt
        return self.final_report


async def deliver(client, session_id, payload, sleep=asyncio.sleep):
    """Same immutable payload/step ID for initial submission and three retries."""
    for attempt in range(4):
        try:
            result = await submit_observation(client, session_id, payload)
            if result.get('persisted'):
                return result
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code < 500 and exc.response.status_code != 429:
                raise
        except httpx.TransportError:
            pass
        if attempt < 3:
            await sleep(2 ** attempt)
    raise RuntimeError('Observation not durably acknowledged after four attempts')


def termination_context(first, parsed, step, reviewer):
    if first is None and parsed and parsed['agent_id'] == reviewer and parsed['completion_declared']:
        first = step
    if first is not None:
        return first, dict(declaration='declared', declared_step=first,
                          source_kind='scenario_rule', evidence=f'reviewer completion_declared at step {first}')
    return None, dict(declaration='none' if parsed else 'unknown',
                      source_kind='scenario_rule', evidence=f'step {step}: ' +
                      ('valid structured output; no reviewer declaration' if parsed else 'structured output missing or invalid'))


def ensure_key_env(upstream, key_env):
    """The runner must read the key the proxy's own upstream configuration names (D-27)."""
    configured = (upstream or {}).get('api_key_env')
    if configured not in (None, key_env):
        raise ValueError('Proxy expects the key from ' + configured + ', not ' + key_env)


def role_system_message(agent, tool_names, scenario, schema_text, facts):
    """Role system prompt. Shared with the offline provider probe so the two cannot drift."""
    return (agent.system_message + '\nUse tools to inspect/edit the actual workspace. '
            + tool_instructions(tool_names) + edit_instructions(tool_names)
            + (harness_facts(agent.writable_paths, scenario.termination.max_llm_calls_per_step) if facts else '') +
            'Final response must be one JSON object matching this schema. Report the full shared state, '
            'not only this role\'s issues. Never claim tests passed without running them.\n' + schema_text)


def schema_instructions(contract, root=ROOT):
    """The schema block appended to every role prompt, per output contract version."""
    if contract.version == V2:
        return json.dumps(contract.schema(), ensure_ascii=False) + '\n' + contract.instructions()
    return (root / 'scenarios/agent-output.schema.json').read_text(encoding='utf-8')


class Workspace:
    def __init__(self, scenario, root):
        self.scenario, self.root, self.counter = scenario, root, 0

    def acceptance(self):
        self.counter += 1
        report = self.root / '.runner-reports' / str(self.counter)
        report.mkdir(parents=True)
        suite = self.scenario.success_criteria.test_suite
        identity = compute_test_suite_id(self.root, suite.test_roots, suite.contract_files, suite.command)
        command = [s.replace('{python}', sys.executable).replace('{report_dir}', str(report))
                   for s in suite.command]
        # Do not pass provider credentials into candidate code. This is not an OS sandbox.
        env = {k: v for k, v in os.environ.items()
               if k.upper() in {'SYSTEMROOT', 'WINDIR', 'PATH', 'TEMP', 'TMP', 'COMSPEC'} }
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        failure = None
        try:
            result = subprocess.run(command, cwd=self.root, env=env, capture_output=True,
                                    text=True, encoding='utf-8', errors='replace', timeout=90)
            save(report / 'process.json', {'returncode': result.returncode,
                 'stdout': result.stdout, 'stderr': result.stderr})
            summary = json.loads((report / 'summary.json').read_text(encoding='utf-8'))
            gate = check_acceptance(self.scenario, self.root, summary)
            if result.returncode not in (0, 1):
                gate['machine_success'] = False
        except (subprocess.TimeoutExpired, OSError, ValueError, KeyError) as exc:
            failure = str(exc)
            summary = {'passed': None, 'tests': None}
            gate = {'machine_success': False, 'reason': 'acceptance_unmeasured'}
        artifact = capture_artifact(self.root, self.scenario.monitored_paths,
            junit_path=report / 'junit.xml' if failure is None else None, test_suite_id=identity)
        return {'summary': summary, 'gate': gate, 'artifact': artifact, 'error': failure}

    def tools(self, agent):
        def read_file(path: str) -> str:
            """Read a UTF-8 file relative to the candidate workspace."""
            return safe_path(self.root, path).read_text(encoding='utf-8')

        def writable(path):
            target = safe_path(self.root, path)
            if target not in {safe_path(self.root, p) for p in agent.writable_paths}:
                raise ValueError('Role is not authorized to edit this file')
            return target

        def write_file(path: str, content: str) -> str:
            """Replace an authorized candidate file with complete UTF-8 content."""
            writable(path).write_text(content, encoding='utf-8')
            return 'written: ' + path

        def replace_in_file(path: str, old: str, new: str) -> str:
            """Replace exactly one occurrence of old with new in an authorized candidate file."""
            target = writable(path)
            text = target.read_text(encoding='utf-8')
            count = text.count(old) if old else 0
            if count != 1:
                raise ValueError(f'old must occur exactly once in {path}; found {count}')
            target.write_text(text.replace(old, new, 1), encoding='utf-8')
            return 'replaced in: ' + path

        async def run_tests() -> str:
            """Run the fixed acceptance command and return measured results."""
            measured = await asyncio.to_thread(self.acceptance)
            return json.dumps({k: measured[k] for k in ('summary', 'gate')}, ensure_ascii=False)

        return [tool for permission, tool in [('read_files', read_file), ('write_files', write_file),
                ('write_files', replace_in_file), ('run_tests', run_tests)] if permission in agent.permissions]


async def run(args):
    # Imports are deferred so --help and local helper tests do not construct clients.
    from autogen_agentchat.agents import AssistantAgent

    collection_policy = getattr(args, "collection_policy", DEFAULT_POLICY)
    if collection_policy not in PROTOCOLS:
        raise ValueError("Unsupported collection policy")
    scenario_path = args.scenario.resolve()
    scenario = load_scenario(scenario_path)
    contract = for_scenario(getattr(args, 'output_contract', V2), scenario)
    if contract.version == V2 and collection_policy != INDEPENDENT:
        # v7 extends the v6 independent-observation protocol; no other combination is labelled.
        raise ValueError('output-contract-v2 requires the independent collection policy')
    requested_protocol = getattr(args, 'runner_protocol', None)
    if contract.version != V2 and requested_protocol is not None:
        raise ValueError('--runner-protocol applies only to output-contract-v2')
    if requested_protocol not in (None, PROTOCOL_V7, PROTOCOL_V8, PROTOCOL_V9, PROTOCOL_V10):
        raise ValueError('Unsupported runner protocol')
    # D-25: no default. Several people run sessions, so the protocol is always stated explicitly.
    if contract.version == V2 and requested_protocol is None:
        raise ValueError('--runner-protocol is required for output-contract-v2')
    runner_protocol = requested_protocol if contract.version == V2 else PROTOCOLS[collection_policy]
    facts = runner_protocol in (PROTOCOL_V8, PROTOCOL_V9, PROTOCOL_V10)
    # The scenario's reasoning_effort and protocol v9 go together, so neither is ignored silently.
    reasoning_protocol = runner_protocol in (PROTOCOL_V9, PROTOCOL_V10)
    if reasoning_protocol != (scenario.reasoning_effort is not None):
        raise ValueError('runner protocol v9 or v10 requires scenario reasoning_effort, and reasoning_effort '
                         'requires runner protocol v9 or v10')
    evidence = scenario.reasoning_effort_evidence
    if evidence is not None and not safe_path(ROOT, evidence).is_file():
        raise ValueError('reasoning_effort_evidence file not found: ' + evidence)
    if {a.id for a in scenario.agents} != {'planner', 'developer', 'reviewer'}:
        raise ValueError('This runner currently supports the approved three-role artifact scenario')
    if scenario.success_criteria.test_suite is None or not scenario.fixture_dir:
        raise ValueError('Executable artifact fixture required')
    if args.run_index < 1 or (args.temperature is not None and not 0 <= args.temperature <= 2):
        raise ValueError('Invalid run index or temperature')
    # The provider is chosen by the proxy config; the runner only forwards the key it is told to read.
    key_env = getattr(args, 'api_key_env', None) or 'GROQ_API_KEY'
    key = os.environ.get(key_env)
    if not key:
        raise ValueError(key_env + ' is required')
    source = safe_path(ROOT, scenario.fixture_dir)
    if any(p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()) for p in source.rglob('*')):
        raise ValueError('Fixture links are not supported')
    suite = scenario.success_criteria.test_suite
    if compute_test_suite_id(source, suite.test_roots, suite.contract_files, suite.command) != suite.test_suite_id:
        raise ValueError('Original fixture does not match the approved suite ID')
    original = fingerprint(source)
    # Checked before the run directory exists, so a refused dataset run leaves nothing behind.
    repository_state = git_state()
    dataset_run = bool(getattr(args, 'dataset_run', False))
    enforce_dataset_clean(dataset_run, repository_state)
    session_id = scenario.scenario_id + '-' + uuid.uuid4().hex
    out = args.output_root.resolve() / session_id
    if out.is_relative_to(source):
        raise ValueError('Output must not be inside the source fixture')
    out.mkdir(parents=True, exist_ok=False)
    candidate = out / 'workspace'
    shutil.copytree(source, candidate, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    work = Workspace(scenario, candidate)
    temperature = scenario.temperature if args.temperature is None else args.temperature
    buffer_messages = (None if args.no_context_buffer else args.context_buffer_messages
                       if args.context_buffer_messages is not None else scenario.context_buffer_messages)
    if buffer_messages is not None and buffer_messages < 1:
        raise ValueError('Context buffer must be positive')
    if args.seed_probe is not None and scenario.seed_support != 'unverified':
        raise ValueError('--seed-probe is only for unverified support')
    versions = {p: version(p) for p in ('autogen-agentchat', 'autogen-core', 'autogen-ext', 'openai')}
    save(out / 'conditions.json', {'scenario': scenario.model_dump(), 'temperature': temperature,
         'versions': versions, 'fixture_hashes': original, 'actual_outcome': None,
         'seed_support': scenario.seed_support, 'session_id': session_id, 'run_index': args.run_index})
    conditions_path = out / 'conditions.json'
    effective = json.loads(conditions_path.read_text(encoding='utf-8'))
    effective.update(context_buffer_messages=buffer_messages, seed_probe=args.seed_probe,
                     requested_seed=args.seed_probe if args.seed_probe is not None else scenario.seed,
                     runner_protocol=runner_protocol, collection_policy=collection_policy,
                     output_contract='flat-state-v2', strict_support='single_probe_passed',
                     strict_probe='strict-probe-3472654ecfca4274b03383123aa03131',
                     final_reasoning_effort=scenario.reasoning_effort or FINAL_REASONING_EFFORT,
                     strict_failure_policy='fail step; abort after two consecutive strict-failed steps; no automatic B fallback',
                     unknown_tool_policy='mark_failed; correction in same step if a tool call slot remains; '
                                         'abort on second invalid response in step',
                     tool_failure_policy='invalid_tool_arguments: mark_failed, split-call correction, '
                                         'one retry in same step, abort on second invalid response; '
                                         'last call of each step carries no tools; '
                                         'step without final text: failed/no_final_output; observation uses collection_policy',
                     recent_messages_policy='parsed narrative only; placeholder when structured output missing; '
                                            'no raw tool results', dataset_run=dataset_run, **repository_state)
    effective.update(output_contract_version=contract.version, allowed_issues_sha256=contract.sha256)
    if contract.version == V2:
        effective.update(recent_messages_policy='parsed narrative; for a failed step the narrative of a verified '
                                                'final report (G0-13); otherwise placeholder; no raw tool results')
        if facts:
            effective.update(harness_facts_policy='system message states writable files and the per-step call '
                                                  'limit; each non-final call carries its call number and '
                                                  'remaining calls (G0-14)')
            # What was asked for and what is known to have taken effect are kept apart (C-11).
            effective.update(reasoning_effort={'requested': FINAL_REASONING_EFFORT, 'applied': 'unverified',
                                               'sent_on': 'final tool-free call of each step only'})
        if runner_protocol in (PROTOCOL_V9, PROTOCOL_V10):
            effective.update(reasoning_effort={'requested': scenario.reasoning_effort, 'sent_on': 'all_calls',
                                               'applied': 'probe_indicated' if evidence else 'unverified',
                                               'evidence': evidence})
        effective.update(output_contract=contract.version, strict_support='unverified', strict_probe=None,
                         strict_failure_policy='fail step; abort after two consecutive strict-failed steps; '
                                               'vocabulary violations fail the step but are excluded from that '
                                               'streak and counted separately; no automatic B fallback')
    save(conditions_path, effective)
    print('session_id:', session_id, 'run_directory:', out, flush=True)
    shutil.copy2(scenario_path, out / 'scenario.yaml')
    headers = {'X-Guardrail-Session': session_id, 'X-Guardrail-Scenario': scenario.scenario_id,
               'X-Guardrail-Run-Index': str(args.run_index),
               'X-Guardrail-Framework-Version': 'autogen-agentchat/' + versions['autogen-agentchat']}
    headers['X-Guardrail-Context-Buffer-Messages'] = str(buffer_messages) if buffer_messages is not None else 'none'
    budget = CallBudget(scenario.termination.max_llm_calls_per_step, contract,
                        scenario.reasoning_effort if reasoning_protocol else None,
                        final_report_allowlist=runner_protocol == PROTOCOL_V10)

    base = args.proxy_url.rstrip('/').removesuffix('/v1')
    model_http = httpx.AsyncClient(event_hooks={'response': [budget.capture]})
    options = dict(model=scenario.model, api_key=key, base_url=base + '/v1',
        default_headers=headers, http_client=model_http, max_retries=0,
        temperature=temperature, max_tokens=scenario.max_tokens,
        model_info={'vision': False, 'function_calling': True, 'json_output': True,
                    'structured_output': True, 'family': 'unknown'})
    if scenario.seed_support == 'supported':
        options['seed'] = scenario.seed
    elif args.seed_probe is not None:
        options['seed'] = args.seed_probe
    model = make_client(options, budget)
    schema_text = schema_instructions(contract)
    role_tools = [work.tools(a) for a in scenario.agents]
    role_names = [[t.__name__ for t in ts] for ts in role_tools]
    save(out / 'registered-tools.json', dict(zip([a.id for a in scenario.agents], role_names)))
    agents = [AssistantAgent(a.id, model_client=model, tools=role_tools[i],
        model_context=make_model_context(buffer_messages),
        reflect_on_tool_use=False, model_client_stream=False,
        system_message=role_system_message(a, role_names[i], scenario, schema_text, facts))
        for i, a in enumerate(scenario.agents)]
    steps, missing, first, latest, baseline = [], [], None, None, None
    observation_first = None
    reason, error, session, started = 'max_steps', None, None, False
    history, cursors = [], [0] * len(agents)
    pending_feedback = [None] * len(agents)
    strict_streak = StrictFailureStreak()
    vocabulary_streak, vocabulary_total = StrictFailureStreak(), 0
    async with httpx.AsyncClient(base_url=base, headers=headers, timeout=60) as client:
        try:
            response = await client.post('/sessions')
            response.raise_for_status()
            started = True
            pin_response = await client.get('/log')
            pin_response.raise_for_status()
            meta = pin_response.json()['meta']
            if meta.get('criteria_version') != scenario.criteria_version:
                raise ValueError('Proxy criteria version differs from scenario')
            ensure_key_env(meta.get('upstream'), key_env)
            effective.update(api_key_env=key_env, upstream=meta.get('upstream'))
            save(conditions_path, effective)
            baseline = await asyncio.to_thread(work.acceptance)
            latest = baseline
            for step in range(1, scenario.termination.max_steps + 1):
                index = (step - 1) % len(agents)
                budget.reset()
                text, parsed, call_error = '', None, None
                context = json.dumps({'task': scenario.task,
                    'monitored_paths': scenario.monitored_paths,
                    'registered_tools': role_names[index],
                    'tool_feedback': pending_feedback[index],
                    'initial_issue_ids': scenario.initial_issue_ids,
                    'acceptance': {k: latest[k] for k in ('summary', 'gate')},
                    'recent_messages': history[cursors[index]:]}, ensure_ascii=False)
                outcome = await perform_step(agents[index], context, budget, role_names[index], budget_notes=facts)
                vocabulary = outcome['strict_failure'] if outcome['strict_failure'] in VOCABULARY_VIOLATIONS else None
                # A vocabulary-violation step is not a strict failure for the stop streak (D-17).
                stop_for_strict = strict_streak.observe(outcome['strict_failure'] if vocabulary is None else None)
                vocabulary_streak.observe(vocabulary)
                vocabulary_total += vocabulary is not None
                text, call_error = outcome['text'], outcome['error']
                pending_feedback[index] = outcome['feedback']
                if not outcome['failed']:
                    try:
                        parsed = contract.parse(text)
                        parsed['agent_id'] = agents[index].name
                        parsed['step_id'] = step
                    except (ValueError, TypeError) as exc:
                        # A text response is not a usable final output until its schema validates.
                        outcome['failed'] = True
                        outcome['final_output'] = False
                        outcome['failure_reasons'].append(getattr(exc, 'code', 'no_final_output'))
                        outcome['feedback'] = '최종 구조화 JSON이 유효하지 않다. 다음 차례에는 지정된 스키마로 응답하라.'
                        pending_feedback[index] = outcome['feedback']
                        call_error = 'invalid_final_output: ' + type(exc).__name__
                # Other roles see only parsed narratives; tool results stay with the agent that read them.
                shared, shared_source = parsed, 'parsed' if parsed else 'placeholder'
                receipt = outcome['observation_report']
                if shared is None and contract.version == V2 and receipt['status'] == 'valid':
                    # G0-13 (v7 only): a verified final report of a failed step is shared, not hidden.
                    # Vocabulary violations never yield a valid receipt, so they keep the placeholder.
                    shared, shared_source = receipt['value'], 'verified_final_report'
                history.append({'agent': agents[index].name,
                                'narrative': shared['narrative'] if shared else NO_OUTPUT_PLACEHOLDER})
                cursors[index] = len(history)
                latest = await asyncio.to_thread(work.acceptance)
                first, termination = termination_context(first, parsed, step,
                    scenario.termination_context_collection.declarer_agent)
                observed_parsed, observed_artifact = select_sources(collection_policy,
                    failed=outcome['failed'], legacy_parsed=parsed, final_report=receipt,
                    artifact=latest['artifact'])
                if collection_policy != LEGACY:
                    if observed_parsed is not None:
                        observed_parsed.update(agent_id=agents[index].name, step_id=step)
                    # Observation declaration must not alter execution success/stop control.
                    observation_first, termination = termination_context(observation_first,
                        observed_parsed, step, scenario.termination_context_collection.declarer_agent)
                metadata = collection_metadata(collection_policy, receipt, observed_parsed,
                    observed_artifact, scenario.progress_source, scenario.progress_metric.model_dump())
                record = {'step_id': step, 'agent': agents[index].name, 'text': text,
                          'llm_calls': budget.used, 'llm_turns': sorted(set(budget.turns)),
                          'acceptance': latest, 'call_error': call_error}
                # G0-6: executed tool errors fail the recorded step only. outcome['failed'] still drives
                # parsing, placeholders, source selection and the success check, so control flow is unchanged.
                tool_execution_error = any(e['is_error'] for e in outcome['tool_executions'])
                record.update(step_status='failed' if outcome['failed'] or tool_execution_error else 'completed',
                              measurement_status='unmeasured' if outcome['failed'] else 'observed',
                              tool_errors=outcome['tool_errors'], tool_feedback=outcome['feedback'],
                              tool_executions=outcome['tool_executions'],
                              final_output=outcome['final_output'],
                              failure_reasons=outcome['failure_reasons']
                                              + ['tool_execution_error'] * tool_execution_error)
                record.update(strict_used=outcome['strict_used'], strict_failure=outcome['strict_failure'],
                              consecutive_strict_failures=strict_streak.count)
                if contract.version == V2:
                    record.update(shared_narrative_source=shared_source)
                    record.update(vocabulary_violation=vocabulary,
                                  consecutive_vocabulary_violations=vocabulary_streak.count,
                                  vocabulary_violations_total=vocabulary_total)
                record['collection'] = metadata
                record['observed_final_report'] = observed_parsed
                if collection_policy != LEGACY:
                    record['measurement_status'] = metadata['measurement_status']
                steps.append(record)
                save(out / 'steps.json', steps)
                if not budget.turns:
                    missing.append(step)
                    raise RuntimeError('No proxy turn ID; cannot submit a linked observation')
                payload = make_observation(step_id=step, agent_id=agents[index].name,
                    llm_turns=record['llm_turns'],
                    text=observed_parsed['narrative'] if observed_parsed else '',
                    progress_source=scenario.progress_source, progress_metric=scenario.progress_metric.model_dump(),
                    artifact=observed_artifact, structured=
                    {k: observed_parsed[k] for k in ('open_issue_ids', 'info_items')} if observed_parsed else
                    {'open_issue_ids': None, 'info_items': None, 'reasons': {'output': 'invalid or missing structured output'}},
                    termination_context=termination,
                    collection=metadata if collection_policy != LEGACY else None,
                    issue_report=contract.report(observed_parsed))
                save(out / 'observations' / f'{step}.pending.json', payload)
                try:
                    ack = await deliver(client, session_id, payload)
                except Exception:
                    missing.append(step)
                    raise
                save(out / 'observations' / f'{step}.ack.json', ack)
                record['observation'] = ack['observation']
                try:
                    log_response = await client.get('/log')
                    log_response.raise_for_status()
                    trace = prompt_trace(steps, log_response.json())
                    record['prompt_tokens'] = trace[-1]
                    save(out / 'prompt-trend.json', trace)
                    print(json.dumps({'step_id': step, 'agent': agents[index].name,
                        'prompt_tokens_per_call': trace[-1]['prompt_tokens_per_call'],
                        'prompt_tokens_sum': trace[-1]['prompt_tokens_sum']}, ensure_ascii=False), flush=True)
                except (httpx.HTTPError, ValueError, KeyError) as exc:
                    record['prompt_trace_error'] = type(exc).__name__
                save(out / 'steps.json', steps)
                if stop_for_strict:
                    reason, error = 'strict_output_failures', 'two_consecutive_strict_failed_steps'
                    break
                if outcome['abort']:
                    raise RuntimeError(call_error or 'step_aborted')
                if outcome['failed']:
                    continue
                if latest['gate']['machine_success'] and (first is not None or
                        not scenario.termination.require_completion_declaration):
                    reason = 'success'
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
                    save(out / 'session.json', session)
                    save(out / 'prompt-trend.json', prompt_trace(steps, session))
                except httpx.HTTPError as exc:
                    cleanup_errors.append('log: ' + str(exc))
            await model.close()
            await model_http.aclose()
            turns = session.get('turns', []) if session else []
            values = [t.get('tokens') for t in turns]
            criteria = [s['observation']['criteria'] for s in steps if 'observation' in s]
            summary = {'session_id': session_id, 'steps': len(steps), 'termination_reason': reason,
                'total_tokens': sum(values) if session is not None and
                    len(turns) == sum(s['llm_calls'] for s in steps) and
                    all(v is not None for v in values) else None,
                'known_tokens_subtotal': sum(v for v in values if v is not None),
                'criteria_latest': criteria[-1] if criteria else {'decision': 'unmeasured'},
                'criteria_alerts': [c for c in criteria if c.get('decision') in ('deadlock', 'termination_failure')],
                'tests_passed_before': baseline['summary']['passed'] if baseline else None,
                'tests_passed_after': latest['summary']['passed'] if latest else None,
                'missing_observation_steps': missing, 'missing_observation_count': len(missing),
                'fixture_unchanged': fingerprint(source) == original, 'error': error,
                'cleanup_errors': cleanup_errors, 'actual_outcome': None}
            summary['context_buffer_messages'] = buffer_messages
            if contract.version == V2:
                summary['vocabulary_violation_steps'] = [s['step_id'] for s in steps if s.get('vocabulary_violation')]
                summary['vocabulary_violations_total'] = vocabulary_total
            summary['failed_steps'] = [{'step_id': s['step_id'], 'reasons': s.get('failure_reasons', [])}
                                       for s in steps if s.get('step_status') == 'failed']
            save(out / 'summary.json', summary)
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            print('run_directory:', out)
    return 1 if error or cleanup_errors or not summary['fixture_unchanged'] else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('scenario', type=Path)
    parser.add_argument('--collection-policy', choices=tuple(PROTOCOLS), default=DEFAULT_POLICY)
    parser.add_argument('--output-contract', choices=VERSIONS, default=V2)
    parser.add_argument('--runner-protocol', choices=(PROTOCOL_V7, PROTOCOL_V8, PROTOCOL_V9, PROTOCOL_V10), default=None,
                        help='required for output-contract-v2 (D-25). v7 reproduces G0-8; '
                             'v9 needs a scenario with reasoning_effort')
    parser.add_argument('--api-key-env', default='GROQ_API_KEY',
                        help='environment variable holding the provider key; must match the proxy config')
    parser.add_argument('--proxy-url', default=os.environ.get('GUARDRAIL_PROXY_URL', 'http://127.0.0.1:8000'))
    parser.add_argument('--output-root', type=Path, default=ROOT / 'runs')
    parser.add_argument('--run-index', type=int, default=1)
    parser.add_argument('--dataset-run', action='store_true',
                        help='mark a pilot or collection session; refuse a dirty Git working tree before model calls')
    parser.add_argument('--temperature', type=float, default=None)
    context_options = parser.add_mutually_exclusive_group()
    context_options.add_argument('--context-buffer-messages', type=int, default=None)
    context_options.add_argument('--no-context-buffer', action='store_true')
    parser.add_argument('--seed-probe', type=int, default=None,
                        help='Explicit unverified seed probe; does not change support status')
    args = parser.parse_args()
    if args.output_contract == V2 and args.runner_protocol is None:
        parser.error('--runner-protocol is required for --output-contract ' + V2)
    return asyncio.run(run(args))


if __name__ == '__main__':
    raise SystemExit(main())
