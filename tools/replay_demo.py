"""Session replay pages of the demo (C-19-1 part 2): a small replay record per session, and static HTML pages from it.

  extract  <runs/demo/<id> raw folder> [--output <file>]   write record/replay.json (default: in that folder)
  render   <record/replay.json> --output <file.html>         one session page
  index    <aggregate.json> --pages <folder> --output <index.html>   the list page of the representative sessions

record/replay.json (demo-replay-v1) holds only what a page shows, per step: the role (its Korean label), the facts of
the verified final report's structured fields (status, handoff_to, adopted item and open issue counts, whether a
deliverable or spec approval was reported, the completion claim and its judge result), the tool calls (name and error
state), the acceptance pass count and changed paths of artifact tasks, the progress state, the decision with its STOP
explanation sentence (explain-v1, made from signal values only), the step's tokens and estimated credits. No narrative,
info_items, deliverable values, tool output or model reasoning is copied (DM-9, C-19-1). It is made from the local raw
files (steps.json, session.json, conditions.json) and is small enough to commit beside the other record files
(DM-64 ⑤). Pages are one file each, with inline style and script, no external resource. Offline; no model call.
"""
import argparse
import html
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import gateway_prices  # noqa: E402

VERSION = 'demo-replay-v1'
STOP_DECISIONS = ('deadlock', 'termination_failure')
STATE_LABELS = {'baseline': '기준', 'progress': '진전', 'stagnant': '정체', 'oscillating': '되돌림',
                'unmeasured': '측정 안 됨', 'declared': '완료 선언'}


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def step_credits(model, turns):
    value = gateway_prices.estimate(model, turns)
    return value['value'] if value['status'] == 'computed' else None


def report_facts(report, status_labels):
    if report is None:
        return None
    facts = {'status': report.get('status'), 'status_label': status_labels.get(report.get('status')),
             'handoff_to': report.get('handoff_to'), 'adopted_items': len(report.get('adopted_items') or []),
             'open_issue_ids': list(report.get('open_issue_ids') or []),
             'deliverable_reported': report.get('deliverable') is not None,
             'completion_declared': report.get('completion_declared')}
    if report.get('spec_approved') is not None:
        facts['spec_approved'] = report['spec_approved']
    return facts


