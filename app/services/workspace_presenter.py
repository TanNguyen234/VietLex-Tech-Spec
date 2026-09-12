"""Provider-free views of retained workspace state; never infer legal validity."""


def source_library(workspace: dict) -> list[dict]:
    groups = {}
    for analysis in reversed((workspace.get("analyses") or [])[-50:]):
        if analysis.get("kind") != "trusted_sources":
            continue
        for index, source in enumerate(
            (analysis.get("result") or {}).get("sources", [])[:3]
        ):
            digest = source.get("document_sha256") or source.get("sha256")
            key = (source.get("url"), digest)
            if key not in groups:
                count = source.get("page_count")
                groups[key] = {
                    "title": source.get("title") or source.get("url"),
                    "url": source.get("url"),
                    "document_sha256": source.get("document_sha256"),
                    "page_count": count
                    if isinstance(count, int) and 1 <= count <= 200
                    else None,
                    "read_pages": set(),
                    "reads": [],
                    "document_number": source.get("document_number"),
                }
            row = groups[key]
            row["reads"].append(
                {
                    "analysis_id": analysis["analysis_id"],
                    "source_index": index,
                    "page_start": source.get("page_start"),
                    "page_end": source.get("page_end"),
                    "method": source.get("method"),
                    "retrieved_at": source.get("retrieved_at"),
                }
            )
            for page in source.get("pages") or []:
                number = page.get("page")
                if (
                    row["page_count"]
                    and isinstance(number, int)
                    and 1 <= number <= row["page_count"]
                    and str(page.get("text") or "").strip()
                ):
                    row["read_pages"].add(number)
    for row in groups.values():
        row["readable_count"] = len(row["read_pages"])
        row["missing_pages"] = sorted(
            set(range(1, (row["page_count"] or 0) + 1)) - row["read_pages"]
        )
        row["read_pages"] = sorted(row["read_pages"])
    return list(groups.values())


def workspace_summary(workspace: dict) -> dict:
    evidence = workspace.get("evidence") or []
    analyses = workspace.get("analyses") or []
    statuses = [
        (item.get("review") or {}).get("status", "to_check") for item in evidence
    ]
    return {
        "sources": len(evidence),
        "text_checked": statuses.count("text_checked"),
        "follow_up": statuses.count("follow_up"),
        "to_check": statuses.count("to_check"),
        "documents": len(workspace.get("documents") or []),
        "reports": sum(item.get("kind") == "research_report" for item in analyses),
        "analyses": len(analyses),
    }
