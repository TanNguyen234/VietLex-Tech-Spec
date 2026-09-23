-- Follow 20260919_legal_body_search.sql. Preserve all passage/source rows and RLS.
-- Rebuild the derived index without retaining a second, stored tsvector copy.
BEGIN;
ALTER TABLE public.legal_body_passages DROP COLUMN fts;
ALTER TABLE public.legal_body_passages SET (toast_tuple_target=128);
CREATE INDEX legal_body_passages_fts ON public.legal_body_passages
    USING gin(to_tsvector('public.vietlex_body_simple'::regconfig, body))
    WITH (fastupdate=off);

CREATE OR REPLACE FUNCTION public.search_legal_body(query_text text, limit_count integer DEFAULT 20,
    offset_count integer DEFAULT 0, type_filter text DEFAULT '', authority_filter text DEFAULT '',
    issued_from text DEFAULT '', issued_to text DEFAULT '', sort_order text DEFAULT 'default')
RETURNS TABLE(document_id bigint, document_number text, title text, source_url text,
    legal_type text, issuing_authority text, issuance_date text, section_id text,
    section_title text, marked text)
LANGUAGE plpgsql STABLE SECURITY INVOKER SET search_path=pg_catalog,public AS $$
DECLARE query tsquery;
BEGIN
    IF query_text IS NULL OR limit_count IS NULL OR offset_count IS NULL OR sort_order IS NULL
       OR char_length(query_text)>200 OR limit_count NOT BETWEEN 1 AND 51 OR offset_count NOT BETWEEN 0 AND 1000
       OR sort_order NOT IN ('default','newest','oldest') THEN RAISE EXCEPTION 'invalid_body_query'; END IF;
    query:=phraseto_tsquery('public.vietlex_body_simple'::regconfig,query_text);
    RETURN QUERY SELECT d.document_id,d.document_number,d.title,d.source_url,d.legal_type,d.issuing_authority,
        d.issuance_date,p.section_id,p.section_title,
        ts_headline('public.vietlex_body_simple'::regconfig,p.body,query,
            'StartSel='||chr(57344)||', StopSel='||chr(57345)||', MaxWords=48, MinWords=15')
    FROM public.legal_body_passages p JOIN public.legal_body_active a ON a.batch_id=p.batch_id
    JOIN public.legal_documents d ON d.document_id=p.document_id AND d.content_sha256=p.content_sha256
    WHERE to_tsvector('public.vietlex_body_simple'::regconfig,p.body) @@ query
        AND (type_filter='' OR d.legal_type=type_filter)
        AND (authority_filter='' OR d.issuing_authority=authority_filter)
        AND (issued_from='' OR d.issuance_date>=issued_from) AND (issued_to='' OR d.issuance_date<=issued_to)
    ORDER BY CASE WHEN sort_order='newest' THEN d.issuance_date END DESC NULLS LAST,
        CASE WHEN sort_order='oldest' THEN d.issuance_date END ASC NULLS LAST,
        ts_rank_cd(to_tsvector('public.vietlex_body_simple'::regconfig,p.body),query) DESC,
        p.document_id,p.document_offset
    LIMIT limit_count OFFSET offset_count;
END $$;
COMMIT;
