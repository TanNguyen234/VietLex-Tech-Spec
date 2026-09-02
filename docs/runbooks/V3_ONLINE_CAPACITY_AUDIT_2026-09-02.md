# V3 online capacity audit

Read-only audit time: `2026-09-02T00:39:33+07:00`.

## Scope and authority

The initial audit queried Qdrant collection metadata, cluster telemetry,
collection memory endpoints, MongoDB `dbStats`/`collStats`, and the supplied
Supabase PostgREST endpoint with a publishable key without mutations. After
explicit authorization, the same workstream created the Supabase schema/RLS
policy and uploaded the exact 4,969-document v3 set. It did not delete, optimize,
resize, or snapshot provider resources. No credentials or document contents
were recorded in this report.

V3 legal evidence is stored in Qdrant. MongoDB stores application/session data
and is not a v3 legal-corpus store. Vercel runs the online-only SSR function and
does not provide durable corpus storage.

## Golden-50 online dependency audit

The run name suffix `online-vercel` is potentially misleading. The immutable
commands show that both evaluations were local CLI processes; they did not send
the 50 questions through the public Vercel `/chat` endpoint. “Online” means the
retrieval/generation providers were remote while the case/label JSON and runner
were local.

Observed and source-validated dependencies were:

| Stage | Actual dependency | Evidence boundary |
| :--- | :--- | :--- |
| Cases and gold labels | Repository JSON files | Local files, not an online database |
| Dense query embedding | Configured Vertex `gemini-embedding-2` | Required by the selected backend code; the run artifact does not retain per-call embedding provider receipts |
| Sparse query encoding and RRF | Local Python code | No remote storage |
| Retrieval | Qdrant `vietlex-legal-rag-v3-vertex-1024` | 50/50 cases; 1,200 traced structural candidates identify source `vertex-qdrant-v3` |
| Answer generation | Google Vertex AI `gemini-3.5-flash` | Observed success in 50/50 case records |
| Input/output guardrails | Local NeMo orchestration with Vertex-primary adapter | 50/50 safe at both stages; artifacts do not persist the observed guardrail provider/fallback identity |
| Ragas judge | Google Vertex AI `gemini-3.5-flash` | Observed in 50/50 case records; same model identity as generation |

Every retrieval case had empty Pinecone and local-FTS lanes, the effective
fallback backend was `null`, and no retrieval or answer technical errors were
recorded. Supabase, MongoDB, Pinecone, local FTS/content store, and the Vercel
HTTP application were **not data or execution dependencies of this Golden-50
run**. The run therefore demonstrated an online Vertex/Qdrant data path, not a
Qdrant/Supabase relational architecture and not an end-to-end 50-request Vercel
benchmark.

## Qdrant observed state

All four collections were `green` on one active peer running Qdrant `1.18.3`.

| Collection | Role | Points | Disk bytes | Decimal GB |
| :--- | :--- | ---: | ---: | ---: |
| `vietlex-legal-rag-v3-vertex-1024` | Active v3 evidence | 51,801 | 467,141,359 | 0.467 |
| `vietlex-legal-rag-v2-pilot-384` | Retained v2 pilot | 134,334 | 681,771,147 | 0.682 |
| `vietlex-embedding-staging` | Legacy/free inference staging | 2,049 | 138,520,365 | 0.139 |
| `vietlex-rerank-staging` | Legacy/free rerank staging | 0 live points | 371,532,538 | 0.372 |
| **Total** | Shared cluster | **188,184 live points** | **1,658,965,409** | **1.659** |

The empty rerank staging collection still occupies disk because its retained
segments contain historical/deleted multivectors and indexes. Reclaiming that
space requires a separately authorized destructive operation; a zero live-point
count is not evidence that deletion is automatically safe.

The collection memory endpoint reported about 28.5 MB non-evictable RAM and
328.0 MB cached pages across the four collections. Current disk capacity, not
resident RAM, is therefore the first sizing constraint for this expansion.

The data-plane API does not expose the Qdrant Cloud billing tier or tenant disk
ceiling. The observed single-node topology and retained project evidence are
consistent with Free Tier, but this is not management-plane proof. Current
Qdrant documentation gives Free Tier 1 GB RAM, 0.5 vCPU, and 4 GB disk. All
capacity numbers below are therefore conditional on that 4,000,000,000-byte
ceiling. Confirm the Cloud Console tier before any write.

## V3 growth estimate

An exhaustive payload-only live scroll reconfirmed exactly 4,969 unique
document IDs and 51,801 points, or 10.4248 points/document. Its observed total
disk ratio is about 9,018 bytes/point or 94,011 bytes/document. The live
distribution has median 10 and p95 16 chunks/document. One retained
anchor/preflight document has 931 records, so the existing collection itself is
not globally capped at 16. The proposed migration must explicitly enforce
`--max-chunks-per-document 16` together with its hard point cap; the conservative
column below is valid only under that write contract.

Following Qdrant's capacity guidance, the safe budget below keeps 20% of the
4 GB disk free for WAL, temporary optimizer segments, and operational headroom.

