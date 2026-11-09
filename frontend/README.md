# Agent Guardrail React frontend

최신 `origin/main`의 `56900c5`를 기준으로 `feat/react-frontend`에서 만든 React/Vite 화면입니다.
기존 Python 데모, `backend/`, `service/`, `storage/`, AWS 배포 스크립트를 수정하거나 교체하지 않습니다.
이 폴더는 아직 AWS 배포 경로에 연결하지 않았습니다.

## 화면만 바로 확인

Node.js 22.12 이상에서 이 `frontend` 폴더를 열고 실행합니다.

```powershell
npm.cmd install
npm.cmd run dev
```

브라우저에서 **http://localhost:5173/?preview=1** 을 엽니다.
실제 저장된 실험 67개(관측 54, 차단 13)를 사용하며 로그인·변경 요청·실시간 호출을 하지 않습니다.
이는 현재 DB 상태나 실제 로그인 성공을 보여주는 모드가 아닙니다.

## 로그인과 로컬 DB 연결

이전에 준비한 로컬 PostgreSQL `guardrail_local_pc`와 허용 이메일을 그대로 사용합니다.
PostgreSQL을 켠 뒤 다음 명령을 **이 폴더에서** 실행합니다.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start-local.ps1
```

Google 웹 클라이언트 ID, 로컬 DB 포트·사용자·비밀번호를 입력합니다.
비밀번호는 프로세스 환경에만 전달하고 파일에 저장하지 않습니다.
DB 확인은 읽기 전용입니다. 스키마 생성·초기화·데이터 재적재를 하지 않습니다.
기존의 8030 데모 서버는 그대로 둘 수 있습니다. 새 로컬 API는 8040, React는 5173입니다.
이 런처의 PostgreSQL 연결은 127.0.0.1의 기존 `guardrail_local_pc`로 제한합니다.

Google 웹 클라이언트에 **기존 AWS 주소를 유지하면서** 다음 값을 추가해야 합니다.

| Google 설정     | 추가 값                                 |
| --------------- | --------------------------------------- |
| JavaScript 원본 | `http://localhost`                      |
| JavaScript 원본 | `http://localhost:5173`                 |
| 리디렉션 URI    | `http://localhost:5173/api/auth/google` |

**http://localhost:5173/login** 에 접속합니다. `127.0.0.1` 브라우저 주소와 섞지 마세요.
이전에 여러 로그인 시도로 CSRF 오류가 나면 localhost 사이트 데이터만 지우거나 InPrivate 새 창에서 재시도합니다.
CSRF 검사와 Google ID 토큰 검증은 기존 백엔드를 그대로 사용합니다.
Ctrl+C로 종료하면 런처가 시작한 로컬 API도 종료합니다.
실행 기록은 git에서 제외되는 `.local-logs/`에 남으며 HTTP access log는 끕니다.

