import { useEffect, useState } from "react";
import { AlertCircle, ArrowUpRight, LoaderCircle } from "lucide-react";
import { number, label } from "./model.js";

export function useResource(load, deps) {
  const [state, set] = useState({ loading: true, data: null, error: null });
  const [revision, retry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    set({ loading: true, data: null, error: null });
    Promise.resolve()
      .then(() => load(controller.signal))
      .then((data) => {
        if (!controller.signal.aborted)
          set({ loading: false, data, error: null });
      })
      .catch((error) => {
        if (!controller.signal.aborted)
          set({ loading: false, data: null, error });
      });
    return () => controller.abort();
    // Each caller supplies explicit resource identity dependencies.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, revision]);
  return { ...state, retry: () => retry((v) => v + 1) };
}

export function ErrorBox({ error, retry }) {
  return (
    <div className="error-box" role="alert">
      <AlertCircle size={19} />
      <div>
        <b>연결을 확인해 주세요</b>
        <p>{error?.message || String(error)}</p>
        {retry && <button onClick={retry}>다시 시도</button>}
        {error?.status === 401 && <a href="/login">다시 로그인</a>}
      </div>
    </div>
  );
}
export function Loading({ text = "기록을 불러오는 중입니다" }) {
  return (
    <div className="loading" role="status">
      <LoaderCircle size={22} className="spin" />
      {text}
    </div>
  );
}
export function Empty({ title = "표시할 기록이 없습니다", children }) {
  return (
    <div className="empty">
      <b>{title}</b>
      {children && <p>{children}</p>}
    </div>
  );
}
export function Panel({ title, subtitle, action, children, className = "" }) {
  return (
    <section className={`panel ${className}`}>
      <div className="panel-head">
        <div>
          <h2>{title}</h2>
          {subtitle && <p>{subtitle}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}
export function Badge({ session }) {
  return (
    <span
      className={`badge ${session.blocked_step != null ? "blocked" : session.first_stop != null ? "stop" : "ok"}`}
    >
      {session.blocked_step != null
        ? `차단 · ${session.blocked_step}`
        : session.first_stop != null
          ? `STOP · ${session.first_stop}`
          : "계속 진행"}
    </span>
  );
}
export function SessionTable({ rows, open }) {
  if (!rows.length)
    return <Empty>필터를 바꾸거나 다른 프로젝트를 선택해 주세요.</Empty>;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>세션 / 시나리오</th>
            <th>모드</th>
            <th>단계</th>
            <th>토큰</th>
            <th>가드레일 판정</th>
            <th>결과</th>
            <th>
              <span className="sr-only">상세</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((s) => (
            <tr key={s.id}>
              <td>
                <button className="table-link" onClick={() => open(s.id)}>
                  {s.task_name} · {label(s.variant)}
                </button>
                <small className="mono">{s.short || s.id}</small>
              </td>
              <td>{label(s.mode)}</td>
              <td>{number(s.steps)}</td>
              <td className="mono">{number(s.tokens)}</td>
              <td>
                <Badge session={s} />
              </td>
              <td>{label(s.class)}</td>
              <td>
                <button
                  className="icon-button"
                  aria-label={`${s.short || s.id} 세션 보기`}
                  onClick={() => open(s.id)}
                >
                  <ArrowUpRight size={17} />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
export function JsonView({ value }) {
  return <pre className="code">{JSON.stringify(value, null, 2)}</pre>;
}
export function Timeline({ steps, selected, onSelect }) {
  return (
    <div className="timeline" aria-label="실험 단계 타임라인">
      {steps.map((step) => (
        <button
          key={step.n}
          aria-label={`${step.n}단계 ${step.stop ? "STOP" : step.label || step.state || ""}`}
          aria-pressed={selected === step.n}
          className={`${step.blocked ? "blocked" : step.stop ? "stop" : step.state === "stagnant" ? "stagnant" : "progress"} ${selected === step.n ? "selected" : ""}`}
          onClick={() => onSelect(step.n)}
        >
          {step.n}
        </button>
      ))}
    </div>
  );
}
export function KeyValue({ entries }) {
  return (
    <dl className="key-values">
      {entries.map(([k, v]) => (
        <div key={k}>
          <dt>{k}</dt>
          <dd>{v ?? "관측값 없음"}</dd>
        </div>
      ))}
    </dl>
  );
}
