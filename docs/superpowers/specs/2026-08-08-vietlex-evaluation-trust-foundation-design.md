# VietLex Evaluation Trust Foundation Design

**Ngày:** 2026-08-08

**Trạng thái:** Thiết kế đã được người dùng duyệt trong conversation; chờ review bản ghi trước khi lập implementation plan

**Phạm vi:** P0 — Evaluation Trust Foundation

**Repository HEAD khi audit:** `4e40be6ab1871e3b64ca6f560f317bed215e05e1`

## 1. Bối cảnh và kết luận audit

VietLex là hệ thống Vietnamese Legal RAG trên corpus được pin gồm 518.255 văn bản. Kiến trúc hiện tại dùng Pinecone làm durable hybrid vector store, SQLite/Zstandard làm full-text content store, SQLite FTS cho document-number/title lookup, Qdrant Cloud cho dense inference và primary ColBERT reranking, cùng Pinecone reranker làm fallback.

Ưu tiên hiện tại không phải thêm tính năng hay thay model. Ưu tiên là thiết lập một chuỗi bằng chứng đo lường được và tái lập được:

`verified gold -> provider-free preflight -> clean retrieval run -> deterministic stage metrics -> deterministic answer metrics -> reproducible report`

Summary đầu vào mô tả đúng phần lớn lịch sử và kiến trúc nhưng dừng tại commit `0bd51e8`. Audit trên HEAD hiện tại xác nhận:

- working tree sạch và đồng bộ `origin/main` tại thời điểm audit;
- local pytest đạt `140 passed, 1 skipped`, trong đó test bị skip là live-provider test;
- focused evaluation/retrieval tests đạt `34 passed`;
- CI lint gate hiện thất bại với 9 lỗi Ruff;
- sidecar hiện có 420 cases, 483 evidence items và 0 verified evidence items;
- baseline ngày 2026-08-03 vẫn invalid cho decision-making;
- nhiều runtime defects đã được sửa trong code nhưng regression coverage tương ứng chưa được khôi phục;
- stage aggregation và reporter đang dùng các schema không khớp nhau;
- legacy evaluation command trong README vẫn bật Ragas mặc định, trái evaluation policy;
- preflight artifact hiện tại vẫn chứa absolute Windows paths và không chứng minh trạng thái HEAD sạch hiện tại.

Do đó P0 chưa hoàn tất dù test suite hiện tại xanh.

## 2. Mục tiêu

P0 xây dựng nền evaluator mà các phase sau có thể tin cậy. P0 hoàn tất khi:

1. Default evaluation path thực hiện 0 LLM judge calls.
2. Runtime runner, retriever, reranker và metrics dùng cùng một contract được strict tests bảo vệ.
3. Mỗi metric có numerator, denominator, coverage, skipped cases và skip reasons phù hợp.
4. Stage metrics phản ánh đúng configured capacity, candidate counts và evidence survival ở từng level.
5. Reporter chỉ đọc một aggregate schema đã được test end-to-end.
6. Full working-tree provenance và source-code fingerprint được ghi riêng, không đánh đổi tính trung thực để lấy fingerprint ổn định.
7. Canonical artifacts là immutable, path trong artifact là repository-relative POSIX path.
8. Audit citation extraction và structural verification không tạo verified evidence từ hint chưa được chứng minh.
9. CI lint, focused tests, full pytest, compile và diff checks đều xanh.
10. Provider-free preflight chứng minh 0 provider calls và block đúng khi selected verified case count bằng 0.

P0 không nhằm làm retrieval quality tốt hơn. P0 chỉ làm cho phép đo đáng tin trước khi tối ưu retrieval.

## 3. Ngoài phạm vi P0

Các việc sau không thuộc P0:

