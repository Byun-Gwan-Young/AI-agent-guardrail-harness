# Agent Guardrail Backend

## 프론트 연동 인수인계

### 현재 바로 연결할 수 있는 기능

구글 가입·로그인, 로그인 상태 조회, 프로젝트·세션 목록·상세, 회원 탈퇴·복구 API가 구현돼 있습니다.
가입은 허용된 구글 계정의 첫 로그인에서 자동 처리하며 별도 가입 API는 없습니다.
프로젝트 생성 API도 사용할 수 있습니다. 키 관리·통계·실시간 알림 HTTP API는 아직 제공하지 않습니다.
기존 데모 API와 현재 프로젝트별 조회 API는 주소와 응답 구조가 다르므로 포트만 바꾸지 말고 아래 명세와 /docs를 기준으로 연결하세요.

### 로컬 연결 설정

프론트 Vite가 5173, 백엔드가 8030인 예시입니다. 프론트 포트가 다르면 아래 주소도 함께 맞춥니다.
브라우저에서는 localhost로 통일하고 프론트의 상대 경로 /api를 호출합니다.
Vite 설정 예시는 다음과 같습니다.

```javascript
server: {
  port: 5173,
  proxy: {
    '/api': { target: 'http://127.0.0.1:8030', changeOrigin: true },
    '/login': { target: 'http://127.0.0.1:8030', changeOrigin: true },
  },
}
```

이 구성에서는 백엔드의 GOOGLE_LOGIN_URI를 http://localhost:5173/api/auth/google로 설정하고,
Google 콘솔에도 로그인 페이지의 Origin인 http://localhost:5173과 해당 리다이렉트 URI를 등록합니다.
GOOGLE_CLIENT_ID는 실제 발급한 웹 클라이언트 ID를 사용하며 백엔드 검증 설정과 일치해야 합니다.
로컬 HTTP에서는 AUTH_COOKIE_SECURE=false로 실행합니다. 세부 서버 실행·DB·허용 이메일 설정은 아래 로컬 실행 절을 참고하세요.
프론트를 file://로 열지 않습니다. 직접 서로 다른 Origin으로 호출하려면 백엔드 CORS 등 추가 설정이 필요하며 현재 앱에는 CORS 설정이 없습니다.

### 로그인과 로그아웃: 현재 구현의 연결 방법

현재는 http://localhost:5173/login으로 페이지 전체를 이동해 백엔드의 테스트 화면에서 로그인할 수 있습니다.
GIS는 credential과 g_csrf_token을 폼으로 /api/auth/google에 전송하며, 백엔드는 CSRF 쿠키와 비교합니다.
현재 엔드포인트는 ID 토큰 JSON이나 Bearer 토큰을 받는 방식이 아닙니다.
인증 성공 시 HttpOnly 세션 쿠키를 발급하고 /login으로 303 리다이렉트합니다.
프론트 대시보드로 자동 이동하는 처리는 아직 없으므로, 테스트 화면에서 로그인 후 프론트 주소로 돌아가 /me로 상태를 확인하세요.

프론트 자체 GIS 버튼·로그인 완료 화면을 붙이려면 백엔드 담당자와 성공 리다이렉트 경로를 먼저 맞춰야 합니다.
현재 로그아웃은 /login HTML의 폼으로 실행하세요.
POST /api/auth/logout은 폼의 csrf_token을 원본 세션 쿠키와 비교하지만, 세션 쿠키는 HttpOnly여서 프론트 JavaScript가 읽을 수 없습니다.
/me에서 받은 별도 CSRF 값을 현재 로그아웃에 보내면 실패합니다.
React 화면에 독립적인 로그아웃 버튼을 만들려면 백엔드가 /me의 CSRF 토큰을 검증하는 규격으로 바뀌어야 합니다.

### 앱 시작 시 로그인 상태 확인

```javascript
const response = await fetch('/api/auth/me', {
  credentials: 'include',
  cache: 'no-store',
});
if (response.status === 401) {
  // 비로그인: 로그인 화면 표시
} else if (response.ok) {
  const user = await response.json();
  if (user.account_status === 'active' && user.session_scope === 'full') {
    // 대시보드 표시
  } else {
    // 복구 또는 재인증 안내. 일반 프로젝트 API 호출 금지
  }
} else {
  // DB 장애 등 오류 안내. 비로그인으로 단정하지 않음
}
```

