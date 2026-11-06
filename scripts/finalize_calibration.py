#!/usr/bin/env python3
"""Finalize calibration: separate valid outputs from failed artifacts and write summaries."""
import csv,datetime as dt,json,pathlib,shutil
import validate_results
ROOT=pathlib.Path(__file__).resolve().parents[1]
with open(ROOT/"lists"/"calibration-top30.csv",newline="",encoding="utf-8-sig") as f: rows=list(csv.DictReader(f))
failed_dir=ROOT/"results"/"failed";artifacts=failed_dir/"artifacts"
failed_dir.mkdir(parents=True,exist_ok=True);artifacts.mkdir(parents=True,exist_ok=True)
summary=[];progress=[]
for row in rows:
 repo=row["repo"];slug=repo.replace("/","__");errors=validate_results.validate(repo);ok=not errors
 if ok:
  card=json.loads((ROOT/"results"/"cards"/(slug+".json")).read_text())
  units=[json.loads(x) for x in (ROOT/"results"/"units"/(slug+".jsonl")).read_text().splitlines() if x.strip()]
  counts={}
  for u in units:counts[u["type"]]=counts.get(u["type"],0)+1
  item={"rank":int(row["rank"]),"repo":repo,"status":"success","topic":card["topics"]["primary"],"risk":card["risk"]["level"],"quality":card["quality"]["grade"],"unit_counts":counts,"unit_total":len(units),"worker":card["worker"],"elapsed_seconds":None}
 else:
  record={"repo":repo,"commit":row["commit"],"tier":"A","status":"failed","errors":errors,"attempts":2,"worker":"gpt-6-luna","recorded_at":dt.datetime.now(dt.timezone.utc).isoformat()}
  (failed_dir/(slug+".json")).write_text(json.dumps(record,ensure_ascii=False,indent=2)+"\n")
  dest=artifacts/slug;dest.mkdir(parents=True,exist_ok=True)
  for directory,suffix in (("cards",".json"),("generated",".jsonl"),("units",".jsonl")):
   p=ROOT/"results"/directory/(slug+suffix)
   if p.exists():shutil.move(str(p),str(dest/(directory+suffix)))
  item={"rank":int(row["rank"]),"repo":repo,"status":"failed","topic":None,"risk":None,"quality":None,"unit_counts":{},"unit_total":0,"worker":"gpt-6-luna","elapsed_seconds":None,"errors":errors}
 summary.append(item)
 progress.append({"repo":repo,"tier":"A","status":item["status"],"worker":item["worker"],"timing":{"download_seconds":None,"extract_seconds":None,"model_seconds":None,"validate_seconds":None,"total_seconds":None},"note":"Calibration run predates reliable per-stage timers; wall-clock throughput is reported in calibration-summary.json."})
(ROOT/"results"/"progress.jsonl").write_text("".join(json.dumps(x,ensure_ascii=False)+"\n" for x in progress))
started=dt.datetime.fromisoformat("2026-11-06T15:34:00+00:00");ended=dt.datetime.now(dt.timezone.utc);wall=(ended-started).total_seconds()
recommendations=[
 "STRATEGY/facts schema should define suspicious_counts and state that suspicious contains bounded representative locations; otherwise large repositories create hundreds of repetitive risk checks.",
 "INDEX-TEXTS should define separate Chinese-character and English-word/character limits. Applying 150-300 characters to English caused repeated otherwise-correct failures.",
 "Schema/evidence rules need a representation for list-derived maintenance facts (commit count, created_at, pushed_at); forcing file:line evidence makes workers cite unrelated package files.",
 "facts.config extraction and validator should cover declarative settings, not only environment-variable regexes, or valid configuration claims will be rejected.",
 "README extraction needs an explicit per-repository cap/deduplication rule. 'all useful sections' produced 2,190 README units across 30 repositories, far above the documented common 2-10.",
 "Unit count and text-length constraints should move into schema where possible; currently schema accepts outputs that the separate validator rejects.",
]
payload={"generated_at":ended.isoformat(),"scope":"lists/calibration-top30.csv only","repositories":len(summary),"successes":sum(x["status"]=="success" for x in summary),"failures":sum(x["status"]=="failed" for x in summary),"wall_seconds":round(wall,1),"wall_seconds_per_repo":round(wall/len(summary),1),"timing_note":"Actual end-to-end wall-clock throughput including script calibration and 10-way model concurrency. Per-repository stage timers were not reliably captured in this calibration and are null in progress.jsonl.","recommendations":recommendations,"repositories_detail":summary}
(ROOT/"results"/"calibration-summary.json").write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n")
report=ROOT/"report";report.mkdir(exist_ok=True)
lines=["# Calibration top-30 report","",f"- Scope: 30 fixed commits from lists/calibration-top30.csv","- Static analysis only; no plugin code executed",f"- Valid: {payload['successes']}; failed after one rewrite: {payload['failures']}",f"- End-to-end wall time: {wall/60:.1f} min; amortized {wall/len(summary):.1f} s/repo with 10-way concurrency","- Per-repository stage timing was not reliably captured; see recommendation below.","","| Rank | Repository | Status | Topic | Risk | Quality | Units |","|---:|---|---|---|---|---|---:|"]
for x in summary:
 lines.append(f"| {x['rank']} | {x['repo']} | {x['status']} | {x.get('topic') or '—'} | {x.get('risk') or '—'} | {x.get('quality') or '—'} | {x['unit_total']} |")
lines += ["","## Failed repositories",""]
for x in summary:
 if x["status"]=="failed":lines.append(f"- {x['repo']}: {'; '.join(x['errors'][:4])}")
lines += ["","## Recommended specification changes",""]+[f"- {x}" for x in recommendations]
(report/"calibration.md").write_text("\n".join(lines)+"\n")
print(json.dumps({"success":payload["successes"],"failed":payload["failures"],"wall_seconds_per_repo":payload["wall_seconds_per_repo"]}))
