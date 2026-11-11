#!/usr/bin/env python3
"""Commit and push only independently accepted DSH analysis outputs."""
from __future__ import annotations
import fcntl, json, pathlib, sqlite3, subprocess, sys
ROOT=pathlib.Path(__file__).resolve().parents[1]
DB=ROOT/"work"/"supervisor.sqlite3"
LOCK=ROOT/"work"/"checkpoint.lock"
KINDS=("facts","cards","c-routing","generated","units")
JSON_KINDS={"facts","cards","c-routing"}
def run(*args,check=True,input=None):
 return subprocess.run(args,cwd=ROOT,text=True,capture_output=True,check=check,input=input)
LOCK.parent.mkdir(parents=True,exist_ok=True)
lock_file=LOCK.open("a+")
try:
 fcntl.flock(lock_file,fcntl.LOCK_EX|fcntl.LOCK_NB)
except BlockingIOError:
 print(json.dumps({"changed":False,"pushed":False,"busy":True}))
 raise SystemExit
db=sqlite3.connect(DB)
repos=[r[0] for r in db.execute("select repo from tasks where state='done' order by rank")]
paths=[]
for repo in repos:
 slug=repo.replace("/","__")
 for kind in KINDS:
  suffix=".json" if kind in JSON_KINDS else ".jsonl"
  p=ROOT/"results"/kind/(slug+suffix)
  if p.is_file(): paths.append(str(p.relative_to(ROOT)))
for rel in ("results/progress.jsonl","results/supervision/status.json","scripts/checkpoint.py","scripts/supervisor.py"):
 if (ROOT/rel).is_file(): paths.append(rel)
audit=run(sys.executable,"scripts/supervisor.py","audit",check=False)
if audit.returncode:
 print(audit.stdout+audit.stderr,file=sys.stderr); raise SystemExit(audit.returncode)
if paths:
 run(
  "git","add","--pathspec-from-file=-","--pathspec-file-nul",
  input="\0".join(paths)+"\0",
 )
diff=run("git","diff","--cached","--quiet",check=False)
if diff.returncode==0:
 head=run("git","rev-parse","HEAD").stdout.strip()
 remote=run("git","rev-parse","origin/main").stdout.strip()
 if head!=remote:
  run("git","push","origin","main")
  run("git","fetch","origin","main")
  remote=run("git","rev-parse","origin/main").stdout.strip()
  if head!=remote: raise SystemExit("origin/main mismatch after retry push")
  print(json.dumps({"changed":False,"pushed":True,"head":head,"retry":True})); raise SystemExit
 print(json.dumps({"changed":False,"pushed":False,"head":head})); raise SystemExit
if diff.returncode!=1: raise SystemExit(diff.returncode)
check=run("git","diff","--cached","--check",check=False)
if check.returncode:
 print(check.stdout+check.stderr,file=sys.stderr); raise SystemExit(check.returncode)
count=run("git","diff","--cached","--name-only").stdout.splitlines()
run("git","commit","-m",f"Checkpoint {len(repos)} validated DSH analyses")
run("git","push","origin","main")
run("git","fetch","origin","main")
head=run("git","rev-parse","HEAD").stdout.strip(); remote=run("git","rev-parse","origin/main").stdout.strip()
if head!=remote: raise SystemExit("origin/main mismatch")
print(json.dumps({"changed":True,"pushed":True,"head":head,"files":len(count),"done":len(repos)}))
