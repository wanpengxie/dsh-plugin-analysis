#!/usr/bin/env python3
"""Merge model-generated units with deterministic declared and README units."""
import argparse,json,pathlib,re
ROOT=pathlib.Path(__file__).resolve().parents[1]

def lang(text):
 zh=sum("\u4e00"<=c<="\u9fff" for c in text)
 return "zh" if zh>max(2,len(text)//20) else "en"

def ident(s):
 s=re.sub(r"[^A-Za-z0-9_.-]+","-",s).strip("-")
 return s[:70] or "item"

def extracted_units(facts):
 repo=facts["repo"];slug=repo.replace("/","__");commit=facts["commit"]
 display=facts.get("manifest",{}).get("displayName") or facts.get("manifest",{}).get("name") or repo.split("/")[-1]
 out=[];used=set()
 for i,item in enumerate(facts["declared"],1):
  base=f"declared-{ident(item['kind']+'-'+item['name'])}";uid=f"{slug}#{base}"
  if uid in used:uid=f"{uid}-{i}"
  used.add(uid)
  desc=("："+item["description"]) if item.get("description") else ""
  label={"tool":"工具","command":"命令","setting":"设置项","ui":"界面项","hook":"钩子","other":"声明项"}.get(item["kind"],"声明项")
  out.append({"unit_id":uid,"repo":repo,"commit":commit,"type":"declared","lang":lang(item.get("description","")),"text":f"{display} 提供{label} {item['name']}{desc}","source":"extracted","evidence":[item["where"]]})
 for i,item in enumerate(facts["readme"],1):
  text=item["text"].strip()
  if len(text)<4:continue
  out.append({"unit_id":f"{slug}#readme-{i}","repo":repo,"commit":commit,"type":"readme","lang":lang(text),"text":f"{display} README · {item['section']}：{text}"[:1200],"source":"extracted","section":item["section"]})
 return out

def main():
 ap=argparse.ArgumentParser();ap.add_argument("--repo",action="append");a=ap.parse_args()
 factsdir=ROOT/"results"/"facts";gendir=ROOT/"results"/"generated";outdir=ROOT/"results"/"units";outdir.mkdir(parents=True,exist_ok=True)
 paths=sorted(factsdir.glob("*.json"))
 if a.repo:paths=[p for p in paths if json.loads(p.read_text())["repo"] in set(a.repo)]
 for fp in paths:
  facts=json.loads(fp.read_text());slug=facts["repo"].replace("/","__");units=[]
  gp=gendir/(slug+".jsonl")
  if gp.exists():
   for no,line in enumerate(gp.read_text().splitlines(),1):
    if line.strip():units.append(json.loads(line))
  units.extend(extracted_units(facts))
  target=outdir/(slug+".jsonl")
  target.write_text("".join(json.dumps(x,ensure_ascii=False,separators=(",",":"))+"\n" for x in units))
  print(json.dumps({"repo":facts["repo"],"generated":len(units)-len(extracted_units(facts)),"total":len(units)},ensure_ascii=False))
if __name__=="__main__":main()
