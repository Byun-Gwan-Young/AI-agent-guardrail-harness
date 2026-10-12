# React 실험 대시보드

React 컴포넌트와 상태(useState)로 구현했습니다. Vite는 개발 서버와 배포 파일 생성을 담당합니다. 기존 HTML 버전은 별도 폴더에 보존했습니다.

## 이 컴퓨터에서 시작하기
1. 이 폴더의 start.cmd를 더블클릭합니다.
2. 창을 켜 둔 상태에서 http://127.0.0.1:5173 을 엽니다.
3. ‘지난 실험 예시 보기’를 누르거나 같은 실행 폴더의 steps.json과 summary.json을 선택합니다.
4. 작업을 끝내면 서버 창에서 Ctrl+C를 누릅니다.

index.html을 직접 더블클릭하지 않습니다. start.cmd는 빌드된 dist의 미리보기 서버입니다. 소스를 수정하면 pnpm build로 다시 빌드하세요. 개발 중 자동 갱신은 pnpm dev를 사용합니다. 학교 API 키는 필요하지 않습니다.

## 일반적인 개발 환경
Node.js 22.12 이상(또는 Vite 7 지원 버전)과 pnpm을 준비한 다음 이 폴더에서:

```text
pnpm install
pnpm dev
pnpm build
```

pnpm-lock.yaml은 설치 버전을 고정합니다. 팀에 전달할 때 node_modules와 dist는 제외하고 소스·잠금 파일을 전달합니다. public/demo.json에는 실제 실험 기록이 포함돼 있습니다.

## 처음 읽을 코드
- src/main.jsx: React를 화면에 연결하는 시작점
- src/App.jsx: 파일 불러오기, 요약(Summary), 단계 상세(StepDetail) 컴포넌트
- src/model.js: 목록·파일 비교, 데이터 확인, 한글 이름
- src/styles.css: 화면 색상과 배치
- public/demo.json: 지난 실험 예시 및 기존 한국어 번역

새 파일은 자동 번역하지 않습니다. 예시 데이터에만 한국어 번역이 있습니다. 파일은 브라우저에서 읽으며 업로드하지 않습니다. 실시간, 백엔드 API, 로그인, 정책 수정은 아직 연결하지 않았습니다. 같은 단계 수를 가진 서로 다른 실행의 steps와 summary는 완전히 구별할 수 없으므로 반드시 같은 실행 폴더에서 선택하세요.
