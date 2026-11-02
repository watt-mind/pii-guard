import json, re, glob, os, unicodedata
HERE=os.path.dirname(os.path.abspath(__file__)); R=os.path.join(HERE,'../../fixtures/visual/')
labels={v["id"]:v for v in json.load(open(R+'labels.json'))["specimens"].values()}
man={s["id"]:s for s in json.load(open(R+'manifest.json'))["specimens"]}
tes={v["id"]:v["words"] for v in json.load(open(R+'ocr/tesseract.json'))["images"].values()}
norm=lambda s: re.sub(r'[\W_]+','',unicodedata.normalize('NFKC',s).lower())
def cov(l,b):
    ix=max(0,min(l[2],b[2])-max(l[0],b[0])); iy=max(0,min(l[3],b[3])-max(l[1],b[1])); return ix*iy/((l[2]-l[0])*(l[3]-l[1]))
res={}
for pad in (0,0.01,0.02,0.03):
  tot=box_ok=txt_ok=both=tes_ok=refused=0; area=0; n=0
  for f in sorted(glob.glob(os.path.join(HERE,'lines/*.out'))):
    sid=os.path.basename(f)[:-4]; spec=labels[sid]; w,h=man[sid]["width"],man[sid]["height"]
    tx=[r for r in spec["regions"] if r["type"]=="text"]
    words=[(t,x1/w,y1/h,x2/w,y2/h) for t,x1,y1,x2,y2,_ in tes[sid]]
    body=open(f).read().split("\n",1)[1]; m=re.search(r'\{.*\}',body,re.S)
    lines=[]
    try: lines=json.loads(m.group(0))["lines"] if m else []
    except Exception: pass
    if not lines: refused+=1
    L=[(l["text"],[l["box"][0]/1000-pad,l["box"][1]/1000-pad*w/h,l["box"][2]/1000+pad,l["box"][3]/1000+pad*w/h]) for l in lines]
    area+=sum((b[2]-b[0])*(b[3]-b[1]) for _,b in L); n+=1
    for r in tx:
      tot+=1
      ref=norm("".join(t for t,*b in words if cov(r["box"],b)>0.5))
      tes_ok+= bool(ref)
      best=max(L,key=lambda x:cov(r["box"],x[1]),default=None)
      bo= best is not None and cov(r["box"],best[1])>=0.9
      to= bool(ref) and any(ref in norm(t) for t,_ in L)
      box_ok+=bo; txt_ok+=to; both+=bo and (to or not ref)
  print(f"pad {pad:.2f}: regions {tot}, box covered {box_ok} ({box_ok/tot:.0%}), text read {txt_ok}/{tes_ok} tesseract-readable, box+text {both} ({both/tot:.0%}), mean line-box area {area/n:.0%} of image, no-JSON {refused}/{n}")
print("-- span boxes interpolated by character offset inside the line (what masking would cover)")
for padx,pady in ((0.01,0.01),(0.02,0.015),(0.03,0.02)):
  ok=tot=0; ar=[]
  for f in sorted(glob.glob(os.path.join(HERE,'lines/*.out'))):
    sid=os.path.basename(f)[:-4]; spec=labels[sid]; w,h=man[sid]["width"],man[sid]["height"]
    words=[(t,x1/w,y1/h,x2/w,y2/h) for t,x1,y1,x2,y2,_ in tes[sid]]
    body=open(f).read().split("\n",1)[1]; m=re.search(r'\{.*\}',body,re.S)
    try: lines=json.loads(m.group(0))["lines"] if m else []
    except Exception: lines=[]
    for r in [r for r in spec["regions"] if r["type"]=="text"]:
      ref=" ".join(t for t,*b in words if cov(r["box"],b)>0.5).strip()
      if not ref: continue
      tot+=1
      for l in lines:
        t=l["text"]; i=t.lower().find(ref.lower())
        if i<0: continue
        x1,y1,x2,y2=[c/1000 for c in l["box"]]; cw=(x2-x1)/max(len(t),1)
        b=[x1+i*cw-padx, y1-pady*w/h, x1+(i+len(ref))*cw+padx, y2+pady*w/h]
        if cov(r["box"],b)>=0.9: ok+=1; ar.append((b[2]-b[0])*(b[3]-b[1])/((r["box"][2]-r["box"][0])*(r["box"][3]-r["box"][1]))); break
  print(f"pad x{padx} y{pady}: span-covered {ok}/{tot} ({ok/tot:.0%}), mask/region area x{sum(ar)/max(len(ar),1):.1f}")
