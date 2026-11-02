import base64, json, os, sys, time, urllib.request
img = sys.argv[1]; url=sys.argv[2]; model=sys.argv[3]; key=os.environ[sys.argv[4]]
b64 = base64.b64encode(open(img,'rb').read()).decode()
prompt = sys.argv[5] if len(sys.argv)>5 else "Transcribe all text in this image."
SYS=os.environ.get("SYS"); body = {"model": model, "max_tokens": 3000, "messages":([{"role":"system","content":SYS}] if SYS else [])+[{"role":"user","content":[
  {"type":"text","text":prompt},
  {"type":"image_url","image_url":{"url":"data:image/png;base64,"+b64}}]}]}
if "baseten" in url: body["reasoning_effort"]="low"
req = urllib.request.Request(url+"/chat/completions", data=json.dumps(body).encode(),
  headers={"Authorization":"Bearer "+key,"Content-Type":"application/json"})
t=time.time()
try:
    r = json.load(urllib.request.urlopen(req, timeout=180))
    print("OK %.1fs"%(time.time()-t), json.dumps(r.get("usage")))
    print(r["choices"][0]["message"].get("content"))
except urllib.error.HTTPError as e:
    print("HTTP", e.code, e.read().decode()[:800])