/me는 id, sub, name, email, account_status, session_scope,
deletion_requested_at, deletion_due_at, can_restore, csrf_token을 반환합니다.
삭제 예정 시각은 ISO 문자열이고 정상 계정의 삭제 시각과 can_restore는 null일 수 있습니다.
쿠키를 localStorage의 토큰으로 대체하거나 API 키로 구글 로그인 인증을 시도하지 않습니다.
세션은 단일 서버 프로세스 메모리에 1시간 보관되며 서버 재시작 시 로그인부터 다시 해야 합니다.
화면에서 메뉴를 숨기는 것과 별개로 실제 접근 권한은 백엔드가 검사합니다.

### 프로젝트·세션 조회

| 메서드·경로 | 프론트 처리 |
|---|---|
| GET /api/projects | 본인 프로젝트 목록. 빈 목록은 소유 프로젝트가 없다는 의미 |
| POST /api/projects | 본인 소유 프로젝트 생성. 아래 생성 예시 참고 |
| GET /api/projects/{project_id}/sessions?limit=20&offset=0 | 세션 목록·페이지네이션 |
| GET /api/projects/{project_id}/sessions/{session_id} | 선택한 세션의 상세 |
| GET /api/auth/me | 로그인 사용자와 계정 상태 조회 |

fetch 요청에는 credentials: 'include'를 사용합니다. 조회 응답 필드·nullable 값·구조는 http://localhost:8030/docs를 확인하세요.
본인 프로젝트만 표시하며, 타인·미존재 프로젝트나 다른 프로젝트 소속 세션은 404입니다.
소유자 없는 기존 프로젝트는 로그인해도 목록에 표시되지 않습니다. 프론트에서 기존 프로젝트를 임의로 본인 소유로 간주하지 않습니다.

### 프로젝트 생성

`POST /api/projects`는 로그인한 활성 사용자만 호출할 수 있습니다.
이름은 앞뒤 공백 제거 후 1~100자이고 모드는 `observe` 또는 `block`입니다. 모드를 생략하면 `observe`입니다.
`csrf_token`은 `/api/auth/me`에서 가져옵니다.

```javascript
const response = await fetch('/api/projects', {
  method: 'POST',
  credentials: 'include',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    name: '첫 프로젝트',
    mode: 'observe',
    csrf_token: user.csrf_token,
  }),
});
if (!response.ok) {
  const error = await response.json();
  throw new Error(error.detail || '프로젝트 생성 실패');
}
const project = await response.json();
// project.id를 선택 상태에 저장하고 GET /api/projects로 목록 갱신
```

성공 시 201과 `id`, `name`, `mode`, `rule_id`, `created_at`을 반환합니다.
소유자는 서버가 세션에서 정합니다. `owner_user_id`, `rule_id`, `provider`, `upstream_url`, `read_only` 같은 추가 필드는 422로 거절합니다.
API 키는 이 요청으로 발급하지 않습니다. 생성 시점에는 실행 세션이 없어 목록이 비어 있는 것이 정상입니다.

생성 기본 provider는 백엔드 설정이 필요합니다. 예를 들어 백엔드 실행 전 같은 터미널에서 다음을 설정합니다.

```powershell
$env:GUARDRAIL_DEFAULT_PROVIDER = "groq"
# 기본 규칙을 바꿀 때만 설정. 생략 시 deadlock-v0.3
$env:GUARDRAIL_DEFAULT_RULE_ID = "deadlock-v0.3"
```

KMU를 사용하는 환경이면 기본 provider를 `kmu`로 정하고 `GUARDRAIL_PROVIDER_KMU_URL`도 실제 학교 게이트웨이 주소로 설정합니다.
Groq/OpenAI의 기본 URL은 Storage가 결정합니다. provider나 규칙 변경은 서버 재시작 후 적용합니다.
서버 provider 설정 누락·오류 또는 DB 실패는 503입니다. 세부 접속 정보는 응답에 노출하지 않습니다.
비로그인은 401, 복구 전용 계정이나 CSRF 불일치는 403, 이름·모드·필드 형식 오류는 422입니다.
프로젝트 이름에 비밀 키로 보이는 문자열도 넣지 않습니다.

