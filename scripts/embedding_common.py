#!/usr/bin/env python3
"""Shared OpenRouter embedding helpers. Never logs credential values."""
from __future__ import annotations
import json,math,os,pathlib,re,time,urllib.error,urllib.request
import numpy as np

MODEL="qwen/qwen3-embedding-8b"
DIMENSIONS=1024
API="https://openrouter.ai/api/v1/embeddings"

def key():
 value=os.environ.get("OPENROUTER_EMB_KEY")
 if value:return value
 path=pathlib.Path.home()/".config"/"atoll"/"env"
 if not path.exists():raise RuntimeError("OPENROUTER_EMB_KEY is not configured")
 match=re.search(r'(?m)^\s*(?:export\s+)?OPENROUTER_EMB_KEY\s*=\s*(.*?)\s*$',path.read_text())
 if not match:raise RuntimeError("OPENROUTER_EMB_KEY is absent from ~/.config/atoll/env")
 value=match.group(1).strip().strip("'\"")
 if not value:raise RuntimeError("OPENROUTER_EMB_KEY is empty")
 return value

def embed(texts,credential=None,retries=7):
 payload=json.dumps({"model":MODEL,"input":texts,"dimensions":DIMENSIONS},ensure_ascii=False).encode()
 request=urllib.request.Request(API,data=payload,method="POST",headers={"Authorization":"Bearer "+(credential or key()),"Content-Type":"application/json","User-Agent":"atoll-dsh-index/1"})
 for attempt in range(retries):
  try:
   with urllib.request.urlopen(request,timeout=180) as response:data=json.load(response)
   ordered=sorted(data.get("data",[]),key=lambda x:x.get("index",0))
   if len(ordered)!=len(texts):raise RuntimeError(f"embedding count mismatch: {len(ordered)} != {len(texts)}")
   vectors=[]
   for item in ordered:
    vector=np.asarray(item.get("embedding",[]),dtype=np.float32)
    if vector.shape!=(DIMENSIONS,) or not np.isfinite(vector).all():raise RuntimeError("invalid embedding vector")
    norm=float(np.linalg.norm(vector))
    if not norm:raise RuntimeError("zero embedding vector")
    vectors.append((vector/norm).astype(np.float16))
   return vectors,data.get("usage",{})
  except urllib.error.HTTPError as exc:
   if exc.code not in {408,409,429,500,502,503,504,524,529} or attempt+1==retries:
    detail=exc.read(500).decode(errors="replace");raise RuntimeError(f"OpenRouter HTTP {exc.code}: {detail}") from exc
  except (urllib.error.URLError,TimeoutError) as exc:
   if attempt+1==retries:raise
  time.sleep(min(60,2**attempt))
 raise RuntimeError("embedding retries exhausted")
