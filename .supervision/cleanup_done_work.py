#!/usr/bin/env python3
"""Safely remove downloaded plugin trees for supervisor tasks already marked done."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import subprocess
from pathlib import Path


ROOT = Path("/work/dsh-plugin-analysis")
WORK_ROOT = ROOT / "work"
DB_PATH = WORK_ROOT / "supervisor.sqlite3"
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def candidate_for(repo: str) -> Path:
    if not REPO_RE.fullmatch(repo):
        raise ValueError(f"unsafe repo name: {repo!r}")
    owner, name = repo.split("/", 1)
    candidate = WORK_ROOT / f"{owner}__{name}"
    if candidate.parent != WORK_ROOT:
        raise ValueError(f"candidate escaped work root: {candidate}")
    return candidate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="perform deletion; default is dry-run")
    parser.add_argument("--limit", type=int, default=500, help="maximum directories per run")
    args = parser.parse_args()

    if args.limit < 1 or args.limit > 2000:
        raise SystemExit("--limit must be between 1 and 2000")
    if ROOT.is_symlink() or WORK_ROOT.is_symlink():
        raise SystemExit("refusing cleanup through a symlinked root")
    if ROOT.resolve() != Path("/work/dsh-plugin-analysis"):
        raise SystemExit(f"unexpected root: {ROOT.resolve()}")
    if WORK_ROOT.resolve() != ROOT.resolve() / "work":
        raise SystemExit(f"unexpected work root: {WORK_ROOT.resolve()}")
    if not DB_PATH.is_file() or DB_PATH.is_symlink():
        raise SystemExit(f"missing or unsafe supervisor database: {DB_PATH}")

    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    # Scan all completed tasks. Applying LIMIT in SQL can permanently hide
    # later directories once the earliest completed directories were already
    # cleaned. The deletion limit is enforced below against eligible targets.
    repos = [row[0] for row in con.execute(
        "SELECT repo FROM tasks WHERE state = 'done' ORDER BY rank"
    )]
    con.close()

    tracked = set(subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "HEAD", "--",
         "results/facts", "results/cards", "results/units"],
        cwd=ROOT, text=True, capture_output=True, check=True,
    ).stdout.splitlines())
    dirty = {
        line[3:] for line in subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all", "--",
             "results/facts", "results/cards", "results/units"],
            cwd=ROOT, text=True, capture_output=True, check=True,
        ).stdout.splitlines() if len(line) >= 4
    }

    removed: list[str] = []
    deferred: list[str] = []
    skipped: list[dict[str, str]] = []
    for repo in repos:
        if len(removed) >= args.limit:
            break
        candidate = candidate_for(repo)
        if not candidate.exists():
            continue
        slug = repo.replace("/", "__")
        required = {
            f"results/facts/{slug}.json",
            f"results/cards/{slug}.json",
            f"results/units/{slug}.jsonl",
        }
        if not required.issubset(tracked) or required.intersection(dirty):
            deferred.append(repo)
            continue
        if candidate.is_symlink() or not candidate.is_dir():
            skipped.append({"repo": repo, "reason": "target is not a real directory"})
            continue
        marker = candidate / ".analysis-source.json"
        if not marker.is_file() or marker.is_symlink():
            skipped.append({"repo": repo, "reason": "missing safe analysis marker"})
            continue
        resolved = candidate.resolve()
        if resolved.parent != WORK_ROOT.resolve() or resolved == WORK_ROOT.resolve():
            skipped.append({"repo": repo, "reason": "resolved path outside direct work child"})
            continue
        if args.apply:
            shutil.rmtree(candidate)
        removed.append(repo)

    print(json.dumps({
        "mode": "apply" if args.apply else "dry-run",
        "eligible": len(removed),
        "repos": removed,
        "deferred_uncheckpointed": deferred,
        "skipped": skipped,
    }, ensure_ascii=False))
    return 0 if not skipped else 2


if __name__ == "__main__":
    raise SystemExit(main())
