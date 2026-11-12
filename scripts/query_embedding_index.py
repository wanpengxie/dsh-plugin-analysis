#!/usr/bin/env python3
"""Hybrid candidate retrieval: lexical union vector, for agent reranking."""
from __future__ import annotations
import argparse,heapq,json,pathlib,re,sqlite3
import numpy as np
from embedding_common import embed

ROOT=pathlib.Path(__file__).resolve().parents[1]
DEFAULT_DB=ROOT/"vector-index"/"repo-qwen3-embedding-8b-1024.sqlite3"

def fts_query(query):
 terms=[]
 terms.extend(re.findall(r'[A-Za-z0-9_.+-]{2,}',query.lower()))
 for sequence in re.findall(r'[\u4e00-\u9fff]+',query):
  if len(sequence)<3:terms.append(sequence)
  else:terms.extend(sequence[i:i+3] for i in range(len(sequence)-2))
 terms=list(dict.fromkeys(x.replace('"','') for x in terms if x))
 return " OR ".join('"'+x+'"' for x in terms[:80])

def main():
 parser=argparse.ArgumentParser();parser.add_argument("query");parser.add_argument("--db",default=str(DEFAULT_DB));parser.add_argument("--vector-k",type=int,default=60);parser.add_argument("--keyword-k",type=int,default=60);parser.add_argument("--output-k",type=int,default=50);parser.add_argument("--full-document",action="store_true");parser.add_argument("--chunk",type=int,default=4096);args=parser.parse_args()
 db=sqlite3.connect(args.db)
 instruction="Instruct: Retrieve DSH plugins relevant to the user's capability request.\nQuery: "+args.query
 vectors,_=embed([instruction]);query=vectors[0].astype(np.float32)
 cursor=db.execute("select repo,vector from repositories");vector_heap=[]
 while True:
  rows=cursor.fetchmany(args.chunk)
  if not rows:break
  matrix=np.vstack([np.frombuffer(x[1],dtype=np.float16).astype(np.float32) for x in rows]);scores=matrix@query
  for row,score in zip(rows,scores):
   item=(float(score),row[0])
   if len(vector_heap)<args.vector_k:heapq.heappush(vector_heap,item)
   elif score>vector_heap[0][0]:heapq.heapreplace(vector_heap,item)
 vector_rows=sorted(vector_heap,reverse=True);vector_rank={repo:(rank,score) for rank,(score,repo) in enumerate(vector_rows,1)}
 lexical_rows=[];expression=fts_query(args.query)
 if expression:
  lexical_rows=db.execute("select repo,bm25(repository_fts) score from repository_fts where repository_fts match ? order by score limit ?",(expression,args.keyword_k)).fetchall()
 lexical_rank={repo:(rank,float(score)) for rank,(repo,score) in enumerate(lexical_rows,1)}
 repos=set(vector_rank)|set(lexical_rank);meta={}
 repo_list=list(repos)
 for start in range(0,len(repo_list),200):
  part=repo_list[start:start+200];marks=','.join('?' for _ in part)
  for row in db.execute(f"select repo,tier,name,document from repositories where repo in ({marks})",part):meta[row[0]]=row
 candidates=[]
 for repo in repos:
  vr,vs=vector_rank.get(repo,(None,None));kr,ks=lexical_rank.get(repo,(None,None))
  # RRF orders the candidate bundle only; it is not the final recommendation score.
  rrf=(1/(60+vr) if vr else 0)+(1/(60+kr) if kr else 0);row=meta[repo]
  document=row[3] if args.full_document else row[3][:2500]
  candidates.append((rrf,{"repo":repo,"tier":row[1],"name":row[2],"vector_rank":vr,"vector_score":round(vs,6) if vs is not None else None,"keyword_rank":kr,"keyword_bm25":round(ks,6) if ks is not None else None,"candidate_rrf":round(rrf,8),"document":document}))
 for _,candidate in sorted(candidates,key=lambda x:x[0],reverse=True)[:args.output_k]:print(json.dumps(candidate,ensure_ascii=False))

if __name__=="__main__":main()