기존 `storage.accounts.create_project`를 사용하므로 별도 스키마 추가는 없습니다.
생성과 감사 기록은 같은 트랜잭션이며, 사용자 행을 잠근 뒤 활성 상태를 재검사해 탈퇴 직후 생성을 차단합니다.

```powershell
.venv/Scripts/python.exe -m unittest backend.test_projects
```

프로젝트 API 테스트 9개와 관련 인증·권한·Storage·삭제 작업을 포함한 회귀 테스트 85개가 통과했습니다.
별도 임시 PostgreSQL 통합 테스트는 7개가 통과했으며 생성 소유자·기본값 저장, 감사 기록 실패 시 롤백, 탈퇴 후 생성 차단을 포함합니다.

### 탈퇴·복구 버튼 요청 예시

/me에서 받은 user.csrf_token을 사용하며 사용자 ID나 이메일은 본문에 넣지 않습니다.
버튼 클릭 시 먼저 확인창을 띄우고 중복 클릭을 막으세요.

```javascript
async function accountAction(action, user) {
  if (!['withdraw', 'restore'].includes(action)) throw new Error('Invalid action');
  const response = await fetch('/api/auth/' + action, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ confirm: true, csrf_token: user.csrf_token }),
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || '계정 요청 실패');
  }
  const result = await response.json();
  // 캐시된 사용자·프로젝트·세션 정보를 지우고 로그인 화면으로 이동
  window.location.assign('/login');
  return result;
}
```

| 동작 | 조건·성공 후 화면 |
|---|---|
| 탈퇴: POST /api/auth/withdraw | active·full 세션 필요. 즉시 로그아웃되며 30일 유예 시작 |
| 탈퇴 후 구글 재로그인 | pending_deletion·recovery 세션. 프로젝트 대신 복구 안내 표시 |
| 복구: POST /api/auth/restore | 유예 기간 내 구글 재인증한 복구 세션으로 10분 이내 요청. 성공 후 다시 로그인 |
| 복구 후 재로그인 | active·full 상태이면 대시보드로 복귀 |

성공 응답은 account_status, deletion_requested_at, deletion_due_at, login_required: true입니다.
복구해도 폐기된 API 키는 복원되지 않습니다.
기존 세션이 복구 전용으로 강등된 경우에는 그 세션만으로 복구할 수 없으므로 Google 재인증을 안내하세요.
유예 기한 이후에는 로그인·복구가 차단되며, 최종 데이터 삭제는 백엔드의 별도 정기 작업이 처리합니다.
프론트는 삭제 작업 명령을 실행하거나 30일 타이머를 유지할 필요가 없습니다.

### 오류 표시와 확인 순서

| 상태 | 처리 |
|---|---|
| 400 로그인 CSRF 오류 | 같은 localhost Origin에서 로그인 화면을 다시 열어 구글 로그인 재시도 |
| 401 | 비로그인·만료 또는 Google 토큰 검증 실패. 로그인 단계에 맞게 재로그인 안내 |
| 403 | 프로젝트 접근은 복구 필요 여부 확인. 로그인은 이메일 허용 여부, 계정 작업은 CSRF·재인증 조건 확인 |
| 404 | 프로젝트·세션 없음 또는 접근 불가 안내 |
| 409 | 복구 기한 경과 안내 |
| 422 | 요청 형식 오류. confirm은 문자열이 아닌 boolean true, 불필요한 필드 제거 |
| 503 | 서버 설정·DB 장애 안내, 사용자 요청 재시도 제공 |

