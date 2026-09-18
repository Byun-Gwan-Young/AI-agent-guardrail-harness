# P0-2 3단계 오프라인 비교

원본 → P0-1 → P0-2. 회복된 대화만 복원하며 폐기된 산출물은 null/unmeasured다.
실제 실행 재현/세션 유효성 판정이 아니다. G0-5 우선순위는 변경하지 않았다.

| step | progress 원본 → P0-1 → P0-2 | criteria 원본 → P0-1 → P0-2 | 대화 복원 | 원본 turn | 산출물 |
|---|---|---|---|---|---|
| 1 | baseline → baseline → baseline | continue → continue → continue | 기존 유지 | 3 | stored_snapshot |
| 2 | progress → baseline → baseline | continue → continue → continue | 기존 유지 | 6 | stored_snapshot |
| 3 | progress → baseline → baseline | continue → continue → continue | 기존 유지 | 9 | stored_snapshot |
| 4 | progress → progress → progress | continue → continue → continue | 기존 유지 | 12 | stored_snapshot |
| 5 | unmeasured → unmeasured → unmeasured | unmeasured → unmeasured → unmeasured | 복원 | 15 | unmeasured |
| 6 | unmeasured → progress → progress | unmeasured → continue → continue | 기존 유지 | 18 | stored_snapshot |
| 7 | progress → stagnant → stagnant | continue → continue → continue | 기존 유지 | 21 | stored_snapshot |
| 8 | unmeasured → unmeasured → unmeasured | unmeasured → unmeasured → unmeasured | 기존 유지 | 24 | stored_snapshot |
| 9 | progress → unmeasured → unmeasured | continue → unmeasured → unmeasured | 기존 유지 | 26 | stored_snapshot |
| 10 | unmeasured → unmeasured → unmeasured | unmeasured → unmeasured → unmeasured | 복원 | 29 | unmeasured |
| 11 | unmeasured → unmeasured → unmeasured | unmeasured → unmeasured → unmeasured | 기존 유지 | 32 | stored_snapshot |
| 12 | progress → unmeasured → unmeasured | continue → unmeasured → unmeasured | 기존 유지 | 34 | stored_snapshot |
| 13 | unmeasured → unmeasured → unmeasured | unmeasured → unmeasured → unmeasured | 복원 | 37 | unmeasured |
| 14 | unmeasured → unmeasured → unmeasured | unmeasured → unmeasured → unmeasured | 기존 유지 | 40 | stored_snapshot |
| 15 | progress → unmeasured → unmeasured | continue → unmeasured → unmeasured | 기존 유지 | 42 | stored_snapshot |
| 16 | unmeasured → unmeasured → unmeasured | unmeasured → unmeasured → unmeasured | 복원 | 45 | unmeasured |
| 17 | unmeasured → unmeasured → unmeasured | unmeasured → unmeasured → unmeasured | 기존 유지 | 48 | stored_snapshot |
| 18 | unmeasured → unmeasured → unmeasured | unmeasured → unmeasured → unmeasured | 미복원 | 49 | unmeasured |

## 자동 집계

```json
{
  "steps": 18,
  "conversation_restored_steps": [
    5,
    10,
    13,
    16
  ],
  "discarded_not_restored_steps": [
    18
  ],
  "discarded_artifact_null_steps": [
    5,
    10,
    13,
    16,
    18
  ],
  "progress_state_changed_steps": [],
  "actual_stop_step": {
    "value": null,
    "status": "unmeasured"
  },
  "measured_detection_latency": {
    "value": null,
    "status": "unmeasured"
  }
}
```

replay.json은 단계별 전체 판정·이벤트·지표 누락 사유·관측·최종 출력 원문 연결을 보관한다.
P0-4 info_items null과 직전 동일 역할의 누락은 progress.metrics의 unmeasured 사유로 구분한다.
공유 산출물 재관측은 p0_1_classification.shared_artifact_events에 남긴다.
