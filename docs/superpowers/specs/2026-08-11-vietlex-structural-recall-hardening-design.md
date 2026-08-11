# VietLex Structural Recall Hardening Design

**Status:** Approved by the user's 2026-08-11 direction to reduce corpus scope when needed and prioritize recall close to 1.0.
**Scope:** P3 Qdrant structural pilot only. No production cutover and no remote execution by Codex.

## 1. Evidence and problem statement

The reproducible P2 benchmark scored Document Recall@24 `0/53`. The two verified
documents never entered any source lane, so reranker quality was not measurable;
the reranker cannot recover candidates it never receives.

The local structural audit proves that the independently selected primary-law
scope contains:

- 827 documents selected only by legal type: `Hiến pháp`, `Luật`, `Pháp lệnh`;
- 134,334 immutable article/clause records;
- all 40 `all-required-verified` cases and all 53 required evidence items;
- no synthetic or remotely fetched corpus content.

The current model probe is not a trustworthy discrimination test. It uploads only
records that already match verified evidence. Most records come from the two gold
documents, so a high top-k score can be obtained without ranking against the other
825 documents. The embedding input is also only `record.body`; it omits the title,
document number, legal type, citation, and structural heading already present in
the pinned corpus.

## 2. Considered approaches

### A. Harden the 827-document structural pilot — selected

Keep direct article/clause points, enrich the indexed text, and test against real
hard negatives from the entire 827-document scope. This maximizes the chance of
both document and structural recall while remaining capacity-bounded.

### B. Reindex all 518,255 documents as one point per document

This fits more easily than full structural indexing but weakens Article/Clause
retrieval and adds a second local selection bottleneck. It is deferred because the
user explicitly permits scope reduction in exchange for recall quality.

### C. Reindex all 518,255 documents structurally

Rejected. Extrapolating the measured pilot density produces about 84.2 million
points. That is incompatible with the Qdrant free cluster's 4 GB disk and 1 GB RAM.

## 3. Corpus and anti-overfit contract

Corpus selection remains independent of the evaluation set. Production code must
select all and only the three pinned primary legal types from the local content
store in stable document-ID order. Gold labels may select evaluation queries and
relevant rows, but may never decide which corpus documents exist in the index.

The bounded pre-upload model probe contains:

1. every real structural record needed to resolve the 40 verified cases;
2. one deterministic real hard-negative record from every non-gold document;
3. deterministic title canaries sampled across legal types and document-ID ranges.

Hard negatives and canaries are derived from the pinned 827-document scope, never
invented. Their record IDs, query IDs, hashes, sampling algorithm version, counts,
and per-legal-type coverage are persisted in the immutable probe report.

## 4. Embedding input contract

Stored evidence bodies remain byte-for-byte unchanged. Dense and BM25 inference
use a versioned, deterministic document text composed of:

```text
Tiêu đề: <title>
Số văn bản: <document_number>
Loại văn bản: <legal_type>
Cấu trúc: <heading_path or citation>
Trích dẫn: <citation>
Nội dung:
<body>
```

Blank optional fields are omitted. The builder normalizes whitespace but does not
summarize, translate, or call a model. The SHA-256 of this exact inference text is
stored in payload and verified on readback. The contract version is bound into the
plan, checkpoint, model probe, upload, finalize, verify, and benchmark artifacts.

Queries keep the current Vietnamese legal retrieval instruction for dense search.
BM25 receives the raw normalized query without the dense instruction.

## 5. Provider and dimension policy

Only Qdrant Cloud Inference models marked free in the user's Qdrant Console are
eligible for the default workflow. There is no local embedding fallback and no
mandatory Pinecone inference comparison. An existing immutable reference artifact
may be audited separately, but the default model probe performs no Pinecone calls.

Live raw-upsert probes established that Qwen is unsupported and the tested
512/768/1024d candidates are either unsupported or not allowed on the free tier.
The verified free multilingual candidate is
`intfloat/multilingual-e5-small` at 384d. It is stored in the separate
`vietlex-legal-rag-v2-pilot-384` collection; the empty 1024d attempt is never
reused with an incompatible schema. The model remains only a candidate until the
Vietnamese legal probe passes every absolute recall gate; dimension and provider
acceptance alone are not quality evidence.

Qdrant documents a free cluster as 1 GB RAM, 0.5 vCPU, and 4 GB disk, approximately
capable of one million 768d vectors. This is only sizing guidance. The existing
conservative estimator plus observed current disk usage must still produce
`PASS_CAPACITY`; otherwise create/upload remains blocked.

## 6. Remote workflow and performance

Remote phases remain explicit and artifact-bound:

`audit -> plan -> create -> probe-model -> upload -> finalize -> verify -> benchmark`

- Create uses a new pilot collection and never deletes or overwrites v1. A later
  immutable plan may adopt that collection only if complete readback proves it
  is empty and schema-exact; adoption emits `ADOPTED_EMPTY` evidence.
- Upload starts with HNSW `m=0`, on-disk vectors/payload, and one shard.
- Streaming batches use adaptive batch size and bounded concurrency.
- Checkpoint identity is record ID plus body hash plus inference-text hash.
- A batch is committed only after exact server acknowledgement and model-usage
  validation; resume skips only identities already acknowledged under the same
  source/model/text contract.
- Finalize enables on-disk HNSW and waits for green optimizer/readback status.
- Verification checks schema, exact count, deterministic samples, payload hashes,
  inference-text hashes, dense shape/finite values, and nonempty sparse vectors.
- No phase silently deletes, recreates, or cleans a remote collection.

Remote phases execute only under explicit authority and stop at the first failed
capacity, model, provenance, or quality gate.

## 7. Retrieval and evaluation

Runtime pilot retrieval keeps concurrent dense, BM25, and exact-reference lanes,
deterministic RRF, per-document caps, bounded reranking, and direct structural
evidence. Every lane persists ranks, scores, latency, provider usage, and typed
technical errors.

Model-probe gates:

- verified-case dense Document Recall@10 = 1.0;
- verified structural Recall@10 >= 0.95;
- title-canary Document Recall@10 >= 0.90;
- all probe vectors and payload hashes pass readback;
- zero technical errors and zero unexpected points.

Final benchmark gates on the exact 40-case P2 denominator:

- fused Document Recall@24 = 1.0;
- fused Article Recall@24 >= 0.95 where applicable;
- fused Clause Recall@24 >= 0.90 where applicable;
- all-required evidence coverage >= 0.95;
- no-candidate, retrieval-error, and reranker-error rates are all 0;
- reranker contribution is reported as before/after metrics, never inferred.

Failure to meet a quality threshold returns `FAIL_QUALITY`; provenance, capacity,
or provider failures return a typed blocked status. Neither status authorizes a
cutover or a fabricated claim that recall is approximately 1.

## 8. Non-goals

- no full 518,255-document reindex in this phase;
- no Pinecone/Qdrant deletion or migration;
- no production retriever cutover;
- no generation, Ragas, guardrail, or paid evaluator calls;
- no claim that 40 verified cases represent whole-corpus legal accuracy.

## 9. Primary references

- Qdrant free-cluster resources and sizing: https://qdrant.tech/documentation/cloud/create-cluster/
- Qdrant Cloud Inference and free-model labels: https://qdrant.tech/documentation/cloud/inference/
- Qdrant quantization/storage trade-offs: https://qdrant.tech/documentation/manage-data/quantization/
- Qwen3 Embedding dimensions, MRL, and instructions: https://github.com/QwenLM/Qwen3-Embedding
