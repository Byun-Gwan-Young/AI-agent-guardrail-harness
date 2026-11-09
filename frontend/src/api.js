export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

export async function request(path, { signal, ...options } = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    cache: "no-store",
    signal: signal
      ? AbortSignal.any([signal, AbortSignal.timeout(12000)])
      : AbortSignal.timeout(12000),
    ...options,
    headers: { Accept: "application/json", ...options.headers },
  });
  if (!response.ok) {
    const messages = {
      401: "로그인이 필요하거나 세션이 만료되었습니다.",
      403: "접근 권한 또는 계정 상태를 확인해 주세요.",
      404: "요청한 기록을 찾을 수 없습니다.",
      503: "서버 또는 DB에 연결할 수 없습니다.",
    };
    throw new ApiError(
      messages[response.status] || `요청에 실패했습니다 (${response.status}).`,
      response.status,
    );
  }
  if (!response.headers.get("content-type")?.includes("application/json")) {
    throw new ApiError(
      "API 대신 HTML이 반환됐습니다. 서버 연결과 로그인 상태를 확인해 주세요.",
      response.redirected ? 401 : 502,
    );
  }
  return response.json();
}

export const post = (path, body) =>
  request(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

// Existing backend expects its session-cookie value, not /me's action CSRF, for logout.
// Read the existing server-rendered form; never copy the token to storage or logs.
export async function logout() {
  const response = await fetch("/legacy-login", {
    credentials: "same-origin",
    cache: "no-store",
  });
  if (!response.ok)
    throw new ApiError("로그아웃 화면을 불러오지 못했습니다.", response.status);
  const doc = new DOMParser().parseFromString(
    await response.text(),
    "text/html",
  );
  const token = doc.querySelector(
    'form[action="/api/auth/logout"] input[name="csrf_token"]',
  )?.value;
  if (!token)
    throw new ApiError(
      "로그인 세션을 확인할 수 없습니다. 다시 로그인해 주세요.",
      401,
    );
  const form = document.createElement("form");
  form.method = "POST";
  form.action = "/api/auth/logout";
  const input = document.createElement("input");
  input.type = "hidden";
  input.name = "csrf_token";
  input.value = token;
  form.append(input);
  document.body.append(form);
  form.submit();
}
