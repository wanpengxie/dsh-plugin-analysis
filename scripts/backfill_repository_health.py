#!/usr/bin/env python3
"""Backfill deterministic repository health into historical facts/cards/units."""
from __future__ import annotations
import argparse,csv,datetime as dt,json,pathlib,sqlite3
from lifecycle import derive_repository_health,repository_health_text

ROOT=pathlib.Path(__file__).resolve().parents[1]

def rows(paths):
 out={}
 for path in paths:
  with open(path,newline="",encoding="utf-8-sig") as handle:
   for row in csv.DictReader(handle):out[row["repo"]]={**out.get(row["repo"],{}),**row}
 return out

def claimed():
 path=ROOT/"work"/"supervisor.sqlite3"
 if not path.exists():return set()
 db=sqlite3.connect(path)
 try:return {x[0] for x in db.execute("select repo from tasks where state='claimed'")}
 finally:db.close()

def main():
 parser=argparse.ArgumentParser();parser.add_argument("--list",action="append",required=True);parser.add_argument("--apply",action="store_true");parser.add_argument("--limit",type=int);args=parser.parse_args()
 metadata=rows(args.list);busy=claimed();now=dt.datetime.now(dt.timezone.utc).isoformat();planned=[];skipped=[]
 for fp in sorted((ROOT/"results"/"facts").glob("*.json")):
  facts=json.loads(fp.read_text());repo=facts.get("repo");row=metadata.get(repo)
  if not row:skipped.append({"repo":repo,"reason":"metadata missing"});continue
  if repo in busy:skipped.append({"repo":repo,"reason":"claimed"});continue
  card_path=ROOT/"results"/"cards"/(fp.stem+".json");units_path=ROOT/"results"/"units"/(fp.stem+".jsonl")
  if not card_path.exists() or not units_path.exists():skipped.append({"repo":repo,"reason":"result missing"});continue
  card=json.loads(card_path.read_text());texts=[x.get("text","") for x in facts.get("readme",[])]
  texts.append(card.get("quality",{}).get("maintenance",{}).get("reason",""))
  health=derive_repository_health(row,ROOT/"work"/fp.stem,now,texts)
  if facts.get("repository_health")==health and card.get("repository_health")==health:continue
  planned.append((fp,card_path,units_path,facts,card,health))
  if args.limit and len(planned)>=args.limit:break
 print(json.dumps({"apply":args.apply,"planned":len(planned),"skipped":len(skipped),"claimed_skipped":sum(x["reason"]=="claimed" for x in skipped)},ensure_ascii=False))
 if not args.apply:return
 for fp,card_path,units_path,facts,card,health in planned:
  facts["repository_health"]=health;card["repository_health"]=health
  units=[json.loads(x) for x in units_path.read_text().splitlines() if x.strip()]
  units=[x for x in units if x.get("type")!="lifecycle"]
  display=facts.get("manifest",{}).get("displayName") or facts.get("manifest",{}).get("name") or facts["repo"].split("/")[-1]
  units.append({"unit_id":f"{fp.stem}#lifecycle-status","repo":facts["repo"],"commit":facts["commit"],"type":"lifecycle","lang":"zh","text":f"{display} 的维护与更新元数据：{repository_health_text(health)}。","source":"extracted"})
  fp.write_text(json.dumps(facts,ensure_ascii=False,indent=2)+"\n");card_path.write_text(json.dumps(card,ensure_ascii=False,indent=2)+"\n");units_path.write_text("".join(json.dumps(x,ensure_ascii=False,separators=(",",":"))+"\n" for x in units))
 print(json.dumps({"updated":len(planned)},ensure_ascii=False))

if __name__=="__main__":main()
