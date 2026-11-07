#!/usr/bin/env python3
"""Read-only integrity and scope checks for this source-only package."""
import hashlib
import json
import pathlib
import re
import stat
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs/PACKAGE_MANIFEST.json"
FORBIDDEN_NAMES = {".env", "records.db", "bridge-token", "oneshot-helper.pack"}
FORBIDDEN_PARTS = {".runtime", "build", "bin", "obj", "node_modules", "vendor", "__pycache__"}
FORBIDDEN_SUFFIXES = {".db", ".dll", ".dylib", ".zip", ".key", ".pem", ".p12", ".gguf", ".pack"}
PRIVATE_TEXT = re.compile(rb"/" + rb"Users/|" + rb"wxid_" + rb"[A-Za-z0-9]{12,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|ghp_[A-Za-z0-9]{10,}|sk-[A-Za-z0-9]{12,}")


def main():
    data = json.loads(MANIFEST.read_text())
    records = data["files"]
    if len(records) != data["count"] or len({r["path"] for r in records}) != len(records):
        raise ValueError("manifest count or duplicate path")
    for record in records:
        relative = pathlib.PurePosixPath(record["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("invalid manifest path")
        path = ROOT.joinpath(*relative.parts)
        if not path.is_file() or path.is_symlink() or path.stat().st_nlink != 1:
            raise ValueError("missing or linked selected source")
        raw = path.read_bytes()
        if len(raw) != record["bytes"] or hashlib.sha256(raw).hexdigest() != record["packageSha256"]:
            raise ValueError("selected source changed")
    allowed = {r["path"] for r in records}
    allowed.update({"CONTRIBUTING.md", "README.md", "THIRD_PARTY.md", ".env.example", ".gitignore", "tools/verify_package.py",
                    "docs/PACKAGE_MANIFEST.json", "docs/OMITTED_FILES.json", "docs/SOURCE_SCOPE.md",
                    "docs/BUILD_GAPS.md", "docs/INTEGRATION_BOUNDARY.md", "docs/PORTABLE_CORE_PROVENANCE.md",
                    "docs/SOURCE_REFRESH_20261106.json"})
    seen = set()
    for path in ROOT.rglob("*"):
        relative = path.relative_to(ROOT)
        if ".git" in relative.parts:
            continue
        if path.is_symlink():
            raise ValueError("symlink in package")
        if not path.is_file():
            continue
        name = relative.as_posix()
        if name not in allowed or path.name in FORBIDDEN_NAMES or any(part in FORBIDDEN_PARTS for part in relative.parts) or path.suffix in FORBIDDEN_SUFFIXES:
            raise ValueError("unexpected package file")
        if path.stat().st_size > 1_000_000:
            raise ValueError("oversized package file")
        raw = path.read_bytes()
        if PRIVATE_TEXT.search(raw):
            raise ValueError("private text pattern in package")
        seen.add(name)
    if seen != allowed:
        raise ValueError("package file list mismatch")
    print(f"PASS source-only manifest: {len(records)} selected inputs; {len(seen)} package files")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print(f"FAIL package audit: {type(error).__name__}", file=sys.stderr)
        sys.exit(1)
