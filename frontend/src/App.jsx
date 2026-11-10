import { useEffect, useState } from "react";
import {
  Activity,
  ArrowRight,
  BookOpen,
  ChartColumn,
  ChevronRight,
  CircleHelp,
  FlaskConical,
  GitCompareArrows,
  KeyRound,
  LayoutDashboard,
  LogIn,
  Menu,
  Network,
  PanelsTopLeft,
  RefreshCw,
  ShieldCheck,
  UserRound,
} from "lucide-react";
import { request } from "./api.js";
import { fromApi } from "./model.js";
import { Empty, ErrorBox, Loading, useResource } from "./components.jsx";
import {
  Dashboard,
  Sessions,
  Compare,
  Statistics,
  SystemPage,
  Guide,
  LivePage,
  Projects,
  Account,
  KeysPage,
} from "./pages.jsx";
import Login from "./Login.jsx";

const navigation = [
  ["dashboard", "대시보드", LayoutDashboard],
  ["session", "세션 재생", PanelsTopLeft],
  ["compare", "비교", GitCompareArrows],
  ["stats", "통계", ChartColumn],
  ["system", "시스템 구조", Network],
  ["guide", "사용 가이드", BookOpen],
  ["live", "실시간 모니터", Activity],
  ["projects", "프로젝트", FlaskConical],
  ["keys", "API 키 관리", KeyRound],
  ["account", "내 계정", UserRound],
];
function route() {
  const [page, id] = location.hash.slice(1).split("/");
  return {
    page: navigation.some((n) => n[0] === page) ? page : "dashboard",
    id: id ? decodeURIComponent(id) : null,
  };
}
function go(page, id) {
  location.hash = id ? `${page}/${encodeURIComponent(id)}` : page;
}

