#!/usr/bin/env python3
"""Validate schemas and the cross-file invariants from STRATEGY section 3.5."""
import argparse,csv,json,pathlib,re,sys
from difflib import SequenceMatcher
import jsonschema
ROOT=pathlib.Path(__file__).resolve().parents[1]

def load_schema(name):
 schema=json.loads((ROOT/"schema"/name).read_text());schema.pop("$id",None);return schema
SCHEMAS={"facts":load_schema("facts.schema.json"),"card":load_schema("card.schema.json"),"unit":load_schema("unit.schema.json")}
TAX=set(re.findall(r"^\|\s*([a-z][a-z0-9-]*)\s*\|", (ROOT/"TAXONOMY.md").read_text(),re.M))

def evidence_ok(root,where):
 m=re.match(r"^(.+?):(\d+)(?:-(\d+))?$",where)
 if not m:return False,"not file:line"
 p=root/m.group(1)
 if not p.is_file():return False,"file missing"
 try:n=sum(1 for _ in p.open(errors="replace"))
 except OSError:return False,"unreadable"
 end=int(m.group(3) or m.group(2))
 return (end<=n,(f"line {end}>{n}" if end>n else ""))

def walk_evidence(x):
 if isinstance(x,dict):
  for k,v in x.items():
   if k=="evidence" and isinstance(v,list):
    for e in v:
     if isinstance(e,str):yield e
   else:yield from walk_evidence(v)
 elif isinstance(x,list):
  for v in x:yield from walk_evidence(v)

def validate(repo):
 slug=repo.replace("/","__");src=ROOT/"work"/slug;errors=[]
 paths={"facts":ROOT/"results"/"facts"/(slug+".json"),"card":ROOT/"results"/"cards"/(slug+".json"),"units":ROOT/"results"/"units"/(slug+".jsonl")}
 if not all(p.exists() for p in paths.values()):
  return [f"missing {k}: {p}" for k,p in paths.items() if not p.exists()]
 try:
  facts=json.loads(paths["facts"].read_text());card=json.loads(paths["card"].read_text())
 except Exception as e:
  return [f"JSON parse: {type(e).__name__}: {e}"]
 try:jsonschema.Draft202012Validator(SCHEMAS["facts"],format_checker=jsonschema.FormatChecker()).validate(facts)
 except Exception as e:errors.append("facts schema: "+str(e).splitlines()[0])
 try:jsonschema.Draft202012Validator(SCHEMAS["card"],format_checker=jsonschema.FormatChecker()).validate(card)
 except Exception as e:errors.append("card schema: "+str(e).splitlines()[0])
 units=[]
 for no,line in enumerate(paths["units"].read_text().splitlines(),1):
  try:u=json.loads(line);jsonschema.Draft202012Validator(SCHEMAS["unit"]).validate(u);units.append(u)
  except Exception as e:errors.append(f"unit line {no}: {str(e).splitlines()[0]}")
 for where in list(walk_evidence(card))+[e for u in units for e in u.get("evidence",[])]:
  ok,msg=evidence_ok(src,where)
  if not ok:errors.append(f"bad evidence {where}: {msg}")
 fact_cfg={x["name"] for x in facts["config"]}
 for x in card.get("requirements",{}).get("api_keys",[]):
  if x["name"] not in fact_cfg:errors.append(f"api key absent from facts.config: {x['name']}")
 for x in card.get("install",{}).get("config_items",[]):
  if x["name"] not in fact_cfg:errors.append(f"config item absent from facts.config: {x['name']}")
 fact_hosts={x["host"].lower() for x in facts["endpoints"]}
 for x in card.get("requirements",{}).get("external_services",[]):
  if x["host"].lower() not in fact_hosts:errors.append(f"service absent from facts.endpoints: {x['host']}")
 primary=card.get("topics",{}).get("primary")
 secondary=card.get("topics",{}).get("secondary",[])
 for topic in [primary]+secondary:
  if topic not in TAX:errors.append(f"unknown topic: {topic}")
 if primary=="other" and not card.get("topics",{}).get("proposed"):errors.append("other topic needs proposed")
 display=(facts.get("manifest",{}).get("displayName") or facts.get("manifest",{}).get("name") or repo.split("/")[-1]).lower()
 intents=[u for u in units if u.get("type")=="intent"]
 if not 8<=len(intents)<=12:errors.append(f"A-tier intent count {len(intents)} not 8..12")
 for u in intents:
  if display and display in u["text"].lower():errors.append(f"intent contains plugin name: {u['unit_id']}")
 for i,a in enumerate(intents):
  for b in intents[i+1:]:
   ratio=SequenceMatcher(None,a["text"].lower(),b["text"].lower()).ratio()
   if ratio>0.8:errors.append(f"intents too similar ({ratio:.2f}): {a['unit_id']} {b['unit_id']}")
 groups={}
 for u in units:groups.setdefault(u["type"],[]).append(u)
 if len(groups.get("card",[]))!=2:errors.append(f"card unit count {len(groups.get('card',[]))} != 2")
 if {u["lang"] for u in groups.get("card",[])}!={"zh","en"}:errors.append("card units must be zh and en")
 for u in groups.get("card",[]):
  n=len(u["text"])
  if not 150<=n<=300:errors.append(f"card length {n}: {u['unit_id']}")
 for u in groups.get("feature",[])+groups.get("caveat",[]):
  n=len(u["text"])
  if not 40<=n<=120:errors.append(f"{u['type']} length {n}: {u['unit_id']}")
 if len(groups.get("caveat",[]))>3:errors.append("more than 3 caveats")
 score=sum(card.get("quality",{}).get(k,{}).get("score",0) for k in ("completeness","code","docs","maintenance","tests"))
 expected="S" if score>=22 and card["quality"]["completeness"]["score"]==5 and card["quality"]["code"]["score"]==5 else ("A" if score>=17 else ("B" if score>=12 else ("C" if score>=7 else "D")))
 if card.get("quality",{}).get("grade")!=expected:errors.append(f"quality grade mismatch: score {score} expects {expected}")
 return errors

def main():
 ap=argparse.ArgumentParser();ap.add_argument("--list",default=str(ROOT/"lists"/"calibration-top30.csv"));ap.add_argument("--repo",action="append");a=ap.parse_args()
 with open(a.list,newline="",encoding="utf-8-sig") as f:repos=[r["repo"] for r in csv.DictReader(f)]
 if a.repo:repos=[r for r in repos if r in set(a.repo)]
 fail=0
 for repo in repos:
  errors=validate(repo)
  print(json.dumps({"repo":repo,"ok":not errors,"errors":errors},ensure_ascii=False))
  fail+=bool(errors)
 return bool(fail)
if __name__=="__main__":raise SystemExit(main())