백엔드에서 확인한 실제 구글 로그인 → 탈퇴 → 복구 → 정상 재로그인 흐름을 프론트에서도 재현하세요.
추가로 본인 프로젝트 조회 성공, 타인 프로젝트 404, 로그아웃 후 401, 복구 전용 세션의 프로젝트 접근 403을 확인합니다.
빈 프로젝트 목록만으로 소유권 검증을 완료하지 않습니다.
현재 로그인 완료 리다이렉트와 로그아웃 규격 조정은 백엔드 담당자와 협의가 필요한 연동 작업입니다.

프로젝트와 에이전트 실행 기록을 조회하는 FastAPI 백엔드입니다.
Google Identity Services(GIS) 기반 로그인, 허용 이메일 검사, 사용자 저장,
세션 인증과 프로젝트 소유권 기반 접근 제어를 제공합니다.

## 구현된 기능

- 구글 ID 토큰과 로그인 요청의 CSRF 쿠키·폼 값 검증
- `allowed_emails`에 등록된 이메일만 로그인 허용
- `google_sub` 기준 사용자 생성·갱신 및 로그인 감사 기록 저장
- HttpOnly 쿠키 기반 로그인, 내 정보 조회, 로그아웃
- `projects.owner_user_id` 기준 프로젝트·실행 기록 조회 제한
- 프로젝트별 실행 기록 페이지네이션 및 DB 상태 확인

회원 탈퇴 요청·복구 API, 프로젝트 생성 API와 30일 경과 계정의 최종 삭제 작업 프로세스를 제공합니다. 삭제 작업은 별도로 실행해야 합니다. 프로젝트 수정 API와 로그인 세션의 DB 저장은 아직 구현하지 않았습니다.


## 파일 구조

```text
backend/
├── main.py                   # FastAPI 앱과 라우터 등록
├── db.py                     # 요청별 PostgreSQL 연결 및 오류 처리
├── schemas.py                # 프로젝트·실행 기록 응답 모델
├── auth/
│   ├── google.py             # 구글 ID 토큰 검증
│   ├── service.py            # 허용 목록 확인, 사용자 저장, 메모리 세션 관리
│   └── dependencies.py       # 보호된 API의 로그인 사용자 확인
├── routers/
│   ├── auth.py               # 로그인 화면과 인증 API
│   ├── projects.py           # 소유 프로젝트 목록
│   └── sessions.py           # 프로젝트별 실행 기록 목록·상세
├── repositories/
│   ├── projects.py           # 소유권 조건을 포함한 프로젝트 SQL
│   └── sessions.py           # 소유권 조건을 포함한 실행 기록 SQL
├── templates/login.html      # 로그인·사용자 정보·로그아웃 화면
├── requirements-auth.txt     # 인증 및 테스트용 추가 의존성
├── test_auth.py              # 로그인·로그아웃 및 오류 처리 테스트
├── test_authorization.py     # 소유권 검사와 기존 조회 동작 회귀 테스트
└── AUTH.md                   # 인증 구현 상세 안내
```

인증 폴더의 `schemas.py`, `__init__.py`는 현재 별도 처리 로직이 없는 파일입니다.
DB 저장은 기존 `storage.accounts` 함수를 재사용합니다.

## 로컬 실행

모든 명령은 저장소 루트에서 PowerShell로 실행합니다.
기존 백엔드 실행에 필요한 FastAPI, Uvicorn, psycopg, python-dotenv 등의
의존성이 설치된 가상환경을 사용하고, 인증용 추가 패키지를 설치합니다.

```powershell
.venv/Scripts/python.exe -m pip install -r backend/requirements-auth.txt
```

### 1. DB 연결 및 스키마 준비

연결은 `storage/db.py` 설정을 공유하며 저장소 루트 `.env`도 읽습니다.
실제 프로세스 환경변수가 `.env` 값보다 우선합니다.

- 배포 연결: `GUARDRAIL_DB_URL` 우선 사용
- 로컬 연결: 위 값이 없으면 `POSTGRES_DB`, `POSTGRES_HOST`, `POSTGRES_PORT`,
  `POSTGRES_USER`, `POSTGRES_PASSWORD` 사용
- 예시 설정: [storage/postgres.env.example](../storage/postgres.env.example)

현재 연결 대상 DB에 최신 스키마를 반영한 뒤 로그인할 이메일을 등록합니다.

