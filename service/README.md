# service — 통합 Storage 조회 API

`service/` 는 이제 PostgreSQL 스키마를 소유하지 않습니다. PostgreSQL 의 canonical schema와 demo 적재는
`storage/schema.sql`, `storage/import_demo.py` 가 담당하고, `service/api.py` 는 그 통합 DB를 **읽기 전용**으로 조회합니다.

- PostgreSQL 쓰기: `storage/` 만 담당
- 조회 API: `service/api.py`
- 기존 `service/schema.sql`: 옛 API 계약을 검증하는 SQLite 오프라인 테스트 fixture 로만 유지
- 기존 `service/load_demo.py rows` / `check --offline`: 커밋된 데모 파일의 독립 검증용으로 유지
- `service.load_demo schema` / `load`: DB 통합 후 퇴역. 실행하면 쓰기 전에 명확하게 거절됨
- narrative · reasoning 본문 · API key 원문은 DB/응답에 내보내지 않음

## 현재 흐름

```text
runs/demo + reports + scenario metadata
                 │
                 ▼
       storage/import_demo.py
                 │
                 ▼
       unified PostgreSQL DB
                 │
                 ▼
       service/queries.py
                 │
                 ▼
       service/api.py (GET only)
```

API 는 데모 화면 호환을 위해 세션/지표는 PostgreSQL 에서 읽고 다시 계산하며, 한국어 시나리오 이름·짝·동결 상태와
aggregate 표처럼 **커밋된 정적 발표 메타데이터**는 저장소 파일에서 읽습니다. 따라서 API 배포에는 이 저장소의
`reports/`, `scenarios/`, `docs/criteria/` 정적 파일도 함께 포함되어야 합니다.

## API

- `GET /api/summary`
- `GET /api/scenarios`
- `GET /api/sessions`
- `GET /api/sessions/{id}`
- `GET /api/sessions/{id}/steps`
- `/docs`, `/redoc`

이 API 는 현재 **demo-record 전용 조회 API**입니다. `live` 세션의 실시간 화면/API 계약은 별도 통합 단계에서 연결합니다.

## 검증

기존 응답 계약(SQLite legacy fixture):

```bash
python -X utf8 -m unittest tests.test_service_demo_db -v
```

통합 Storage 응답 계약(실제 115개 데모 원본을 unified shape 로 재구성해 legacy API 와 비교):

```bash
python -X utf8 -m unittest tests.test_service_unified_api -v
```

실제 PostgreSQL 검증은 `GUARDRAIL_DB_URL` 이 있을 때만 별도로 실행합니다.

```bash
python -X utf8 -m unittest service.test_live_db -v
```

DB 없이 파일 자체를 검증하는 기존 명령도 계속 사용할 수 있습니다.

```bash
python -B -m service.load_demo rows
python -B -m service.load_demo check --offline
```

PostgreSQL 초기화/데모 동기화는 반드시 Storage 명령을 사용합니다.

```bash
python -m storage init
python -X utf8 -m storage demo-all
```
