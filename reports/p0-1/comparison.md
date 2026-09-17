# P0-1 역할별 비교 replay

원본 SHA-256: `da8636936f5978e74c330937216a427412db385bd86bfa71dafeeb00446901fe`
v1 저장 결과 바이트 일치: `True`

재현 범위: 저장된 관측의 비교 대상만 변경. 역할 매핑은 요청 시스템 메시지의 명시적 접두문으로 복원했다.
원본 판정·null·종결 문맥은 보존한다. 경보 없음은 실패 기준이 아니다.

| step | 역할 | 기존→새 비교 step | progress 기존→새 | criteria 기존→새 | 원인 |
|---|---|---|---|---|---|
| 1 | planner | None → None | baseline → baseline | continue → continue | 역할 첫 관측 |
| 2 | developer | 1 → None | progress → baseline | continue → continue | 역할 간 ID만으로 생긴 progress 제거; 역할 첫 관측; P0-4 현재 info_items null |
| 3 | reviewer | 2 → None | progress → baseline | continue → continue | 역할 간 ID만으로 생긴 progress 제거; 역할 첫 관측; P0-4 현재 info_items null |
| 4 | planner | 3 → 1 | progress → progress | continue → continue | 기존 ID 변화 + 독립 변화 혼합; 산출물 변화 |
| 5 | developer | 4 → 2 | unmeasured → unmeasured | unmeasured → unmeasured | P0-2 현재 관측 폐기; P0-4 직전 동일 역할 info_items null |
| 6 | reviewer | 5 → 3 | unmeasured → progress | unmeasured → continue | 공유 산출물 변경 재관측; P0-4 현재 info_items null; P0-4 직전 동일 역할 info_items null; 기존 progress 우선순위 유지 |
| 7 | planner | 6 → 4 | progress → stagnant | continue → continue | 역할 간 ID만으로 생긴 progress 제거; 동일 역할 관측 변화 없음 |
| 8 | developer | 7 → 5 | unmeasured → unmeasured | unmeasured → unmeasured | P0-2 직전 동일 역할 공백; P0-4 현재 info_items null |
| 9 | reviewer | 8 → 6 | progress → unmeasured | continue → unmeasured | 역할 간 ID만으로 생긴 progress 제거; P0-4 현재 info_items null; P0-4 직전 동일 역할 info_items null |
| 10 | planner | 9 → 7 | unmeasured → unmeasured | unmeasured → unmeasured | P0-2 현재 관측 폐기 |
| 11 | developer | 10 → 8 | unmeasured → unmeasured | unmeasured → unmeasured | P0-4 현재 info_items null; P0-4 직전 동일 역할 info_items null |
| 12 | reviewer | 11 → 9 | progress → unmeasured | continue → unmeasured | 역할 간 ID만으로 생긴 progress 제거; P0-4 현재 info_items null; P0-4 직전 동일 역할 info_items null |
| 13 | planner | 12 → 10 | unmeasured → unmeasured | unmeasured → unmeasured | P0-2 현재 관측 폐기 |
| 14 | developer | 13 → 11 | unmeasured → unmeasured | unmeasured → unmeasured | P0-4 현재 info_items null; P0-4 직전 동일 역할 info_items null |
| 15 | reviewer | 14 → 12 | progress → unmeasured | continue → unmeasured | 역할 간 ID만으로 생긴 progress 제거; P0-4 현재 info_items null; P0-4 직전 동일 역할 info_items null |
| 16 | planner | 15 → 13 | unmeasured → unmeasured | unmeasured → unmeasured | P0-2 현재 관측 폐기 |
| 17 | developer | 16 → 14 | unmeasured → unmeasured | unmeasured → unmeasured | P0-4 현재 info_items null; P0-4 직전 동일 역할 info_items null |
| 18 | reviewer | 17 → 15 | unmeasured → unmeasured | unmeasured → unmeasured | P0-2 현재 관측 폐기; P0-4 직전 동일 역할 info_items null |

## 자동 집계

```json
{
  "steps": 18,
  "cross_role_issue_progress_candidates": 6,
  "removed": 6,
  "retained": 0,
  "unresolved_roles": 0,
  "p0_1_success": true,
  "shared_artifact_steps": [
    6
  ],
  "first_deadlock_step": null,
  "first_termination_failure_step": null,
  "measured_detection_latency": {
    "value": null,
    "status": "unmeasured"
  },
  "actual_stop_step": {
    "value": null,
    "status": "unmeasured"
  }
}
```

판독 규칙: docs/P0-1-replay-protocol.md. 상세 이벤트·누락 사유·역할 매핑 근거는 replay.json에 있다.
공유 산출물 재관측은 해당 역할이 파일을 수정했다는 뜻이 아니다. 실측 탐지 성능/실제 STOP은 미측정이다.
