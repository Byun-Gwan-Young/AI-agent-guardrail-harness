import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  ArrowDown,
  ArrowRight,
  Bell,
  Check,
  ChevronLeft,
  ChevronRight,
  CircleHelp,
  Database,
  Download,
  ExternalLink,
  KeyRound,
  Layers,
  LogOut,
  Pause,
  Play,
  Plus,
  Search,
  ShieldCheck,
  Square,
  Workflow,
} from "lucide-react";
import { logout, post, request } from "./api.js";
import {
  Badge,
  Empty,
  ErrorBox,
  JsonView,
  KeyValue,
  Loading,
  Panel,
  SessionTable,
  Timeline,
  useResource,
} from "./components.jsx";
import {
  date,
  filterSessions,
  groupedStats,
  label,
  number,
  percent,
  stepFromApi,
} from "./model.js";

export function Dashboard({ data, open }) {
  const h = data.headline;
  const alerts = data.sessions.filter((s) => s.first_stop != null);
  return (
    <>
      <div className="metrics">
        <Metric
          title="관측한 세션"
          value={number(h.observe_sessions)}
          detail={`성공 ${number(h.observe_classes?.success)} · 교착 ${number(h.observe_classes?.stalled)} · 에스컬레이션 ${number(h.observe_classes?.escalated)}`}
          tag={`차단 ${number(h.block_sessions)}개 별도`}
          icon={Layers}
        />
        <Metric
          title="교착 판정 STOP"
          value={`${number(h.stall_detected)} / ${number(h.stall_reached)}`}
          detail="교착에 닿은 교착판 관측 중 탐지"
          tag={`정상판 오탐 ${number(h.false_positive)} / ${number(h.normal_success)}`}
          icon={ShieldCheck}
          tone="orange"
        />
        <Metric
          title="멈췄다면 아꼈을 토큰"
          value={percent(h.saving_mean)}
          detail="탐지된 교착판 · 첫 STOP 이후 토큰 비율 평균"
          tag="실제 절감이 아닌 관측 추정"
          icon={Workflow}
          tone="blue"
        />
        <Metric
          title="규칙 판정 지연 p99"
          value={`${number(data.judgement_ms?.p99)} ms`}
          detail={`p50 ${number(data.judgement_ms?.p50)} ms · 네트워크·LLM 제외`}
          tag="판정 기록 기준"
          icon={Activity}
        />
      </div>
      <div className="dashboard-grid">
        <Panel
          title="최근 세션"
          subtitle="유효한 실험 기록을 시나리오와 모드별로 살펴보세요."
          action={<span className="count">{data.sessions.length} 세션</span>}
        >
          <FilteredTable sessions={data.sessions} open={open} />
        </Panel>
        <div className="stack">
          <Panel title="판정 알림" action={<Bell size={18} />}>
            <div className="alerts">
              {alerts.slice(0, 7).map((s) => (
                <button
                  key={s.id}
                  onClick={() => open(s.id)}
                  className={`alert-card ${s.mode === "block" ? "blocked-alert" : ""}`}
                >
                  <span className="alert-top">
                    <Badge session={s} />
                    <small>{s.short}</small>
                  </span>
                  <b>
                    {s.task_name} · {label(s.variant)}
                  </b>
                  <p>
                    {s.stop_text ||
                      `${s.first_stop}단계에서 STOP 판정이 기록되었습니다.`}
                  </p>
                  <span className="text-link">
                    판정 근거 보기 <ArrowRight size={14} />
                  </span>
                </button>
              ))}
              {!alerts.length && <Empty title="판정 알림이 없습니다" />}
            </div>
          </Panel>
          <div className="info-card">
            <ShieldCheck size={24} />
            <h3>관측과 차단의 차이</h3>
            <p>
              관측 모드는 STOP 이후에도 실행을 이어갑니다. 차단 모드는 이후
              요청을 차단합니다. 결과를 비교할 때 모드를 함께 확인하세요.
            </p>
          </div>
        </div>
      </div>
    </>
  );
}
function Metric({ title, value, detail, tag, icon: Icon, tone = "" }) {
  return (
    <section className={`metric ${tone}`}>
      <div>
        <span>{title}</span>
        <Icon size={18} />
      </div>
      <strong>{value}</strong>
      <p>{detail}</p>
      <small>{tag}</small>
    </section>
  );
}

