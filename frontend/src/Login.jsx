import { useEffect, useRef, useState } from "react";
import { ArrowRight, ShieldCheck } from "lucide-react";

export default function Login() {
  const mount = useRef(null);
  const [error, setError] = useState("");
  const clientId = import.meta.env.VITE_GOOGLE_CLIENT_ID;
  useEffect(() => {
    if (!clientId) return;
    let active = true;
    const existing = document.getElementById("google-identity");
    const initialize = () => {
      if (!active || !mount.current || !window.google) return;
      mount.current.replaceChildren();
      window.google.accounts.id.initialize({
        client_id: clientId,
        ux_mode: "redirect",
        login_uri: `${location.origin}/api/auth/google`,
        auto_select: false,
      });
      window.google.accounts.id.renderButton(mount.current, {
        theme: "outline",
        size: "large",
        width: 300,
        locale: "ko",
      });
    };
    if (window.google) initialize();
    else if (existing) existing.addEventListener("load", initialize);
    else {
      const script = document.createElement("script");
      script.id = "google-identity";
      script.src = "https://accounts.google.com/gsi/client";
      script.async = true;
      script.onload = initialize;
      script.onerror = () =>
        active &&
        setError(
          "Google 로그인 스크립트를 불러오지 못했습니다. 네트워크를 확인해 주세요.",
        );
      document.head.append(script);
    }
    return () => {
      active = false;
      existing?.removeEventListener("load", initialize);
    };
  }, [clientId]);
  return (
    <div className="login-layout">
      <section className="login-story">
        <div className="brand">
          <ShieldCheck size={32} />
          agent guardrail
        </div>
        <div>
          <p className="eyebrow">OBSERVE. UNDERSTAND. IMPROVE.</p>
          <h1>
            에이전트의 다음 단계,
            <br />
            근거와 함께.
          </h1>
          <p>
            실험의 흐름을 관측하고, 교착 신호를 발견하고,
            <br />
            작업 기록으로 판정을 확인하세요.
          </p>
          <div className="login-steps">
            <span>01 관측</span>
            <i />
            <span>02 판정</span>
            <i />
            <span>03 기록</span>
          </div>
        </div>
        <small>CAPSTONE · MULTI-AGENT EXPERIMENT CONSOLE</small>
      </section>
      <section className="login-form">
        <div className="login-card">
          <span className="brand-icon">
            <ShieldCheck size={26} />
          </span>
          <p className="eyebrow">WELCOME BACK</p>
          <h2>실험 워크스페이스에 로그인</h2>
          <p>
            허용된 Google 계정으로 계속하세요.
            <br />첫 로그인 시 서비스 계정이 생성됩니다.
          </p>
          <div ref={mount} className="google-button" />
          {!clientId && (
            <div className="notice">
              Google 클라이언트 ID가 필요합니다.{" "}
              <code>frontend/.env.local</code>의{" "}
              <code>VITE_GOOGLE_CLIENT_ID</code>를 설정하고 개발 서버를 다시
              실행해 주세요.
            </div>
          )}
          {error && <p role="alert">{error}</p>}
          <p className="muted small">
            Google 비밀번호는 이 서비스에 전달되지 않습니다.
            <br />
            로컬 로그인은 localhost 주소로 통일하세요.
          </p>
          <a className="preview-link" href="/?preview=1">
            저장된 데모 먼저 살펴보기
            <ArrowRight size={16} />
          </a>
        </div>
      </section>
    </div>
  );
}
