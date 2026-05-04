# LongMemEval Judge 슈퍼·초·울트라 리뷰 가이드

> 목표: 이 문서는 “코드 한 줄씩 따라가며” LongMemEval judge가 어떻게 동작하는지,
> 원본 대비 무엇이 달라졌는지, 실험자가 어디서 실수하기 쉬운지를 **즉시 검증 가능하게** 정리한다.

---

## 0) 30초 요약

- LongMemEval 행은 generic judge가 아니라 task별 프롬프트 judge로 채점된다.
- `question_id`에 `_abs`가 있으면 abstention 전용 프롬프트로 바뀐다.
- yes/no 파싱은 원본보다 엄격해서 형식이 흐트러지면 0점 처리될 수 있다.

즉, 성능 수치에는 “모델 품질”뿐 아니라 “judge 출력 형식”이 강하게 개입한다.

---

## 1) 먼저 큰 그림: 어떤 파일을 어떤 순서로 보면 되나

아래 순서대로 보면 된다.

1. `scripts/stages/judge.py`
   - 실제 파이프라인에서 judge를 어떻게 호출하는지
2. `evaluation/retrieval_agent/llm_judge.py`
   - 어떤 프롬프트를 쓰고, yes/no를 어떻게 파싱하는지
3. `evaluation/retrieval_agent/evaluate.py`
   - 레거시 경로도 같은 LongMemEval 분기를 타는지

---

## 2) “내가 바로 확인” 가능한 추적 절차 (명령 + 의미)

> 아래 명령은 repo root(`/workspace/MemMachine`) 기준.

## Step 1. 파이프라인 judge 진입점 확인

```bash
rg -n "def run\(|_LONGMEMEVAL_TASKS|evaluate_llm_judge_longmemeval|json_mode=False" scripts/stages/judge.py
```

의미:
- stage run 루프 안에서 LongMemEval category를 만나면
  `evaluate_llm_judge_longmemeval()`을 호출하는지 확인.
- plain-text judge(`json_mode=False`)를 lazy 생성하는지 확인.

## Step 2. LongMemEval task 목록 확인

```bash
rg -n "_LONGMEMEVAL_TASKS" scripts/stages/judge.py evaluation/retrieval_agent/evaluate.py
```

의미:
- 파이프라인 경로와 레거시 경로가 같은 task key 집합을 쓰는지 확인.
- `category` 문자열이 이 집합과 다르면 generic judge로 빠질 수 있음을 확인.

## Step 3. 원본 기반 task-specific prompt 확인

```bash
rg -n "_LME_TEMPLATE_|def get_anscheck_prompt" evaluation/retrieval_agent/llm_judge.py
```

의미:
- general/temporal/knowledge-update/preference/abstention 템플릿 존재 확인.
- LongMemEval 전용 프롬프트 분기 함수가 실제로 있는지 확인.

## Step 4. `_abs` abstention 분기 확인

```bash
rg -n "_abs|abstention|evaluate_llm_judge_longmemeval" evaluation/retrieval_agent/llm_judge.py
```

의미:
- `question_id`에 `_abs`가 포함되면 abstention prompt로 전환되는지 확인.

## Step 5. yes/no 파싱 정책 확인 (lenient / strict)

```bash
rg -n "_YES_NO_RE|def _parse_yes_no|policy ==|LongMemEvalYesNoPolicy" evaluation/retrieval_agent/llm_judge.py
```

의미:
- 두 가지 정책이 있음을 확인:
  - **`lenient` (기본)** — `'yes' in lower(raw)` substring 매칭. `xiaowu0162/LongMemEval` 원본과 100% 동일. `"yesterday"` / `"Yes, the answer..."` / `"yes and no"` 모두 1. **paper 수치 재현용**.
  - **`strict`** — `\A\s*(yes|no)[\s.!?,]*\Z` whole-string 매칭. 위 케이스 모두 0. substring trap (`yesterday`) 회피용.
- 정책 설정 우선순위:
  1. (legacy) `python evaluate.py --longmemeval-yesno-policy {lenient,strict}` CLI 플래그
  2. (eval-tool) `python generate_config.py --longmemeval-yesno-policy {lenient,strict}` → `run_cfg.judge.longmemeval_yesno_policy`
  3. fallback: `configuration.yml` 의 `retrieval_agent.longmemeval_yesno_policy` (Pydantic default = `lenient`)
- 실행 시점에 `[evaluate] longmemeval_yesno_policy=...` 또는 `[judge] ... longmemeval_yesno_policy=...` 로그가 항상 찍히므로 결과 jsonl 옆에 어떤 정책이었는지 추적 가능.

> ⚠️ **lenient 의 substring trap 주의**: `"yesterday"` 도 1 로 채점됨. 원본 LongMemEval 의 알려진 동작이며, paper 수치 재현 시엔 그대로 유지해야 함. 운영용 / 점수 부풀리기 회피용에선 `strict` 권장.

## Step 6. judge 모델 선택 우선순위 확인

```bash
rg -n "judge_llm_model|llm_model|create_judge_fn|ValueError" evaluation/retrieval_agent/llm_judge.py scripts/stages/judge.py
```

