#!/usr/bin/env python3
"""Build/resume one semantic embedding per DSH repository."""
from __future__ import annotations
import argparse,concurrent.futures,datetime as dt,hashlib,json,pathlib,sqlite3,time
from embedding_common import DIMENSIONS,MODEL,embed,key

ROOT=pathlib.Path(__file__).resolve().parents[1]
DEFAULT_DB=ROOT/"vector-index"/"repo-qwen3-embedding-8b-1024.sqlite3"
SEMANTIC_TYPES=("card","intent","feature","declared","caveat","lifecycle")
MAX_CHARS=28000

def connect(path):
 path.parent.mkdir(parents=True,exist_ok=True);db=sqlite3.connect(path,timeout=60)
 db.execute("pragma journal_mode=WAL");db.execute("pragma synchronous=NORMAL")
 db.execute("""create table if not exists repositories(
  repo text primary key,commit_sha text not null,tier text,name text not null,document text not null,
  document_hash text not null,model text not null,dimensions integer not null,vector blob not null,
  embedded_at text not null)""")
 db.execute("create index if not exists repositories_tier on repositories(tier)")
 db.execute("create virtual table if not exists repository_fts using fts5(repo unindexed,document,tokenize='trigram')")
 db.execute("create table if not exists meta(key text primary key,value text not null)");db.commit();return db

def clean(value):return " ".join(str(value or "").split())

def repo_document(card,units):
 sections=[]
 def add(label,values,limit=None):
  seen=[];known=set()
  for value in values:
   text=clean(value)
   if not text or text in known:continue
   known.add(text);seen.append(text)
   if limit and len(seen)>=limit:break
  if seen:sections.append(label+"：\n"+"\n".join("- "+x for x in seen))
 one=card.get("one_liner",{});topics=card.get("topics",{});keywords=card.get("keywords",{})
 add("插件",[card.get("name"),card.get("repo")])
 add("能力摘要",[one.get("zh"),one.get("en")])
 add("分类与接入面",[topics.get("primary"),*topics.get("secondary",[]),*card.get("surfaces",[]),*card.get("clients",[])])
 add("检索关键词",[*keywords.get("zh",[]),*keywords.get("en",[])])
 by_type={kind:[] for kind in SEMANTIC_TYPES}
 for unit in units:
  if unit.get("type") in by_type:by_type[unit["type"]].append(unit.get("text",""))
 add("高质量插件卡片",by_type["card"])
 add("用户可能提出的需求",by_type["intent"],16)
 add("核心功能",by_type["feature"],12)
 add("注册工具与命令",by_type["declared"],30)
 add("使用限制",by_type["caveat"],6)
 add("维护与更新",by_type["lifecycle"],2)
 return "\n\n".join(sections)[:MAX_CHARS]

def sources(wanted=None):
 for card_path in sorted((ROOT/"results"/"cards").glob("*.json")):
  try:card=json.loads(card_path.read_text())
  except Exception:continue
  if wanted and card.get("repo") not in wanted:continue
  units_path=ROOT/"results"/"units"/(card_path.stem+".jsonl")
  if not units_path.exists():continue
  try:units=[json.loads(x) for x in units_path.read_text().splitlines() if x.strip()]
  except Exception:continue
  document=repo_document(card,units)
  if not document:continue
  digest=hashlib.sha256((MODEL+"\0"+str(DIMENSIONS)+"\0repo-v1\0"+document).encode()).hexdigest()
  yield {"repo":card["repo"],"commit_sha":card["commit"],"tier":card.get("tier"),"name":clean(card.get("name")),"document":document,"document_hash":digest}

def chunks(items,size):
 batch=[]
 for item in items:
  batch.append(item)
  if len(batch)>=size:yield batch;batch=[]
 if batch:yield batch

def main():
 parser=argparse.ArgumentParser();parser.add_argument("--db",default=str(DEFAULT_DB));parser.add_argument("--batch-size",type=int,default=32);parser.add_argument("--workers",type=int,default=6);parser.add_argument("--limit",type=int);parser.add_argument("--repo",action="append");parser.add_argument("--prune",action="store_true");args=parser.parse_args()
 db=connect(pathlib.Path(args.db));existing={x[0]:x[1] for x in db.execute("select repo,document_hash from repositories")};pending=[];seen=set();scanned=0
 for item in sources(set(args.repo or [])):
  scanned+=1;seen.add(item["repo"])
  if existing.get(item["repo"])!=item["document_hash"]:pending.append(item)
  if args.limit and len(pending)>=args.limit:break
 print(json.dumps({"event":"scan","repositories":scanned,"existing":len(existing),"pending":len(pending),"model":MODEL,"dimensions":DIMENSIONS}),flush=True)
 credential=key();started=time.time();done=tokens=0
 def work(batch):
  vectors,usage=embed([x["document"] for x in batch],credential);return batch,vectors,usage
 batches=iter(chunks(pending,max(1,args.batch_size)));inflight=set()
 with concurrent.futures.ThreadPoolExecutor(max_workers=max(1,args.workers)) as pool:
  for _ in range(max(1,args.workers)*2):
   try:inflight.add(pool.submit(work,next(batches)))
   except StopIteration:break
  while inflight:
   finished,_=concurrent.futures.wait(inflight,return_when=concurrent.futures.FIRST_COMPLETED)
   for future in finished:
    inflight.remove(future);batch,vectors,usage=future.result();now=dt.datetime.now(dt.timezone.utc).isoformat()
    db.executemany("""insert into repositories(repo,commit_sha,tier,name,document,document_hash,model,dimensions,vector,embedded_at)
     values(?,?,?,?,?,?,?,?,?,?) on conflict(repo) do update set commit_sha=excluded.commit_sha,tier=excluded.tier,name=excluded.name,document=excluded.document,document_hash=excluded.document_hash,model=excluded.model,dimensions=excluded.dimensions,vector=excluded.vector,embedded_at=excluded.embedded_at""",
     [(x["repo"],x["commit_sha"],x["tier"],x["name"],x["document"],x["document_hash"],MODEL,DIMENSIONS,v.tobytes(),now) for x,v in zip(batch,vectors)])
    done+=len(batch);tokens+=int(usage.get("total_tokens") or usage.get("prompt_tokens") or 0);db.commit()
    if done%256<args.batch_size:print(json.dumps({"event":"progress","done":done,"pending":len(pending),"tokens":tokens,"repos_per_second":round(done/max(.001,time.time()-started),2)}),flush=True)
    try:inflight.add(pool.submit(work,next(batches)))
    except StopIteration:pass
 if args.prune and not args.limit and not args.repo:
  db.execute("create temp table current(repo text primary key)");db.executemany("insert into current values(?)",((x,) for x in seen));removed=db.execute("delete from repositories where repo not in current").rowcount;db.commit()
 else:removed=0
 total=db.execute("select count(*) from repositories").fetchone()[0]
 # FTS is a disposable lexical view over the canonical repository documents.
 db.execute("delete from repository_fts")
 db.execute("insert into repository_fts(repo,document) select repo,document from repositories")
 db.commit()
 print(json.dumps({"event":"complete","embedded":done,"total":total,"tokens":tokens,"pruned":removed,"seconds":round(time.time()-started,1),"db":args.db}),flush=True)

if __name__=="__main__":main()