def extract(folder):
    folder = Path(folder)
    conditions, steps, summary = load(folder / 'conditions.json'), load(folder / 'steps.json'), load(folder / 'summary.json')
    log = load(folder / 'session.json')
    registration = conditions.get('registration') or {}
    labels = registration.get('role_labels') or {}
    status_labels = {s['id']: s['label'] for s in registration.get('status_values') or []}
    status_labels.update({s['id']: s['label'] for s in registration.get('terminal_statuses') or []})
    observations = {o['step_id']: o for o in log['observations']}
    turns = {t['turn']: t for t in log['turns']}
    model = log['meta'].get('model')
    rows = []
    for step in steps:
        own = [turns[t] for t in step.get('llm_turns') or [] if t in turns]
        usage = gateway_prices.usage_totals(own)
        observation = observations.get(step['step_id']) or {}
        progress, criteria = observation.get('progress') or {}, observation.get('criteria') or {}
        t3 = progress.get('t3') or {}
        acceptance = (step.get('acceptance') or {}).get('summary')
        claim = step.get('completion_claim')
        explanation = criteria.get('explanation') if criteria.get('decision') in STOP_DECISIONS else None
        state = progress.get('state')
        if (progress.get('flags') or {}).get('revert') or t3.get('global_revert'):
            state_label = '되돌림'
        else:
            state_label = STATE_LABELS.get(state, state)
        rows.append({
            'step_id': step['step_id'], 'agent': step['agent'], 'role': labels.get(step['agent'], step['agent']),
            'step_status': step.get('step_status'), 'failure_reasons': step.get('failure_reasons') or [],
            'report': report_facts(step.get('observed_final_report'), status_labels),
            'completion_claim': None if claim is None else {'accepted': claim['accepted'], 'reasons': claim['reasons'],
                                                            'missing': claim['gate']['missing']},
            'tools': [{'tool': e.get('tool'), 'is_error': bool(e.get('is_error'))} for e in step.get('tool_executions') or []],
            'tests': None if not acceptance else {'passed': acceptance['passed'], 'total': acceptance['tests']},
            'changed_paths': t3.get('changed_paths') or [],
            'state': state, 'state_label': state_label,
            'decision': criteria.get('decision'),
            'stop': None if explanation is None else {'template_id': explanation.get('template_id'),
                                                      'text': explanation.get('text')},
            'blocked': step.get('step_status') == 'blocked',
            'tokens': {k: usage[k] for k in ('prompt', 'cached_prompt', 'completion', 'reasoning')},
            'usage_missing_turns': usage['usage_missing_turns'],
            'credits_estimated': step_credits(model, own)})
    cumulative_tokens = cumulative_credits = 0
    for row in rows:
        cumulative_tokens += row['tokens']['prompt'] + row['tokens']['completion']
        row['cumulative_tokens'] = cumulative_tokens
        if row['credits_estimated'] is not None and cumulative_credits is not None:
            cumulative_credits = round(cumulative_credits + row['credits_estimated'], 5)
        else:
            cumulative_credits = None
        row['cumulative_credits'] = cumulative_credits
    stops = [r['step_id'] for r in rows if r['stop']]
    first = stops[0] if stops else None
    total_tokens = rows[-1]['cumulative_tokens'] if rows else 0
    after = sum(r['tokens']['prompt'] + r['tokens']['completion'] for r in rows if first is not None and r['step_id'] > first)
    total_credits = rows[-1]['cumulative_credits'] if rows else None
    after_credits = (None if total_credits is None or first is None else
                     round(sum(r['credits_estimated'] for r in rows if r['step_id'] > first), 5))
    blocked = [r['step_id'] for r in rows if r['blocked']]
    scenario = conditions['scenario']
    return {'replay_version': VERSION, 'session_id': summary['session_id'], 'scenario_id': scenario['scenario_id'],
            'title': scenario.get('title'), 'task_kind': conditions.get('task_kind'),
            'guardrail_mode': log['meta'].get('guardrail_mode'), 'model': model,
            'termination_reason': summary['termination_reason'], 'escalated_by': summary.get('escalated_by'),
            'steps_reached': summary['steps'], 'max_steps': scenario['termination']['max_steps'],
            'batch': conditions.get('batch'), 'role_labels': labels,
            'first_stop_step': first, 'stop_steps': stops, 'blocked_step': blocked[0] if blocked else None,
            'if_stopped': None if first is None else {
                'stop_step': first, 'tokens_after': after, 'tokens_total': total_tokens,
                'token_ratio': round(after / total_tokens, 4) if total_tokens else None,
                'credits_after': after_credits, 'credits_total': total_credits,
                'basis': 'tokens (prompt + completion) of the steps after the first STOP step: a block-mode proxy '
                         'refuses the next request after the STOP (DM-7); credits are the token x price estimate'},
            'steps': rows}


PAGE_STYLE = """
:root{--bg:#fbfaf7;--fg:#1d1d1b;--muted:#6b6a65;--line:#dedbd2;--card:#fff;--stop:#b3261e;--stopbg:#fdecea;
--prog:#1b6e3a;--stag:#8a6d00;--rev:#7a3e9d;--accent:#1f5fa8;--save:#e8f0fb}
@media (prefers-color-scheme:dark){:root{--bg:#161614;--fg:#ecebe6;--muted:#a3a29b;--line:#36352f;--card:#1f1f1c;
--stop:#ff8a80;--stopbg:#3a1f1d;--prog:#7fd29b;--stag:#e2c45c;--rev:#c79be6;--accent:#8ab8f0;--save:#1d2a3a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 -apple-system,
"Apple SD Gothic Neo","Noto Sans KR",system-ui,sans-serif}main{max-width:960px;margin:0 auto;padding:20px 16px 48px}
h1{font-size:1.35rem;margin:0 0 4px}.sub{color:var(--muted);font-size:.9rem;margin-bottom:16px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin:12px 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px 10px}
.card b{display:block;font-size:1.1rem}.card span{color:var(--muted);font-size:.8rem}
.nav{display:flex;gap:8px;align-items:center;margin:14px 0;flex-wrap:wrap}
button{font:inherit;padding:4px 12px;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--fg);cursor:pointer}
input[type=range]{flex:1;min-width:160px}
.step{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 14px}
.step h2{font-size:1.05rem;margin:0 0 6px}.state{font-weight:600}
.s-진전{color:var(--prog)}.s-정체{color:var(--stag)}.s-되돌림{color:var(--rev)}
.stop{background:var(--stopbg);border-left:4px solid var(--stop);padding:8px 10px;margin:8px 0;border-radius:4px}
.saved{background:var(--save);border-left:4px solid var(--accent);padding:8px 10px;margin:8px 0;border-radius:4px}
dl{display:grid;grid-template-columns:max-content 1fr;gap:2px 12px;margin:6px 0}dt{color:var(--muted)}dd{margin:0}
svg{width:100%;height:auto;display:block}.axis{stroke:var(--line)}.lineT{fill:none;stroke:var(--accent);stroke-width:2}
.mark{stroke:var(--stop);stroke-width:1.5;stroke-dasharray:4 3}.cur{stroke:var(--fg);stroke-width:1}
.dot{fill:var(--accent)}.lbl{fill:var(--muted);font-size:11px}
table{border-collapse:collapse;width:100%;font-size:.9rem}td,th{border-bottom:1px solid var(--line);padding:4px 6px;text-align:left}
tr.sel{background:var(--save)}tr{cursor:pointer}a{color:var(--accent)}.note{color:var(--muted);font-size:.85rem}
"""