| Scenario | Additional v3 documents at current average | Additional v3 documents if every document reaches 16 chunks |
| :--- | ---: | ---: |
| Preserve every current collection; stop at 80% disk | **16,392** | **10,680** |
| Preserve every current collection; consume disk to 100% | 24,901 | 16,224 |
| Retire v2 plus both staging collections; stop at 80% disk | 29,069 | 18,940 |

The 100% figures are a mathematical ceiling, not an operational recommendation.
They leave no safe room for optimization, WAL, or variance in document length.

### Recommended approval unit

Approve at most **10,000 additional documents** while preserving all current
collections, then stop, let Qdrant optimize, re-run the memory/disk audit, verify
unique document IDs and point counts, and run a bounded retrieval regression.

At the observed average, that batch is estimated to bring total cluster disk to
about 2.599 GB (65.0%). At the configured 16-chunk worst case, it is estimated
at about 3.102 GB (77.5%). This stays within the 20% headroom target under both
models, subject to Cloud Console confirmation of the 4 GB tier.

Retiring `vietlex-legal-rag-v2-pilot-384` and the two staging collections could
reclaim about **1.192 GB**, but deletion would remove retained evaluation and
legacy/free runtime infrastructure. It requires a separate explicit approval
that names the collections; it is not part of the recommended first batch.

A complete 518,255-document v3 corpus does not fit this tier. Extrapolating the
observed v3 ratio gives roughly 49 GB before operational headroom and about
58 GB with 20% planning headroom, before allowing for a different document-length
mix. Full-corpus v3 therefore needs a paid, materially larger cluster and a new
migration/benchmark contract.

## MongoDB observed state

MongoDB `Legal-RAG` contained 7 collections and 111 objects:

- logical data: 33,420,999 bytes;
- indexes: 733,184 bytes;
- allocated collection storage: 24,936,448 bytes;
- 93 legacy rows in `raw_legal_documents` account for nearly all logical data;
- application collections contain only 18 current rows in total.

The database protocol does not expose the Atlas billing tier. If it is the
current 512 MB Free cluster, `dataSize + indexSize` is about 34.15 MB, roughly
6.4-6.7% of the tier depending on decimal/binary display. MongoDB does not limit
the proposed v3 document expansion because the active v3 corpus is not written
there. Do not copy full legal documents into MongoDB as part of a Qdrant v3
expansion without a separate storage design and authorization.

## Supabase relational state

The initial read-only audit returned `404 PGRST205` for
`public.legal_documents`. Later on 2026-09-02, the repository-generated schema
was executed through the authenticated Supabase SQL Editor. The table, its
document-number and content-hash indexes, and RLS now exist. A server-side REST
connection check returned HTTP 200. The exact 4,969-document bundle represented
by Qdrant v3 was then uploaded with a resumable checkpoint. Server-side and
publishable-key exact counts both returned **4,969 rows**; sampled IDs `2143`,
`14288`, and `431147` matched their local `content_sha256` values. The online-only
application now uses this table for legal search and full-document pages; chat
retrieval remains independent and reads evidence directly from Qdrant payloads.

The publishable and server-only service-role credentials are stored under their
distinct names in the Git-ignored local environment. RLS policy
`legal_documents_public_read` grants `SELECT` to `anon` and `authenticated`, and
a publishable-key REST request returned HTTP 206 with the exact 4,969-row count.
No anonymous write policy exists; backend ingestion continues to require
server-only authority.

Current Supabase Free Plan documentation specifies 500 MB database size per
project and read-only mode after exceeding that quota. The pinned corpus contains
10,672,662,244 uncompressed content bytes (2,507,228,225 bytes in the local
Zstandard store) before PostgreSQL row/index overhead. Consequently the full
518,255-document relational corpus cannot fit a Free project. After the 4,969-row
upload, `pg_database_size` was **58,895,507 bytes** and
`pg_total_relation_size('public.legal_documents')` was **48,340,992 bytes**,
including **983,040 bytes** of indexes. The observed relation cost is about
9,729 bytes per document. A linear estimate leaves room for roughly 29,900 more
documents at a conservative 350 MB database soft ceiling, but Qdrant capacity
remains the tighter preserve-all constraint and the estimate must be remeasured
after every batch.

## Approval boundaries

This audit records the completed schema/RLS setup and 4,969-document upload. A
later expansion approval must specify:

1. the maximum additional document count;
2. whether all current collections must be preserved;
3. the selection policy for new documents;
4. the allowed Vertex embedding spend/quota;
5. the required post-upload retrieval evaluation and rollback evidence.

Recommended decision: approve a resumable **10,000-document, preserve-all** v3
expansion, with a hard point cap of 160,000 new points and a mandatory capacity
re-audit before any subsequent batch.

## External references

- Qdrant Free Tier and cluster resources: <https://qdrant.tech/documentation/cloud/create-cluster/>
- Qdrant capacity planning and 20% headroom: <https://qdrant.tech/documentation/capacity-planning/>
- Qdrant collection memory endpoint: <https://qdrant.tech/documentation/ops-monitoring/memory-usage/>
- MongoDB Atlas current Free/Flex storage: <https://www.mongodb.com/pricing>
- MongoDB storage-limit accounting: <https://www.mongodb.com/docs/atlas/reference/faq/storage/>
- Supabase plan database limits: <https://supabase.com/pricing>
- Supabase database size and read-only behavior: <https://supabase.com/docs/guides/platform/database-size>
