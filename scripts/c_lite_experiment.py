#!/usr/bin/env python3
"""Build an A+B capability baseline and route a deterministic C-lite sample."""
from __future__ import annotations

import argparse
import collections
import csv
import json
import math
import pathlib
import re
import subprocess
import shutil

ROOT = pathlib.Path(__file__).resolve().parents[1]
EXP = ROOT / "experiments" / "c-lite"
TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_.+-]{1,}|[\u4e00-\u9fff]")


def tokens(text: str) -> list[str]:
    raw = TOKEN_RE.findall((text or "").lower())
    latin = [x for x in raw if not (len(x) == 1 and "\u4e00" <= x <= "\u9fff")]
    han = "".join(x for x in raw if len(x) == 1 and "\u4e00" <= x <= "\u9fff")
    return latin + [han[i:i + 2] for i in range(max(0, len(han) - 1))]


def tracked(pattern: str) -> list[pathlib.Path]:
    out = subprocess.run(
        ["git", "ls-files", pattern], cwd=ROOT, text=True, capture_output=True, check=True
    ).stdout.splitlines()
    return [ROOT / x for x in out]


def sample(count: int) -> None:
    with (ROOT / "lists" / "zero-star.csv").open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    if count < 1 or count > len(rows):
        raise SystemExit("invalid sample size")
    indexes = [round(i * (len(rows) - 1) / (count - 1)) for i in range(count)] if count > 1 else [0]
    chosen = [rows[i] for i in indexes]
    EXP.mkdir(parents=True, exist_ok=True)
    with (EXP / "sample.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=rows[0].keys())
        writer.writeheader(); writer.writerows(chosen)
    print(json.dumps({"sample": len(chosen), "first": chosen[0]["repo"], "last": chosen[-1]["repo"]}))


def baseline() -> None:
    with (ROOT / "lists" / "high-priority.csv").open(encoding="utf-8-sig", newline="") as fh:
        allowed = {r["repo"] for r in csv.DictReader(fh)}
    docs: dict[str, list[str]] = collections.defaultdict(list)
    for path in tracked("results/cards/*.json"):
        try: card = json.loads(path.read_text())
        except Exception: continue
        repo = card.get("repo")
        if not repo or repo not in allowed: continue
        one = card.get("one_liner", {})
        docs[repo].extend([one.get("zh", ""), one.get("en", "")])
        docs[repo].extend(card.get("keywords", []))
        docs[repo].extend(card.get("surfaces", []))
        topics = card.get("topics", {})
        docs[repo].append(str(topics.get("primary", "")))
        docs[repo].extend(topics.get("secondary", []))
    for path in tracked("results/units/*.jsonl"):
        try:
            for line in path.read_text().splitlines():
                unit = json.loads(line); repo = unit.get("repo")
                if repo in allowed and unit.get("type") in {"card", "intent", "feature", "declared"}:
                    docs[repo].append(unit.get("text", ""))
        except Exception:
            continue
    EXP.mkdir(parents=True, exist_ok=True)
    with (EXP / "ab-baseline.jsonl").open("w", encoding="utf-8") as fh:
        for repo in sorted(docs):
            counts = collections.Counter(tokens("\n".join(docs[repo])))
            fh.write(json.dumps({"repo": repo, "tokens": counts}, ensure_ascii=False) + "\n")
    print(json.dumps({"baseline_repos": len(docs)}))


def load_sample() -> list[dict]:
    with (EXP / "sample.csv").open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def c_text(row: dict, facts: dict) -> str:
    manifest = facts.get("manifest", {})
    bits = [row.get("description", ""), str(manifest.get("name", "")), str(manifest.get("description", ""))]
    kw = manifest.get("keywords", [])
    if isinstance(kw, list): bits.extend(map(str, kw))
    for item in facts.get("declared", []): bits.extend([item.get("kind", ""), item.get("name", ""), item.get("description", "")])
    bits.extend(facts.get("entries", []))
    for item in facts.get("readme", [])[:8]: bits.extend([item.get("section", ""), item.get("text", "")[:600]])
    return "\n".join(bits)


def classify() -> None:
    rows = load_sample()
    base = [json.loads(x) for x in (EXP / "ab-baseline.jsonl").read_text().splitlines() if x]
    df = collections.Counter()
    for doc in base: df.update(doc["tokens"].keys())
    n = len(base)
    def weight(counts):
        out = {t: (1 + math.log(c)) * math.log((n + 1) / (df.get(t, 0) + 1)) for t, c in counts.items()}
        norm = math.sqrt(sum(v * v for v in out.values())) or 1.0
        return {t: v / norm for t, v in out.items()}
    weighted = [(d["repo"], weight(d["tokens"])) for d in base]
    inv: dict[str, list[tuple[int, float]]] = collections.defaultdict(list)
    for i, (_, vec) in enumerate(weighted):
        for t, v in vec.items(): inv[t].append((i, v))
    decisions=[]
    facts_dir=EXP/"facts"
    for row in rows:
        repo=row["repo"]; slug=repo.replace("/","__"); p=facts_dir/(slug+".json")
        if not p.exists():
            decisions.append({"repo":repo,"decision":"failed","reasons":["facts_missing"]}); continue
        f=json.loads(p.read_text()); q=weight(collections.Counter(tokens(c_text(row,f))))
        scores=collections.defaultdict(float)
        for t,qv in q.items():
            for i,dv in inv.get(t,[]): scores[i]+=qv*dv
        nearest=sorted(((v,weighted[i][0]) for i,v in scores.items()),reverse=True)[:5]
        lines=sum(v for k,v in f.get("tree",{}).get("lines_by_language",{}).items() if k not in {"Markdown","JSON","YAML"})
        surfaces=len(f.get("declared",[]))+len(f.get("entries",[]))+len(f.get("bundle",[]))
        qr=f.get("quality_raw",{}); commits=int(qr.get("commits") or 0)
        files=f.get("tree",{}).get("files",0); tests=int(qr.get("test_files") or 0)
        top=nearest[0][0] if nearest else 0.0
        promotion_score=sum((lines>=1000,files>=15,commits>=5,tests>0,bool(qr.get("has_ci")),
                             bool(qr.get("typed")),len(f.get("declared",[]))>0,top<0.06))
        reasons=[f"source_lines={lines}",f"files={files}",f"surfaces={surfaces}",f"commits={commits}",
                 f"ab_top_similarity={top:.3f}",f"promotion_score={promotion_score}/8"]
        if surfaces==0 and lines<80 and commits<=1:
            decision="drop"; reasons.append("thin_without_runtime_surface")
        elif promotion_score>=6:
            decision="promote"; reasons.append("strong_multi_signal_candidate")
        else:
            decision="lite"; reasons.append("retain_light_record")
        decisions.append({"repo":repo,"decision":decision,"reasons":reasons,
                          "signals":{"source_lines":lines,"files":files,"surfaces":surfaces,"declared":len(f.get("declared",[])),
                                     "commits":commits,"tests":tests,"ci":bool(qr.get("has_ci")),"typed":bool(qr.get("typed")),
                                     "promotion_score":promotion_score},
                          "nearest_ab":[{"repo":r,"similarity":round(s,4)} for s,r in nearest]})
    EXP.mkdir(parents=True,exist_ok=True)
    with (EXP/"decisions.jsonl").open("w",encoding="utf-8") as fh:
        for d in decisions:fh.write(json.dumps(d,ensure_ascii=False)+"\n")
    counts=collections.Counter(d["decision"] for d in decisions)
    boundary=sum(d.get("signals",{}).get("promotion_score")==5 for d in decisions)
    summary={"sample":len(decisions),"counts":dict(counts),"boundary_score_5":boundary,
             "projected_at_12642":{k:round(v/len(decisions)*12642) for k,v in counts.items()},
             "thresholds":{"drop":"surfaces=0, source_lines<80, commits<=1","promote":"at least 6 of 8 strong/auxiliary signals; novelty contributes at most one"}}
    (EXP/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n")
    promote=[d for d in decisions if d["decision"]=="promote"]
    report=["# C-lite 100 仓库实验结果","",f"- promote: {counts.get('promote',0)}",f"- lite: {counts.get('lite',0)}",
            f"- drop: {counts.get('drop',0)}",f"- failed: {counts.get('failed',0)}",f"- 边界分数 5: {boundary}","",
            "## Promote 候选","","| 仓库 | 分数 | 最近 A+B 项目 | 相似度 |","|---|---:|---|---:|"]
    for d in promote:
        near=d.get("nearest_ab",[{}])[0]
        report.append(f"| {d['repo']} | {d['signals']['promotion_score']}/8 | {near.get('repo','')} | {near.get('similarity',0):.4f} |")
    report += ["","## 解释","","晋级由多信号共同决定；近邻相似度最多贡献 1 分。`decisions.jsonl` 保留每个样本的完整信号、理由与 Top-5 近邻。",""]
    (EXP/"report.md").write_text("\n".join(report),encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False))


def cleanup(apply: bool) -> None:
    removed=[]; skipped=[]
    for row in load_sample():
        repo=row["repo"]; target=ROOT/"work"/repo.replace("/","__")
        if not target.exists(): continue
        marker=target/".analysis-source.json"
        try: meta=json.loads(marker.read_text())
        except Exception: skipped.append({"repo":repo,"reason":"missing_or_invalid_marker"});continue
        if meta.get("repo")!=repo or meta.get("commit")!=row["commit"]:
            skipped.append({"repo":repo,"reason":"marker_mismatch"});continue
        if target.is_symlink() or target.resolve().parent!=(ROOT/"work").resolve():
            skipped.append({"repo":repo,"reason":"unsafe_target"});continue
        if apply: shutil.rmtree(target)
        removed.append(repo)
    print(json.dumps({"mode":"apply" if apply else "dry-run","eligible":len(removed),"skipped":skipped},ensure_ascii=False))


def main():
    ap=argparse.ArgumentParser(); sub=ap.add_subparsers(dest="cmd",required=True)
    s=sub.add_parser("sample");s.add_argument("--count",type=int,default=100)
    sub.add_parser("baseline");sub.add_parser("classify")
    c=sub.add_parser("cleanup");c.add_argument("--apply",action="store_true")
    a=ap.parse_args()
    {"sample":lambda:sample(a.count),"baseline":baseline,"classify":classify,
     "cleanup":lambda:cleanup(a.apply)}[a.cmd]()


if __name__=="__main__":main()