- thay dense model, dimension, Pinecone metric hoặc embedding prefix;
- thay persistent sparse representation;
- rebuild/recreate Pinecone index hay Qdrant collections;
- full-corpus ingestion hoặc FTS rebuild;
- chạy live retrieval/answer benchmark;
- tự động gán `verified` cho gold labels;
- tối ưu retrieval limits, hybrid alpha hoặc reranker provider;
- production deployment, load testing hoặc frontend redesign;
- commit, push, PR hoặc remote mutation khi chưa có quyền riêng.

## 4. Kiến trúc delivery tổng thể

Project sẽ được hoàn thiện bằng gated vertical slices thay vì một mega-patch.

### Phase P0 — Evaluation Trust Foundation

Sửa contract, provenance, artifacts, deterministic metrics, reporting, default commands, tests và CI. Đây là phạm vi của design này.

### Phase P1 — Verified Gold Adjudication

Sinh adjudication queue bất biến cho khoảng 40 answerable cases, cân bằng factoid và multi-hop. Mỗi evidence item giữ candidate identities, anchors, Article/Clause, quyết định, confidence và notes. Không có label nào trở thành `verified` nếu không có evidence provenance.

### Phase P2 — Clean Retrieval Baseline

Chạy ba profile trên cùng clean code SHA, corpus revision, sidecar và selected case set. So sánh stage recall, MRR, nDCG, exact-reference hit, multi-hop coverage, latency và technical errors.

### Phase P3 — Evidence-Driven Retrieval Optimization

Mỗi experiment thay đúng một biến. Mọi provider switch dùng identical reranker inputs. Thay đổi ingestion contract chỉ được thực hiện sau migration plan và authorization riêng.

### Phase P4 — Answer and Guardrail Evaluation

Hoàn thiện deterministic answer metrics, expected number/date/entity labels, citation validity và guardrail `off`/`shadow`/`enforce`. Ragas chỉ là opt-in audit trên subset nhỏ.

### Phase P5 — Delivery Readiness

API integration, security, Docker, load tests, SLO/alerts và deployment verification. UI chỉ được đánh giá sau khi retrieval và answer quality có reproducible evidence.

Mỗi phase sau sẽ có design và implementation plan riêng. Kết quả đo của phase trước là input cho phase sau; không lập chi tiết optimization trước khi có baseline để tránh giả định và token rework.

## 5. Thiết kế P0 theo component

### 5.1 Regression contract layer

Các regression tests từng tồn tại nhưng đã bị xóa phải được khôi phục theo hành vi, không sao chép mù code lịch sử. Coverage bắt buộc gồm:

- `EvaluationProfile` immutable và đủ tám field độc lập;
- factory `get_legal_retriever()` và real `retrieve_detailed(query, sparse_query, *, profile)` contract;
- one retrieval per answer case;
- three-argument generation contract;
- reranker routing và `rerank_return_limit` qua Qdrant/Pinecone;
- run-directory overwrite protection;
- staged/tracked/untracked Git provenance;
- verified-only denominator;
- refusal and text metrics;
- rewrite call counts;
- input guardrail enforce rejection tạo 0 retrieval calls;
- default judge-free execution;
- network isolation cho unit/default evaluation paths.

Mocks ở boundary phải dùng `autospec` hoặc `spec_set` khi cần bắt signature. Test không được chỉ kiểm tra `hasattr`, tổng test count hoặc code path không có assertion về output/interaction.

### 5.2 Runtime retrieval evaluation contract

`evaluate_single_retrieval_case()` tiếp tục là adapter giữa `GoldenCase` và `LegalRetriever`. Adapter phải:

1. giữ original query cho sparse/exact-reference retrieval;
2. chỉ dùng rewritten query cho dense path khi profile bật rewrite;
3. truyền nguyên `EvaluationProfile` vào retriever;
4. build `RetrievalStageCapacities` từ effective profile và settings;
5. truyền stage trace và capacities vào metrics;
6. trả typed technical status khi rewrite/retrieval/reranker lỗi;
7. không biến technical errors thành `no_candidate` hoặc refusal.

