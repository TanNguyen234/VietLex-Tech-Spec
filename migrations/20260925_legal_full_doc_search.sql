-- Uses the existing legal_documents.content; does not copy or publish passages.
-- Run each index statement separately; the Dashboard times out on one index
-- over all documents. Modulo shards cover every document ID exactly once.
-- Preflight database size and confirm Free headroom before each shard.
CREATE INDEX IF NOT EXISTS legal_documents_body_fts_v1_0 ON public.legal_documents USING gin
    (to_tsvector('public.vietlex_body_simple'::regconfig, content)) WITH (fastupdate=off)
    WHERE document_id % 8 = 0;
CREATE INDEX IF NOT EXISTS legal_documents_body_fts_v1_1 ON public.legal_documents USING gin
    (to_tsvector('public.vietlex_body_simple'::regconfig, content)) WITH (fastupdate=off)
    WHERE document_id % 8 = 1;
CREATE INDEX IF NOT EXISTS legal_documents_body_fts_v1_2 ON public.legal_documents USING gin
    (to_tsvector('public.vietlex_body_simple'::regconfig, content)) WITH (fastupdate=off)
    WHERE document_id % 8 = 2;
CREATE INDEX IF NOT EXISTS legal_documents_body_fts_v1_3 ON public.legal_documents USING gin
    (to_tsvector('public.vietlex_body_simple'::regconfig, content)) WITH (fastupdate=off)
    WHERE document_id % 8 = 3;
CREATE INDEX IF NOT EXISTS legal_documents_body_fts_v1_4 ON public.legal_documents USING gin
    (to_tsvector('public.vietlex_body_simple'::regconfig, content)) WITH (fastupdate=off)
    WHERE document_id % 8 = 4;
CREATE INDEX IF NOT EXISTS legal_documents_body_fts_v1_5 ON public.legal_documents USING gin
    (to_tsvector('public.vietlex_body_simple'::regconfig, content)) WITH (fastupdate=off)
    WHERE document_id % 8 = 5;
CREATE INDEX IF NOT EXISTS legal_documents_body_fts_v1_6 ON public.legal_documents USING gin
    (to_tsvector('public.vietlex_body_simple'::regconfig, content)) WITH (fastupdate=off)
    WHERE document_id % 8 = 6;
CREATE INDEX IF NOT EXISTS legal_documents_body_fts_v1_7 ON public.legal_documents USING gin
    (to_tsvector('public.vietlex_body_simple'::regconfig, content)) WITH (fastupdate=off)
    WHERE document_id % 8 = 7;

CREATE OR REPLACE FUNCTION public.legal_full_doc_coverage() RETURNS jsonb
LANGUAGE sql STABLE SECURITY INVOKER SET search_path=pg_catalog,public AS $$
    SELECT CASE WHEN (
        SELECT count(*) FROM pg_catalog.pg_index i
        JOIN pg_catalog.pg_class c ON c.oid=i.indexrelid
        WHERE c.relnamespace='public'::regnamespace
          AND c.relname IN (
            'legal_documents_body_fts_v1_0','legal_documents_body_fts_v1_1',
            'legal_documents_body_fts_v1_2','legal_documents_body_fts_v1_3',
            'legal_documents_body_fts_v1_4','legal_documents_body_fts_v1_5',
            'legal_documents_body_fts_v1_6','legal_documents_body_fts_v1_7')
          AND i.indisvalid AND i.indisready
    ) = 8 THEN jsonb_build_object(
        'document_count',(SELECT count(*) FROM public.legal_documents),
        'index_version',1
    ) ELSE NULL END;
$$;

CREATE OR REPLACE FUNCTION public.vietlex_normalize_phrase(value text) RETURNS text
LANGUAGE sql STABLE STRICT SECURITY DEFINER SET search_path=pg_catalog,extensions AS $$
    SELECT pg_catalog.btrim(pg_catalog.regexp_replace(
        pg_catalog.lower(extensions.unaccent(value)), '[^[:alnum:]]+', ' ', 'g'
    ));
$$;

CREATE OR REPLACE FUNCTION public.search_legal_full_doc(query_text text, limit_count integer DEFAULT 20,
    offset_count integer DEFAULT 0, type_filter text DEFAULT '', authority_filter text DEFAULT '',
    issued_from text DEFAULT '', issued_to text DEFAULT '', sort_order text DEFAULT 'default')
