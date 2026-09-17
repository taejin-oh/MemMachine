# 사전 임베딩 벡터 데이터셋 조사 (MemMachine DB 병목 에뮬레이터용)

**결론:** 한 데이터셋만으로 여섯 요구사항을 모두 만족하는 경우는 없습니다. 권장안은 `Snowflake/msmarco-v2.1-snowflake-arctic-embed-m-v1.5`(768차원, 256차원 절단)와 `CohereLabs/msmarco-v2.1-embed-english-v3`(텍스트, 1024차원, 질의+GT)의 조합입니다. 샤드 2개로 3,750,897개 벡터를 확보할 수 있고, 두 저장소를 행 단위로 붙일 수 있는지는 샤드 00~02에서 직접 확인했습니다.

**읽기 전 참고**
- 입력 중 "very-large" 계열 조사 결과는 Snowflake arctic-embed-l 항목 중간에서 잘려 있고, 그 계열의 교차 검증 결과는 받지 못했습니다. 그래서 핵심 추천 후보는 2026-09-14에 직접 다시 확인했고, 해당 항목은 **[직접확인]**으로 표시했습니다.
- 교차 검증에서 나온 정정은 모두 반영했습니다. 확인되지 않은 주장은 삭제했거나 "미확인"으로 표시했습니다.

---

## 1. "Pes2o-VE"의 정체

**결론: 실제로 있는 데이터셋입니다.** 정식 이름은 Pes2o-Vector-Embeddings이고, Materials Data Facility(MDF)에 DOI 10.18126/2pev-mz97로 등록되어 있습니다(source_id e31e3225-7f75-4313-9983-f8b75811405f, 등록일 2026-06-03, 저자 Ockerman 외).

**내용**
- MDF 초록: "Pes2o-Vector-Embeddings (Pes2o-VE) is a set of embeddings generated using hybrid-semantic-chunking with the Qwen3-Embedding-4B model from the Pes2o text corpus, which is composed of over 8 million academic papers … used in the paper When More Cores Hurts: The Vector Database Scaling Paradox in HPC."
  - 출처: https://search.api.globus.org/v1/index/1a57bbe5-5272-477f-9d31-343b8258b7a5/search?q=Pes2o
- 청킹 방식: section, paragraph, line 경계로 재귀 분할(512-token budget)한 뒤, quantile 기반 cosine 임계값으로 semantic chunking을 합니다. quantile 값은 명시되어 있지 않습니다(같은 출처).
- 규모: 88,453,763개, 2560차원, float32, 843.56 GB. 논문 문구는 "All vectors are stored using float32 representations"와 "≈88 million embeddings or 843.56 GB"입니다.
  - 출처: https://arxiv.org/html/2606.08950v1 (Table I)
- 거리 척도: Cosine. 출처: https://github.com/OckermanSethGVSU/VECHINI (README)

