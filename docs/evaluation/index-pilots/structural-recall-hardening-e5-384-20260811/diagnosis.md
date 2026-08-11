# Provider-usage diagnosis

The first Qdrant upsert was acknowledged with `status=ok` and `result.status=completed`.
The sanitized response reported:

```json
{
  "usage": {
    "inference": {
      "models": {
        "intfloat/multilingual-e5-small": {"tokens": 30}
      }
    }
  }
}
```

No `qdrant/bm25` inference token entry was returned. Qdrant's BM25 sparse generation is cluster-native and unmetered in this response. Requiring a fabricated positive token count for it is therefore invalid. The source fix must validate only metered model entries while continuing to bind the sparse model identity in the immutable plan and collection schema.

Cleanup evidence: the 64 probe record IDs plus one diagnostic record ID were deleted explicitly, and a subsequent exact count returned 0 for `vietlex-legal-rag-v2-pilot-384`.