```powershell
.venv/Scripts/python.exe -m storage init
.venv/Scripts/python.exe -m storage allow-email "user@gmail.com"
.venv/Scripts/python.exe -m storage allowed-emails
```

`init`은 현재 canonical 스키마를 적용하며 기존 사용자·실행 기록을 삭제하는
초기화 명령이 아닙니다. 상세 계약은 [Storage README](../storage/README.md)를 참고하세요.
허용 이메일이 하나도 없으면 모든 신규 로그인 요청이 거절됩니다.

등록을 해제하려면 다음 명령을 사용합니다.

```powershell
.venv/Scripts/python.exe -m storage remove-email "user@gmail.com"
```

허용 목록에서 삭제해도 이미 발급한 세션은 즉시 폐기되지 않습니다.
기존 세션은 로그아웃, 만료 또는 서버 재시작 전까지 유지됩니다.

### 2. 구글 콘솔 설정

OAuth 클라이언트 유형을 **웹 애플리케이션**으로 생성합니다.
일반 API 키가 아닌 `.apps.googleusercontent.com`으로 끝나는 Client ID를 사용합니다.

| 설정 | 로컬 등록 값 |
|---|---|
| 승인된 JavaScript 원본 | `http://localhost:8030` |
| 승인된 리디렉션 URI | `http://localhost:8030/api/auth/google` |

구글 앱이 테스트 모드라면 필요한 계정을 테스트 사용자로 등록합니다.
구글 콘솔의 테스트 사용자와 서비스 DB의 `allowed_emails`는 별도 설정입니다.
이 ID 토큰 로그인 방식에는 Client Secret이 필요하지 않습니다.

### 3. 환경변수 설정 후 서버 실행

```powershell
$env:GOOGLE_CLIENT_ID = "YOUR_CLIENT_ID.apps.googleusercontent.com"
$env:GOOGLE_LOGIN_URI = "http://localhost:8030/api/auth/google"
$env:AUTH_COOKIE_SECURE = "false"

.venv/Scripts/python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8030
```

환경변수를 설정한 **같은 터미널**에서 서버를 실행합니다.
새 터미널에서는 환경변수를 다시 설정해야 합니다.
코드 변경 후에는 서버를 종료하고 다시 실행하거나 개발 중 `--reload` 옵션을 사용하세요.

- 로그인 화면: <http://localhost:8030/login>
- Swagger UI: <http://localhost:8030/docs>
- DB 상태: <http://localhost:8030/healthz>

로그인 HTML을 파일로 직접 열지 마세요. 로그인 시작부터 완료까지
`localhost`를 사용하고 `127.0.0.1` 주소와 섞지 않아야 쿠키가 유지됩니다.

## 인증과 DB 저장 흐름

```text
GET /login → 구글 로그인 버튼 → 구글 계정 인증
    ↓
POST /api/auth/google (폼: credential, g_csrf_token)
    ↓
CSRF 검증 → 구글 ID 토큰 검증 → 인증된 이메일 확인
    ↓
allowed_emails 확인 → users 생성·갱신 + auth_events 성공 기록
    ↓
메모리 세션 생성 → guardrail_session 쿠키 설정 → 303 /login
```

- `users`: DB 사용자 ID, 구글 `sub`, 이메일, 이름, 생성·최근 로그인 시간
- `allowed_emails`: 대소문자를 구분하지 않는 로그인 허용 목록
- `auth_events`: 로그인 성공·허용 목록 거절 등의 감사 기록
- `projects.owner_user_id`: 프로젝트 소유자의 `users.id`
- 기존 `sessions`: 에이전트 실행 기록이며 웹 로그인 세션과 다릅니다.

`upsert_user_from_google()`는 사용자 저장과 성공 이벤트 기록을 하나의 트랜잭션으로 처리합니다.
허용 목록 거절 시 `google_login_denied` 이벤트를 기록하고 사용자·세션을 생성하지 않습니다.
구글 ID 토큰과 로그인 세션 토큰 원문은 DB에 저장하지 않습니다.

## API