**라이선스**
- MDF 레코드는 ODC-BY 1.0입니다(Globus Search 레코드).
- DataCite 레코드는 rightsList가 비어 있습니다(https://api.datacite.org/dois/10.18126/2pev-mz97).
- 논문은 CC BY 4.0, 임베딩 모델은 apache-2.0입니다(https://huggingface.co/Qwen/Qwen3-Embedding-4B).

**질의와 GT**
- 질의: BV-BRC 용어 22,723개입니다. 템플릿은 "Retrieve the most relevant passages to the term '<term>'"이고 prompt_name="query"를 씁니다. 릴리스 파일에 들어 있는지는 **미확인**입니다.
- GT: 논문 Table V가 "Pes2o-EV-10M" 부분집합의 Recall@10을 보고하므로 GT가 만들어진 적은 있습니다. 공개 여부는 명시되어 있지 않습니다.

**확인하지 못한 것:** 파일 목록, 파일 포맷, 원문 텍스트 포함 여부, 부분 다운로드 가능 여부.
- MDF 상세 페이지는 JS 껍데기만 있습니다.
- https://data.materialsdatafacility.org/mdf_open/e31e3225-7f75-4313-9983-f8b75811405f/1.0/ 는 Content-Length 0을 돌려줍니다.
- 다운로드에는 Globus 로그인이 필요하고, ACDC 포털은 접속을 거부했습니다.
- VECHINI 설정에 `.npy` 입력과 VECTOR_DIM=2560이 있지만, 이것은 벤치마크 도구의 입력 형식일 뿐 릴리스 포장 형태를 알려주지 않습니다.
- ResearchGate figure(403)는 확인할 수 없어 근거에서 뺐습니다.

**가장 가까운 관련 자료**

1. **Zenodo 17101276** (같은 그룹의 이전 릴리스, CC-BY-4.0, 2025-09-11)
   - Qwen3-Embedding-4B 2560차원 float32 벡터 8,293,485개입니다. 논문 전문 한 편당 벡터 하나이고 청킹은 없습니다.
   - 파일: pes2o_corpus.npz 39,748,381,931 B(단일 deflate 멤버, 압축 해제 시 84,925,286,528 B).
   - 질의 파일:
     - queries_v1.npz와 queries_v2.npz: 각 (22723, 2560). v1은 논문 평가용이고, v2는 prompt_name="query"로 다시 생성한 것입니다.
     - query_text.csv: 22,723줄이지만 고유한 줄은 8,875개입니다.
   - meta ID는 Zenodo 설명에 따르면 "ID corresponding to an extracted version of a paper's text stored in a JSON file internally at Argonne"입니다. 공개 매핑이 없어서 **텍스트와 조인할 수 없습니다**. GT도 없습니다.
   - 출처: https://zenodo.org/records/17101276 , https://zenodo.org/api/records/17101276
2. **allenai/peS2o** (텍스트만 있고 벡터는 없음)
   - HF 카드 라이선스는 ODC-By이고, GitHub 저장소 라이선스는 Apache-2.0입니다.
   - v2는 문서 38.97M개입니다. HF usedStorage는 463,592,387,529 B입니다.
   - data/v2 train은 86,572,369,890 B이며, 약 1.57 GB 샤드 10개와 약 7.08 GB 샤드 10개로 되어 있습니다. v1과 v3도 있습니다.
   - 조사 원본에 있던 "308 GB"는 어떤 페이지에서도 확인되지 않아 삭제했습니다.
   - 출처: https://huggingface.co/datasets/allenai/peS2o , https://huggingface.co/api/datasets/allenai/peS2o?expand[]=usedStorage
3. **common-pile/peS2o_filtered**
   - 공개 라이선스 논문만 추린 텍스트이며, 약 6.1M 문서, 182.6 GB입니다. 벡터는 없습니다.
   - 출처: https://huggingface.co/datasets/common-pile/peS2o_filtered
4. **Semantic Scholar embeddings-specter_v2**
   - "120M records in 30 28GB files", Apache 2.0이고 API key가 필요합니다. 차원은 확인한 1차 페이지에 명시되어 있지 않습니다.
   - 출처: https://api.semanticscholar.org/datasets/v1/release/latest

**요구사항 대비 평가:** 차원은 2560 하나뿐이라 두 번째 차원은 MRL 절단(모델 카드상 32~2560)으로만 얻을 수 있습니다. 규모는 충분합니다. 텍스트는 미확인이고, 약 843 GB를 Globus로 받아야 하며, 도메인은 학술 논문입니다. **이번 용도에는 권장하지 않습니다.**

---

## 2. 후보 비교표

**적합도 기준 (1~6 순서)**

| 번호 | 요구사항 | O | △ | X |
|---|---|---|---|---|
| 1 | 두 개 이상 차원 | 같은 텍스트에 2개 이상 차원 벡터를 파일로 제공 | 저장된 차원은 하나지만 MRL·절단이 카드에 명시되어 있음, 또는 같은 텍스트에 다른 모델·다른 차원 | 그 외 |
| 2 | 규모 | 1,000만 개 이상 | 250만~1,000만 개 | 250만 개 미만 |
| 3 | 텍스트 | 같은 파일에 있거나, 행 순서가 명시된 동반 파일에 있음 | 키로 조인 필요 | 없음 또는 매핑 불명 |
| 4 | 질의 | 질의 벡터 또는 질의+GT 제공 | 토픽·qrels만 있거나 재생성 필요 | 없음 |
| 5 | 라이선스·다운로드 | 라이선스 명시 + 샤드 단위 부분 다운로드 | 둘 중 하나만 충족 | 둘 다 미충족 |
| 6 | 도메인 | 채팅 | 대화 인접(포럼 등) | 그 외 |

| # | 이름 (URL) | 텍스트 포함 | 모델·차원(변형별) | 벡터 수 | 총 크기 | 부분 다운로드 | 질의 세트/GT | 라이선스 | 적합도 1/2/3/4/5/6 |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Pes2o-VE https://www.materialsdatafacility.org/detail/e31e3225-7f75-4313-9983-f8b75811405f-1.0 | 미확인 | Qwen3-Embedding-4B 2560 float32 | 88,453,763 | 843.56 GB | 미확인(Globus) | BV-BRC 22,723(포함 여부 미확인)/GT 미공개 | ODC-BY 1.0 | △/O/X/△/△/X |
| 2 | Zenodo 17101276 https://zenodo.org/records/17101276 | X(내부 ID, 매핑 없음) | Qwen3-Embedding-4B 2560 float32 | 8,293,485 (+질의 22,723) | 39,940,272,785 B | 파일 단위, 코퍼스는 단일 npz라 앞에서부터만 | 질의 벡터 v1/v2/GT 없음 | CC-BY-4.0 | △/△/X/O/△/X |
| 3 | CohereLabs/msmarco-v2.1-embed-english-v3 https://huggingface.co/datasets/CohereLabs/msmarco-v2.1-embed-english-v3 | O(docid, url, title, headings, segment, start_char, end_char) [직접확인] | embed-english-v3.0 1024 float32 | 113,520,750 (+질의 1,677) | parquet 263.6 GB / npy 232.5 GB / jsonl 26.9 GB (60개씩) | O(60 샤드; jsonl 샤드 00은 430,869,937 B) [직접확인] | 질의 벡터 1,677 + brute-force top-1000 + qrels(215개) | 임베딩 Apache 2.0, 텍스트는 MS MARCO v2.1 조건 | X/O/O/O/△/X |
| 4 | Snowflake/msmarco-v2.1-snowflake-arctic-embed-m-v1.5 https://huggingface.co/datasets/Snowflake/msmarco-v2.1-snowflake-arctic-embed-m-v1.5 | X(컬럼은 doc_id, embedding뿐 [직접확인]; #3과 조인 가능) | arctic-embed-m-v1.5 768 float32, 정규화 안 됨. 카드가 768과 256(절단)을 모두 평가 [직접확인] | 113,520,750(very-large 조사의 footer 합, 검증 미수신) | 350,164,128,419 B (60개; 카드의 "~620GB"와 불일치) | O(샤드 00/01/02 = 5.43/6.14/5.85 GB) [직접확인] | topics/qrels/runs(질의 임베딩 포함 여부 미기재) | 명시 없음(모델은 apache-2.0) | △/O/△/△/△/X |
| 5 | Snowflake/msmarco-v2.1-snowflake-arctic-embed-l https://huggingface.co/datasets/Snowflake/msmarco-v2.1-snowflake-arctic-embed-l | O(doc_id, embedding, text, url) | arctic-embed-l 1024 float32 | 뷰어 추정치만 있음(총계 미검증) | 504,233,026,684 B (60개, 5.1~10.8 GB) | O | topics/qrels/runs | 명시 없음 | X/O/O/△/△/X |
| 6 | Sherlock-Comms/wikipedia-en-2026-07-01-qwen3-embed-4b (+ -passages) https://huggingface.co/datasets/Sherlock-Comms/wikipedia-en-2026-07-01-qwen3-embed-4b | O(동반 저장소, 행 순서가 ids.txt와 일치한다고 명시) [직접확인] | Qwen3-Embedding-4B를 MRL로 1024까지 절단 후 L2 정규화, float16 | 17,473,199 | 벡터 35,785,118,848 B (npy 57개) + 텍스트 약 19.30 GB (jsonl 19개) | O(폴더 단위) [직접확인] | 없음 | CC BY-SA 4.0 | △/O/O/X/O/X |
| 7 | maknee/bioasq_bier_{1024,2048,3072,4096}_1m https://huggingface.co/datasets/maknee/bioasq_bier_1024_1m | O | Qwen3-Embedding-8B 1024/2048/3072/4096 (1024·2048이 3072의 정규화 prefix, 0~1행 확인) | 차원별 1,000,000 | base.parquet 4.99/8.93/12.42/16.06 GB | 차원별 파일 선택 가능 | queries.fbin(크기로 보아 10,000개로 추정) + gt_100.fbin | MIT | O/X/O/O/O/X |
| 8 | Qdrant/dbpedia-entities-openai3-text-embedding-3-large-3072-1M (+1536-1M) https://huggingface.co/datasets/Qdrant/dbpedia-entities-openai3-text-embedding-3-large-3072-1M | O(_id, title, text) | 3-large 3072 float64 + ada-002 1536 float32 (같은 행). 1536-1M은 3072의 정규화 prefix(cosine 0.9997~1.0) | 1,000,000 | 24,796,927,580 B (63개) / 9,551,862,565 B (26개) | O | 없음 | apache-2.0 / MIT | O/X/O/X/O/X |
| 9 | filipecosta90/dbpedia-openai-1M-text-embedding-3-large-{512d…3072d} https://huggingface.co/datasets/filipecosta90/dbpedia-openai-1M-text-embedding-3-large-1536d | O | 3-large 512/1024/1536/2048/3072 float64 (prefix 관계, cosine ≥0.99999) | 각 1,000,000 | 5개 합계 약 67.8 GB | O | 없음 | 명시 없음 | O/X/O/X/△/X |
| 10 | jaitrychroma/wikipedia-openai-3072-5M https://huggingface.co/datasets/jaitrychroma/wikipedia-openai-3072-5M | O | 3072 float64 (모델명 없음) | 5,000,000 | 90.48 GB (251개) | O | 없음 | 명시 없음 | X/△/O/X/△/X |
| 11 | fzoll/with_embeddings_wikipedia_20231101.en + davanstrien/wikipedia-en-embeddings https://huggingface.co/datasets/fzoll/with_embeddings_wikipedia_20231101.en | O | 512 float64(모델 미기재) / all-MiniLM-L6-v2 384. 같은 텍스트(첫 행만 확인) | 각 6,407,814 | 33.69 GB / 21.46 GB | O | 없음 | 둘 다 명시 없음 | △/△/O/X/△/X |
| 12 | mixedbread-ai/wikipedia-embed-en-2023-11 https://huggingface.co/datasets/mixedbread-ai/wikipedia-embed-en-2023-11 | O | 1024 float64 (카드에 모델 없음; 파생 카드에는 mxbai-embed-large-v1, 모델 카드상 MRL 지원) | 41,488,110 | 93.93 GB | O | 없음 | 명시 없음 | △/O/O/X/△/X |
| 13 | anton-l/wiki-embed-mxbai-embed-large-v1 https://huggingface.co/datasets/anton-l/wiki-embed-mxbai-embed-large-v1 | O(다국어) | 1024 float32 | 19,399,177 | 107.68 GB (235개) | O | 없음 | 명시 없음 | △/O/O/X/△/X |
| 14 | CohereLabs/wikipedia-2023-11-embed-multilingual-v3 (+ -int8-binary) https://huggingface.co/datasets/CohereLabs/wikipedia-2023-11-embed-multilingual-v3 | O | multilingual-v3 1024. float32/int8/ubinary는 정밀도 변형일 뿐 차원은 같음 | 전체 247,154,006 / en 41,488,110 | 536.27 GB (en 90.13 GB, 415개) | O | 없음 | 명시 없음 | X/O/O/X/△/X |
| 15 | Upstash/wikipedia-2024-06-bge-m3 https://huggingface.co/datasets/Upstash/wikipedia-2024-06-bge-m3 | O | BGE-M3 float32 (차원 미검증) | 약 144M (en 47,018,430) | 633.1 GB (1,447개) | O | 없음 | Apache-2.0 | X/O/O/X/O/X |
| 16 | Qdrant/FineWeb-10B https://huggingface.co/datasets/Qdrant/FineWeb-10B | O | gte-multilingual-base 768 halffloat + sparse. 모델 카드상 출력 차원 [128, 768] | 10,074,324,060 | 약 46.5 TB (data/00만 476,778,195,193 B) | O(약 5 GB 샤드) | MS MARCO 질의 + exact top-1000 GT(전체 코퍼스 기준). 질의는 재배포하지 않음 | ODC-BY-1.0 | △/O/O/△/O/X |
| 17 | Qdrant/PubMed-MV https://huggingface.co/datasets/Qdrant/PubMed-MV | O | BGE-M3 dense 1024 float32 + sparse + multi-vector | 23,898,701 | 약 35 TiB | O | 질의 1,000 + top-1000 GT | Apache-2.0 | X/O/O/O/△/X |
| 18 | CohereLabs/msmarco-v2-embed-english-v3 / -multilingual-v3 https://huggingface.co/datasets/CohereLabs/msmarco-v2-embed-english-v3 | O | 두 모델 모두 1024 (같은 텍스트) | 각 138,364,198 | 289.90 / 289.89 GB | O | 명시 없음 | 명시 없음(README 없음) | X/O/O/X/△/X |
| 19 | Elastic rally-tracks msmarco-v2-vector https://github.com/elastic/rally-tracks/tree/master/msmarco-v2-vector | O | Cohere embed-english-v3.0 1024 | 138.3M | 3,000,000 문서 단위 zst(track.json에 압축 약 28.9 GB, 파일당인지 모호) | O | queries + brute-force top 1000 | 명시 없음 | X/O/O/O/△/X |
| 20 | Elastic rally-tracks openai_vector https://github.com/elastic/rally-tracks/tree/master/openai_vector | O | ada-002 1536 | 2,580,961 + 100,000 | bz2 32,076,749,416 B | 대형 단일 파일 | queries + true top 1000 | 명시 없음 | X/△/O/O/X/X |
| 21 | big-ann Wikipedia-Cohere 35M https://raw.githubusercontent.com/harsha-simhadri/big-ann-benchmarks/main/benchmark/datasets.py | X | Cohere 768 float32 | 35,000,000 (+질의 5,000, Simple Wikipedia) | 107,520,000,008 B | O(Range로 앞 N개) | 질의 + 100K/1M/10M/35M GT | 명시 없음 | X/O/X/O/△/X |
| 22 | big-ann Caselaw https://raw.githubusercontent.com/harsha-simhadri/big-ann-benchmarks/main/dataset_preparation/caselaw_dataset.md | △(parquet 32개, 274,325,982,689 B; case_id로 매핑) | text-embedding-3-small 1536 float32 (문서엔 "1532"라고 적혀 있고 헤더는 1536) | 7,414,023 (+질의 89,812) | base.bin 45,551,757,320 B | O(Range) | 질의 + GT(7M/1M/100K) | 원본 CC0 1.0 / 임베딩 CDLA-2.0 | △/△/△/O/O/X |
| 23 | VectorDBBench Cohere 10M https://s3.us-west-2.amazonaws.com/assets.zilliz.com?list-type=2&prefix=benchmark/cohere_large_10m/ | X(id, emb만) | 768 (모델 미기재) | 10,000,000 | shuffled 47,166,038,503 B (float64) / unshuffled 31,326,939,213 B (float32) | O(익명 S3) | test 1,000 + neighbors, tenant_labels_1000x10k.parquet | 데이터 라이선스 명시 없음 | X/O/X/O/△/X |
| 24 | VectorDBBench OpenAI 5M https://s3.us-west-2.amazonaws.com/assets.zilliz.com?list-type=2&prefix=benchmark/openai_large_5m/ | X | 1536 float64 (C4) | 5,000,000 | 90,042,426,177 B (사본 2개) | O | test 1,000 + neighbors | 명시 없음 | X/△/X/O/△/X |
| 25 | VectorDBBench Bioasq 10M https://s3.us-west-2.amazonaws.com/assets.zilliz.com?list-type=2&prefix=benchmark/bioasq_large_10m/ | X | 1024 float32 | 10,000,000 | 19,280,984,409 B (shuffled만) | O | test(1M 폴더 기준 3,106) + neighbors | 명시 없음 | X/O/X/O/△/X |
| 26 | Zilliz msmarco_v2_138M_parquet https://assets.zilliz.com/benchmark/msmarco_v2_138M_parquet/README | X | 1536 float32 (모델 미기재) | pk 0~138,364,197 | 852,018,132,378 B | O(50만 행 단위) | query.npy 10,000×1536 + L2 GT top-1000 | 명시 없음 | X/O/X/O/△/X |
| 27 | VIBE https://huggingface.co/datasets/vector-index-bench/vibe | X(카드에 텍스트 배열 설명이 없어 구조로 추론) | dpr-jina 768 / msmarco-qwen 1024 / hotpotqa-harrier 640 (데이터셋마다 단일 차원) | 20,969,760 / 8,840,823 / 5,233,329 | 저장소 271,282,401,415 B | 데이터셋당 HDF5 1개 | test + top-100 | CC BY 4.0 | X/O/X/O/△/X |
| 28 | amkdg/wildchat-4.8M-Embeddings https://huggingface.co/datasets/amkdg/wildchat-4.8M-Embeddings | △(1M-only 67,340개 대화만 포함; 나머지는 conversation_hash로 allenai/WildChat-4.8M과 조인) | Qwen3-Embedding-8B-NVFP4 4096 float16 | 3,735,087 | emb.npy 30,597,832,832 B (단일) | 명시 없음 | 없음 | odc-by | △/△/△/X/△/O |
| 29 | amkdg/lmsys-chat-1M-Embeddings https://huggingface.co/datasets/amkdg/lmsys-chat-1M-Embeddings | X(AarushSah/lmsys-chat-1m과 조인) | 같은 모델 4096 | 1,004,674 | 8,288,528,424 B | 명시 없음 | 없음 | cc-by-nc-4.0; 원문은 LMSYS 계약(제3자 이전 금지) | △/X/△/X/X/O |
| 30 | labofsahil/hackernews-vector-search-dataset https://huggingface.co/datasets/labofsahil/hackernews-vector-search-dataset | O | all-MiniLM-L6-v2 384 | 28,737,557 | 53,165,493,589 B (73개) | O | 없음 | 명시 없음 | X/O/O/X/△/△ |
| 31 | syntropicsignal-ai/wildchat-asking-en-{text-embedding-3-small, gemini-embedding-001} https://huggingface.co/datasets/syntropicsignal-ai/wildchat-asking-en-gemini-embedding-001 | O | 3-small 1536 / gemini-embedding-001 1536 (3072의 MRL prefix), 같은 텍스트 | 189,916 | 563,928,745 B / 1,112,574,701 B | 파일 단위 | 없음 | odc-by | △/X/O/X/O/O |
| 32 | friendshipkim/reddit_eval_embeddings_luar https://huggingface.co/datasets/friendshipkim/reddit_eval_embeddings_luar | O | 512 float64 (모델 미기재) | 1,259,584 | 4,552,565,188 B | split 단위 | queries split (169,936)/GT 미기재 | 명시 없음 | X/X/O/△/X/△ |
| 33 | CohereLabs/beir-embed-english-v3 https://huggingface.co/datasets/CohereLabs/beir-embed-english-v3 | O(bioasq, robust04, trec-news, signal1m 제외) | embed-english-v3.0 1024 | 합계 50,490,419 (msmarco-corpus 8,841,823) | 102.98 GB | O(config 단위) | 질의 벡터 + qrels | 명시 없음 | X/△/O/O/△/X |

**표에서 뺀 후보와 이유**
- MSMARCO Web Search(101M): 텍스트를 쓰려면 ClueWeb22 라이선스가 따로 필요하고, 비상업 전용입니다.
- big-ann Turing, SPACEV: 100차원이고 텍스트가 없습니다.
- ann-benchmarks의 GloVe와 NYTimes: 250만 개보다 훨씬 작습니다.
- qdrant `dbpedia_openai_1M.tgz`: 975,000개이고 텍스트가 없습니다.
- `cohere-wiki-1m.tgz`: 999,999개입니다.
- `arxiv.tar.gz`: 2,138,591개, 384차원입니다.
- Qdrant arxiv instructor-xl(2.25M): 라이선스 명시가 없습니다.
- VDBBench multimodal: 텍스트 컬럼이 없습니다.
- Snowflake mteb arctic MSMARCO 8.8M: 텍스트가 없습니다.
- nomic-embed-v2-wikivecs(en 6,407,814×768): 텍스트가 없습니다.
- Supabase dbpedia-3-large: 뷰어 수치가 부분 통계입니다.
- Cohere/wikipedia-22-12-*: HF에서 401을 돌려주므로 사용할 수 없는 것으로 봤습니다.
- ReadyAi podcast: 벡터가 태그 임베딩입니다.
- scaleinvariant: 토큰 activation이지 문장 임베딩이 아닙니다.
- brianv1981 LanceDB: 약 10만 개입니다.
- mteb/LongMemEval: 텍스트, 질의, qrels만 있고 벡터가 없습니다. 질의·GT 소스로는 쓸 수 있습니다.

---

## 3. 추천

### 1순위: Snowflake arctic-embed-m-v1.5 (768 / 256) + CohereLabs msmarco-v2.1 (텍스트, 선택적으로 1024)

**선정 이유**
- **차원 비교가 공정합니다.** 같은 텍스트, 같은 모델의 768차원과 256차원을 비교할 수 있습니다. 근거는 다음과 같습니다 [직접확인].
  - 데이터셋 카드: "supports embedding truncation and quantization", "Since the M-v1.5 model supports Vector Truncation we do so to 256 dimensions". 768 Dimensions와 256 Dimensions 결과표가 함께 실려 있습니다.
  - 모델 카드: "Truncation and renormalization to 256 dimensions (a la Matryoskha Representation Learning…)" (https://huggingface.co/Snowflake/snowflake-arctic-embed-m-v1.5)
- **세 번째 차원도 가능합니다.** 같은 텍스트에 대한 Cohere embed-english-v3.0 1024차원을 쓸 수 있습니다. 모델이 다르다는 점은 감안해야 합니다.
- **텍스트 조인이 실제로 됩니다** [직접확인].
  - 샤드 00/01/02의 parquet footer 행 수가 두 저장소에서 똑같습니다: 1,760,180 / 1,990,717 / 1,898,129.
  - Snowflake m-v1.5의 첫 5개 `doc_id`(`msmarco_v2.1_doc_00_0#0_0`, `#1_1557`, `#2_3101`, `#3_4486`, `#4_5974`)가 Cohere `passages_jsonl/…_00.json.gz`의 `docid`와 순서까지 같습니다. arctic-l의 첫 3개도 같습니다.
- **규모 여유가 가장 큽니다.** 113,520,750개이고, 질의 1,677개와 top-1000 GT, qrels가 있습니다.

**다운로드 구성 (2.5M 기준)**
- 필요한 샤드: 00과 01, 합계 3,750,897행 [직접확인].
- 벡터: Snowflake `corpus/00.parquet` + `01.parquet` = 11,569,445,083 B.
- 텍스트: Cohere `passages_jsonl/…_00`, `_01` = 912,724,880 B. jsonl에는 텍스트와 메타데이터만 있습니다.
- 1024차원도 쓸 경우: Cohere `passages_parquet` 00+01 = 8,721,437,084 B를 추가합니다.

**10M 기준**
- 샤드 00~02(5,649,026행)만 확인했습니다.
- 평균 113,520,750/60 ≈ 1.89M/샤드로 계산하면 약 6개 샤드가 필요합니다. 추정치이며, 03번 이후 샤드의 정렬은 미확인입니다.

**용량 계산 (float32 원시값 기준, 3.75M개)**
- 768차원: 약 11.5 GB
- 256차원: 약 3.8 GB

**텍스트 길이** [직접확인]: Cohere jsonl_00 앞부분 33,395행 표본에서 segment 길이는 median 898자, mean 952자, p10 430자, p90 1,457자였습니다.

**감수해야 할 점**
- Snowflake 데이터셋 라이선스가 명시되어 있지 않습니다.
- MS MARCO 텍스트는 "non-commercial research purposes only"입니다(https://microsoft.github.io/msmarco/ , very-large 조사 인용, 교차 검증 미수신).
- Snowflake 벡터는 정규화되어 있지 않으니 사용 전에 정규화해야 합니다.
- Cohere GT는 Cohere 벡터 공간과 1억 1천만 전체 코퍼스 기준이라, 부분집합이나 Snowflake 벡터에는 쓸 수 없습니다. 다시 계산해야 합니다.

### 2순위: Sherlock-Comms Qwen3-Embedding-4B Wikipedia (1024 / 512 절단)

**선정 이유**
- **라이선스가 명확합니다.** CC BY-SA 4.0입니다.
- **텍스트와 벡터의 행 대응이 카드에 명시되어 있습니다** [직접확인].
  - 벡터 카드: "Row *i* of the concatenated shards is passage `ids.txt` line *i*"
  - 텍스트 카드: "Line order matches `ids.txt` / vector row order"
  - 실제로 ids.txt 첫 줄 `39#0`이 `enwiki-2026-07-01-p10p1400054.jsonl`의 첫 id와 같습니다.
- **MRL 기반 차원 축소가 모델 차원에서 지원됩니다.** 카드에 "Native dim truncated to 1024 via the model's Matryoshka (MRL) support … then L2-normalized"라고 되어 있고, Qwen3-Embedding-4B 모델 카드는 32~2560 MRL을 지원한다고 합니다. 따라서 1024와 512(prefix 후 재정규화)를 같은 텍스트·같은 모델로 비교할 수 있습니다.
- **규모:** 17,473,199개로 10M 이상을 충족합니다.

**다운로드 구성 (2.5M 기준)** [직접확인]
- 정렬 순서상 앞의 두 폴더를 받습니다. `p10p1400054`의 npy 3개가 1,855,371행, `p1400055p4535457`의 npy 3개가 1,760,581행으로 합계 3,615,952행입니다.
- 크기: npy 7,405,470,464 B + jsonl 4,551,029,376 B, 합계 약 12.0 GB.

**텍스트 길이** [직접확인]: 첫 파일 표본은 median 1,426자, mean 1,391자였고, 다른 파일(p50570416…) 표본은 median 666자, mean 935자였습니다. 카드의 청킹 규칙은 "~500 tokens (2000 chars) … chunks under 200 chars dropped"입니다.

**감수해야 할 점**
- 질의 세트가 없습니다. 질의로 쓸 문서를 따로 떼어 두거나, 소량의 질의를 `prompt_name="query"`로 직접 임베딩해야 합니다.
- 512차원 절단 품질은 이 데이터에서 검증된 적이 없습니다.
- float16으로 저장되어 있습니다.
- 폴더별 jsonl과 npy가 첫 id 이후에도 계속 대응하는지는 추론입니다. ids.txt(203,301,845 B)로 확인하는 것을 권장합니다.
- CC BY-SA이므로 결과물을 외부에 배포하면 동일조건 조항이 적용됩니다.

### 3순위: 조합안 (대규모 I/O 측정과 차원 품질 검증을 분리)

**구성**
- 규모와 I/O 측정(250만~1천만 개): 1순위 또는 2순위 데이터셋을 씁니다.
- 차원별 recall·지연 비교: `maknee/bioasq_bier_{1024,2048,3072,4096}_1m`을 씁니다.
  - MIT 라이선스이고, 같은 텍스트에 네 가지 차원이 네이티브로 있으며, prefix 관계가 확인됐습니다.
  - queries.fbin과 gt_100.fbin이 있습니다.
- 대안: 텍스트가 짧아도 된다면 `Qdrant/…-3072-1M`(Apache-2.0, 3072 / ada 1536, prefix 확인)을 쓸 수 있습니다.

**트레이드오프**
- 1M 규모의 품질 결과를 2.5M 이상 규모에 그대로 옮길 수는 없습니다.
- 1M 데이터를 사용자마다 반복해서 2.5M을 채우면 중복 벡터가 생겨 HNSW 동작이 왜곡됩니다. 이 부분은 추론이므로 권장하지 않습니다.

**참고 대안**
- 채팅 도메인이 중요하다면 `amkdg/wildchat-4.8M-Embeddings`를 쓸 수 있습니다.
  - 3,735,087개, 4096차원이고 odc-by입니다. 텍스트는 allenai/WildChat-4.8M과 조인해야 합니다.
  - NVFP4 양자화 모델에서도 MRL 절단이 유효한지는 명시되어 있지 않습니다.
  - 벡터 하나가 대화 전체 또는 8192-token 청크 단위이고, 30.6 GB 단일 파일입니다.
- 텍스트가 같은 행에 있고 라이선스가 명확하면서 1천만 개 이상 여유가 필요하다면 `Qdrant/FineWeb-10B`를 쓸 수 있습니다.
  - ODC-BY이고, 모델 카드상 128~768차원을 지원합니다.
  - 다만 문서 길이는 명시되어 있지 않고, sparse 컬럼이 같은 파일에 포함되어 있으며, GT는 100억 전체 기준입니다.

**사용자 분할 (500명 × 5,000개):** 어느 데이터셋이든 사용자 분할은 합성으로 만들어야 합니다. VectorDBBench `tenant_labels_1000x10k.parquet`(10M행, id와 labels)이 참고 사례로 있지만, 파일 구조는 문서화되어 있지 않습니다.

---

## 4. 위험 및 확인 필요 사항

**라이선스**
- Snowflake msmarco-v2.1 저장소들은 라이선스가 명시되어 있지 않습니다.
- MS MARCO 텍스트는 비상업 연구 전용입니다(교차 검증 미수신). 내부 연구 목적이라도 법무 확인을 권장합니다.
- 다음 저장소들도 라이선스 명시가 없습니다: filipecosta90, jaitrychroma, fzoll, davanstrien, mixedbread, anton-l, CohereLabs wiki/msmarco-v2/beir, HN, VectorDBBench 데이터.
- 제한이 있는 라이선스:
  - Sherlock: CC BY-SA 4.0(동일조건).
  - amkdg lmsys, sharechat: cc-by-nc-4.0.
  - LMSYS 원문: 제3자 이전 금지이고, 제공자가 삭제를 요구할 수 있습니다.

**크기와 다운로드**
- HF에서 익명 다운로드에 rate limit이 걸린 사례가 관측됐으므로 HF_TOKEN이 필요합니다.
- Snowflake 샤드는 5~11 GB입니다.
- 카드 수치가 실제 파일과 다른 경우가 있습니다: Snowflake m-v1.5는 카드 "~620GB"에 실제 350 GB이고, Sherlock 텍스트는 카드 21 GB에 실제 19.30 GB입니다.
- Pes2o-VE는 약 843 GB이고 Globus로만 받을 수 있으며, 파일 구조를 알 수 없습니다.

**포맷 변환**
- float64로 저장된 것(DBpedia 계열, jaitrychroma, VectorDBBench shuffled 파일)은 float32로 바꿔야 합니다.
- float16으로 저장된 것(Sherlock, amkdg, FineWeb)은 정밀도 방침을 정해야 합니다.
- MRL 절단 후에는 반드시 재정규화해야 합니다. Snowflake 벡터는 원래부터 정규화되어 있지 않습니다.
- Zenodo npz는 단일 deflate 멤버라 임의 행에 접근할 수 없습니다.

**텍스트 길이 불일치**
- 우리 데이터는 짧은 사용자 발화(median 184자)와 긴 어시스턴트 답변(median 1,700자)이 섞인 이봉 분포입니다.
- 후보들은 단봉 분포입니다: MS MARCO segment median 898자(직접 표본), Sherlock 666~1,426자(표본), DBpedia 351자, Wikipedia 2023-11 en 281자.
- 제안(설계 판단이며 데이터 사실은 아님): DB I/O 에뮬레이션에서는 텍스트와 벡터의 의미가 일치하지 않아도 되므로, payload 텍스트를 우리 채팅 길이 분포에 맞게 재샘플링하거나 잘라서 넣는 방안을 검토할 만합니다.

**벡터 단위 불일치**
- amkdg는 대화 전체 또는 청크, Zenodo는 논문 전체, 나머지는 passage 단위입니다. 메시지 단위로 저장하는 MemMachine과는 모두 다릅니다.

**질의 비대칭**
- Qwen3와 arctic 모델은 질의에 prefix나 prompt를 붙여야 합니다. 문서 벡터를 떼어 질의로 쓰면 실제 검색 분포와 달라집니다.
- 기존 GT는 대부분 전체 코퍼스와 특정 벡터 공간 기준이므로, 부분집합이나 절단된 차원에서는 다시 계산해야 합니다.

**미확인으로 남은 항목**
- Pes2o-VE의 파일 구조, 텍스트 포함 여부, GT 공개 여부
- Snowflake와 Cohere 샤드 03번 이후의 정렬
- Sherlock의 폴더별 jsonl과 npy 대응(첫 id 이후)
- 저장된 벡터를 MRL로 절단했을 때의 품질(Sherlock, amkdg NVFP4)
- Qdrant 100K 저장소들의 prefix 관계
- jaitrychroma의 모델
- Snowflake m-v2.0의 차원과 전체 행 수
- very-large 계열 조사 원문 중 잘린 뒤쪽 후보들(수신하지 못함)

**근거에서 뺀 주장**
- peS2o "308 GB"
- ResearchGate의 Pes2o-VE figure
- "VIBE 카드에 텍스트가 없다고 적혀 있다"(카드 문구가 아니라 구조로 추론한 것)
- Semantic Scholar specter_v2 768차원(1차 페이지에 없음)
- rag-repo.org의 "Available" 표시