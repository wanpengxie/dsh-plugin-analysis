#!/usr/bin/env python3
"""Static fact extraction. Plugin files are read as data and never executed."""
from __future__ import annotations
import argparse,csv,datetime as dt,json,pathlib,re
from collections import Counter
from urllib.parse import urlparse

ROOT=pathlib.Path(__file__).resolve().parents[1]
MAX_TEXT=2*1024*1024
IGNORE={".git","node_modules","dist","build","coverage",".next",".cache","vendor"}
LANG={".js":"JavaScript",".jsx":"JavaScript",".mjs":"JavaScript",".cjs":"JavaScript",".ts":"TypeScript",".tsx":"TypeScript",".py":"Python",".go":"Go",".rs":"Rust",".java":"Java",".kt":"Kotlin",".rb":"Ruby",".php":"PHP",".sh":"Shell",".html":"HTML",".css":"CSS",".vue":"Vue",".svelte":"Svelte",".json":"JSON",".yaml":"YAML",".yml":"YAML",".toml":"TOML",".md":"Markdown"}
URL=re.compile(r"""https?://[^\s"'<>)}\]]+""")
ENV=[
 re.compile(r"""process\.env(?:\.([A-Za-z_][A-Za-z0-9_]*)|\[['"]([^'"]+)['"]\])"""),
 re.compile(r"""os\.environ(?:\.get\(\s*['"]([^'"]+)['"]|\[\s*['"]([^'"]+)['"]\s*\])"""),
 re.compile(r"""os\.getenv\(\s*['"]([^'"]+)['"]"""),
 re.compile(r"""Deno\.env\.get\(\s*['"]([^'"]+)['"]""")]
DECL=[
 ("tool",re.compile(r"""(?:registerTool|tool)\s*\(\s*['"]([^'"]+)['"](?:\s*,\s*['"]([^'"]{1,240})['"])?""")),
 ("command",re.compile(r"""(?:registerCommand|command)\s*\(\s*['"]([^'"]+)['"](?:\s*,\s*['"]([^'"]{1,240})['"])?""")),
 ("setting",re.compile(r"""(?:registerSetting|defineSetting|setting)\s*\(\s*['"]([^'"]+)['"](?:\s*,\s*['"]([^'"]{1,240})['"])?""")),
 ("hook",re.compile(r"""(?:registerHook|addHook)\s*\(\s*['"]([^'"]+)['"]"""))]
IMPORT_RE=re.compile(r"""(?:from\s*['"]([^'"]+)['"]|require\(\s*['"]([^'"]+)['"]\s*\)|import\(\s*['"]([^'"]+)['"]\s*\))""")

def read_text(p):
 try:
  if p.stat().st_size>MAX_TEXT:return None
  b=p.read_bytes()
  if b"\0" in b[:8192]:return None
  return b.decode("utf-8",errors="replace")
 except OSError:return None

def files(root):
 for p in sorted(root.rglob("*")):
  if p.is_file() and not any(x in IGNORE for x in p.relative_to(root).parts):yield p

def flatten(v):
 if isinstance(v,str):yield v
 elif isinstance(v,list):
  for x in v:yield from flatten(x)
 elif isinstance(v,dict):
  for x in v.values():yield from flatten(x)

def resolve(raw,root):
 raw=raw.split("#",1)[0].strip()
 # Import-like text inside bundled sourcemaps can be an entire source fragment
 # rather than a path. Reject it before constructing a filesystem path.
 if len(raw)>1024 or any(ch in raw for ch in ("\n","\r","\0")):return None
 if not raw or raw.startswith(("http://","https://","npm:")):return None
 if raw.startswith("./"):raw=raw[2:]
 cand=[root/raw]
 if not pathlib.Path(raw).suffix:cand += [root/(raw+s) for s in (".js",".mjs",".cjs",".ts",".tsx",".py",".yaml",".yml",".json")]
 for p in cand:
  try:p.resolve().relative_to(root.resolve())
  except ValueError:continue
  if p.is_file():return p.resolve()
 return None

def uniq(xs,key):
 out=[];seen=set()
 for x in xs:
  k=key(x)
  if k not in seen:seen.add(k);out.append(x)
 return out

