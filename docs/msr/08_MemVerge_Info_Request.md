# MemVerge 문의 항목 리스트 [v3]

[← Executive Report](./00_Executive_Report_Outline.md) · [← 재현 평가 상세 설계](./06_Reproduction_Evaluation_Design.md)

**작성일**: 2026-04-22
**용도**: 재현 평가를 위한 MemVerge 질문 정리. §4 에 메일 초안 포함.

> **v3 변경점**: 톤을 "공식 요청" 에서 "가벼운 질문" 으로 변경. 우리가 이미 파악한 것은 확인만 요청, 모르는 것만 공식 요청.

---

## §1 배경

MemMachine 논문 (arXiv:2604.04853v1) 재현 평가 준비 중. 공개 리포 (commit `15380b7`) 조사 결과, 재현에 필요한 일부 정보가 코드에서 확인되지 않거나 휴면 상태여서 MemVerge 에 몇 가지만 여쭤보려 합니다.

---

## §2 질문 항목 4건

### Q1. Edwin prompt 공유 가능 여부

**상황**: 논문 §8.4.5 의 Edwin1, Edwin3 search prompt 를 리포에서 못 찾았습니다.

**질문**: 재현 평가용으로 Edwin1, Edwin3 prompt 전문을 공유해주실 수 있을까요? (Edwin2 는 본 재현에 불필요)

---

### Q2. user_q 구현 방식 확인

**상황**: 논문 §8.4.2 의 `"user:"` prefix 가 `evaluation/episodic_memory/longmemeval_search.py:161` 에서는 하드코딩으로 확인되는데, retrieval_agent 경로 (`longmemeval_test.py`) 에는 해당 로직이 안 보입니다.

**우리 추정 재현 방법**:
```python
# longmemeval_test.py:214 직전에 한 줄 추가
question = f"User: {question}"
```

**질문**: 논문 C5/C6 측정 시 이 방법으로 하셨나요? 아니면 다른 경로·방법이 있나요?

---

### Q3. json_str 활성화 방법 확인

**상황**: `evaluation/utils/memmachine_helper_base.py:140` 의 `do_json_str` 플래그가 리포 내에서 True 로 세팅되는 곳을 못 찾았습니다 (YAML/CLI/하드코딩 모두 0 hit). `restapiv2_locomo_search.py:91,98` 의 `build_ctx()` 호출에도 `do_json_str` 미지정.

**질문**: 논문 Table 12 의 JSON-str=on 구성 (C5~C15) 은 어떻게 활성화하셨나요? 특히 LongMemEvalS 평가 (retrieval_agent 경로) 에서의 활성화 방법이 궁금합니다.

---

### Q4. exclude_abstention 적용값 (가벼운 확인)

**상황**: `longmemeval_evaluate.py` 의 `evaluate_responses()` 기본값은 `exclude_abstention=True` 인데, 같은 파일 `main()` 은 `False` 로 하드코딩되어 있습니다.

**질문**: 논문 수치 산출 시 어느 값을 쓰셨나요? (우리는 True 로 진행 예정이나 확인 차 여쭤봅니다)

---

## §3 물어보지 않는 항목 (참고)

우리가 코드에서 직접 확인했거나 사내 결정으로 처리한 항목:

| 항목 | 처리 |
|---|---|
| chunk flag 제어 방법 | 확인됨 — YAML `long_term_memory.message_sentence_chunking` |
| C1~C17 전체 매핑 | 6개 후보 재현엔 C5·C6·C12 만 필요 |
| `expand_context` 기본값 | 코드 기본값 그대로 사용 결정 |
| LoCoMo cat5 필터 | retrieval_agent 경로에 우리가 직접 포팅 |
| HotpotQA "hard 500" 선정 기준 | S1 (앞 500) + S2 (seed=42 무작위) 병행 실험 |

---

## §4 메일 초안

---

**Subject**: A few questions about reproducing MemMachine LongMemEvalS results

**To**: [MemMachine team contact]

---

Dear MemMachine team,

Hello. My name is [Name] from [Team/Company]. Our team is preparing reproduction experiments based on the MemMachine paper (arXiv:2604.04853v1), using our in-house open LLMs.

We have reviewed the public repository (commit `15380b7`, 2026-04-20). Most things are clear, but we have a few small questions. We would really appreciate your help.

---

**Q1. Edwin prompts**

We could not find the Edwin1 and Edwin3 search prompts described in §8.4.5 of the paper. Would it be possible to share the full text of Edwin1 and Edwin3 (MemMachine v0.3.x)? We do not need Edwin2 for this phase.

---

**Q2. `user:` prefix implementation**

For the `"user:"` prefix in §8.4.2, we found it hardcoded in the legacy path (`evaluation/episodic_memory/longmemeval_search.py:161`). But in the retrieval_agent path (`longmemeval_test.py`), we could not find this logic.

Our plan is to add one line just before `longmemeval_test.py:214`:
```python
question = f"User: {question}"
```

Is this how you measured C5/C6, or is there another path/method we should use?

---

**Q3. JSON-str activation**

For the `do_json_str` flag in `evaluation/utils/memmachine_helper_base.py:140`, we could not find any place where it is set to `True` in the repository (no YAML key, no CLI argument, no hardcoded assignment). The only caller `restapiv2_locomo_search.py:91,98` does not pass `do_json_str` either.

How did you enable JSON-str = on for the Table 12 configurations (especially for LongMemEvalS in the retrieval_agent path)?

---

**Q4. exclude_abstention value (light check)**

We noticed `evaluate_responses()` in `longmemeval_evaluate.py` uses `exclude_abstention=True` by default, while `main()` in the same file passes `False` (hardcoded).

Which value did you use for the paper's numbers? We plan to use `True`, but wanted to double-check.

---

We would be grateful for any help on the above. Even partial answers would be very useful.

Thank you for open-sourcing MemMachine and for the detailed paper. Your work has been a great reference for our team.

Best regards,
[Name]
[Team] / [Company]

---

## 변경 이력

- **v3 (2026-04-22)**: 톤 가볍게 조정. 우리가 이미 파악한 것 (chunk=YAML key 확정) 은 질문에서 제외, 확인이 필요한 것만 4건 남김
- v2 (2026-04-22): JSON-str 활성화 방법 필수 3 신설
- v1 (2026-04-22): 초기 작성