PAGE_SCRIPT = """
const D=JSON.parse(document.getElementById('replay-data').textContent);let i=0;
const $=s=>document.querySelector(s);const esc=t=>String(t??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function facts(s){const r=s.report,out=[];
 if(r){if(r.status_label||r.status)out.push(['처리 상태',r.status_label||r.status]);if(r.handoff_to)out.push(['다음 담당',D.role_labels[r.handoff_to]||r.handoff_to]);
  out.push(['채택 항목',r.adopted_items]);out.push(['열린 쟁점',r.open_issue_ids.length?r.open_issue_ids.join(', '):'없음']);
  if(r.deliverable_reported)out.push(['결과물','보고함']);if(r.spec_approved!==undefined)out.push(['SPEC 승인',r.spec_approved?'승인':'미승인']);
  if(r.completion_declared)out.push(['완료 선언','예']);}else out.push(['최종 보고','없음']);
 if(s.completion_claim)out.push(['완료 주장',s.completion_claim.accepted?'통과':'거절 ('+s.completion_claim.reasons.concat(s.completion_claim.missing).join(', ')+')']);
 if(s.tests)out.push(['통과 테스트',s.tests.passed+'/'+s.tests.total]);if(s.changed_paths.length)out.push(['바뀐 파일',s.changed_paths.join(', ')]);
 if(s.tools.length){const c={};s.tools.forEach(t=>{const k=t.tool+(t.is_error?' (오류)':'');c[k]=(c[k]||0)+1});out.push(['도구 호출',Object.entries(c).map(([k,v])=>k+' ×'+v).join(', ')]);}
 if(s.failure_reasons.length)out.push(['실패 사유',s.failure_reasons.join(', ')]);
 out.push(['토큰 (입력/출력)',s.tokens.prompt+' / '+s.tokens.completion]);return out;}
function chart(){const W=900,H=180,P=36,n=D.steps.length,max=Math.max(1,...D.steps.map(s=>s.cumulative_tokens));
 const x=k=>P+(W-2*P)*(n<2?0:(k)/(n-1)),y=v=>H-24-(H-40)*v/max;let p='';
 D.steps.forEach((s,k)=>{p+=(k?'L':'M')+x(k).toFixed(1)+' '+y(s.cumulative_tokens).toFixed(1)});
 let g='<svg viewBox="0 0 '+W+' '+H+'" role="img" aria-label="누적 토큰"><line class="axis" x1="'+P+'" y1="'+(H-24)+'" x2="'+(W-P)+'" y2="'+(H-24)+'"/>'+
  '<path class="lineT" d="'+p+'"/>';
 const mk=(step,label)=>{const k=D.steps.findIndex(s=>s.step_id===step);if(k<0)return'';return '<line class="mark" x1="'+x(k)+'" y1="10" x2="'+x(k)+'" y2="'+(H-24)+'"/><text class="lbl" x="'+(x(k)+4)+'" y="20">'+label+'</text>'};
 if(D.first_stop_step)g+=mk(D.first_stop_step,D.guardrail_mode==='block'?'STOP (차단)':'STOP — 여기서 멈췄다면');
 if(D.blocked_step)g+=mk(D.blocked_step,'403 차단');
 g+='<line class="cur" id="cur" x1="0" y1="10" x2="0" y2="'+(H-24)+'"/>';
 g+='<text class="lbl" x="'+P+'" y="'+(H-6)+'">step '+D.steps[0].step_id+'</text><text class="lbl" x="'+(W-P-60)+'" y="'+(H-6)+'">step '+D.steps[n-1].step_id+'</text>';
 g+='<text class="lbl" x="'+P+'" y="12">누적 토큰 '+max.toLocaleString()+'</text></svg>';$('#chart').innerHTML=g;
 window._x=x;}
function show(k){i=Math.max(0,Math.min(D.steps.length-1,k));const s=D.steps[i];$('#range').value=i;
 let h='<h2>step '+s.step_id+' · '+esc(s.role)+'</h2><div class="state s-'+esc(s.state_label)+'">판정 상태 : '+esc(s.state_label||'-')+'</div>';
 if(s.stop)h+='<div class="stop"><b>STOP ('+esc(s.stop.template_id)+')</b> '+esc(s.stop.text)+'</div>';
 if(s.blocked)h+='<div class="stop"><b>차단</b> 이 step 의 요청은 STOP 뒤라 프록시가 403 으로 돌려보냈다 (업스트림에 보내지 않음).</div>';
 if(D.if_stopped&&s.step_id===D.if_stopped.stop_step&&D.guardrail_mode!=='block')h+='<div class="saved">여기서 멈췄다면 뒤의 '+D.if_stopped.tokens_after.toLocaleString()+' 토큰 ('+(100*D.if_stopped.token_ratio).toFixed(1)+'%'+(D.if_stopped.credits_after!==null?', 약 '+D.if_stopped.credits_after+' 크레딧':'')+')을 아낄 수 있었다.</div>';
 h+='<dl>'+facts(s).map(([a,b])=>'<dt>'+esc(a)+'</dt><dd>'+esc(b)+'</dd>').join('')+'<dt>누적</dt><dd>'+s.cumulative_tokens.toLocaleString()+' 토큰'+(s.cumulative_credits!==null?' · '+s.cumulative_credits+' 크레딧 (추정)':'')+'</dd></dl>';
 $('#step').innerHTML=h;const c=$('#cur');if(c){c.setAttribute('x1',window._x(i));c.setAttribute('x2',window._x(i));}
 document.querySelectorAll('#list tr[data-k]').forEach(r=>r.classList.toggle('sel',+r.dataset.k===i));}
function list(){$('#list').innerHTML='<tr><th>step</th><th>역할</th><th>판정</th><th>STOP</th><th>통과/상태</th></tr>'+D.steps.map((s,k)=>
 '<tr data-k="'+k+'"><td>'+s.step_id+'</td><td>'+esc(s.role)+'</td><td class="s-'+esc(s.state_label)+'">'+esc(s.state_label||'-')+'</td><td>'+(s.stop?esc(s.stop.template_id):(s.blocked?'403':''))+'</td><td>'+
 (s.tests?s.tests.passed+'/'+s.tests.total:esc(s.report&&(s.report.status_label||s.report.status)||''))+'</td></tr>').join('');
 document.querySelectorAll('#list tr[data-k]').forEach(r=>r.onclick=()=>show(+r.dataset.k));}
$('#range').max=D.steps.length-1;$('#range').oninput=e=>show(+e.target.value);$('#prev').onclick=()=>show(i-1);$('#next').onclick=()=>show(i+1);
$('#tostop').onclick=()=>show(Math.max(0,D.steps.findIndex(s=>s.stop)));
document.addEventListener('keydown',e=>{if(e.key==='ArrowLeft')show(i-1);if(e.key==='ArrowRight')show(i+1)});
chart();list();show(0);
"""