def split_readme(text):
 text=re.sub(r"!\[[^\]]*\]\([^)]*\)","",text)
 sec=[];title="Introduction";body=[]
 def emit():
  nonlocal body
  raw="\n".join(body).strip();body=[]
  if not raw or re.search(r"(donat|捐赠|求\s*star|微信群|qq群|contact|联系方式|changelog|更新日志)",title,re.I):return
  raw=re.sub(r"(?s)[\x60]{3}.*?[\x60]{3}",lambda m:"\n".join(m.group(0).splitlines()[:5]),raw)
  paras=[x.strip() for x in re.split(r"\n\s*\n",raw) if x.strip()];chunk=""
  for para in paras:
   if len(chunk)+len(para)+2>500 and chunk:
    if len(chunk)>=80:sec.append({"section":title,"text":chunk[:1200]})
    chunk=""
   chunk=(chunk+"\n\n"+para).strip()
  if chunk:sec.append({"section":title,"text":chunk[:1200]})
 for line in text.splitlines():
  m=re.match(r"^#{1,6}\s+(.+?)\s*$",line)
  if m:emit();title=m.group(1).strip()
  else:body.append(line)
 emit();return sec

SLACK_WEBHOOK=re.compile(r"https://hooks\.slack\.com/services/[A-Za-z0-9_/?=&%.-]+")

def redact_secrets(value):
 if isinstance(value,str):return SLACK_WEBHOOK.sub("https://hooks.slack.com/services/[REDACTED]",value)
 if isinstance(value,list):return [redact_secrets(x) for x in value]
 if isinstance(value,dict):return {k:redact_secrets(v) for k,v in value.items()}
 return value

