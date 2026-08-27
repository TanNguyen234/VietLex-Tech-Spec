# Supabase full-document export

This lane copies a bounded set of full legal documents from the local SQLite/Zstandard store. It does not change the production retrieval source.

1. Set server-only `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`.
2. Run `python run_supabase_full_doc_upload.py --print-schema` in an authorized SQL editor. The schema enables RLS and creates no anonymous write policy.
3. Run `python run_supabase_full_doc_upload.py --check-connection`.
4. Run a bounded upload, for example `python run_supabase_full_doc_upload.py --max-documents 50000 --batch-size 50 --allow-remote-write`.
5. Preserve the checkpoint outside Git and verify remote row counts and sampled `content_sha256` values before making any runtime-storage decision.

The publishable key cannot authorize this backend write. Never log or commit either credential.