def page(replay, summary=None):
    """One self-contained HTML page for one session's replay record."""
    title = f"{replay['scenario_id']} — 세션 재생"
    cards = [('종료', replay['termination_reason'] + (f" ({replay['escalated_by']})" if replay.get('escalated_by') else '')),
             ('도달 step', f"{replay['steps_reached']} / {replay['max_steps']}"),
             ('모드', replay['guardrail_mode']), ('첫 STOP', replay['first_stop_step'] or '없음')]
    if replay.get('if_stopped') and replay['guardrail_mode'] != 'block':
        cards.append(('멈췄다면 아낄 토큰', f"{100 * replay['if_stopped']['token_ratio']:.1f}%"))
    if summary:
        measured = (summary.get('credits_measured') or {}).get('value')
        estimated = (summary.get('credits_estimated') or {}).get('value')
        cards.append(('크레딧', f"{measured} (실측)" if measured is not None else f"{estimated} (추정)"))
    data = json.dumps(replay, ensure_ascii=False).replace('</', '<\\/')
    card_html = ''.join(f'<div class="card"><b>{html.escape(str(v))}</b><span>{html.escape(k)}</span></div>' for k, v in cards)
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(replay['scenario_id'])} 재생</title><style>{PAGE_STYLE}</style></head>
<body><main><h1>{html.escape(title)}</h1>
<div class="sub">{html.escape(replay.get('title') or '')} · 세션 {html.escape(replay['session_id'])} · 모델 {html.escape(str(replay.get('model')))} · 데모 세션 기준 (데이터셋 아님)</div>
<div class="cards">{card_html}</div>
<div id="chart"></div>
<div class="nav"><button id="prev">◀ 이전</button><input id="range" type="range" min="0" value="0" aria-label="step"><button id="next">다음 ▶</button><button id="tostop">첫 STOP 으로</button></div>
<section class="step" id="step"></section>
<p class="note">판정 상태와 STOP 원인 설명은 프록시 판정 기록(deadlock-v0.3, explain-v1)이고, 사실 요약은 최종 보고의 구조화 필드·도구 호출 이름·테스트 결과에서 만들었다. 모델의 서술·추론 내용은 넣지 않았다. 크레딧은 토큰 × 단가 추정이다.</p>
<table id="list"></table>
<script type="application/json" id="replay-data">{data}</script>
<script>{PAGE_SCRIPT}</script></main></body></html>
"""


def index_page(aggregate, pages):
    """The list page: the representative sessions by task type, with the selection reason."""
    groups = {}
    for row in aggregate.get('representatives', []):
        groups.setdefault(row['task_type'], []).append(row)
    parts = []
    for task_type in sorted(groups):
        rows = ''.join(
            f"<tr><td><a href=\"{html.escape(pages.get(r['session_id'], '#'))}\">{html.escape(r['scenario_id'])}</a></td>"
            f"<td>{html.escape(r['role'])}</td><td>{html.escape(str(r.get('first_stop_step') or '-'))}</td>"
            f"<td>{html.escape(r.get('template_id') or '-')}</td><td>{html.escape(r['reason'])}</td></tr>"
            for r in groups[task_type])
        parts.append(f"<h2>{html.escape(task_type)}</h2><table><tr><th>시나리오</th><th>구분</th><th>첫 STOP</th>"
                     f"<th>템플릿</th><th>선정 근거</th></tr>{rows}</table>")
    plan = ', '.join(aggregate.get('plans', []))
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>데모 세션 재생</title><style>{PAGE_STYLE}</style></head>
<body><main><h1>데모 세션 재생 — 대표 세션</h1>
<div class="sub">계획 {html.escape(plan)} · 데모 세션 기준 (데이터셋 아님, DM-2) · 유형 T1 대화 / T2 대화+산출물 / T3 산출물</div>
{''.join(parts) or '<p>대표 세션 없음</p>'}
<p class="note">선정 규칙은 tools/aggregate_demo.py 의 representatives 에 있다.</p></main></body></html>
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='action', required=True)
    one = sub.add_parser('extract')
    one.add_argument('run_dir', type=Path)
    one.add_argument('--output', type=Path)
    two = sub.add_parser('render')
    two.add_argument('replay', type=Path)
    two.add_argument('--output', type=Path, required=True)
    three = sub.add_parser('index')
    three.add_argument('aggregate', type=Path)
    three.add_argument('--pages', type=Path, required=True, help='folder of the session pages (<session id>.html)')
    three.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.action == 'extract':
        replay = extract(args.run_dir)
        output = args.output or args.run_dir / 'record' / 'replay.json'
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(replay, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    elif args.action == 'render':
        replay = load(args.replay)
        summary_path = args.replay.parent / 'demo-summary.json'
        summary = load(summary_path) if summary_path.is_file() else None
        output = args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(page(replay, summary), encoding='utf-8')
    else:
        aggregate = load(args.aggregate)
        pages = {p.stem: p.name for p in args.pages.glob('*.html') if p.name != args.output.name}
        output = args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(index_page(aggregate, pages), encoding='utf-8')
    print(output)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