def extract(row, output_dir=None):
 repo,commit=row["repo"],row["commit"];root=ROOT/"work"/repo.replace("/","__")
 meta=json.loads((root/".analysis-source.json").read_text())
 if meta.get("commit")!=commit:raise ValueError("downloaded commit does not match list")
 ps=list(files(root));pkg=root/"package.json";manifest={}
 if pkg.exists():
  try:manifest=json.loads(pkg.read_text())
  except Exception:pass
 entries=[];bundle=[]
 for key in ("main","module","browser","bin","exports"):
  for raw in flatten(manifest.get(key)):
   p=resolve(raw,root)
   if p:entries.append(p.relative_to(root).as_posix())
 dsh=manifest.get("dsh") if isinstance(manifest.get("dsh"),dict) else {}
 for raw in flatten(dsh.get("bundle") if isinstance(dsh,dict) else None):
  p=resolve(raw,root)
  if p:
   rp=p.relative_to(root).as_posix();entries.append(rp);text=read_text(p)
   if text is not None:bundle.append({"path":rp,"text":text})
 # Build a conservative runtime-reachable set. Seeds are manifest/bundle entries,
 # conventional runtime entries, and files that register DSH surfaces.
 seed_paths=set(entries)
 for name in ("index.js","index.mjs","index.cjs","index.ts","src/index.js","src/index.ts","lib/index.js","lib/index.mjs","main.py","__init__.py"):
  if (root/name).is_file():seed_paths.add(name)
 for p in ps:
  rp=p.relative_to(root).as_posix();t=read_text(p)
  if t and re.search(r"\b(?:registerTool|registerCommand|registerSetting|defineSetting|registerHook|addHook)\s*\(",t):
   seed_paths.add(rp)
 runtime=set()
 queue=[root/x for x in seed_paths if (root/x).is_file()]
 while queue:
  p=queue.pop()
  if p in runtime:continue
  runtime.add(p);t=read_text(p)
  if not t:continue
  for m in IMPORT_RE.finditer(t):
   raw=next((x for x in m.groups() if x),None)
   if not raw or not raw.startswith("."):continue
   q=resolve(str((p.parent.relative_to(root)/raw).as_posix()),root)
   if q and q not in runtime:queue.append(q)
  if p.suffix.lower() in {".yaml",".yml",".json"}:
   for raw in re.findall(r"""['"]?([A-Za-z0-9_./-]+\.(?:js|mjs|cjs|ts|tsx|py|go|rs))['"]?""",t):
    q=resolve(raw,root)
    if q and q not in runtime:queue.append(q)
 outline=[];langs=Counter();config=[];endpoints=[];declared=[];total=0
 for p in ps:
  rp=p.relative_to(root).as_posix()
  if rp==".analysis-source.json":continue
  total+=p.stat().st_size
  if len(pathlib.PurePosixPath(rp).parts)<=3:outline.append(rp)
  text=read_text(p)
  if text is None:continue
  langs[LANG.get(p.suffix.lower(),"Other")]+=len(text.splitlines())
  semantic_source=p.suffix.lower() in {".js",".jsx",".mjs",".cjs",".ts",".tsx",".py",".go",".rs",".java",".kt",".rb",".php",".sh",".bash",".zsh",".json",".jsonc",".yaml",".yml",".toml",".vue",".svelte"} and p.name.lower() not in {"package-lock.json","pnpm-lock.yaml","yarn.lock","bun.lock","bun.lockb"}
  for no,line in enumerate(text.splitlines(),1):
   where=f"{rp}:{no}"
   if semantic_source:
    for pat in ENV:
     for m in pat.finditer(line):
      name=next((g for g in m.groups() if g),None)
      if name:config.append({"name":name,"kind":"env","where":where})
    for m in URL.finditer(line):
     url=m.group(0).rstrip(".,;:")
     try:host=urlparse(url).hostname
     except ValueError:host=None
     if host:endpoints.append({"host":host.lower(),"url":url[:1000],"where":where})
    for kind,pat in DECL:
     for m in pat.finditer(line):
      item={"kind":kind,"name":m.group(1),"where":where}
      if m.lastindex and m.lastindex>1 and m.group(2):item["description"]=m.group(2)
      declared.append(item)
 scripts=manifest.get("scripts")
 clean=dict(manifest)
 if isinstance(scripts,dict):clean["scripts"]={k:(v[:237]+"..." if isinstance(v,str) and len(v)>240 else v) for k,v in scripts.items()}
 readme=[]
 for name in ("README.md","README.MD","readme.md","README.en.md","README.zh-CN.md"):
  p=root/name
  if p.exists() and (t:=read_text(p)):readme.extend(split_readme(t))
 test_files=sum(bool(re.search(r"(?:^|/)(?:test|tests|__tests__)(?:/|$)|(?:\.test|\.spec)\.[^.]+$",p.relative_to(root).as_posix(),re.I)) for p in ps)
 facts={"repo":repo,"commit":commit,"extracted_at":dt.datetime.now(dt.timezone.utc).isoformat(),
  "tree":{"files":sum(p.name!=".analysis-source.json" for p in ps),"bytes":total,"lines_by_language":dict(sorted(langs.items())),"outline":outline},
  "manifest":clean,"bundle":bundle,"entries":list(dict.fromkeys(entries)),
  "config":uniq(config,lambda x:(x["name"],x["where"])),"endpoints":uniq(endpoints,lambda x:(x["host"],x["where"])),
  "declared":uniq(declared,lambda x:(x["kind"],x["name"],x["where"])),
  "deps":{"dependencies":manifest.get("dependencies",{}) if isinstance(manifest.get("dependencies"),dict) else {},"devDependencies":manifest.get("devDependencies",{}) if isinstance(manifest.get("devDependencies"),dict) else {}},
  "quality_raw":{"test_files":test_files,"has_ci":any(p.relative_to(root).as_posix().startswith(".github/workflows/") for p in ps),"has_lint":any(p.name.lower() in {"eslint.config.js","eslint.config.mjs",".eslintrc",".eslintrc.json","ruff.toml",".flake8","biome.json"} for p in ps),"typed":any(p.suffix.lower() in {".ts",".tsx"} or p.name in {"py.typed","mypy.ini"} for p in ps),"commits":int(row.get("commits") or 0),"pushed_at":row.get("pushed_at") or "","created_at":row.get("created_at") or ""},
  "runtime_files":sorted(p.relative_to(root).as_posix() for p in runtime),"readme":readme,"skipped":[x["path"] for x in meta.get("skipped",[])]}
 facts=redact_secrets(facts)
 out=pathlib.Path(output_dir) if output_dir else ROOT/"results"/"facts"
 out.mkdir(parents=True,exist_ok=True);target=out/(repo.replace("/","__")+".json")
 target.write_text(json.dumps(facts,ensure_ascii=False,indent=2)+"\n")
 return {"repo":repo,"files":facts["tree"]["files"]}

def main():
 ap=argparse.ArgumentParser();ap.add_argument("--list",default=str(ROOT/"lists"/"calibration-top30.csv"));ap.add_argument("--repo",action="append");ap.add_argument("--output-dir");a=ap.parse_args()
 with open(a.list,newline="",encoding="utf-8-sig") as f:rows=list(csv.DictReader(f))
 if a.repo:rows=[r for r in rows if r["repo"] in set(a.repo)]
 fail=0
 for row in rows:
  try:print(json.dumps(extract(row,a.output_dir),ensure_ascii=False),flush=True)
  except Exception as e:fail+=1;print(json.dumps({"repo":row["repo"],"error":f"{type(e).__name__}: {e}"},ensure_ascii=False),flush=True)
 return bool(fail)
if __name__=="__main__":raise SystemExit(main())
