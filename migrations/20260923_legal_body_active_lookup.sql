-- Same read boundary, expressed as one active-batch lookup so the primary index
-- can reject unpublished batches without scanning every staged passage.
BEGIN;
ALTER POLICY legal_body_passages_read ON public.legal_body_passages
    USING (
        batch_id = (SELECT a.batch_id FROM public.legal_body_active a WHERE a.singleton)
        AND EXISTS (
            SELECT 1 FROM public.legal_documents d
            WHERE d.document_id=legal_body_passages.document_id
              AND d.content_sha256=legal_body_passages.content_sha256
        )
    );
COMMIT;
