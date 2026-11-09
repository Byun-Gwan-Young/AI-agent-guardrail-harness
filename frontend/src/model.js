export const number = (v) =>
  v == null
    ? "—"
    : new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 2 }).format(v);
export const percent = (v) =>
  v == null
    ? "—"
    : `${new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 1 }).format(v * 100)}%`;
export const labels = {
  normal: "정상판",
  stall: "교착판",
  natural: "비교군",
  observe: "관측",
  block: "차단",
  success: "성공",
  stalled: "교착",
  escalated: "에스컬레이션",
  other: "기타",
};
export const label = (v) => labels[v] || v || "—";
export const date = (v) =>
  !v || Number.isNaN(Date.parse(v))
    ? "시각 없음"
    : new Date(v).toLocaleString("ko-KR", { timeZone: "Asia/Seoul" });
export function fromApi(row, names = {}) {
  return {
    id: row.session_id,
    short: row.session_id.slice(-32).slice(0, 8),
    scenario: row.scenario_id,
    task: row.task,
    task_name: names[row.task] || row.task,
    variant: row.variant,
    type: row.task_type,
    mode: row.mode,
    class: row.class,
    steps: row.steps,
    tokens: row.tokens_total,
    credits: row.credits_measured ?? row.credits_estimated,
    first_stop: row.first_stop_step,
    stop_text: row.first_stop_text,
    template: row.first_stop_template,
    blocked_step: row.blocked_step,
    termination: row.termination_reason,
    started_at: row.started_at,
    roles: row.role_labels || {},
    step_rows: [],
    loaded: false,
  };
}
export function filterSessions(rows, filters) {
  return rows.filter(
    (s) =>
      (!filters.task || s.task === filters.task) &&
      (!filters.mode || s.mode === filters.mode) &&
      (!filters.variant || s.variant === filters.variant) &&
      (!filters.search ||
        `${s.id} ${s.task_name} ${s.scenario}`
          .toLowerCase()
          .includes(filters.search.toLowerCase())),
  );
}
export function stepFromApi(f, roles = {}) {
  const rp = f.report && Object.keys(f.report).length ? f.report : null;
  return {
    n: f.step_id,
    agent: f.agent,
    role: f.role || roles[f.agent],
    state: f.state,
    label: f.state_label,
    stop:
      f.stop && Object.keys(f.stop).length
        ? { t: f.stop.template_id, text: f.stop.text }
        : null,
    blocked: !!f.blocked,
    status: f.step_status,
    fail: f.failure_reasons || [],
    tests:
      f.tests && Object.keys(f.tests).length
        ? [f.tests.passed, f.tests.total]
        : null,
    report: rp
      ? {
          status: rp.status_label || rp.status,
          handoff: roles[rp.handoff_to] || rp.handoff_to,
          adopted: rp.adopted_items,
          issues: rp.open_issue_ids?.length,
          issue_ids: rp.open_issue_ids || [],
          spec: rp.spec_approved,
          declared: !!rp.completion_declared,
          deliverable: !!rp.deliverable_reported,
        }
      : null,
    changed: f.changed_paths?.length || 0,
    paths: f.changed_paths || [],
    tok: (f.tokens?.prompt || 0) + (f.tokens?.completion || 0),
    cum: f.cumulative_tokens,
    cumc: f.cumulative_credits,
    tools: f.tools?.length || 0,
    tool_errors: f.tools?.filter((x) => x.is_error).length || 0,
  };
}
export function groupedStats(rows) {
  return [...new Set(rows.map((s) => s.task))].map((task) => {
    const group = rows.filter((s) => s.task === task);
    return {
      task,
      name: group[0].task_name,
      count: group.length,
      success: group.filter((s) => s.class === "success").length,
      stall: group.filter((s) => s.class === "stalled").length,
      stop: group.filter((s) => s.first_stop != null).length,
      tokens: group.reduce((sum, s) => sum + (s.tokens || 0), 0),
    };
  });
}
