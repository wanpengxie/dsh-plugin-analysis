#!/usr/bin/env python3
"""Persistent single-source-of-truth scheduler for DSH repository analysis."""
from __future__ import annotations
import argparse, concurrent.futures, csv, datetime as dt, json, os, pathlib, sqlite3, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
DB = ROOT / "work" / "supervisor.sqlite3"
SNAPSHOT = ROOT / "results" / "supervision" / "status.json"
LISTS = {"A": ROOT/"lists"/"high-priority.csv", "B": ROOT/"lists"/"high-priority.csv",
         "C": ROOT/"lists"/"zero-star.csv"}
VALIDATOR = ROOT / "scripts" / "validate_results.py"
CLAIMS_PAUSED = ROOT / ".supervision" / "pause-claims"

def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def connect():
    DB.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB, timeout=30, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""CREATE TABLE IF NOT EXISTS tasks(
      repo TEXT PRIMARY KEY, rank INTEGER NOT NULL, tier TEXT NOT NULL, commit_sha TEXT NOT NULL,
      state TEXT NOT NULL DEFAULT 'queued', worker TEXT, attempts INTEGER NOT NULL DEFAULT 0,
      claimed_at TEXT, finished_at TEXT, last_error TEXT, updated_at TEXT NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS events(
      id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, repo TEXT, worker TEXT,
      event TEXT NOT NULL, detail TEXT)""")
    return db

def rows(tier):
    source = LISTS.get(tier, LISTS["A"])
    with source.open(newline="", encoding="utf-8-sig") as f:
        return [r for r in csv.DictReader(f) if not tier or r["tier"] == tier]

def list_for_repo(repo):
    db = connect(); row = db.execute("SELECT tier FROM tasks WHERE repo=?", (repo,)).fetchone()
    return LISTS.get(row["tier"] if row else "A", LISTS["A"])

def valid(repo):
    slug = repo.replace("/", "__")
    required = [ROOT/"results"/"facts"/(slug+".json"),
                ROOT/"results"/"cards"/(slug+".json"),
                ROOT/"results"/"units"/(slug+".jsonl")]
    if not all(p.is_file() for p in required):
        return False
    p = subprocess.run([sys.executable, str(VALIDATOR), "--list", str(list_for_repo(repo)), "--repo", repo],
                       cwd=ROOT, text=True, capture_output=True)
    return p.returncode == 0

def required_result_paths(repo):
    slug = repo.replace("/", "__")
    return {
        f"results/facts/{slug}.json",
        f"results/cards/{slug}.json",
        f"results/units/{slug}.jsonl",
    }

def event(db, event_name, repo=None, worker=None, detail=None):
    db.execute("INSERT INTO events(at,repo,worker,event,detail) VALUES(?,?,?,?,?)",
               (now(), repo, worker, event_name, detail))

def sync(tier):
    db = connect()
    inserted = completed = 0
    with db:
        for r in rows(tier):
            exists = db.execute("SELECT state FROM tasks WHERE repo=?", (r["repo"],)).fetchone()
            if exists:
                continue
            state = "done" if valid(r["repo"]) else "queued"
            db.execute("""INSERT INTO tasks(repo,rank,tier,commit_sha,state,updated_at)
                          VALUES(?,?,?,?,?,?)""",
                       (r["repo"], int(r["rank"]), r["tier"], r["commit"], state, now()))
            event(db, "imported_existing" if state == "done" else "queued", r["repo"])
            inserted += 1
            completed += state == "done"
    snapshot(db)
    print(json.dumps({"inserted": inserted, "already_valid": completed}, ensure_ascii=False))

def claim(worker, tier):
    db = connect()
    db.execute("BEGIN IMMEDIATE")
    try:
        # Repeated or ambiguous claim calls must return this worker's existing task.
        existing = db.execute("""SELECT * FROM tasks WHERE state='claimed' AND worker=?
                                 ORDER BY rank LIMIT 1""", (worker,)).fetchone()
        if existing:
            db.execute("COMMIT")
            print(json.dumps(dict(existing), ensure_ascii=False))
            return
        if CLAIMS_PAUSED.exists():
            db.execute("COMMIT")
            print("null")
            return
        row = db.execute("""SELECT * FROM tasks WHERE state='queued' AND tier=?
                            ORDER BY rank LIMIT 1""", (tier,)).fetchone()
        if not row:
            db.execute("COMMIT")
            print("null")
            return
        at = now()
        changed = db.execute("""UPDATE tasks SET state='claimed',worker=?,attempts=attempts+1,
                                claimed_at=?,updated_at=?,last_error=NULL
                                WHERE repo=? AND state='queued'""",
                             (worker, at, at, row["repo"])).rowcount
        if changed != 1:
            raise RuntimeError("atomic claim lost")
        event(db, "claimed", row["repo"], worker)
        db.execute("COMMIT")
        print(json.dumps(dict(db.execute("SELECT * FROM tasks WHERE repo=?", (row["repo"],)).fetchone()),
                         ensure_ascii=False))
    except Exception:
        db.execute("ROLLBACK")
        raise
    snapshot(db)

def owned(worker):
    db = connect()
    row = db.execute("""SELECT * FROM tasks WHERE state='claimed' AND worker=?
                       ORDER BY rank LIMIT 1""", (worker,)).fetchone()
    print(json.dumps(dict(row), ensure_ascii=False) if row else "null")


def finish(repo, worker):
    db = connect()
    row = db.execute("SELECT * FROM tasks WHERE repo=?", (repo,)).fetchone()
    if not row:
        raise SystemExit(f"unknown repo: {repo}")
    if row["state"] != "claimed" or row["worker"] != worker:
        raise SystemExit(f"ownership mismatch: state={row['state']} worker={row['worker']}")
    if not valid(repo):
        raise SystemExit("validator rejected outputs; task remains claimed")
    at = now()
    with db:
        db.execute("""UPDATE tasks SET state='done',finished_at=?,updated_at=?,last_error=NULL
                      WHERE repo=?""", (at, at, repo))
        event(db, "accepted", repo, worker)
    snapshot(db)
    print(json.dumps({"repo": repo, "state": "done"}))

def reject(repo, worker, error, retry=True):
    db = connect()
    row = db.execute("SELECT * FROM tasks WHERE repo=?", (repo,)).fetchone()
    if not row or row["state"] != "claimed" or row["worker"] != worker:
        raise SystemExit("ownership mismatch")
    state = "queued" if retry and row["attempts"] < 3 else "failed"
    with db:
        db.execute("""UPDATE tasks SET state=?,worker=NULL,claimed_at=NULL,last_error=?,updated_at=?
                      WHERE repo=?""", (state, error[:2000], now(), repo))
        event(db, "requeued" if state == "queued" else "failed", repo, worker, error[:2000])
    snapshot(db)
    print(json.dumps({"repo": repo, "state": state}))

def requeue_stale(minutes):
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=minutes)).isoformat()
    db = connect()
    stale = db.execute("""SELECT repo,worker FROM tasks
                          WHERE state='claimed' AND claimed_at < ?""", (cutoff,)).fetchall()
    with db:
        for row in stale:
            db.execute("""UPDATE tasks SET state='queued',worker=NULL,claimed_at=NULL,
                          last_error='stale claim requeued',updated_at=? WHERE repo=?""",
                       (now(), row["repo"]))
            event(db, "stale_requeued", row["repo"], row["worker"])
    snapshot(db)
    print(json.dumps({"requeued": len(stale)}))

def audit():
    db = connect()
    errors = []
    dup_workers = db.execute("""SELECT worker,count(*) n FROM tasks WHERE state='claimed'
                                GROUP BY worker HAVING n>1""").fetchall()
    for x in dup_workers:
        errors.append(f"worker {x['worker']} owns {x['n']} tasks")
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
    done = db.execute("SELECT repo FROM tasks WHERE state='done'").fetchall()
    validate_repos = []
    for x in done:
        repo = x["repo"]
        source = ROOT / "work" / repo.replace("/", "__")
        required = required_result_paths(repo)
        if source.is_dir():
            validate_repos.append(repo)
        elif not required.issubset(tracked) or required.intersection(dirty):
            errors.append(f"done task source cleaned before validated checkpoint: {repo}")
    # Validation is repository-local and subprocess-isolated. Keep concurrency
    # bounded so a full A+B+C audit remains practical without changing any
    # acceptance rule or competing heavily with analysis workers.
    audit_workers = max(1, min(8, os.cpu_count() or 1))
    with concurrent.futures.ThreadPoolExecutor(max_workers=audit_workers) as pool:
        for repo, ok in zip(validate_repos, pool.map(valid, validate_repos)):
            if not ok:
                errors.append(f"done task fails validation: {repo}")
    known = {x["repo"] for x in db.execute("SELECT repo FROM tasks")}
    loaded_tiers = {x["tier"] for x in db.execute("SELECT DISTINCT tier FROM tasks")}
    expected = set()
    for tier in loaded_tiers: expected.update(x["repo"] for x in rows(tier))
    missing = sorted(expected-known)
    if missing:
        errors.append(f"{len(missing)} list rows absent from ledger")
    snapshot(db)
    result = {"ok": not errors, "errors": errors}
    print(json.dumps(result, ensure_ascii=False))
    return bool(errors)

def snapshot(db=None):
    db = db or connect()
    counts = {r["state"]: r["n"] for r in db.execute(
        "SELECT state,count(*) n FROM tasks GROUP BY state")}
    tier_counts = [dict(r) for r in db.execute(
        "SELECT tier,state,count(*) n FROM tasks GROUP BY tier,state ORDER BY tier,state")]
    active = [dict(r) for r in db.execute(
        """SELECT repo,rank,tier,worker,attempts,claimed_at FROM tasks
           WHERE state='claimed' ORDER BY rank""")]
    failed = [dict(r) for r in db.execute(
        """SELECT repo,rank,tier,attempts,last_error FROM tasks
           WHERE state='failed' ORDER BY rank""")]
    payload = {"generated_at": now(), "counts": counts, "by_tier": tier_counts,
               "active": active, "failed": failed}
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    temp = SNAPSHOT.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2)+"\n")
    os.replace(temp, SNAPSHOT)
    return payload

def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("sync"); p.add_argument("--tier", choices=["A","B","C"], default="A")
    p = sub.add_parser("claim"); p.add_argument("--worker", required=True); p.add_argument("--tier", choices=["A","B","C"], default="A")
    p = sub.add_parser("owned"); p.add_argument("--worker", required=True)
    p = sub.add_parser("finish"); p.add_argument("--repo", required=True); p.add_argument("--worker", required=True)
    p = sub.add_parser("reject"); p.add_argument("--repo", required=True); p.add_argument("--worker", required=True); p.add_argument("--error", required=True); p.add_argument("--no-retry", action="store_true")
    p = sub.add_parser("requeue-stale"); p.add_argument("--minutes", type=int, default=30)
    sub.add_parser("status"); sub.add_parser("audit")
    a = ap.parse_args()
    if a.cmd == "sync": sync(a.tier)
    elif a.cmd == "claim": claim(a.worker, a.tier)
    elif a.cmd == "owned": owned(a.worker)
    elif a.cmd == "finish": finish(a.repo, a.worker)
    elif a.cmd == "reject": reject(a.repo, a.worker, a.error, not a.no_retry)
    elif a.cmd == "requeue-stale": requeue_stale(a.minutes)
    elif a.cmd == "status": print(json.dumps(snapshot(), ensure_ascii=False, indent=2))
    elif a.cmd == "audit": raise SystemExit(audit())

if __name__ == "__main__":
    main()
