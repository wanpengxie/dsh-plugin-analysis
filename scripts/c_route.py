#!/usr/bin/env python3
"""Deterministically route one C-tier facts file to lite or promote."""
from __future__ import annotations
import argparse,json,pathlib

ROOT=pathlib.Path(__file__).resolve().parents[1]

def route(repo):
 slug=repo.replace("/","__");f=json.loads((ROOT/"results"/"facts"/(slug+".json")).read_text())
 q=f.get("quality_raw",{}); lines=sum(v for k,v in f.get("tree",{}).get("lines_by_language",{}).items() if k not in {"Markdown","JSON","YAML"})
 files=int(f.get("tree",{}).get("files",0));commits=int(q.get("commits") or 0);tests=int(q.get("test_files") or 0);declared=len(f.get("declared",[]))
 checks={"source_lines_1000":lines>=1000,"files_15":files>=15,"commits_5":commits>=5,"has_tests":tests>0,
         "has_ci":bool(q.get("has_ci")),"typed":bool(q.get("typed")),"declared_surface":declared>0}
 score=sum(checks.values());mode="promote" if score>=6 else "lite"
 payload={"repo":repo,"commit":f["commit"],"mode":mode,"score":score,"checks":checks,
          "signals":{"source_lines":lines,"files":files,"commits":commits,"tests":tests,"declared":declared}}
 out=ROOT/"results"/"c-routing";out.mkdir(parents=True,exist_ok=True);(out/(slug+".json")).write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n")
 print(json.dumps(payload,ensure_ascii=False));return payload

def main():
 ap=argparse.ArgumentParser();ap.add_argument("--repo",required=True);a=ap.parse_args();route(a.repo)
if __name__=="__main__":main()