| 메서드 | 경로 | 동작 |
|---|---|---|
| GET | `/login` | 로그인 또는 현재 사용자·로그아웃 화면 |
| POST | `/api/auth/google` | GIS 폼 수신, 토큰 검증 및 로그인 |
| GET | `/api/auth/me` | 현재 로그인 사용자 반환 |
| POST | `/api/auth/logout` | 세션·쿠키 삭제 후 `/login`으로 이동 |
| POST | `/api/projects` | 활성 로그인 사용자를 소유자로 프로젝트 생성, 성공 201 |
| GET | `/api/projects` | 로그인 사용자 소유 프로젝트 목록 |
| GET | `/api/projects/{project_id}/sessions` | 소유 프로젝트 실행 기록 목록 |
| GET | `/api/projects/{project_id}/sessions/{session_id}` | 소유 프로젝트 실행 기록 상세 |
| GET | `/healthz` | DB 연결 확인 |

`/api/auth/me`는 `id`, `sub`, `email`, `name`을 반환합니다.
로그아웃은 HTML 폼의 `csrf_token` 값이 현재 세션 쿠키와 일치해야 합니다.
로그아웃은 우리 서비스 세션만 종료하며 구글 계정 자체에서는 로그아웃하지 않습니다.

실행 기록 목록은 `limit`(기본 20, 범위 1~200), `offset`(기본 0, 범위
0~9223372036854775807)을 받습니다. 응답은 `items`, `total`, `limit`, `offset`입니다.
최신 `started_at` 순으로 정렬하고 동률이면 실행 ID 순으로 정렬합니다.

### 접근 권한

프로젝트 화면에 처음 진입할 때뿐 아니라 **각 조회 요청마다** 로그인과 소유권을 검사합니다.
실행 기록은 요청한 프로젝트에 속해야 하며 해당 프로젝트의 소유자도 일치해야 합니다.

- 미로그인·만료·잘못된 세션: `401`
- 프로젝트 목록: 본인 소유 항목만 반환. 없으면 빈 배열
- 다른 사용자 소유·소유자 없는·존재하지 않는 프로젝트의 실행 기록 조회: `404`
- 소유 프로젝트에 없는 실행 기록: `404`

기존 프로젝트의 소유자를 자동으로 지정하지 않습니다.
`owner_user_id IS NULL`인 데모 프로젝트도 현재 보호된 API에서는 조회할 수 없습니다.
`/healthz`, `/docs`, `/openapi.json`은 로그인 없이 접근할 수 있습니다.

### 주요 오류

| 상황 | 상태 코드 |
|---|---|
| 로그인 CSRF 값 불일치 | 400 |
| 잘못된 구글 토큰·인증된 이메일 누락 | 401 |
| 허용되지 않은 이메일 | 403 |
| 로그아웃 폼 토큰 불일치 | 403 |
| 소유권 없는 프로젝트·없는 실행 기록 | 404 |
| 필수 폼 값 누락·잘못된 경로·페이지네이션 입력 | 422 |
| 로그인 설정 누락·인증 DB 처리 실패 | 503 |
| 조회 DB 연결 불가 | 503 |

인증 실패와 입력 오류가 동시에 있으면 처리 순서에 따라 반환 코드가 달라질 수 있습니다.
`relation "allowed_emails" does not exist`는 최신 스키마 미반영 또는 연결 대상 DB 불일치를 확인하세요.

## 테스트

```powershell
.venv/Scripts/python.exe -m unittest backend.test_auth backend.test_authorization
```

인증·권한 테스트로 로그인·로그아웃, CSRF, 세션 만료, 이메일 허용 목록,
DB 오류, 소유자별 조회, 비로그인 차단 및 기존 페이지네이션·입력 검증을 확인합니다.
인증 DB 호출은 mock, 조회 SQL은 메모리 SQLite를 사용하므로 외부 DB 없이 실행합니다.
`test_authorization.py`는 기존 `tests/test_backend_sessions.py`의 조회 테스트를
인증된 사용자와 소유권 칼럼을 갖춘 fixture로 재사용합니다.
별도 임시 PostgreSQL에서 가입·탈퇴·복구·최종 삭제 통합 테스트 6개가 통과했습니다.
인증·권한·Storage·삭제 작업 회귀 테스트 101개도 통과했습니다.
이는 실제 구글 계정을 사용하는 브라우저 수동 검증과 구분됩니다.

