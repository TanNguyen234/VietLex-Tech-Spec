"""Validate Vercel's enumerated upload against the frozen local bundle."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import stat

RUN = Path(__file__).resolve().parent
ROOT = Path.cwd()
BUNDLE = (Path((RUN / "bundle-path.txt").read_text(encoding="utf-8").strip())).resolve()
ALLOWED_OMISSIONS = {
    "app/data/namsyntax_legal_qa_420.json",
    "app/data/namsyntax_legal_qa_420_curated_v1.json",
}


def main() -> None:
    output = RUN / "deploy-dry-validation.json"
    if output.exists():
        raise SystemExit("Refusing to replace immutable upload validation")
    dry = json.loads((RUN / "deploy-dry.json").read_text(encoding="utf-8-sig"))
    manifest = json.loads((RUN / "release-bundle-manifest-final.json").read_text(encoding="utf-8"))
    expected = {entry["path"]: entry for entry in manifest["included_files"]}
    seen, directories, mismatches, private, unexpected = set(), [], [], [], []
    for entry in dry["files"]:
        relative = entry["path"].replace("\\", "/")
        path = PurePosixPath(relative)
        if path.is_absolute() or ".." in path.parts or ":" in relative:
            raise RuntimeError("Unsafe path in upload enumeration")
        target = (BUNDLE / relative).resolve()
        if not target.is_relative_to(BUNDLE):
            raise RuntimeError("Upload path escaped release bundle")
        if any(part in {".git", ".vercel"} or part == ".env" or part.startswith(".env.")
               for part in path.parts) or path.suffix.lower() in {".key", ".pem", ".p12", ".pfx"}:
            private.append(relative)
        if stat.S_ISDIR(entry["mode"]):
            if not target.is_dir():
                raise RuntimeError("Upload directory missing from bundle")
            directories.append(relative)
            continue
        if relative in seen:
            raise RuntimeError("Duplicate uploaded file path")
        seen.add(relative)
        if relative not in expected:
            unexpected.append(relative)
            continue
        content = target.read_bytes()
        if (hashlib.sha1(content).hexdigest() != entry["sha"]
                or hashlib.sha256(content).hexdigest() != expected[relative]["sha256"]
                or len(content) != entry["size"]):
            mismatches.append(relative)
    omitted = sorted(set(expected) - seen)
    passed = not (mismatches or private or unexpected) and set(omitted) == ALLOWED_OMISSIONS
    report = {
        "passed": passed, "uploaded_entries": dry["fileCount"],
        "uploaded_regular_files": len(seen), "uploaded_bytes": dry["totalSize"],
        "directory_entries": directories, "file_hash_mismatches": mismatches,
        "sensitive_paths": private, "unexpected_regular_files": unexpected,
        "omitted_offline_qa_files": omitted,
        "source_manifest_sha256": manifest["source_baseline"]["manifest_sha256"],
    }
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
    print(json.dumps(report))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
