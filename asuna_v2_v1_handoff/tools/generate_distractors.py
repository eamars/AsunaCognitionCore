#!/usr/bin/env python3
"""Generate synthetic retrieval distractors; no network or model calls."""
import argparse, json, random
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--count',type=int,default=200);p.add_argument('--seed',type=int,default=20260919);a=p.parse_args()
if not 0<=a.count<=100000:p.error('count must be 0..100000')
r=random.Random(a.seed);rows=[]
for i in range(a.count):
 scope=r.choice(['scene:g1','scene:g2','scene:dm-a','scene:dm-b'])
 rows.append({'id':f'D{i:05d}','scope_key':scope,'status':'active','kind':'episodic','epistemic_type':'observed_fact','body_markdown':f'合成档案{i}：{r.choice(["蓝盒","清单","谜题","咖啡","暂时中断"])}记录编号 N{r.randrange(1000,9999)}。这是另一件日常整理记录，未涉及上述人物的新承诺。','source_event_ids':[f'ev-D{i:05d}']})
a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text('\n'.join(json.dumps(x,ensure_ascii=False) for x in rows)+'\n',encoding='utf-8')
print(json.dumps({'generated':len(rows),'seed':a.seed,'out':str(a.out)}))