export default function App() {
  const preview = new URLSearchParams(location.search).get("preview") === "1";
  const [current, setCurrent] = useState(route);
  const [mobile, setMobile] = useState(false);
  const auth = useResource(
    (signal) =>
      preview ? Promise.resolve(null) : request("/api/auth/me", { signal }),
    [preview],
  );
  useEffect(() => {
    const update = () => {
      setCurrent(route());
      setMobile(false);
    };
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, []);
  const loggedIn = !!auth.data;
  if (!preview && auth.loading)
    return <Loading text="로그인 상태를 확인하는 중입니다" />;
  if (!preview && auth.error?.status !== 401 && auth.error)
    return (
      <div className="auth-shell">
        <ShieldCheck size={38} />
        <h1>Agent Guardrail</h1>
        <ErrorBox error={auth.error} retry={auth.retry} />
        <p>
          <a href="/?preview=1">저장된 데모 화면 살펴보기</a>
        </p>
      </div>
    );
  if (!preview && !loggedIn) return <Login onDone={auth.retry} />;
  if (
    !preview &&
    location.pathname === "/login" &&
    new URLSearchParams(location.search).get("reauth") === "1"
  )
    return <Login />;
  // Recovery-only accounts can inspect account state but cannot load demo/project APIs.
  if (
    !preview &&
    (auth.data.account_status !== "active" ||
      auth.data.session_scope !== "full")
  )
    return (
      <div className="auth-shell">
        <Account user={auth.data} refresh={auth.retry} />
      </div>
    );
  const title = navigation.find((n) => n[0] === current.page)?.[1];
  return (
    <div className="app">
      <a href="#main-content" className="skip-link">
        본문으로 이동
      </a>
      <aside className={`sidebar ${mobile ? "expanded" : ""}`}>
        <a className="brand" href="#dashboard">
          <span className="brand-icon">
            <ShieldCheck size={24} />
          </span>
          <div>
            agent<span>guardrail</span>
            <small>EXPERIMENT CONSOLE</small>
          </div>
        </a>
        <div className="workspace">
          <span className="workspace-avatar">G</span>
          <div>
            캡스톤 데모<small>실험 워크스페이스</small>
          </div>
          <ChevronRight size={15} />
        </div>
        <div className="nav-label">워크스페이스</div>
        <nav aria-label="주 메뉴">
          {navigation.map(([key, name, Icon], index) => (
            <button
              key={key}
              className={`${current.page === key ? "active" : ""} ${index === 7 ? "nav-divider" : ""}`}
              aria-current={current.page === key ? "page" : undefined}
              onClick={() => go(key)}
            >
              <Icon size={18} />
              <span>{name}</span>
              {key === "live" && <i className="live-dot" />}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <a href="#guide">
            <CircleHelp size={16} />
            사용 가이드
            <ArrowRight size={15} />
          </a>
          <button className="account-link" onClick={() => go("account")}>
            <span className="avatar">
              {preview ? "D" : (auth.data.name || "G").slice(0, 1)}
            </span>
            <span>
              {preview ? "데모 미리보기" : auth.data.name || "내 계정"}
              <small>
                {preview ? "저장된 기록만 조회" : "Google 계정으로 로그인됨"}
              </small>
            </span>
          </button>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <div>
            <button
              className="icon-button menu-button"
              aria-label="메뉴 열기"
              onClick={() => setMobile(!mobile)}
            >
              <Menu size={20} />
            </button>
            <span>워크스페이스</span>
            <ChevronRight size={14} />
            <b>{title}</b>
          </div>
          <span className={`connection ${preview ? "preview" : ""}`}>
            <i />
            {preview ? "저장된 데모" : "로컬 API 연결"}
          </span>
        </header>
        <main id="main-content">
          <div className="page-heading">
            <div>
              <p className="eyebrow">
                AGENT GUARDRAIL / {current.page.toUpperCase()}
              </p>
              <h1>{title}</h1>
              <p>멀티에이전트 실험의 진행과 판정 근거를 함께 살펴보세요.</p>
            </div>
            <span className="version">
              <ShieldCheck size={15} />
              관측 · 차단 모드
            </span>
          </div>
          {preview && (
            <div className="preview-notice">
              <BookOpen size={17} />
              <span>
                저장된 실제 실험 67개를 살펴보는 미리보기입니다. 로그인·프로젝트
                변경·실시간 조회는 사용할 수 없습니다.
              </span>
              <a href="/login">로그인하기</a>
            </div>
          )}
          {current.page === "account" ? (
            <Account user={auth.data} preview={preview} refresh={auth.retry} />
          ) : current.page === "projects" ? (
            <Projects user={auth.data} preview={preview} />
          ) : current.page === "keys" ? (
            <KeysPage />
          ) : (
            <DataPages current={current} preview={preview} />
          )}
        </main>
        <footer>
          <span>Agent Guardrail · 캡스톤 실험</span>
          <span>
            교착 판정은 자동 규칙의 결과입니다. 작업·테스트 근거를 함께
            검토하세요.
          </span>
        </footer>
      </div>
    </div>
  );
}

function DataPages({ current, preview }) {
  const data = useResource(
    async (signal) => {
      const ref = await request(
        preview ? "/records.json" : "/api/frontend/reference",
        { signal },
      );
      if (preview) return ref;
      const [summary, list] = await Promise.all([
        request("/api/summary", { signal }),
        request("/api/sessions?validity=valid", { signal }),
      ]);
      if (!Array.isArray(list.sessions) || !summary.headline)
        throw new Error("조회 API의 응답 구조를 확인해 주세요.");
      return {
        ...ref,
        headline: summary.headline,
        judgement_ms: summary.judgement_ms,
        sessions: list.sessions.map((s) => fromApi(s, ref.task_names)),
        api: true,
      };
    },
    [preview],
  );
  const open = (id) => go("session", id);
  if (data.loading) return <Loading />;
  if (data.error)
    return (
      <>
        <ErrorBox error={data.error} retry={data.retry} />
        <p className="muted">
          서버 데이터가 없어도 <a href="/?preview=1">저장된 기록 미리보기</a>를
          별도로 열 수 있습니다.
        </p>
      </>
    );
  if (!data.data) return <Empty />;
  const props = { data: data.data, open, preview };
  const pages = {
    dashboard: Dashboard,
    session: Sessions,
    compare: Compare,
    stats: Statistics,
    system: SystemPage,
    guide: Guide,
    live: LivePage,
  };
  const Page = pages[current.page] || Dashboard;
  return (
    <>
      <div className="data-toolbar">
        <span>
          <i className="source-dot" />
          {preview ? "저장된 실제 실험 기록" : "DB 조회 API · 집계와 세션"}
          <small> · 비교 기준·구성 설명은 동결 기록 기준</small>
        </span>
        <button onClick={data.retry}>
          <RefreshCw size={14} />
          새로고침
        </button>
      </div>
      <Page {...props} selectedId={current.id} />
      <p className="source-line">출처 · {data.data.source}</p>
    </>
  );
}
