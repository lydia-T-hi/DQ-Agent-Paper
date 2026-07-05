# 유사 논문 조사 및 선행연구 절 초안 — 2026-07-05

> 조사 방법: 웹 검색으로 링크·서지 검증 (2026-07-05 기준). 요약문은 초록/검색 결과 수준 —
> **본문 인용 전 원문 PDF 정독 필수** (특히 ★ 표시는 우리 논문과 직접 경쟁/비교 대상).
> 본 논문 주제: 결정론 선처리 + 선택적 LLM 라우팅 + 이종 모델 검증의 비용-효율 DQ 파이프라인.

---

## 1. 유사 논문 목록 (주제 축별)

### 축 A — 규칙·학습 기반 오류 탐지/정정 (비LLM 베이스라인 계열)

| 논문 | 출처 | 링크 | 본 논문과의 관계 |
|---|---|---|---|
| ★ **Raha: A Configuration-Free Error Detection System** (Mahdavi et al.) | SIGMOD 2019 | [PDF](http://raulcastrofernandez.com/papers/raha.pdf) · [GitHub](https://github.com/BigDaMa/raha) | E2 벤치마크(Hospital/Flights) 출처. 다중 탐지 전략 앙상블 + 소량 라벨. 비LLM 최강 베이스라인 위치 |
| **Baran: Effective Error Correction via a Unified Context Representation and Transfer Learning** (Mahdavi & Abedjan) | PVLDB 13(11), 2020 | [ACM DL](https://dl.acm.org/doi/10.14778/3407790.3407801) | 오류 '정정' 대응물 — 2B의 corrected_value 제안과 비교 지점 |
| **HoloClean: Holistic Data Repairs with Probabilistic Inference** (Rekatsinas et al.) | PVLDB 10(11), 2017 | [arXiv](https://arxiv.org/abs/1702.00820) | 규칙·통계 신호의 확률적 통합 — 우리 Stage 4 합의의 고전적 선례 |

### 축 B — LLM 기반 데이터 정제 (직접 경쟁 계열)

| 논문 | 출처 | 링크 | 본 논문과의 관계 |
|---|---|---|---|
| ★ **Can Foundation Models Wrangle Your Data?** (Narayan et al.) | PVLDB 16(4), 2022 | [arXiv](https://arxiv.org/abs/2205.09911) · [PVLDB](https://www.vldb.org/pvldb/vol16/p738-narayan.pdf) | LLM few-shot이 오류 탐지·매칭에서 SOTA 가능함을 최초 체계 제시. 단, 전 레코드 호출 비용 미해결 — **우리의 공백 지점** |
| ★ **ZeroED: Hybrid Zero-shot Error Detection through LLM Reasoning** | arXiv 2025 | [arXiv](https://arxiv.org/abs/2504.05345) | LLM 추론+경량학습 하이브리드 오류 탐지 — 최신 직접 경쟁. 비용 계측·구성별 한계효용 분석 없음 (차별점) |
| **Jellyfish: A Large Language Model for Data Preprocessing** (Zhang et al.) | EMNLP 2024 | [arXiv](https://arxiv.org/abs/2312.01678) · [ACL](https://aclanthology.org/2024.emnlp-main.497/) | 로컬 소형 LLM 튜닝으로 전처리 — 비용 절감의 '모델 축소' 접근 (우리는 '호출 최소화' 접근) |
| **IterClean: An Iterative Data Cleaning Framework with LLMs** (Ni et al.) | 2024 | (원문 링크 미확정 — 확인 필요) | 반복적 탐지-정정 루프 — 파이프라인 구조 비교 대상 |
| **CleanAgent** (Qi & Wang) / **AutoDCWorkflow** | 2024 | [AutoDCWorkflow arXiv](https://arxiv.org/html/2412.06724v1) | LLM 에이전트로 정제 워크플로 자동 생성 — 멀티에이전트 관점의 이웃 연구 |
| **Exploring LLM Agents for Cleaning Tabular ML Datasets** | arXiv 2025 | [arXiv](https://arxiv.org/abs/2503.06664) | LLM 에이전트 정제 실증 — 관련연구 최신 항목 |

### 축 C — LLM-as-a-Judge와 이종 모델 검증 (3A Validator 근거)

| 논문 | 출처 | 링크 | 본 논문과의 관계 |
|---|---|---|---|
| ★ **Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena** (Zheng et al.) | NeurIPS 2023 D&B | [arXiv](https://arxiv.org/abs/2306.05685) · [NeurIPS](https://neurips.cc/virtual/2023/poster/73434) | GPT-4 심판의 인간 일치 80%+ 실증 + 위치·장황·자기선호 편향 보고 — Judge 유효성과 한계의 동시 근거 |
| ★ **LLM Evaluators Recognize and Favor Their Own Generations** (Panickssery et al.) | NeurIPS 2024 | [arXiv](https://arxiv.org/abs/2404.13076) | 자기인식-자기선호 선형 상관 실증 — **2B(Claude)↔3A(GPT) 이종 검증 설계의 직접 근거** |

### 축 D — LLM 비용 효율화 (CEI 지표의 이론적 이웃)

| 논문 | 출처 | 링크 | 본 논문과의 관계 |
|---|---|---|---|
| ★ **FrugalGPT: How to Use LLMs While Reducing Cost and Improving Performance** (Chen, Zaharia & Zou) | arXiv 2023 / TMLR 2024 | [arXiv](https://arxiv.org/abs/2305.05176) · [TMLR PDF](https://lingjiaochen.com/papers/2024_FrugalGPT_TMLR.pdf) | LLM 캐스케이드로 비용 80%↓ — '싼 판단을 먼저, 비싼 판단은 선택적으로'의 일반형. 우리 2A→2B 라우팅은 이를 DQ 도메인에 결정론 단계로 특수화한 것 |

### 축 E — 벤치마크 오염 (E2 해석의 방법론적 단서)

| 논문 | 출처 | 링크 | 본 논문과의 관계 |
|---|---|---|---|
| **NLP Evaluation in Trouble: On the Need to Measure LLM Data Contamination for each Benchmark** (Sainz et al.) | EMNLP 2023 Findings | [ACL](https://aclanthology.org/2023.findings-emnlp.722/) · [arXiv](https://arxiv.org/abs/2310.18018) | 오염 수준 정의·측정 촉구 — E2 F1을 "상한 추정치"로 보고하는 우리 프로토콜의 인용 근거 |

---

## 2. 선행연구 절 문장 초안 (국문, 인용표기는 서식 확정 후 치환)

### 2.1 규칙·학습 기반 오류 탐지

> 정형 데이터의 오류 탐지는 무결성 제약과 통계적 신호를 결합하는 접근이 주류를
> 이루어 왔다. HoloClean은 제약·외부지식·통계를 확률 그래프 모델로 통합하여 확률적
> 복구를 수행하였고[Rekatsinas et al., 2017], Raha는 다수의 탐지 전략을 특징으로
> 삼아 소량의 사용자 라벨만으로 분류기를 구성하는 설정 불필요(configuration-free)
> 탐지를 제안하며 Hospital, Flights 등 표준 벤치마크를 확립하였다[Mahdavi et al., 2019].
> 후속 연구인 Baran은 오류 문맥의 통합 표현과 전이학습으로 정정(correction)까지
> 확장하였다[Mahdavi & Abedjan, 2020]. 이들 접근은 라벨 효율성을 크게 개선했으나,
> 도메인마다 탐지 전략·라벨을 재구성해야 하고 의미 수준의 오류 해석은 여전히
> 인간의 몫으로 남는다.

### 2.2 LLM 기반 데이터 정제

> Narayan 등은 대형 언어모델의 few-shot 프롬프팅만으로 오류 탐지·엔티티 매칭 등
> 데이터 랭글링 과업에서 당시 최고 수준의 성능이 가능함을 처음 체계적으로
> 보였다[Narayan et al., 2022]. 이후 로컬 소형 모델을 전처리 전용으로 튜닝하는
> Jellyfish[Zhang et al., 2024], LLM 추론과 경량 학습을 결합한 zero-shot 오류 탐지
> ZeroED[Ni et al., 2025], 정제 워크플로 자동 생성 에이전트[Qi & Wang, 2024; Lan et
> al., 2024] 등 LLM 중심 정제 연구가 빠르게 확장되고 있다. 그러나 이들 연구는
> 대체로 전 레코드를 LLM에 노출하는 것을 전제하거나, 호출 비용을 성능과 함께
> 통제된 지표로 보고하지 않는다. 표 단위 실무 데이터에서 토큰 비용은 도입 여부를
> 결정하는 일차 제약이라는 점에서, 탐지 성능과 비용의 한계 효용을 구성 단위로
> 분해·측정하는 연구는 드물다.

### 2.3 LLM 판단의 검증: 이종 모델 Judge

> LLM을 평가자로 쓰는 LLM-as-a-Judge 패러다임은 강한 모델이 인간 선호와 80% 이상
> 일치함이 확인되며 빠르게 확산되었으나, 같은 연구에서 위치 편향·장황함 편향과 함께
> 자기 출력 선호(self-enhancement) 편향이 보고되었다[Zheng et al., 2023]. Panickssery
> 등은 LLM이 자기 출력을 식별하는 능력과 자기선호 강도 사이의 선형 상관을 실증하여,
> 동일 모델에 의한 자기 검증의 구조적 한계를 보였다[Panickssery et al., 2024]. 본
> 연구가 탐지자(Claude)와 검증자(GPT)를 서로 다른 모델 계열로 분리하는 이종 모델
> 교차검증을 채택하는 것은 이러한 자기선호 편향을 설계 수준에서 회피하기 위함이다.

### 2.4 LLM 비용 효율화

> LLM 추론 비용을 통제하는 일반 전략으로 Chen 등은 프롬프트 적응, 근사, 그리고 저비용
> 모델을 먼저 시도하고 필요 시에만 고비용 모델로 승급하는 캐스케이드를 제시하여 GPT-4
> 대비 최대 98%의 비용 절감을 보고하였다[Chen et al., 2023]. 본 연구의 2단계 라우팅 —
> 결정론적 규칙이 처리 가능한 셀을 선처리하고 통계적으로 모호한 셀만 LLM에 위임 —
> 은 캐스케이드의 첫 단을 '무비용 결정론 단계'로 대체한 도메인 특수화로 볼 수 있으며,
> 구성별 증분 비용 대비 성능 이득(CEI)을 사전 등록된 지표로 보고한다는 점에서
> 기존 LLM 정제 연구와 구별된다.

### 2.5 벤치마크 오염 (E2 해석 단서용)

> 한편 공개 벤치마크는 LLM 사전학습에 포함되었을 가능성이 있어, Sainz 등은 벤치마크별
> 오염 수준의 측정과 보고를 촉구한 바 있다[Sainz et al., 2023]. 본 연구는 이를 수용하여
> 값 자체가 실험 시점에 생성되어 오염이 원천 불가능한 합성 데이터를 주실험으로 삼고,
> Hospital·Flights 등 공개 벤치마크 결과는 오염 가능성을 명시한 상한 추정치로만 보고한다.

---

## 3. 후속 작업

- [ ] ★ 5편 원문 PDF 정독 (Raha, Narayan, ZeroED, Zheng, Panickssery, FrugalGPT)
- [ ] IterClean 원문 링크 확정 (검색 결과 서지 불완전)
- [ ] KCI 국내 선행연구 검색 (데이터 품질 + LLM 국문 문헌 — 국문지 투고 시 필요)
- [ ] 인용 서식(번호/저자-연도)을 투고 학회지 규정으로 확정 후 위 초안 치환
- [ ] 04/05 문서의 인용 지점(LLM-as-a-Judge, Raha 벤치마크)과 본 초안 연결