RETURNS TABLE(document_id bigint, document_number text, title text, source_url text,
    legal_type text, issuing_authority text, issuance_date text, content text, content_sha256 text)
LANGUAGE plpgsql STABLE SECURITY INVOKER SET search_path=pg_catalog,public AS $$
DECLARE query tsquery;
BEGIN
    IF query_text IS NULL OR limit_count IS NULL OR offset_count IS NULL OR sort_order IS NULL
       OR char_length(query_text)>200 OR limit_count NOT BETWEEN 1 AND 51
       OR offset_count NOT BETWEEN 0 AND 1000 OR sort_order NOT IN ('default','newest','oldest')
       OR (issued_from<>'' AND issued_from !~ '^\d{4}-\d{2}-\d{2}$')
       OR (issued_to<>'' AND issued_to !~ '^\d{4}-\d{2}-\d{2}$')
       THEN RAISE EXCEPTION 'invalid_body_query'; END IF;
    -- PostgreSQL caps tsvector positions at 16383. Use GIN for all-term candidates,
    -- then check the actual normalized phrase in the original full document.
    query:=plainto_tsquery('public.vietlex_body_simple'::regconfig,query_text);
    RETURN QUERY WITH matching_ids AS MATERIALIZED (
        SELECT doc.document_id FROM public.legal_documents doc WHERE doc.document_id % 8 = 0 AND to_tsvector('public.vietlex_body_simple'::regconfig,doc.content) @@ query
        UNION ALL SELECT doc.document_id FROM public.legal_documents doc WHERE doc.document_id % 8 = 1 AND to_tsvector('public.vietlex_body_simple'::regconfig,doc.content) @@ query
        UNION ALL SELECT doc.document_id FROM public.legal_documents doc WHERE doc.document_id % 8 = 2 AND to_tsvector('public.vietlex_body_simple'::regconfig,doc.content) @@ query
        UNION ALL SELECT doc.document_id FROM public.legal_documents doc WHERE doc.document_id % 8 = 3 AND to_tsvector('public.vietlex_body_simple'::regconfig,doc.content) @@ query
        UNION ALL SELECT doc.document_id FROM public.legal_documents doc WHERE doc.document_id % 8 = 4 AND to_tsvector('public.vietlex_body_simple'::regconfig,doc.content) @@ query
        UNION ALL SELECT doc.document_id FROM public.legal_documents doc WHERE doc.document_id % 8 = 5 AND to_tsvector('public.vietlex_body_simple'::regconfig,doc.content) @@ query
        UNION ALL SELECT doc.document_id FROM public.legal_documents doc WHERE doc.document_id % 8 = 6 AND to_tsvector('public.vietlex_body_simple'::regconfig,doc.content) @@ query
        UNION ALL SELECT doc.document_id FROM public.legal_documents doc WHERE doc.document_id % 8 = 7 AND to_tsvector('public.vietlex_body_simple'::regconfig,doc.content) @@ query
    ) SELECT d.document_id,d.document_number,d.title,d.source_url,d.legal_type,
        d.issuing_authority,d.issuance_date,d.content,d.content_sha256
    FROM matching_ids m JOIN public.legal_documents d USING(document_id)
    WHERE strpos(
          ' ' || public.vietlex_normalize_phrase(d.content) || ' ',
          ' ' || public.vietlex_normalize_phrase(query_text) || ' '
      ) > 0
      AND (type_filter='' OR d.legal_type=type_filter)
      AND (authority_filter='' OR d.issuing_authority=authority_filter)
      AND (issued_from='' OR d.issuance_date>=issued_from)
      AND (issued_to='' OR d.issuance_date<=issued_to)
    ORDER BY CASE WHEN sort_order='newest' THEN d.issuance_date END DESC NULLS LAST,
        CASE WHEN sort_order='oldest' THEN d.issuance_date END ASC NULLS LAST,
        ts_rank_cd(to_tsvector('public.vietlex_body_simple'::regconfig,d.content),query) DESC,
        d.document_id
    LIMIT limit_count OFFSET offset_count;
END $$;

REVOKE ALL ON FUNCTION public.legal_full_doc_coverage() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.vietlex_normalize_phrase(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.search_legal_full_doc(text,integer,integer,text,text,text,text,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.legal_full_doc_coverage(), public.vietlex_normalize_phrase(text),
    public.search_legal_full_doc(text,integer,integer,text,text,text,text,text)
    TO anon,authenticated,service_role;