Contract test sẽ gọi adapter với strict fake retriever và xác minh arguments, số lần gọi, stage trace và output ordering.

### 5.3 Provenance model

Provenance được tách thành hai khái niệm:

- **Working-tree provenance:** phản ánh trung thực toàn bộ tracked, staged và untracked state có liên quan. Generated evaluation artifacts không được làm `git_dirty=false` nếu Git thực tế coi chúng là thay đổi.
- **Source-state fingerprint:** hash ổn định cho code/config/test inputs, loại các output directories định nghĩa rõ như preflight/runs và không đọc hay ghi raw secrets.

Manifest phải lưu ít nhất:

- Git commit SHA;
- `git_dirty`, tracked/staged/untracked flags;
- full diff SHA-256 hoặc typed reason khi không tính được;
- source-state SHA-256;
- dataset revision và evaluation dataset SHA-256;
- sidecar SHA-256;
- selected case IDs SHA-256;
- configuration fingerprint;
- provider/model identifiers;
- metric/schema versions;
- exact command và UTC timestamp.

Git command failure không được bị nuốt thành một clean state giả. Nó phải sinh typed unavailable/error provenance.

### 5.4 Preflight artifact builder

Preflight được chia thành ba lớp:

1. **Pure validation:** load dataset/sidecar, validate exact case set, select cases, build profile configs và compute fingerprints.
2. **Pure payload construction:** tạo hoàn chỉnh batch payload trong memory; không shallow-copy nested dictionaries và không ghi file trong profile loop.
3. **Persistence:** ghi canonical artifacts sau khi toàn batch đã hợp lệ.

Batch payload có schema:

```json
{
  "meta": {},
  "case_selection": {},
  "profiles": {
    "legacy": {},
    "separated_no_intent": {},
    "separated_intent": {}
  }
}
```

Mọi profile dùng cùng dataset SHA, sidecar SHA, source-state fingerprint và selected case set. `canonical_artifact_path` là repository-relative POSIX path. Batch meta không chứa profile name của profile cuối.

Canonical writer không overwrite file đã tồn tại. Nếu rerun tạo cùng canonical identity, chương trình phải hoặc xác minh bytes giống hệt và reuse có ghi nhận, hoặc fail typed collision. Alias mutable như `latest_preflight.json` phải được tách rõ khỏi canonical artifacts và không được dùng làm audit evidence.

Preflight chạy trước mọi provider factory/call và ghi `provider_calls=0`. Với `--verified-only` và 0 selected cases, nó ghi artifact `BLOCKED` rồi exit non-zero mà không tạo live run directory.

### 5.5 Citation and gold audit contract

Hai citation parser hiện tại phải được hợp nhất thành một deterministic parser dùng chung. Parser tạo citation units theo thứ tự xuất hiện và hỗ trợ tối thiểu:

- một citation đầy đủ;
- hai document numbers khác nhau;
- nhiều Article/Clause dùng chung document number;
- Article/Clause không có document number;
- repeated citations và deterministic deduplication;
- không tạo Cartesian product giữa doc/article/clause lists.

Identity resolution chỉ thử doc ID hoặc URL khi input thật sự cung cấp hint đó. Khi dataset không có field tương ứng, audit ghi `not_applicable`; không tuyên bố hierarchy level đã được chạy.

Document verification cần resolved document identity và anchor evidence. Article/Clause verification cần matched structural chunk. Nếu không có structural chunk, status là unresolved/not-found tương ứng; regex hint không bao giờ được dùng làm verification evidence.

Audit generator không overwrite canonical sidecar/report. Một audit run mới phải dùng versioned/unique artifact path hoặc fail nếu target tồn tại.

### 5.6 Deterministic retrieval metric schema

Per-case metric result phải chứa:

- applicability và skip reason;
- applicable gold counts theo document/article/clause;
- matched counts và Recall@K;
- MRR theo level;
- nDCG@K với relevance definition được version hóa;
- exact legal-reference hit;
- all-required multi-hop coverage và partial-hop coverage;
- no-candidate, retrieval-error và reranker-error flags;
- stage metrics cho Pinecone, FTS, merged, resolved, structural, local, reranker input, reranker output và final evidence.

