#!/usr/bin/env python3
"""Add GitHub lifecycle metadata to a CSV before incremental analysis."""
from __future__ import annotations

import argparse,csv,datetime as dt,json,os,pathlib,shutil,statistics,subprocess,time,urllib.request

FIELDS = ("archived","disabled","has_issues","open_issues_count","github_updated_at","commits_30d","commits_90d","commits_365d","active_months_12m","median_commit_interval_days","issue_sample_size","issue_open_sample","issue_closed_sample","issue_close_rate_sample","issue_median_close_days_sample","issues_updated_90d_sample","latest_issue_updated_at")

def fetch(repo, token=None):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "dsh-plugin-analysis/1"}
    if token: headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(f"https://api.github.com/repos/{repo}", headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response: return json.load(response)

def fetch_list(repo, endpoint, token=None):
    headers={"Accept":"application/vnd.github+json","User-Agent":"dsh-plugin-analysis/1"}
    if token:headers["Authorization"]=f"Bearer {token}"
    request=urllib.request.Request(f"https://api.github.com/repos/{repo}/{endpoint}",headers=headers)
    with urllib.request.urlopen(request,timeout=30) as response:return json.load(response)

def github_time(value):
    return dt.datetime.fromisoformat(value.replace("Z","+00:00")) if value else None

def detailed_metrics(repo, token):
    now=dt.datetime.now(dt.timezone.utc)
    commits=fetch_list(repo,"commits?per_page=100",token)
    dates=[github_time(x.get("commit",{}).get("committer",{}).get("date")) for x in commits]
    dates=[x for x in dates if x]
    intervals=[(a-b).total_seconds()/86400 for a,b in zip(dates,dates[1:]) if a>=b]
    issues=[x for x in fetch_list(repo,"issues?state=all&sort=updated&direction=desc&per_page=100",token) if "pull_request" not in x]
    closed=[x for x in issues if x.get("state")=="closed"]
    close_days=[]
    for item in closed:
        created=github_time(item.get("created_at"));closed_at=github_time(item.get("closed_at"))
        if created and closed_at:close_days.append((closed_at-created).total_seconds()/86400)
    return {
        "commits_30d":sum((now-x).days<=30 for x in dates),"commits_90d":sum((now-x).days<=90 for x in dates),"commits_365d":sum((now-x).days<=365 for x in dates),
        "active_months_12m":len({(x.year,x.month) for x in dates if (now-x).days<=365}),"median_commit_interval_days":round(statistics.median(intervals),2) if intervals else "",
        "issue_sample_size":len(issues),"issue_open_sample":sum(x.get("state")=="open" for x in issues),"issue_closed_sample":len(closed),
        "issue_close_rate_sample":round(len(closed)/len(issues),4) if issues else "","issue_median_close_days_sample":round(statistics.median(close_days),2) if close_days else "",
        "issues_updated_90d_sample":sum((now-github_time(x.get("updated_at"))).days<=90 for x in issues if github_time(x.get("updated_at"))),"latest_issue_updated_at":issues[0].get("updated_at","") if issues else "",
    }

def main():
    parser=argparse.ArgumentParser();parser.add_argument("--list",required=True);parser.add_argument("--output",required=True);parser.add_argument("--delay",type=float,default=.2);parser.add_argument("--basic-only",action="store_true");args=parser.parse_args()
    source=pathlib.Path(args.list);target=pathlib.Path(args.output)
    if source.resolve()==target.resolve():raise SystemExit("--output must differ from --list")
    with source.open(newline="",encoding="utf-8-sig") as handle:
        reader=csv.DictReader(handle);rows=list(reader);names=list(reader.fieldnames or [])
    for field in FIELDS:
        if field not in names:names.append(field)
    token=os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token and shutil.which("gh"):
        auth=subprocess.run(["gh","auth","token"],text=True,capture_output=True)
        if auth.returncode==0:token=auth.stdout.strip()
    progress=target.with_suffix(target.suffix+".progress.jsonl");cached={}
    if progress.exists():
        for line in progress.read_text().splitlines():
            try:item=json.loads(line);cached[item["repo"]]=item
            except (json.JSONDecodeError,KeyError):pass
    failures=0
    for row in rows:
        if row["repo"] in cached:
            row.update(cached[row["repo"]]);continue
        try:
            data=fetch(row["repo"],token);row["archived"]=str(bool(data.get("archived"))).lower();row["disabled"]=str(bool(data.get("disabled"))).lower();row["has_issues"]=str(bool(data.get("has_issues"))).lower();row["open_issues_count"]=data.get("open_issues_count","");row["github_updated_at"]=data.get("updated_at") or ""
            if data.get("pushed_at"):row["pushed_at"]=data["pushed_at"]
            if not args.basic_only:row.update(detailed_metrics(row["repo"],token))
            with progress.open("a",encoding="utf-8") as handle:handle.write(json.dumps({k:row.get(k,"") for k in ["repo",*FIELDS]},ensure_ascii=False)+"\n")
        except Exception as exc:
            failures+=1;print(json.dumps({"repo":row.get("repo"),"error":f"{type(exc).__name__}: {exc}"}),flush=True)
        time.sleep(max(0,args.delay))
    target.parent.mkdir(parents=True,exist_ok=True)
    with target.open("w",newline="",encoding="utf-8") as handle:
        writer=csv.DictWriter(handle,fieldnames=names);writer.writeheader();writer.writerows(rows)
    print(json.dumps({"rows":len(rows),"cached":len(cached),"failures":failures,"output":str(target),"progress":str(progress)}));return bool(failures)

if __name__=="__main__":raise SystemExit(main())