의미:
- `judge_llm_model` 우선, 없으면 `llm_model` fallback인지 확인.
- 잘못된 model ID일 때 명시적 에러를 내는지 확인.

---

## 3) 단계별로 “왜 중요한가”

## 3.1 category 확인이 중요한 이유

LongMemEval 여부는 데이터셋명이 아니라 row의 `category` 문자열로 판정된다.
즉, category 오타/정규화 실패는 “다른 judge 규칙”을 타게 만든다.

## 3.2 `_abs` 확인이 중요한 이유

abstention 문항은 일반 문항과 판정 기준이 다르다.
`_abs` 태깅이 틀리면 채점 의미 자체가 바뀐다.

## 3.3 yes/no 정책 (lenient / strict) 확인이 중요한 이유

strict parser는 보수적이다.
정책에 따라 동일한 judge 출력이 다른 점수가 된다:
- 작은 / verbose judge 모델 (Llama 8B, Mistral 7B 등) + `strict` 조합은 정답을 0 으로 깎음 → judge format compliance 가 측정됨
- 큰 / 지시 잘 따르는 judge (GPT-4o) + 어느 정책이든 → 거의 동일
- paper 수치 재현 / leaderboard 비교 → `lenient` 필수
- 운영 환경에서 false positive 회피 → `strict` 권장

## 3.4 judge 모델 ID 확인이 중요한 이유

fallback이 자동으로 일어나므로, 실험자가 의도한 “분리 judge”가
실제로는 적용되지 않았는데도 눈치 못 챌 위험이 있다.

---

## 4) 실험 전에 최소로 해야 할 10분 검증

1. category 분포 확인

```bash
python - <<'PY'
import json
from collections import Counter
p='results/<run_name>/generate.jsonl'
c=Counter()
with open(p,encoding='utf-8') as f:
    for line in f:
        if line.strip():
            c[json.loads(line).get('category','<missing>')] += 1
print(c)
PY
```

의미: LongMemEval task key 외 값이 비정상적으로 많은지 확인.

2. `_abs` 샘플 확인

```bash
python - <<'PY'
import json
p='results/<run_name>/generate.jsonl'
count=0
with open(p,encoding='utf-8') as f:
    for line in f:
        if not line.strip():
            continue
        row=json.loads(line)
        qid=str(row.get('question_id',''))
        if '_abs' in qid:
            print(qid, row.get('category'))
            count+=1
            if count>=10:
                break
print('shown:',count)
PY
```

의미: abstention 태깅이 실제로 들어가 있는지 빠르게 눈검증.

3. judge 설정 확인

```bash
python - <<'PY'
import yaml
cfg='evaluation/retrieval_agent/configuration.yml'  # 또는 working config 경로
c=yaml.safe_load(open(cfg,encoding='utf-8'))
ra=c.get('retrieval_agent',{})
print('judge_llm_model=',ra.get('judge_llm_model'))
print('llm_model=',ra.get('llm_model'))
PY
```

의미: 어떤 모델이 judge로 resolve될지 사전 확인.

---

## 5) 자주 터지는 실패 패턴과 즉시 대응

1. **점수가 갑자기 크게 하락**
   - 원인 후보: judge가 verbose reply를 많이 내서 strict parser 실패
   - 대응: judge raw 출력 샘플링, yes/no 단답 유도 설정 강화

2. **원본 LongMemEval 결과와 미묘하게 불일치**
   - 원인 후보: strict parser 차이 + category/_abs 메타 차이
   - 대응: 소량 샘플을 원본 judge와 교차검증

3. **분리 judge를 썼다고 생각했는데 실제론 fallback**
   - 원인 후보: `judge_llm_model` 미설정/미등록
   - 대응: 실행 전후 config snapshot + resolved model ID 로그 기록

---

## 6) 추천 운영 프로토콜 (재현 실험용)

1. 30~50문항 파일럿으로 judge 응답 형식 안정화
2. 본 실험에서는 judge 모델/provider/temperature 고정
3. run 시작 전에 category 분포·`_abs` 샘플 확인
4. run 종료 후 하위 점수 샘플을 parser 영향/진짜 오답으로 분리
5. 최종 리포트에 judge 조건(모델ID/provider/라우팅규칙)을 표로 고정 기재

---

## 7) 코드 포인터 (빠른 점프)

- `scripts/stages/judge.py`
  - `_LONGMEMEVAL_TASKS`
  - `_judge_config_path()`
  - `run()` 내 LongMemEval 분기 + `json_mode=False`
- `evaluation/retrieval_agent/llm_judge.py`
  - `get_anscheck_prompt()`
  - `evaluate_llm_judge_longmemeval()`
  - `_YES_NO_RE`, `_parse_yes_no()`
  - `create_judge_fn()`
- `evaluation/retrieval_agent/evaluate.py`
  - 레거시 경로의 `_LONGMEMEVAL_TASKS` 분기

---

## 8) 결론

이 judge는 “원본 의도 복원”과 “채점 안전성 강화”를 함께 추구한다.
그래서 실험자는 반드시 아래를 분리해서 봐야 한다.

- 모델이 답을 맞췄는가?
- judge가 그 답을 형식적으로 통과시켰는가?

이 둘을 분리해서 기록하면, 재현 실험 해석이 훨씬 안정적이다.
