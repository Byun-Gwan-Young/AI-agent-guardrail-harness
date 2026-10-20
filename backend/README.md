# Agent Guardrail Backend

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

회원 탈퇴, 프로젝트 생성·수정 API, 로그인 세션의 DB 저장은 아직 구현하지 않았습니다.

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

현재 24개 테스트로 로그인·로그아웃, CSRF, 세션 만료, 이메일 허용 목록,
DB 오류, 소유자별 조회, 비로그인 차단 및 기존 페이지네이션·입력 검증을 확인합니다.
인증 DB 호출은 mock, 조회 SQL은 메모리 SQLite를 사용하므로 외부 DB 없이 실행합니다.
`test_authorization.py`는 기존 `tests/test_backend_sessions.py`의 조회 테스트를
인증된 사용자와 소유권 칼럼을 갖춘 fixture로 재사용합니다.
실제 구글 계정 및 PostgreSQL 연결은 별도 통합 확인이 필요합니다.

## 운영 시 현재 한계

- 로그인 세션은 프로세스 메모리에 1시간 저장됩니다. 서버 재시작·개발 reload 시 해제됩니다.
- 단일 worker 기준입니다. 다중 worker·서버 운영에는 공유 세션 저장소가 필요합니다.
- 세션 생성 당시 사용자 정보를 보관하며, 허용 목록 변경을 매 요청마다 재검사하지 않습니다.
- 회원 탈퇴, 모든 기기 로그아웃, 사용자 비활성화는 구현하지 않았습니다.
- 운영에서는 HTTPS와 `AUTH_COOKIE_SECURE=true`(기본값)를 사용하고 실제 도메인을 등록합니다.
- 프론트와 같은 Origin의 `/login`, `/api/`를 백엔드로 전달하는 배포 구성이 단순합니다.
  서로 다른 Origin 간 CORS 설정은 현재 앱에 추가되어 있지 않습니다.
