# Deployment contract

Vercel is only the public HTTP gateway. `api/proxy.py` requires `BACKEND_ORIGIN` and forwards traffic to a persistent FastAPI origin; it does not contain the legal corpus or run persistent RAG workers.

The FastAPI origin requires:

- the local SQLite/Zstandard content store and SQLite FTS files mounted at `CONTENT_STORE_PATH` and `LEGAL_FTS_PATH`, until a separately verified remote full-text adapter is approved;
- Pinecone and Qdrant credentials for the configured production retrieval path;
- Google Cloud ADC or a configured generation fallback for live answers;
- MongoDB when session/history persistence is required.

Deploy in this order: build the Docker image, mount/verify the two SQLite files, start the persistent origin, verify `/health/ready`, then set Vercel `BACKEND_ORIGIN`. Provider connectivity belongs in a bounded administrative diagnostic, not a paid call on every readiness probe.

The default production backend remains Pinecone v1 plus local FTS. Vertex/Qdrant v3 can be selected explicitly by offline evaluation and can run as `VERTEX_QDRANT_SHADOW_ENABLED=true`; shadow results never replace production evidence.