프로젝트의 `.venv`가 없으면 이 PC의 기존 Python 가상환경을 재사용합니다.
다른 PC에서는 저장소 루트에서 가상환경과 의존성을 먼저 준비하거나 `-PythonPath`를 지정하세요.

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r service\requirements-server.txt
# frontend에서
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start-local.ps1 -PythonPath ..\.venv\Scripts\python.exe
```

`dev_server.py`는 기존 FastAPI 라우터와 조회·실시간 모듈을 한 프로세스에 묶는 로컬 전용 어댑터입니다.
실제 인증 세션은 프로세스 메모리에 있으므로 다른 API 프로세스나 기존 AWS 로그인 세션과 공유되지 않습니다.
브라우저는 상대 `/api`만 호출하고 Vite가 8040으로 전달합니다. CORS 설정이나 백엔드 코드를 바꾸지 않습니다.
실시간 모니터는 새 clone에 있는 `runs/demo`, `logs/demo` 기록의 변경을 읽습니다. 실행기를 시작하는 기능은 없습니다.

### 수동 실행

`.env.example`을 참고하여 git에서 제외되는 `frontend/.env.local`에 공개 클라이언트 ID와 로컬 DB 설정을 입력할 수 있습니다.
`VITE_` 접두사 변수는 브라우저에 공개됩니다. **비밀번호·API 키·Client Secret을 VITE\_ 변수에 넣지 마세요.**
DB 설정은 `GUARDRAIL_DB_URL` 또는 `POSTGRES_*`를 사용하며 기존 backend/storage 규격을 따릅니다.

```powershell
# 저장소 루트, DB 환경변수와 Google 설정을 지정한 터미널
.\.venv\Scripts\python.exe -B frontend\dev_server.py
# 다른 터미널, frontend 폴더
npm.cmd run dev
```

## 화면과 기존 API

| 화면                    | 데이터 / 동작                                                                                           |
| ----------------------- | ------------------------------------------------------------------------------------------------------- |
| 대시보드                | `/api/summary`, `/api/sessions?validity=valid`; 필터·페이지 이동·판정 알림                              |
| 세션 재생               | `/api/sessions/{id}`, `/api/sessions/{id}/steps`; 타임라인·자동 재생·첫 STOP·테스트·쟁점·파일 변화·토큰 |
| 비교                    | 정상판/교착판 관측 세션의 사용량·결과 비교; 동결 기록의 변경 조건                                       |
| 통계                    | 현재 조회 세션의 유형·결과 집계; 동결된 차단 비교 결과                                                  |
| 시스템 구조·사용 가이드 | 기존 `demo_ui.collect`의 구성·스키마 검증된 예시·판정 해석                                              |
| 로그인·내 계정          | `/api/auth/me`, Google 로그인 POST, 탈퇴·복구·로그아웃                                                  |
| 프로젝트                | GET/POST `/api/projects`, 프로젝트별 세션 목록·상세; 생성 시 `/me`의 CSRF 사용                          |
| 실시간 모니터           | `/api/live/sessions`, `/api/live/sessions/{id}`; 2.5초 조회, 오류 표시·중단·화면 이탈 시 정리           |
| API 키 관리             | 현재 main에 키 관리 HTTP API가 없음을 표시; 발급·폐기는 아직 불가                                       |

인증·계정 범위에 따라 401/403/503을 구분합니다. 복구 전용 계정은 계정 화면만 열 수 있습니다.
백엔드의 로그아웃은 `/me`의 CSRF가 아닌 기존 HTML 폼의 토큰을 요구하므로 `/legacy-login` 프록시로 기존 폼 값을 읽어 그대로 제출합니다.
토큰은 localStorage·파일·콘솔에 저장하지 않습니다. 탈퇴·복구는 확인 후 중복 제출을 막습니다.
서버 오류는 기록 미리보기로 자동 전환하지 않습니다. 사용자가 미리보기를 별도로 선택해야 합니다.
동결된 참고 데이터는 인증된 `/api/frontend/reference`에서 기존 수집기로 읽습니다.
공개 미리보기의 `public/records.json`은 원래 공개 저장소의 정제된 데모 기록입니다.

## UI 수정 위치

- `src/App.jsx`: 앱 구성, 메뉴·인증·페이지 전환·데이터 로딩
- `src/pages.jsx`: 대시보드·재생·비교·통계·시스템·가이드·프로젝트·계정·실시간
- `src/Login.jsx`: React 로그인 화면과 Google 버튼
- `src/components.jsx`: 표·타임라인·상태·오류 표시
- `src/styles.css`: 기존 데모의 색조를 참고한 반응형 스타일
- `src/api.js`, `src/model.js`: 기존 API 계약과 화면 데이터 변환
- `vite.config.js`: 로컬 API 프록시, 고정 포트 (리디렉션 주소가 바뀌지 않도록 strictPort)

`export_reference.py`로 공개 미리보기 기록을 다시 생성할 수 있습니다.
Windows 날짜 형식 차이는 수집기를 메모리에 로드할 때만 처리하며 원본 `demo_ui.py`는 수정하지 않습니다.

## 검증

```powershell
npm.cmd test
npm.cmd run build
# 기본은 설치된 Edge, 또는 Chromium을 준비해 선택
npx.cmd playwright install chromium
$env:BROWSER_CHANNEL = 'chromium'
npm.cmd run test:e2e
```

기존 Python 환경에서는 로컬 어댑터의 인증 보호와 API 등록도 DB에 쓰지 않고 검사할 수 있습니다.

```powershell
# 저장소 루트
.\.venv\Scripts\python.exe -B frontend\tests\test_local_adapter.py
```

브라우저 테스트는 공개 기록과 **가짜 HTTP 응답**으로 UI, 필터·재생, 인증 오류, 프로젝트 CSRF/목록/상세, 폴링 중단을 검증합니다.
실제 Google 계정 로그인과 사용자 PostgreSQL 연결 검증은 별도로 필요합니다.
빌드 결과는 `dist/`입니다. AWS 게시·기존 데모 전환은 이 작업에서 실행하지 않습니다.