## 운영 시 현재 한계

- 로그인 세션은 프로세스 메모리에 1시간 저장됩니다. 서버 재시작·개발 reload 시 해제됩니다.
- 단일 worker 기준입니다. 다중 worker·서버 운영에는 공유 세션 저장소가 필요합니다.
- 세션 생성 당시 사용자 정보를 보관하며, 허용 목록 변경을 매 요청마다 재검사하지 않습니다.
- 탈퇴·복구 성공 시 해당 사용자의 모든 메모리 세션을 폐기합니다. 다중 프로세스 세션 공유는 아직 지원하지 않습니다.
- 운영에서는 HTTPS와 `AUTH_COOKIE_SECURE=true`(기본값)를 사용하고 실제 도메인을 등록합니다.
- 프론트와 같은 Origin의 `/login`, `/api/`를 백엔드로 전달하는 배포 구성이 단순합니다.
  서로 다른 Origin 간 CORS 설정은 현재 앱에 추가되어 있지 않습니다.


## 계정 탈퇴 상태를 반영한 로그인

이 변경은 `backend-foundation`에서 작성했으며 `db-unify` 브랜치는 통합하지 않았습니다.
현재 로컬 DB에는 `python -m storage init`을 적용했습니다.
`users.account_status`, `deletion_requested_at`, `deletion_due_at` 칼럼과
제약조건이 현재 스키마에 포함되며, 기존 사용자는 기본적으로 active가 됩니다.
다른 개발자 PC나 배포 DB에서도 최초 구성 시 같은 스키마 적용이 필요합니다.
해당 환경에서 미반영 상태로 실행하면 인증 DB 오류(503)가 반환됩니다.

- 정상 계정: 일반 세션 발급, 프로젝트 조회 허용
- 탈퇴 유예 계정: 복구용 제한 세션 발급, 상태 확인·로그아웃 허용, 프로젝트 조회 403
- 삭제 기한 경과 계정: 로그인 403, 기존 세션 폐기
- 삭제된 계정: 기존 세션 폐기, 이후 인증 요청 401
- DB 조회 실패: 접근을 허용하지 않고 503 반환

로그인 화면·내 정보·프로젝트 요청마다 현재 계정 상태를 DB에서 확인합니다.
유예기한은 PostgreSQL 시각으로 판단합니다. 기존 세션도 탈퇴 상태가 확인되면
제한 세션으로 바뀌며, DB에서 복구하더라도 기존 토큰이 일반 세션으로 자동 승격되지는 않습니다.
다시 구글 로그인해야 합니다. `/api/auth/me` 응답에 `account_status`,
`deletion_requested_at`, `deletion_due_at`, `can_restore`, `session_scope`가 추가됩니다.

탈퇴·복구 API는 DB 작업 성공 후 `revoke_user_sessions(user_id)`를 호출합니다.
복구는 탈퇴 상태에서 구글 재인증으로 발급받은 세션으로 10분 이내에 요청해야 합니다.
세션은 여전히 단일 프로세스 메모리에 저장됩니다.


## 회원 탈퇴 요청과 계정 복구

로그인 화면에 회원 탈퇴·계정 복구 버튼이 추가되었습니다.

| 메서드 | 경로 | 조건과 결과 |
|---|---|---|
| POST | `/api/auth/withdraw` | 활성 일반 세션 필요. 30일 유예 시작, API 키·웹 세션 폐기 |
| POST | `/api/auth/restore` | 최근 10분 내 구글 재인증한 복구 세션 필요. 유예기간 내 active 복구 |

두 API는 JSON `{ "confirm": true, "csrf_token": "..." }`을 받습니다.
`csrf_token`은 로그인 후 `/api/auth/me`에서 읽습니다. 로그인 토큰과 별개인 난수이며,
다른 사용자의 ID나 이메일은 요청에 넣지 않습니다. 추가 필드는 422로 거절합니다.
성공 응답은 `account_status`, `deletion_requested_at`, `deletion_due_at`, `login_required`입니다.
성공 시 쿠키도 삭제됩니다. 복구 후에는 다시 구글 로그인해야 합니다.