Mỗi stage metric chứa:

- configured capacity;
- observed candidate count;
- applicable gold numerator/denominator theo level;
- Recall@K và MRR theo level;
- null/skip reasons;
- first-loss information cho từng required evidence item.

Aggregate result phải chứa:

- macro values;
- micro numerators, denominators và ratios;
- total/scored/skipped cases và coverage;
- skip-reason counts;
- candidate distribution `min`, `mean`, `p50`, `p95`, `max`;
- no-candidate, retrieval technical-error và reranker technical-error rates kèm counts;
- stage-specific aggregates với cùng schema naming ổn định.

Document, article và clause dùng denominator riêng. Multi-hop coverage xét required evidence ở đúng required level; document-only required items không bị bỏ khỏi coverage chỉ vì không có article.

### 5.7 Reporter contract

Reporter chỉ tiêu thụ aggregate schema mới. Không có fallback âm thầm sang legacy key names. Schema mismatch phải fail test hoặc sinh typed report error, không render `N/A` như thể metric đơn thuần không áp dụng.

Golden report test dùng synthetic cases có known expected output để xác minh:

- top-level metric names;
- numerator/denominator/coverage;
- stage capacities;
- micro/macro values;
- candidate distributions;
- skip reasons và technical errors;
- no raw private content ngoài dữ liệu evaluation đã được phép.

### 5.8 Default entry points and documentation

Canonical commands là `run_retrieval_eval.py` và `run_answer_eval.py`. `run_eval_suite.py` phải được deprecate/delegate hoặc đổi default sao cho không gọi Ragas nếu người dùng không opt in.

README và current evaluation docs phải:

- đưa deterministic provider-free preflight lên trước;
- mô tả Ragas là optional audit;
- cảnh báo live provider cost/side effects;
- không coi historical invalid runs là baseline;
- không tuyên bố production-ready;
- phân biệt `PASS`, `BLOCKED`, `NOT RUN` và historical claims.

Các historical reports được giữ nguyên bytes khi preservation policy yêu cầu, nhưng current status document phải chỉ rõ chúng đã superseded hoặc invalid. Không chỉnh historical evidence để làm quá khứ trông nhất quán hơn.

### 5.9 CI and static verification

Ruff errors hiện tại phải được sửa tối thiểu, không dùng broad ignore để làm gate xanh. CI tiếp tục chạy provider-free unit tests. Python 3.10 CI compatibility phải được bảo vệ dù local audit dùng Python 3.12.4.

Static verification bắt buộc:

```text
python -m ruff check --select E4,E7,E9,F app/
python -m compileall -q app tests
git diff --check
```

## 6. Data flow sau P0

Provider-free preflight:

```text
dataset + sidecar + profiles + git/source provenance
    -> strict validation
    -> case selection
    -> in-memory three-profile payload
    -> immutable canonical artifacts
    -> BLOCKED when verified case count is zero
```

Live retrieval evaluation sau khi P1 có verified gold và có authorization:

```text
GoldenCase
    -> optional dense-query rewrite
    -> LegalRetriever.retrieve_detailed(original sparse query, effective profile)
    -> typed RetrievalOutcome + full stage trace
    -> offline deterministic per-case metrics
    -> typed aggregate schema
    -> immutable manifest/config/raw-results/report
```

Answer evaluation sau P4:

```text
Stage A online under semaphore
    -> input guardrail
    -> one retrieval
    -> generation
    -> output guardrail
    -> release semaphore
Stage B offline
    -> deterministic retrieval/answer metrics
    -> optional opt-in judge audit
    -> immutable artifacts
```

## 7. Error handling

Các trạng thái tối thiểu được phân biệt:

