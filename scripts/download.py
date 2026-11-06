#!/usr/bin/env python3
"""Download fixed GitHub commits and safely unpack them for static analysis only."""
from __future__ import annotations
import argparse, csv, io, json, os, pathlib, shutil, tarfile, tempfile, time
import urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_LIST = ROOT / "lists" / "calibration-top30.csv"
WORK = ROOT / "work"
MAX_EXPANDED = 200 * 1024 * 1024
MAX_DATA = 1 * 1024 * 1024
SKIP_PARTS = {"node_modules", "dist", "build", "coverage", ".next", ".cache", "vendor"}
SOURCE_EXT = {
    ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".py", ".go", ".rs", ".java",
    ".kt", ".rb", ".php", ".sh", ".bash", ".zsh", ".html", ".css", ".scss",
    ".json", ".jsonc", ".yaml", ".yml", ".toml", ".md", ".txt", ".xml", ".vue",
    ".svelte", ".graphql", ".gql", ".proto", ".sql",
}
BINARY_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip", ".gz",
    ".tgz", ".bz2", ".xz", ".7z", ".rar", ".mp3", ".wav", ".ogg", ".mp4",
    ".mov", ".avi", ".mkv", ".woff", ".woff2", ".ttf", ".otf", ".exe", ".dll",
    ".so", ".dylib", ".bin", ".wasm", ".class", ".jar", ".pyc",
}

def safe_rel(name: str) -> pathlib.PurePosixPath | None:
    p = pathlib.PurePosixPath(name)
    parts = p.parts[1:] if len(p.parts) > 1 else ()
    if not parts or any(x in ("", ".", "..") for x in parts):
        return None
    rel = pathlib.PurePosixPath(*parts)
    if rel.is_absolute():
        return None
    return rel

def should_skip(rel: pathlib.PurePosixPath, member: tarfile.TarInfo, large: bool) -> str | None:
    if member.issym() or member.islnk() or member.isdev() or member.isfifo():
        return "non-regular"
    if not large or member.isdir():
        return None
    lowparts = {p.lower() for p in rel.parts}
    if lowparts & SKIP_PARTS:
        return "build-or-dependency"
    ext = pathlib.PurePosixPath(rel.name).suffix.lower()
    if ext in BINARY_EXT:
        return "binary"
    if member.size > MAX_DATA and ext not in SOURCE_EXT:
        return "large-data"
    return None

def download(row: dict, force: bool = False) -> dict:
    repo, commit = row["repo"], row["commit"]
    slug = repo.replace("/", "__")
    dest = WORK / slug
    marker = dest / ".analysis-source.json"
    started = time.monotonic()
    if marker.exists() and not force:
        try:
            old = json.loads(marker.read_text())
            if old.get("repo") == repo and old.get("commit") == commit:
                return {"repo": repo, "status": "cached", "seconds": round(time.monotonic()-started, 3)}
        except Exception:
            pass
    url = f"https://codeload.github.com/{repo}/tar.gz/{commit}"
    req = urllib.request.Request(url, headers={"User-Agent": "dsh-plugin-analysis/1"})
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=120) as response:
                payload = response.read()
            break
        except Exception as exc:
            last = exc
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
    tmp = pathlib.Path(tempfile.mkdtemp(prefix=f".{slug}.", dir=WORK))
    skipped: list[dict] = []
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as tf:
            members = tf.getmembers()
            expanded = sum(m.size for m in members if m.isfile())
            large = expanded > MAX_EXPANDED
            for member in members:
                rel = safe_rel(member.name)
                if rel is None:
                    continue
                reason = should_skip(rel, member, large)
                if reason:
                    skipped.append({"path": str(rel), "reason": reason, "bytes": member.size})
                    continue
                target = tmp.joinpath(*rel.parts)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if not member.isfile():
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                source = tf.extractfile(member)
                if source is None:
                    continue
                with target.open("wb") as fh:
                    shutil.copyfileobj(source, fh)
                os.chmod(target, 0o644)
        meta = {
            "repo": repo, "commit": commit, "url": url,
            "archive_bytes": len(payload), "expanded_bytes": expanded,
            "large_repo_filter": large, "skipped": skipped,
        }
        (tmp / ".analysis-source.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n")
        if dest.exists():
            shutil.rmtree(dest)
        tmp.rename(dest)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return {
        "repo": repo, "status": "downloaded", "archive_bytes": len(payload),
        "expanded_bytes": expanded, "skipped": len(skipped),
        "seconds": round(time.monotonic()-started, 3),
    }

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", default=str(DEFAULT_LIST))
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--repo", action="append", help="only these owner/name values")
    args = ap.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    with open(args.list, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    if args.repo:
        wanted = set(args.repo)
        rows = [r for r in rows if r["repo"] in wanted]
    failures = 0
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        futures = {pool.submit(download, row, args.force): row for row in rows}
        for future in as_completed(futures):
            row = futures[future]
            try:
                print(json.dumps(future.result(), ensure_ascii=False), flush=True)
            except Exception as exc:
                failures += 1
                print(json.dumps({"repo": row["repo"], "status": "failed", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False), flush=True)
    return 1 if failures else 0

if __name__ == "__main__":
    raise SystemExit(main())
