-- Additive migration. Run once with SQL administrator access.
-- Does not populate data, publish a batch, or modify existing corpus/vector indexes.
BEGIN;
CREATE SCHEMA IF NOT EXISTS extensions;
CREATE EXTENSION IF NOT EXISTS unaccent WITH SCHEMA extensions;
CREATE TEXT SEARCH CONFIGURATION public.vietlex_body_simple (COPY = pg_catalog.simple);
ALTER TEXT SEARCH CONFIGURATION public.vietlex_body_simple
    ALTER MAPPING FOR hword, hword_part, word WITH extensions.unaccent, pg_catalog.simple;

CREATE TABLE public.legal_body_runs (
    batch_id uuid PRIMARY KEY,
    expected_documents integer NOT NULL CHECK (expected_documents > 0),
    expected_passages integer NOT NULL CHECK (expected_passages > 0),
    source_sha256 text NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
    state text NOT NULL DEFAULT 'building' CHECK (state IN ('building','ready')),
    built_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE public.legal_body_passages (
    batch_id uuid NOT NULL REFERENCES public.legal_body_runs(batch_id),
    document_id bigint NOT NULL REFERENCES public.legal_documents(document_id),
    section_id text NOT NULL CHECK (section_id ~ '^(section-[0-9]+|preamble|full-text)$'),
    section_title text NOT NULL,
    document_offset integer NOT NULL CHECK (document_offset >= 0),
    content_sha256 text NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    body text NOT NULL CHECK (char_length(body) BETWEEN 1 AND 2400),
    fts tsvector GENERATED ALWAYS AS (to_tsvector('public.vietlex_body_simple'::regconfig, body)) STORED,
    PRIMARY KEY(batch_id, document_id, document_offset)
);
CREATE INDEX legal_body_passages_fts ON public.legal_body_passages USING gin(fts);
CREATE TABLE public.legal_body_active (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    batch_id uuid NOT NULL REFERENCES public.legal_body_runs(batch_id),
    published_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.legal_body_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.legal_body_passages ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.legal_body_active ENABLE ROW LEVEL SECURITY;
CREATE POLICY legal_body_runs_read ON public.legal_body_runs FOR SELECT TO anon, authenticated USING (state='ready');
CREATE POLICY legal_body_active_read ON public.legal_body_active FOR SELECT TO anon, authenticated USING (true);
CREATE POLICY legal_body_passages_read ON public.legal_body_passages FOR SELECT TO anon, authenticated USING (
    EXISTS (SELECT 1 FROM public.legal_body_active a WHERE a.batch_id=legal_body_passages.batch_id)
    AND EXISTS (SELECT 1 FROM public.legal_documents d WHERE d.document_id=legal_body_passages.document_id
                AND d.content_sha256=legal_body_passages.content_sha256)
);
CREATE POLICY legal_body_runs_write ON public.legal_body_runs TO service_role USING (true) WITH CHECK (true);
CREATE POLICY legal_body_passages_write ON public.legal_body_passages TO service_role USING (true) WITH CHECK (true);
CREATE POLICY legal_body_active_write ON public.legal_body_active TO service_role USING (true) WITH CHECK (true);
GRANT SELECT ON public.legal_body_runs, public.legal_body_passages, public.legal_body_active TO anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON public.legal_body_runs, public.legal_body_passages, public.legal_body_active TO service_role;

CREATE FUNCTION public.publish_legal_body(batch uuid) RETURNS void
LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog,public AS $$
DECLARE expected public.legal_body_runs; documents integer; passages integer;
BEGIN
    -- Serialize publication, not reader traffic. No generation is deleted.
    PERFORM pg_advisory_xact_lock(19092026);
    SELECT * INTO STRICT expected FROM public.legal_body_runs WHERE batch_id=batch FOR UPDATE;
    SELECT count(DISTINCT document_id), count(*) INTO documents,passages
        FROM public.legal_body_passages WHERE batch_id=batch;
    IF documents<>expected.expected_documents OR passages<>expected.expected_passages THEN
        RAISE EXCEPTION 'body_batch_incomplete';
    END IF;
    IF EXISTS (SELECT 1 FROM public.legal_body_passages p JOIN public.legal_documents d USING(document_id)
               WHERE p.batch_id=batch AND (p.content_sha256<>d.content_sha256
               OR substring(d.content FROM p.document_offset+1 FOR char_length(p.body))<>p.body)) THEN
        RAISE EXCEPTION 'body_source_mismatch';
    END IF;
    UPDATE public.legal_body_runs SET state='ready' WHERE batch_id=batch;
    INSERT INTO public.legal_body_active(singleton,batch_id) VALUES(true,batch)
        ON CONFLICT(singleton) DO UPDATE SET batch_id=excluded.batch_id,published_at=now();
END $$;
REVOKE ALL ON FUNCTION public.publish_legal_body(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.publish_legal_body(uuid) TO service_role;

CREATE FUNCTION public.legal_body_coverage() RETURNS jsonb
LANGUAGE sql STABLE SECURITY INVOKER SET search_path=pg_catalog,public AS $$
    SELECT jsonb_build_object('document_count',r.expected_documents,'passage_count',r.expected_passages,
        'built_at',r.built_at,'source_sha256',r.source_sha256,'batch_id',r.batch_id)
    FROM public.legal_body_active a JOIN public.legal_body_runs r USING(batch_id) WHERE r.state='ready';
$$;
CREATE FUNCTION public.search_legal_body(query_text text, limit_count integer DEFAULT 20,
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
    WHERE p.fts @@ query AND (type_filter='' OR d.legal_type=type_filter)
        AND (authority_filter='' OR d.issuing_authority=authority_filter)
        AND (issued_from='' OR d.issuance_date>=issued_from) AND (issued_to='' OR d.issuance_date<=issued_to)
    ORDER BY CASE WHEN sort_order='newest' THEN d.issuance_date END DESC NULLS LAST,
        CASE WHEN sort_order='oldest' THEN d.issuance_date END ASC NULLS LAST,
        ts_rank_cd(p.fts,query) DESC,p.document_id,p.document_offset
    LIMIT limit_count OFFSET offset_count;
END $$;
REVOKE ALL ON FUNCTION public.legal_body_coverage() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.search_legal_body(text,integer,integer,text,text,text,text,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.legal_body_coverage(), public.search_legal_body(text,integer,integer,text,text,text,text,text)
    TO anon,authenticated,service_role;
COMMIT;
