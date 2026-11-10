#!/usr/bin/env python3
"""Create compact, loss-aware model input from facts; source remains separately readable."""
import argparse,csv,json,pathlib
ROOT=pathlib.Path(__file__).resolve().parents[1]

def load_rows(paths):
 rows={}
 for path in paths:
  with open(path,newline="",encoding="utf-8-sig") as f:
   for r in csv.DictReader(f): rows[r["repo"]]=r
 return rows

def first_by(items,key):
 seen=set();result=[]
 for item in items:
  value=key(item)
  if value not in seen:seen.add(value);result.append(item)
 return result

def main():
 ap=argparse.ArgumentParser()
 ap.add_argument("--list",action="append",dest="lists")
 ap.add_argument("--repo",action="append")
 a=ap.parse_args()
 list_paths=[pathlib.Path(x) for x in (a.lists or [ROOT/"lists"/"high-priority.csv",ROOT/"lists"/"calibration-top30.csv"])]
 rows=load_rows(list_paths); selected=set(a.repo or [])
 out=ROOT/"work"/"_contexts";out.mkdir(parents=True,exist_ok=True)
 for p in sorted((ROOT/"results"/"facts").glob("*.json")):
  if selected and p.stem not in {r.replace("/","__") for r in selected}: continue
  f=json.loads(p.read_text())
  if selected and f["repo"] not in selected: continue
  m=f.get("manifest",{})
  compact={
   "repo":f["repo"],"commit":f["commit"],"list":rows.get(f["repo"],{}),
   "tree":{"files":f["tree"]["files"],"bytes":f["tree"].get("bytes"),"lines_by_language":f["tree"]["lines_by_language"]},
   "manifest":{k:m.get(k) for k in ("name","version","description","main","module","exports","bin","dsh","engines","license","dependencies","devDependencies") if k in m},
   "bundle_paths":[x["path"] for x in f.get("bundle",[])],
   "entries":f["entries"],"config":first_by(f["config"],lambda x:(x["name"],x["kind"])),"endpoints":first_by(f["endpoints"],lambda x:x["host"]),
   "declared":first_by(f["declared"],lambda x:(x["kind"],x["name"])),"deps":f["deps"],"quality_raw":f["quality_raw"],
   "readme_sections":[x["section"] for x in f["readme"]],"skipped":f["skipped"]}
  target=out/(p.stem+".json");target.write_text(json.dumps(compact,ensure_ascii=False,indent=2)+"\n")
  print(f["repo"],target.stat().st_size)

if __name__=="__main__":main()
