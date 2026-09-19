"""Build a new bounded body-search sidecar without modifying the content store."""

import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--limit", required=True, type=int, help="Explicit maximum documents; 1..15000"
    )
    args = parser.parse_args()
    if not 1 <= args.limit <= 15000:
        parser.error("--limit must be 1..15000; no implicit full-corpus build")
    if not args.store.is_file():
        parser.error("source content store does not exist")
    if args.output.exists():
        parser.error("output already exists; choose a new path")
    from app.ingestion.content_store import ContentStore
    from app.services.body_search import BodySearchIndex
    import json

    store = ContentStore(args.store)

    def documents():
        after, count = -1, 0
        while count < args.limit:
            ids = store.iter_document_ids(
                after_id=after, limit=min(50, args.limit - count)
            )
            if not ids:
                break
            rows = store.get_many(ids)
            for identifier in ids:
                if identifier not in rows:
                    raise ValueError("source_document_missing")
                yield rows[identifier]
            after, count = ids[-1], count + len(ids)

    index = BodySearchIndex.build(args.output, documents())
    print(json.dumps(index.coverage(), indent=2))


if __name__ == "__main__":
    main()