function FilteredTable({ sessions, open }) {
  const [filters, set] = useState({
    search: "",
    task: "",
    variant: "",
    mode: "",
  });
  const [page, setPage] = useState(0);
  const filtered = useMemo(
    () => filterSessions(sessions, filters),
    [sessions, filters],
  );
  const size = 10;
  const currentPage = Math.min(
    page,
    Math.max(0, Math.ceil(filtered.length / size) - 1),
  );
  const change = (key, value) => {
    set((v) => ({ ...v, [key]: value }));
    setPage(0);
  };
  return (
    <>
      <div className="filters">
        <label className="search">
          <Search size={15} />
          <input
            aria-label="세션 검색"
            placeholder="세션 ID 또는 시나리오 검색"
            value={filters.search}
            onChange={(e) => change("search", e.target.value)}
          />
        </label>
        <select
          aria-label="시나리오 필터"
          value={filters.task}
          onChange={(e) => change("task", e.target.value)}
        >
          <option value="">시나리오 전체</option>
          {[...new Map(sessions.map((s) => [s.task, s.task_name]))].map(
            ([id, name]) => (
              <option key={id} value={id}>
                {name}
              </option>
            ),
          )}
        </select>
        <select
          aria-label="유형 필터"
          value={filters.variant}
          onChange={(e) => change("variant", e.target.value)}
        >
          <option value="">정상·교착 전체</option>
          <option value="normal">정상판</option>
          <option value="stall">교착판</option>
          <option value="natural">비교군</option>
        </select>
        <select
          aria-label="모드 필터"
          value={filters.mode}
          onChange={(e) => change("mode", e.target.value)}
        >
          <option value="">관측·차단 전체</option>
          <option value="observe">관측</option>
          <option value="block">차단</option>
        </select>
      </div>
      <SessionTable
        rows={filtered.slice(currentPage * size, (currentPage + 1) * size)}
        open={open}
      />
      <div className="pagination">
        <span>
          총 {number(filtered.length)}개 · {currentPage + 1} /{" "}
          {Math.max(1, Math.ceil(filtered.length / size))} 페이지
        </span>
        <div>
          <button
            aria-label="이전 페이지"
            disabled={currentPage === 0}
            onClick={() => setPage(currentPage - 1)}
          >
            <ChevronLeft size={15} />
          </button>
          <button
            aria-label="다음 페이지"
            disabled={(currentPage + 1) * size >= filtered.length}
            onClick={() => setPage(currentPage + 1)}
          >
            <ChevronRight size={15} />
          </button>
        </div>
      </div>
    </>
  );
}

export function Sessions({ data, selectedId, open }) {
  const selected =
    data.sessions.find((s) => s.id === selectedId) ||
    (!selectedId ? data.sessions[0] : null);
  return (
    <div className="stack">
      <Panel
        title="세션 선택"
        subtitle="각 단계의 작업·테스트·판정 근거를 재생합니다."
      >
        <select
          className="wide-select"
          aria-label="재생할 세션"
          value={selected?.id || ""}
          onChange={(e) => open(e.target.value)}
        >
          {!selected && <option value="">세션을 찾을 수 없습니다</option>}
          {data.sessions.map((s) => (
            <option key={s.id} value={s.id}>
              {s.task_name} · {label(s.variant)} · {label(s.mode)} · {s.short}
            </option>
          ))}
        </select>
      </Panel>
      {selected ? (
        <SessionViewer
          key={`${data.api}:${selected.id}`}
          session={selected}
          api={data.api}
          issueDefs={data.issue_defs}
        />
      ) : (
        <Empty title="선택한 세션을 찾을 수 없습니다" />
      )}
    </div>
  );
}