- 탈퇴 전 일반 세션이 상태 변경으로 제한 세션이 된 경우, 그것만으로 복구할 수 없습니다.
- 복구해도 폐기한 API 키는 복원되지 않습니다. 허용 이메일은 유예기간 동안 보존합니다.
- 재요청은 저장 계층에서 삭제 예정 시간을 연장하지 않습니다. HTTP 재요청은 이미 세션이 폐기됐다면 401입니다.
- DB 오류는 503이며, 저장 트랜잭션 실패 시 세션을 임의로 지우지 않습니다.
- 최종 삭제는 아래 별도 작업 프로세스가 수행합니다. API 서버 실행만으로 삭제 작업이 시작되지는 않습니다.

Storage API 키 회귀 테스트:

```powershell
.venv/Scripts/python.exe -m unittest discover -s tests -p test_storage_accounts.py
```

실제 PostgreSQL 트랜잭션 테스트(개발 DB의 CREATE SCHEMA 권한 필요):

```powershell
$env:RUN_ACCOUNT_DB_TESTS = "1"
.venv/Scripts/python.exe -m unittest backend.test_account_lifecycle_db
Remove-Item Env:RUN_ACCOUNT_DB_TESTS
```

이 테스트는 별도 임시 스키마를 트랜잭션 안에 만들고 전체 롤백합니다.
실제 사용자 계정을 탈퇴시키지 않습니다. 키 폐기, 재요청, 복구 기한, 감사 기록 실패 시 롤백, 최종 삭제, 첫 가입의 중복 방지를 확인합니다.

## 30일 경과 계정의 최종 삭제

`db-unify`의 계정 처리 함수와 스키마를 반영했습니다. 첫 구글 로그인에서 허용 이메일을 확인한 뒤 사용자를 등록하며, 같은 `google_sub`의 재로그인은 기존 사용자를 갱신합니다. 탈퇴 유예 계정은 자동 복구되지 않습니다.

삭제 대상 확인만 하는 명령입니다. 데이터는 변경하지 않습니다.

```powershell
.venv/Scripts/python.exe -m backend.purge_accounts
```

운영자가 대상 DB와 삭제 대상을 확인한 뒤 실행합니다. 다음 명령은 만료된 계정을 최대 100개씩 최종 삭제합니다.

```powershell
.venv/Scripts/python.exe -m backend.purge_accounts --execute --limit 100
```

별도 터미널에서 다음 작업 프로세스를 실행하면 시작 즉시 한 번, 이후 1시간마다 처리합니다. `Ctrl+C`로 중지합니다. 배포에서는 이 명령을 서비스 관리자에 등록해 재부팅 후에도 실행되게 해야 합니다.

```powershell
.venv/Scripts/python.exe -m backend.purge_accounts --execute --interval 3600
```

API 서버와 삭제 작업은 같은 DB 설정을 사용해야 합니다. 계정별 트랜잭션으로 처리하며 일부 실패는 다음 주기에 다시 시도합니다. 단발 실행에서 실패가 있으면 종료 코드는 1입니다. 한 번에 100개까지만 처리하므로 대상이 많으면 `--limit` 또는 실행 간격을 조정합니다.

최종 삭제 대상은 사용자, 소유 프로젝트와 하위 실행 데이터, API 키, 식별 가능한 인증 기록, 허용 이메일입니다. 다른 사용자와 소유자 없는 공용 데모는 유지합니다. 최종 삭제 후 재가입하려면 관리자가 이메일을 다시 허용해야 합니다. 복구 기한은 DB 시간으로 판단하며, 복구해도 폐기한 API 키는 살아나지 않습니다.

가입·탈퇴·복구·삭제 작업 회귀 테스트:

```powershell
.venv/Scripts/python.exe -m unittest backend.test_auth backend.test_authorization backend.test_purge_accounts tests.test_storage_accounts tests.test_storage_accounts_hardening tests.test_storage_live tests.test_storage_live_hardening
```