- `ok`;
- `no_candidate`;
- `retrieval_error`;
- `reranker_error`;
- `input_guardrail_rejected`;
- `input_guardrail_error`;
- `output_guardrail_rejected`;
- `output_guardrail_error`;
- `preflight_blocked`;
- `provenance_unavailable`;
- `artifact_collision`;
- `schema_error`.

Technical errors không được tính là hallucination, honest refusal hoặc zero-quality score mà không có denominator policy rõ ràng. Aggregate reports giữ error counts/rates riêng và không silently drop failed cases.

## 8. Test strategy và execution order

Implementation tuân theo TDD. Mỗi task là một independently reviewable behavior slice:

1. thêm/khôi phục failing tests cho đúng slice;
2. chạy focused test để xác nhận RED với failure mong đợi;
3. sửa tối thiểu;
4. chạy focused GREEN;
5. chạy broader relevant suite;
6. kiểm tra diff và review contract;
7. chỉ chuyển task khi gate đã đạt.

Không dùng tổng số pytest toàn repo để thay thế targeted assertions. Live provider tests không chạy trong P0. Test doubles chỉ nằm trong tests.

## 9. P0 acceptance gates

P0 chỉ được báo hoàn tất khi tất cả điều kiện sau đúng:

- mọi regression behavior liệt kê tại mục 5.1 có targeted tests;
- strict runner/retriever/reranker contract tests pass;
- synthetic metric fixtures chứng minh macro/micro numerator và denominator;
- reporter golden test pass và không đọc legacy keys;
- citation parser/audit negative tests pass;
- two-run source fingerprint stability test pass;
- working-tree dirty truthfulness test pass;
- canonical artifact collision/relative-path tests pass;
- provider-free preflight isolation test chứng minh 0 provider calls;
- default retrieval/answer CLI contract test chứng minh 0 LLM judge calls khi không truyền opt-in judge flag; live retrieval providers không được gọi trong P0 tests;
- `python -m pytest -q` pass với live test skipped theo policy;
- Ruff, compileall và `git diff --check` pass;
- provider calls: 0;
- remote data modified: no;
- ingestion/reindex/migration: not run;
- remaining limitations được ghi rõ, đặc biệt 0 verified gold nếu P1 chưa thực hiện.

P0 completion không đồng nghĩa retrieval quality đạt yêu cầu hay system production-ready.

## 10. Side-effect và approval gates

- Code/test/doc edits trong P0 nằm trong phạm vi đã duyệt.
- Commit, push, PR vẫn cần authorization riêng theo `AGENTS.md`.
- Live Pinecone/Qdrant/LLM calls cần authorization trước khi chạy P2/P4 benchmark.
- Gold label `verified` cần adjudication evidence; không được fabricate.
- Full ingestion, index/collection deletion/recreation và persistent embedding migration cần authorization cho đúng operation.

## 11. Audit trail của design

Các nguồn chính đã kiểm tra:

- `AGENTS.md`;
- `docs/PROJECT_CONTEXT.md`;
- `docs/AGENT_WORKFLOW.md`;
- `docs/CURRENT_ARCHITECTURE.md`;
- `app/config.py`;
- evaluation runners, schemas, metrics, reporting, audit script và affected tests;
- Git history từ `0bd51e8` đến `4e40be6`;
- current sidecar, summary và preflight artifacts;
- CRG graph được cập nhật tới HEAD và dùng cho change/test-impact analysis.

Các verification commands quan trọng:

```text
python -m pytest -q tests/test_evaluation_framework.py tests/test_defect_fixes.py tests/services/test_retrieval.py
python -m pytest -q
python -m ruff check --select E4,E7,E9,F app/
python -m compileall -q app tests
git diff --check
git status --short --branch
```

Kết quả audit trước implementation:

- focused tests: 34 passed;
- full tests: 140 passed, 1 skipped;
- Ruff: failed, 9 errors;
- compileall: passed;
- diff check: passed;
- provider calls: 0;
- remote data modified: no.