function SessionViewer({ session, api = false, issueDefs }) {
  const resource = useResource(
    async (signal) => {
      if (!api || session.loaded) return session;
      const id = encodeURIComponent(session.id);
      const [detail, steps] = await Promise.all([
        request(`/api/sessions/${id}`, { signal }),
        request(`/api/sessions/${id}/steps`, { signal }),
      ]);
      if (!Array.isArray(steps.steps))
        throw new Error("세션 단계 응답을 확인해 주세요.");
      return {
        ...session,
        name: detail.session?.scenario?.korean_name,
        title: detail.session?.scenario?.title,
        step_rows: steps.steps.map((f) => stepFromApi(f, session.roles)),
        loaded: true,
      };
    },
    [session.id, api],
  );
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const rows = resource.data?.step_rows || [];
  useEffect(() => {
    if (!playing) return;
    const timer = setInterval(
      () =>
        setIndex((i) => {
          if (i >= rows.length - 1) {
            setPlaying(false);
            return i;
          }
          return i + 1;
        }),
      900,
    );
    return () => clearInterval(timer);
  }, [playing, rows.length]);
  if (resource.loading)
    return <Loading text="세션 단계의 판정 기록을 읽는 중입니다" />;
  if (resource.error)
    return <ErrorBox error={resource.error} retry={resource.retry} />;
  const s = resource.data;
  const step = rows[Math.min(index, rows.length - 1)];
  const change = (i) => {
    setIndex(i);
    setPlaying(false);
  };
  const previous =
    step && rows.slice(0, index).findLast((r) => r.agent === step.agent);
  return (
    <>
      <Panel
        title={s.name || `${s.task_name} · ${label(s.variant)}`}
        subtitle={`${label(s.mode)} · ${label(s.class)} · ${s.steps} 단계 · ${number(s.tokens)} 토큰`}
        action={<Badge session={s} />}
      >
        <div className="session-meta">
          <code>{s.id}</code>
          <span>{date(s.started_at)}</span>
        </div>
        {!rows.length ? (
          <Empty title="이 세션에는 재생할 단계 기록이 없습니다" />
        ) : (
          <>
            <Timeline
              steps={rows}
              selected={step.n}
              onSelect={(n) => change(rows.findIndex((x) => x.n === n))}
            />
            <div className="legend">
              <span>
                <i className="progress" />
                진행·기준
              </span>
              <span>
                <i className="stagnant" />
                정체
              </span>
              <span>
                <i className="stop" />
                STOP
              </span>
              <span>
                <i className="blocked" />
                차단
              </span>
            </div>
            <div className="replay-controls">
              <button
                aria-label="이전 단계"
                disabled={!index}
                onClick={() => change(index - 1)}
              >
                <ChevronLeft size={16} />
              </button>
              <button
                className="primary"
                onClick={() => {
                  if (!playing && index === rows.length - 1) setIndex(0);
                  setPlaying(!playing);
                }}
              >
                {playing ? <Pause size={15} /> : <Play size={15} />}{" "}
                {playing ? "일시정지" : "자동 재생"}
              </button>
              <button
                aria-label="다음 단계"
                disabled={index >= rows.length - 1}
                onClick={() => change(index + 1)}
              >
                <ChevronRight size={16} />
              </button>
              <button
                disabled={
                  s.first_stop == null ||
                  !rows.some((r) => r.n === s.first_stop)
                }
                onClick={() =>
                  change(rows.findIndex((r) => r.n === s.first_stop))
                }
              >
                첫 STOP으로
              </button>
              <span className="muted">
                {index + 1} / {rows.length} 단계
              </span>
            </div>
            <TokenChart steps={rows} />
          </>
        )}
      </Panel>
      {step && (
        <Panel
          title={`${step.n}단계 · ${step.role || step.agent || "역할 미기록"}`}
          subtitle={`판정 상태 · ${step.label || step.state || "관측값 없음"}`}
        >
          <div className="step-layout">
            <div>
              {step.stop && (
                <div className="stop-message">
                  <b>STOP · {step.stop.t}</b>
                  <p>{step.stop.text}</p>
                </div>
              )}
              {step.blocked && (
                <div className="notice">
                  차단 모드에서 요청을 업스트림으로 전달하지 않고 403으로 반환한
                  단계입니다.
                </div>
              )}
              <KeyValue
                entries={[
                  [
                    "테스트",
                    step.tests
                      ? `${number(step.tests[0])} / ${number(step.tests[1])} 통과`
                      : null,
                  ],
                  [
                    "변경 파일",
                    step.paths?.length
                      ? step.paths.join(", ")
                      : step.tests == null
                        ? null
                        : "바뀐 파일 없음",
                  ],
                  ["작업 상태", step.report?.status],
                  ["인계 대상", step.report?.handoff],
                  [
                    "채택 항목",
                    step.report?.adopted == null
                      ? null
                      : number(step.report.adopted),
                  ],
                  [
                    "도구 호출 / 오류",
                    `${number(step.tools)} / ${number(step.tool_errors)}`,
                  ],
                  ["이 단계 토큰", number(step.tok)],
                  ["누적 토큰", number(step.cum)],
                  ["누적 크레딧 (추정)", number(step.cumc)],
                ]}
              />
            </div>
            <div className="detail-box">
              <h3>미해결 쟁점</h3>
              {step.report ? (
                <>
                  <p className="muted">
                    {previous?.report
                      ? `같은 역할의 ${previous.n}단계와 비교`
                      : "같은 역할의 이전 보고가 없습니다"}
                  </p>
                  <div className="chips">
                    {step.report.issue_ids?.length ? (
                      step.report.issue_ids.map((id) => (
                        <span key={id} title={issueDefs?.[s.scenario]?.[id]}>
                          {id}
                        </span>
                      ))
                    ) : (
                      <span>쟁점 없음</span>
                    )}
                  </div>
                  {previous?.report && (
                    <KeyValue
                      entries={[
                        [
                          "추가",
                          step.report.issue_ids
                            .filter(
                              (x) => !previous.report.issue_ids.includes(x),
                            )
                            .join(", ") || "없음",
                        ],
                        [
                          "빠짐",
                          previous.report.issue_ids
                            .filter((x) => !step.report.issue_ids.includes(x))
                            .join(", ") || "없음",
                        ],
                      ]}
                    />
                  )}
                </>
              ) : (
                <p className="muted">
                  검증된 보고가 없어 쟁점 변화를 확인할 수 없습니다.
                </p>
              )}
              <div className="notice">
                목록에서 빠졌다는 사실만으로 해결이 증명되지는 않습니다. 파일
                변화는 직전 단계 기준이며, 같은 역할 기준의 변화와 다를 수
                있습니다.
              </div>
            </div>
          </div>
        </Panel>
      )}
    </>
  );
}
function TokenChart({ steps }) {
  const max = Math.max(1, ...steps.map((s) => s.cum || 0));
  return (
    <div className="token-chart">
      <span className="muted small">단계별 누적 토큰</span>
      <div className="chart-bars">
        {steps.map((s) => (
          <div
            key={s.n}
            style={{ height: `${Math.max(3, ((s.cum || 0) / max) * 100)}%` }}
            className={s.stop ? "stop-bar" : ""}
            title={`${s.n}단계 · ${number(s.cum)} 토큰`}
          >
            <span>{s.n}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function Compare({ data, open }) {
  const tasks = Object.entries(data.task_names).filter(([id]) =>
    data.sessions.some((s) => s.task === id),
  );
  const [task, setTask] = useState(tasks[0]?.[0]);
  const options = (variant) =>
    data.sessions.filter(
      (s) => s.task === task && s.variant === variant && s.mode === "observe",
    );
  const [chosen, setChosen] = useState({});
  const normal =
    options("normal").find((s) => s.id === chosen.normal) ||
    options("normal")[0];
  const stall =
    options("stall").find((s) => s.id === chosen.stall) || options("stall")[0];
  return (
    <div className="stack">
      <Panel
        title="정상판과 교착판 비교"
        subtitle="같은 과제의 기록을 나란히 봅니다. 유도된 교착 실험이며 일반 탐지 성능으로 해석하지 않습니다."
      >
        <select
          aria-label="비교 시나리오"
          value={task}
          onChange={(e) => {
            setTask(e.target.value);
            setChosen({});
          }}
        >
          {tasks.map(([id, name]) => (
            <option key={id} value={id}>
              {name}
            </option>
          ))}
        </select>
      </Panel>
      <div className="grid-two">
        {[
          ["normal", normal],
          ["stall", stall],
        ].map(([variant, s]) => (
          <Panel
            key={variant}
            title={label(variant)}
            action={
              <span className={`badge ${variant === "normal" ? "ok" : "stop"}`}>
                {variant === "normal" ? "비교 기준" : "유도한 교착"}
              </span>
            }
          >
            <select
              className="wide-select"
              aria-label={`${label(variant)} 세션 선택`}
              value={s?.id || ""}
              onChange={(e) =>
                setChosen((v) => ({ ...v, [variant]: e.target.value }))
              }
            >
              {options(variant).map((row) => (
                <option key={row.id} value={row.id}>
                  {row.short} · {label(row.class)} · {row.steps}단계
                </option>
              ))}
            </select>
            {s ? (
              <>
                <KeyValue
                  entries={[
                    ["결과", label(s.class)],
                    ["단계", number(s.steps)],
                    ["토큰", number(s.tokens)],
                    ["첫 STOP", s.first_stop ?? "없음"],
                    ["크레딧", number(s.credits)],
                  ]}
                />
                <button onClick={() => open(s.id)}>
                  세션 재생으로 보기
                  <ArrowRight size={15} />
                </button>
              </>
            ) : (
              <Empty />
            )}
          </Panel>
        ))}
      </div>
      <Panel
        title="교착판에서 달라진 조건"
        subtitle="동결된 실험 시나리오의 변경 내역입니다."
      >
        {data.pairs?.[task]?.lines?.length ? (
          <pre className="diff">
            {data.pairs[task].lines.map((x, i) => (
              <span
                key={i}
                className={x.line.startsWith("+") ? "added" : "removed"}
              >
                {x.where}: {x.line}
                {"\n"}
              </span>
            ))}
          </pre>
        ) : (
          <Empty title="표시할 변경 줄이 없습니다" />
        )}
        <p className="muted">
          시나리오 변경 항목 ·{" "}
          {(data.pairs?.[task]?.scenario_keys || []).join(", ") ||
            "없음 / 별도 기록 없음"}
        </p>
      </Panel>
    </div>
  );
}

export function Statistics({ data }) {
  const groups = groupedStats(data.sessions);
  const max = Math.max(1, ...groups.map((g) => g.count));
  return (
    <div className="stack">
      <div className="grid-two">
        <Panel
          title="시나리오별 세션"
          subtitle="현재 조회한 유효 세션 · 관측과 차단 포함"
        >
          <div className="bar-list">
            {groups.map((g) => (
              <div key={g.task}>
                <span>{g.name}</span>
                <div>
                  <i style={{ width: `${(g.count / max) * 100}%` }} />
                </div>
                <b>{g.count}</b>
              </div>
            ))}
          </div>
        </Panel>
        <Panel title="결과 분포" subtitle="전체 세션의 최종 결과">
          <div className="result-grid">
            {["success", "stalled", "escalated", "other"].map((k) => (
              <div key={k}>
                <span>{label(k)}</span>
                <strong>
                  {data.sessions.filter((s) => s.class === k).length}
                </strong>
              </div>
            ))}
          </div>
        </Panel>
      </div>
      <Panel
        title="시나리오 요약"
        subtitle="현재 API 응답에서 계산한 집계입니다. STOP은 실제 교착과 다를 수 있습니다."
      >
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>시나리오</th>
                <th>세션</th>
                <th>성공</th>
                <th>교착</th>
                <th>STOP</th>
                <th>총 토큰</th>
              </tr>
            </thead>
            <tbody>
              {groups.map((g) => (
                <tr key={g.task}>
                  <td>{g.name}</td>
                  <td>{g.count}</td>
                  <td>{g.success}</td>
                  <td>{g.stall}</td>
                  <td>{g.stop}</td>
                  <td>{number(g.tokens)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
      <Panel
        title="차단 세션의 절감 결과"
        subtitle="같은 시나리오 관측 평균과 비교 · 동결된 본 실행 집계"
      >
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>시나리오</th>
                <th>차단 실행</th>
                <th>STOP</th>
                <th>토큰 절감</th>
                <th>크레딧 절감</th>
                <th>판정기 효과</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(data.headline.block || {}).map(([id, row]) => (
                <tr key={id}>
                  <td>{id}</td>
                  <td>{row.runs}</td>
                  <td>{row.with_stop}</td>
                  <td>{percent(row.token_saving)}</td>
                  <td>{percent(row.credit_saving)}</td>
                  <td>
                    {row.judged
                      ? "STOP이 난 시나리오"
                      : "판정기 효과로 해석하지 않음"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}

export function SystemPage({ data }) {
  const s = data.system;
  return (
    <div className="stack">
      <Panel
        title="요청과 관측의 흐름"
        subtitle="기존 프록시·판정기·저장소 구성은 유지합니다."
      >
        <div className="architecture">
          {[
            [Workflow, "멀티에이전트", "작업 실행 · 테스트"],
            [ShieldCheck, "Guardrail 프록시", "모델 요청 관측 · 차단"],
            [Layers, "업스트림 모델", s.model],
            [Database, "실험 기록", "PostgreSQL · 구조화 기록"],
          ].map(([Icon, title, sub], i) => (
            <div className="architecture-node" key={title}>
              <Icon size={26} />
              <h3>{title}</h3>
              <p>{sub}</p>
              {i < 3 && <ArrowRight className="architecture-arrow" size={20} />}
            </div>
          ))}
        </div>
        <p className="muted">
          실행기가 관측 API로 작업 근거를 보내고, 대시보드는 조회 API로 기록을
          읽습니다.
        </p>
      </Panel>
      <div className="grid-two">
        <Panel title="판정 구성">
          <KeyValue
            entries={[
              ["교착 기준", s.criteria_version],
              ["진행 판정", s.progress_version],
              ["설명 버전", s.explanation_version],
              ["연속 단계 n", s.n],
              ["정체 기준 k", s.k],
              ["차단 상태 코드", s.block_status],
            ]}
          />
        </Panel>
        <Panel title="연결 계약">
          <KeyValue
            entries={[
              ["모델 요청", s.chat_route],
              ["세션 등록", s.session_route],
              ["관측 전송", s.observation_route],
              ["세션 헤더", s.session_header],
              ["턴 헤더", s.turn_header],
              ["관측 / 차단 포트", `${s.port_observe} / ${s.port_block}`],
            ]}
          />
        </Panel>
      </div>
      <Panel
        title="관측 요청 예시"
        subtitle={`스키마 검증 ${data.example?.schema_checked ? "확인됨" : "미확인"} · 실제 기록의 구조화 값`}
      >
        <JsonView value={data.example?.body || {}} />
      </Panel>
    </div>
  );
}

export function Guide({ data, open }) {
  const steps = [
    [
      "프로젝트 만들기",
      "프로젝트 메뉴에서 이름과 관측·차단 모드를 선택하세요. 본인 소유의 프로젝트만 조회됩니다.",
    ],
    [
      "API 키와 연동 확인",
      "현재 main에는 API 키 관리 HTTP API가 없습니다. 키 발급은 백엔드 담당자와 확인하세요.",
    ],
    [
      "모델 호출 주소 연결",
      `프록시 주소와 ${data.system.session_header} 헤더를 실행기에 설정합니다. 이 화면에서 실행기를 시작하지 않습니다.`,
    ],
    [
      "작업 근거 전송",
      `실행기가 단계마다 ${data.system.observation_route}로 테스트와 구조화 보고를 보냅니다.`,
    ],
    [
      "기록과 판정 확인",
      "세션 재생에서 STOP 원인, 테스트, 파일 변화와 미해결 쟁점을 함께 확인합니다.",
    ],
    [
      "관측과 차단 비교",
      "관측의 추정 절감과 차단의 실제 사용량 차이를 구분하고, 정상판 오탐도 함께 살펴보세요.",
    ],
  ];
  return (
    <div className="stack">
      <Panel
        title="실험을 살펴보는 여섯 단계"
        subtitle="설정부터 기록 확인까지, 현재 제공되는 기능을 기준으로 안내합니다."
      >
        <div className="guide-steps">
          {steps.map(([title, text], i) => (
            <div key={title}>
              <span>{String(i + 1).padStart(2, "0")}</span>
              <div>
                <h3>{title}</h3>
                <p>{text}</p>
              </div>
            </div>
          ))}
        </div>
        <button
          className="primary"
          onClick={() => open(data.guide_session || data.sessions[0]?.id)}
        >
          대표 세션 재생
          <ArrowRight size={15} />
        </button>
      </Panel>
      <Panel title="판정 결과를 읽을 때">
        <div className="grid-two">
          <div className="notice">
            STOP은 자동 규칙의 신호입니다. 성공한 정상판에 STOP이 나면 오탐으로
            집계합니다. 쟁점 감소만으로 해결이 증명되지는 않습니다.
          </div>
          <div className="notice">
            이 데모의 교착판은 의도적으로 유도한 실험입니다. 현재 수치를
            일반적인 에이전트 탐지 성능으로 확장하지 마세요.
          </div>
        </div>
      </Panel>
    </div>
  );
}

export function LivePage({ preview }) {
  const [rows, setRows] = useState([]);
  const [error, setError] = useState(null);
  const [updated, setUpdated] = useState(null);
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [paused, setPaused] = useState(false);
  useEffect(() => {
    if (preview || paused) return;
    let active = true;
    const controller = new AbortController();
    let timer;
    const poll = async () => {
      try {
        const list = await request("/api/live/sessions", {
          signal: controller.signal,
        });
        const one = selected
          ? await request(
              `/api/live/sessions/${encodeURIComponent(selected)}`,
              { signal: controller.signal },
            )
          : null;
        if (active) {
          setRows(list.sessions || []);
          setUpdated(list.now);
          setDetail(one?.session || null);
          setError(null);
        }
      } catch (e) {
        if (active) setError(e);
      } finally {
        if (active) timer = setTimeout(poll, 2500);
      }
    };
    poll();
    return () => {
      active = false;
      controller.abort();
      clearTimeout(timer);
    };
  }, [preview, selected, paused]);
  if (preview)
    return (
      <Panel title="실시간 모니터">
        <Empty title="저장된 기록 미리보기에서는 실시간 조회를 하지 않습니다">
          로그인한 로컬 실행에서 API를 연결해 주세요.
        </Empty>
      </Panel>
    );
  return (
    <div className="stack">
      <Panel
        title="최근 변경된 실행 기록"
        subtitle={`2.5초마다 조회 · 마지막 갱신 ${date(updated)}`}
        action={
          <button onClick={() => setPaused(!paused)}>
            {paused ? <Play size={15} /> : <Pause size={15} />}{" "}
            {paused ? "조회 재개" : "조회 일시정지"}
          </button>
        }
      >
        {error && <ErrorBox error={error} />}
        <SessionTable rows={rows} open={(id) => setSelected(id)} />
        <p className="muted">
          파일 갱신 시각 기준입니다. 실행 중 표시는 최근 활동의 보장이 아니며,
          이 화면은 새 에이전트 실행을 시작하지 않습니다.
        </p>
      </Panel>
      {detail && (
        <SessionViewer key={`${detail.id}:${detail.steps}`} session={detail} />
      )}
    </div>
  );
}

export function Projects({ user, preview }) {
  const projects = useResource(
    (signal) =>
      preview ? Promise.resolve([]) : request("/api/projects", { signal }),
    [preview],
  );
  const [name, setName] = useState("");
  const [mode, setMode] = useState("observe");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [offset, setOffset] = useState(0);
  const sessions = useResource(
    (signal) =>
      !selected
        ? Promise.resolve(null)
        : request(
            `/api/projects/${selected}/sessions?limit=20&offset=${offset}`,
            { signal },
          ),
    [selected, offset],
  );
  const create = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await post("/api/projects", {
        name: name.trim(),
        mode,
        csrf_token: user.csrf_token,
      });
      setName("");
      projects.retry();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  const select = (id) => {
    setSelected(id);
    setOffset(0);
    setDetail(null);
  };
  const loadDetail = async (id) => {
    setError(null);
    try {
      setDetail(
        await request(
          `/api/projects/${selected}/sessions/${encodeURIComponent(id)}`,
        ),
      );
    } catch (e) {
      setError(e);
    }
  };
  if (preview)
    return (
      <Panel title="프로젝트 관리">
        <Empty title="프로젝트 관리에는 로그인이 필요합니다">
          미리보기에서는 프로젝트를 생성하거나 사용자 데이터를 조회하지
          않습니다.
        </Empty>
      </Panel>
    );
  return (
    <div className="stack">
      <div className="grid-two">
        <Panel
          title="내 프로젝트"
          subtitle="로그인한 계정이 소유한 프로젝트만 표시합니다."
        >
          {projects.loading ? (
            <Loading />
          ) : projects.error ? (
            <ErrorBox error={projects.error} retry={projects.retry} />
          ) : projects.data.length ? (
            <div className="project-list">
              {projects.data.map((p) => (
                <button
                  className={selected === p.id ? "selected-project" : ""}
                  key={p.id}
                  onClick={() => select(p.id)}
                >
                  <span className="project-symbol">
                    <Layers size={20} />
                  </span>
                  <span>
                    <b>{p.name}</b>
                    <small>
                      {label(p.mode)} · {p.rule_id}
                    </small>
                  </span>
                  <ChevronRight size={17} />
                </button>
              ))}
            </div>
          ) : (
            <Empty title="소유한 프로젝트가 없습니다">
              새 프로젝트를 만들어 시작하세요. 기존 데모 기록은 자동으로 본인
              프로젝트에 연결되지 않습니다.
            </Empty>
          )}
        </Panel>
        <Panel title="프로젝트 만들기">
          <form onSubmit={create} className="form">
            <label>
              프로젝트 이름
              <input
                maxLength={100}
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="예: 캡스톤 실험 01"
              />
            </label>
            <label>
              실행 모드
              <select value={mode} onChange={(e) => setMode(e.target.value)}>
                <option value="observe">관측</option>
                <option value="block">차단</option>
              </select>
            </label>
            <button className="primary" disabled={busy || !name.trim()}>
              <Plus size={16} />
              {busy ? "생성 중…" : "프로젝트 만들기"}
            </button>
          </form>
        </Panel>
      </div>
      {error && <ErrorBox error={error} />}
      {selected && (
        <Panel
          title="프로젝트 세션"
          subtitle={`프로젝트 #${selected} · 20개씩 표시`}
        >
          {sessions.loading ? (
            <Loading />
          ) : sessions.error ? (
            <ErrorBox error={sessions.error} retry={sessions.retry} />
          ) : (
            <>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>세션</th>
                      <th>시나리오</th>
                      <th>상태</th>
                      <th>기록 시각</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(sessions.data?.items || []).map((s) => (
                      <tr key={s.id}>
                        <td>
                          <button
                            className="table-link mono"
                            onClick={() => loadDetail(s.id)}
                          >
                            {s.id}
                          </button>
                        </td>
                        <td>{s.scenario_id}</td>
                        <td>{s.status}</td>
                        <td>{date(s.started_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {!sessions.data?.items?.length && (
                <Empty title="이 프로젝트의 세션이 없습니다" />
              )}
              <div className="pagination">
                <span>전체 {number(sessions.data?.total)}개</span>
                <div>
                  <button
                    disabled={!offset}
                    onClick={() => {
                      setOffset(Math.max(0, offset - 20));
                      setDetail(null);
                    }}
                  >
                    이전
                  </button>
                  <button
                    disabled={offset + 20 >= (sessions.data?.total || 0)}
                    onClick={() => {
                      setOffset(offset + 20);
                      setDetail(null);
                    }}
                  >
                    다음
                  </button>
                </div>
              </div>
            </>
          )}
        </Panel>
      )}
      {detail && (
        <Panel title="프로젝트 세션 상세">
          <KeyValue
            entries={Object.entries(detail).map(([k, v]) => [
              k,
              v && typeof v === "object" ? JSON.stringify(v) : String(v ?? "—"),
            ])}
          />
        </Panel>
      )}
    </div>
  );
}

export function Account({ user, preview, refresh }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const action = async (type) => {
    const message =
      type === "withdraw"
        ? "계정을 탈퇴하시겠습니까? 즉시 로그아웃되고 키가 폐기되며, 30일 뒤 데이터가 삭제될 수 있습니다."
        : "계정을 복구하시겠습니까? 복구 후 다시 로그인해야 합니다.";
    if (!window.confirm(message)) return;
    setBusy(true);
    setError(null);
    try {
      await post(`/api/auth/${type}`, {
        confirm: true,
        csrf_token: user.csrf_token,
      });
      location.assign("/login");
    } catch (e) {
      setError(e);
      setBusy(false);
    }
  };
  const signOut = async () => {
    setBusy(true);
    setError(null);
    try {
      await logout();
    } catch (e) {
      setError(e);
      setBusy(false);
    }
  };
  if (preview)
    return (
      <Panel title="내 계정">
        <Empty title="로그인한 계정이 없습니다">
          저장된 기록 미리보기입니다.
        </Empty>
        <a className="button primary" href="/login">
          Google 로그인
        </a>
      </Panel>
    );
  return (
    <div className="stack">
      <Panel
        title="내 계정"
        subtitle="Google 계정과 서비스 계정의 상태를 확인합니다."
      >
        <div className="profile">
          <span className="profile-avatar">
            {(user.name || "G").slice(0, 1)}
          </span>
          <div>
            <h2>{user.name || "Google 사용자"}</h2>
            <p>{user.email}</p>
            <span
              className={`badge ${user.account_status === "active" ? "ok" : "stop"}`}
            >
              {user.account_status === "active" ? "활성 계정" : "탈퇴 유예 중"}
            </span>
          </div>
        </div>
        <KeyValue
          entries={[
            ["로그인 방식", "Google Identity Services"],
            [
              "접근 범위",
              user.session_scope === "full" ? "정상 서비스 이용" : "복구 전용",
            ],
            [
              "삭제 예정 시각",
              user.deletion_due_at ? date(user.deletion_due_at) : "없음",
            ],
          ]}
        />
        <div className="actions">
          <button disabled={busy} onClick={signOut}>
            <LogOut size={16} />
            로그아웃
          </button>
          <button disabled={busy} onClick={refresh}>
            상태 다시 확인
          </button>
        </div>
      </Panel>
      {error && <ErrorBox error={error} />}
      <Panel
        title={user.account_status === "active" ? "계정 탈퇴" : "계정 복구"}
        subtitle={
          user.account_status === "active"
            ? "탈퇴 시 세션과 API 키가 폐기됩니다. 복구해도 기존 키는 복원되지 않습니다."
            : "복구는 Google 재인증 후 10분 이내에 요청해야 합니다."
        }
      >
        {user.account_status === "active" ? (
          <button
            className="danger"
            disabled={busy}
            onClick={() => action("withdraw")}
          >
            계정 탈퇴 요청
          </button>
        ) : (
          <>
            <button
              disabled={busy || !user.can_restore}
              onClick={() => action("restore")}
            >
              계정 복구
            </button>
            <a href="/login?reauth=1">Google로 다시 인증</a>
          </>
        )}
      </Panel>
    </div>
  );
}

export function KeysPage() {
  return (
    <Panel
      title="API 키 관리"
      subtitle="현재 main에 제공된 서버 기능을 기준으로 표시합니다."
    >
      <div className="feature-pending">
        <span className="feature-icon">
          <KeyRound size={32} />
        </span>
        <span className="badge">서버 API 미제공</span>
        <h3>키 관리 API 연결이 필요합니다</h3>
        <p>
          현재 백엔드에는 API 키 발급·조회·폐기 HTTP 엔드포인트가 없습니다.
          <br />
          키를 임의로 생성하거나 저장하지 않습니다. 백엔드 API가 제공되면
          프로젝트 소유권과 인증 규격에 맞춰 연결해야 합니다.
        </p>
        <a href="#projects">
          프로젝트 확인
          <ArrowRight size={15} />
        </a>
      </div>
    </Panel>
  );
}
