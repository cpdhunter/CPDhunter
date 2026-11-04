"""
CPD Hunter - daily CPD collector v1.2
Fixes:
- tolerant AI JSON parsing
- clearer errors
- browser-like HTTP headers
- HTML/Markdown-safe AI response parsing
"""
import json, os, re, sys, time, hashlib, datetime as dt
import urllib.robotparser
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "events.json")
SOURCES = os.path.join(ROOT, "sources.json")
MANUAL = os.path.join(ROOT, "manual.json")

BOT = "CPDHunterBot"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36 (compatible; CPDHunterBot/1.2; free CPD calendar)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9,zh-HK;q=0.8",
}
HKT = dt.timezone(dt.timedelta(hours=8))
TODAY = dt.datetime.now(HKT).date()
KEEP_DAYS_AHEAD = 180
KEEP_DAYS_PAST = 31
MAX_TEXT = 6000

API = os.getenv("LLM_API", "https://models.github.ai/inference/chat/completions")
MODEL = os.getenv("LLM_MODEL", "openai/gpt-4o-mini")
TOKEN = os.getenv("LLM_TOKEN") or os.getenv("GITHUB_TOKEN")

TYPES = ["Technical", "GPM", "H&S"]
DISCS = ["Aircraft", "Biomedical", "Building", "Building Services", "Chemical", "Civil",
         "Control, Automation & Instrumentation", "Electrical", "Electronics", "Energy",
         "Environmental", "Fire", "Gas", "Geotechnical", "Information", "Logistics & Transportation",
         "Manufacturing, Industrial & Systems", "Marine & Naval Architecture", "Materials",
         "Mechanical", "Nuclear", "Structural", "General"]
_robots = {}
AI_DEAD = None

class StepError(Exception):
    pass

def log(*a):
    print(*a, file=sys.stderr, flush=True)

def allowed(url):
    p = urlparse(url)
    base = f"{p.scheme}://{p.netloc}"
    if base not in _robots:
        rp = urllib.robotparser.RobotFileParser()
        try:
            r = requests.get(base + "/robots.txt", headers=HEADERS, timeout=15)
            rp.parse(r.text.splitlines() if r.status_code == 200 else [])
        except Exception:
            rp.parse([])
        _robots[base] = rp
    return _robots[base].can_fetch(BOT, url)

def fetch(url):
    if not allowed(url):
        raise StepError("robots.txt 唔准讀取")
    last = None
    for attempt in range(2):
        try:
            r = requests.get(url, headers=HEADERS, timeout=40)
        except requests.exceptions.SSLError:
            raise StepError("讀取網頁失敗：SSL 憑證問題")
        except requests.exceptions.Timeout:
            last = "讀取網頁失敗：逾時"; time.sleep(5); continue
        except Exception as ex:
            last = f"讀取網頁失敗：{type(ex).__name__}"; time.sleep(5); continue
        if r.status_code == 200:
            r.encoding = r.apparent_encoding or r.encoding
            return r.text
        last = f"讀取網頁失敗：HTTP {r.status_code}" + ("（網站封鎖咗雲端伺服器）" if r.status_code in (401,403,429) else "")
        if r.status_code in (401,403,404): break
        time.sleep(5)
    raise StepError(last or "讀取網頁失敗")

def walk(o):
    if isinstance(o, list):
        for x in o: yield from walk(x)
    elif isinstance(o, dict):
        t = o.get("@type"); t = t if isinstance(t, list) else [t]
        if any(str(x).endswith("Event") for x in t if x): yield o
        for k in ("@graph","itemListElement","item","subEvent"):
            if k in o: yield from walk(o[k])

def norm_off(off):
    if not off: return None
    if off == "Z": return "+00:00"
    return off if ":" in off else off[:3] + ":" + off[3:]

def jsonld_events(soup, base):
    out=[]
    for s in soup.find_all("script", type="application/ld+json"):
        try: data=json.loads(s.string or "")
        except Exception: continue
        for e in walk(data):
            m=re.match(r"(\d{4}-\d{2}-\d{2})(?:T(\d{2}:\d{2}))?(?::\d{2})?(?:\.\d+)?(Z|[+-]\d{2}:?\d{2})?",str(e.get("startDate","")))
            if not m: continue
            em=re.search(r"T(\d{2}:\d{2})",str(e.get("endDate","")))
            offers=e.get("offers") or {}
            if isinstance(offers,list): offers=offers[0] if offers else {}
            price=str(offers.get("price","")) if isinstance(offers,dict) else ""
            org=e.get("organizer") or {}
            out.append({"title":e.get("name"),"organizer":org.get("name") if isinstance(org,dict) else str(org),
              "date":m.group(1),"start_time":m.group(2),"end_time":em.group(1) if em else None,
              "utc_offset":norm_off(m.group(3)),"url":urljoin(base,e.get("url") or base),
              "is_online":("Online" in str(e.get("eventAttendanceMode",""))) or None,
              "is_free":(price in ("0","0.0","0.00")) if price else None,
              "cpd_hours":None,"type":None,"disciplines":None})
    return out

def page_text(soup, base):
    for t in soup(["script","style","noscript","svg","header","footer","nav","form","iframe"]): t.decompose()
    for a in soup.find_all("a",href=True):
        txt=a.get_text(" ",strip=True)
        if txt: a.replace_with(f"{txt} <{urljoin(base,a['href'])}>")
    return re.sub(r"\s+"," ",(soup.body or soup).get_text(" ",strip=True))[:MAX_TEXT]

PROMPT='''You extract upcoming professional development events from a web page for engineers.
Today is {today}. Source: {name} ({region}). Return one JSON object with key "events" only.
Each event has: title, organizer, date (YYYY-MM-DD), start_time, end_time, utc_offset, url, is_online, is_free, cpd_hours, type, disciplines, is_social.
type must be Technical, GPM, or H&S. disciplines must use values from {discs}, or General.
Only include events dated today or later. Do not invent facts. If none, return {{"events":[]}}.
PAGE: {text}'''

def parse_ai_json(content):
    if isinstance(content, dict): data=content
    elif isinstance(content, list): data={"events":content}
    else:
        text=str(content or "").strip()
        text=re.sub(r"^```(?:json)?\s*","",text,flags=re.I)
        text=re.sub(r"\s*```$","",text).strip()
        candidates=[text]
        a,b=text.find("{"),text.rfind("}")
        if a>=0 and b>a: candidates.append(text[a:b+1])
        a,b=text.find("["),text.rfind("]")
        if a>=0 and b>a: candidates.append(text[a:b+1])
        data=None; last=None
        for c in candidates:
            try:
                p=json.loads(c)
                if isinstance(p,list): data={"events":p}
                elif isinstance(p,dict): data=p
                if data is not None: break
            except json.JSONDecodeError as ex: last=ex
        if data is None:
            raise StepError(f"AI JSON 解析失敗：{last}; 回覆開頭：{text[:300].replace(chr(10),' ')}")
    events=data.get("events",[])
    if not isinstance(events,list): raise StepError(f"AI JSON events 唔係 array，而係 {type(events).__name__}")
    return events

def llm_extract(text,src):
    global AI_DEAD
    if AI_DEAD: raise StepError(AI_DEAD)
    if not TOKEN:
        AI_DEAD="AI 抽取失敗：冇 token"; raise StepError(AI_DEAD)
    if len(text)<80: raise StepError("網頁冇內容（可能用 JavaScript 載入）")
    body={"model":MODEL,"temperature":0,"response_format":{"type":"json_object"},
          "messages":[{"role":"user","content":PROMPT.format(today=TODAY.isoformat(),name=src["name"],region=src["region"],discs=DISCS,text=text)}]}
    for attempt in range(3):
        try:
            r=requests.post(API,json=body,timeout=90,headers={"Authorization":f"Bearer {TOKEN}","Content-Type":"application/json"})
        except Exception as ex: raise StepError(f"AI 抽取失敗：{type(ex).__name__}: {ex}")
        if r.status_code==429: time.sleep(40*(attempt+1)); continue
        if r.status_code in (401,403):
            AI_DEAD=f"AI 抽取失敗：HTTP {r.status_code}（GitHub Models 權限問題）{r.text[:120]}"; raise StepError(AI_DEAD)
        if r.status_code!=200: raise StepError(f"AI 抽取失敗：HTTP {r.status_code} {r.text[:150]}")
        try:
            payload=r.json(); content=payload["choices"][0]["message"]["content"]
            return parse_ai_json(content)
        except StepError: raise
        except Exception as ex:
            raise StepError(f"AI 回覆結構錯誤：{type(ex).__name__}: {ex}; API 回覆：{r.text[:300].replace(chr(10),' ')}")
    raise StepError("AI 抽取失敗：免費額度用晒 (429)")

def norm_title(t): return re.sub(r"[^a-z0-9\u4e00-\u9fff]","",(t or "").lower())

def to_hkt(e):
    if not (e.get("start_time") and e.get("utc_offset")): return e["date"],e.get("start_time"),e.get("end_time")
    m=re.match(r"([+-])(\d{2}):?(\d{2})",str(e["utc_offset"]))
    if not m: return e["date"],e.get("start_time"),e.get("end_time")
    sign=1 if m.group(1)=="+" else -1
    tz=dt.timezone(sign*dt.timedelta(hours=int(m.group(2)),minutes=int(m.group(3))))
    def conv(t):
        x=dt.datetime.fromisoformat(f"{e['date']}T{t}").replace(tzinfo=tz).astimezone(HKT)
        return x.date().isoformat(),x.strftime("%H:%M")
    d,s=conv(e["start_time"]); end=conv(e["end_time"])[1] if e.get("end_time") else None
    return d,s,end

def est_hours(s,e):
    try:
        mins=(dt.datetime.strptime(e,"%H:%M")-dt.datetime.strptime(s,"%H:%M")).seconds/60
        if 20<=mins<=480: return round(mins/30)/2
    except Exception: pass
    return None

def clean(e,src):
    try:
        title=(e.get("title") or "").strip(); e["date"]=dt.date.fromisoformat(str(e.get("date"))[:10]).isoformat(); url=e.get("url") or src["url"]
        if not title or not str(url).startswith("http"): return None
        for k in ("start_time","end_time"):
            if e.get(k) and not re.fullmatch(r"\d{2}:\d{2}",str(e[k])): e[k]=None
        d_hkt,s_hkt,e_hkt=to_hkt(e)
    except Exception: return None
    d=dt.date.fromisoformat(d_hkt)
    if d<TODAY or d>TODAY+dt.timedelta(days=KEEP_DAYS_AHEAD): return None
    if e.get("is_free") is False: return None
    if src["region"]!="HK" and e.get("is_online") is False: return None
    if e.get("is_social"): return None
    if e.get("is_free") is None and src.get("free"): e["is_free"]=True
    typ=e.get("type") if e.get("type") in TYPES else (src.get("type") or "Technical")
    discs=[x for x in (e.get("disciplines") or []) if x in DISCS] or ["General"]
    hrs=e.get("cpd_hours"); hrs=hrs if isinstance(hrs,(int,float)) and 0<hrs<50 else None; est=False
    if hrs is None and s_hkt and e_hkt: hrs=est_hours(s_hkt,e_hkt); est=hrs is not None
    return {"id":"a"+hashlib.sha1(f"{norm_title(title)}|{d_hkt}".encode()).hexdigest()[:12],"name":title[:200],"org":(e.get("organizer") or src["name"])[:120],"date":d_hkt,"time":f"{s_hkt}-{e_hkt}" if s_hkt and e_hkt else (s_hkt or ""),"hrs":hrs,"hrs_est":est,"type":typ,"disc":discs,"url":url,"region":src["region"],"online":e.get("is_online"),"free":e.get("is_free"),"source":src["name"],"group":src.get("group") or src["name"],"auto":True}

def load(path,default):
    try:
        with open(path,encoding="utf-8") as f: return json.load(f)
    except Exception: return default

def main():
    sources=load(SOURCES,[]); old=load(OUT,{}).get("events",[]); found={}; status=[]
    log(f"AI token: {'有' if TOKEN else '冇'}；model: {MODEL}")
    for src in sources:
        if src.get("disabled"): continue
        log(f"▶ {src['name']}")
        try:
            html=fetch(src["url"]); soup=BeautifulSoup(html,"html.parser"); raw=jsonld_events(soup,src["url"]); method="jsonld"
            if not raw: raw=llm_extract(page_text(soup,src["url"]),src); method="ai"
            n=0
            for e in raw:
                c=clean(e,src)
                if c: found[c["id"]]=c; n+=1
            log(f"  OK {method}: extracted {len(raw)}, kept {n}"); status.append({"source":src["name"],"ok":True,"n":n})
        except StepError as ex:
            log(f"  FAIL {ex}"); status.append({"source":src["name"],"ok":False,"n":0,"err":str(ex)[:200]})
        except Exception as ex:
            log(f"  FAIL {type(ex).__name__}: {ex}"); status.append({"source":src["name"],"ok":False,"n":0,"err":f"{type(ex).__name__}: {str(ex)[:150]}"})
        time.sleep(4)
    cutoff=(TODAY-dt.timedelta(days=KEEP_DAYS_PAST)).isoformat()
    for e in old:
        if e.get("auto") and e.get("date","")>=cutoff and e.get("id") not in found: found[e["id"]]=e
    for e in load(MANUAL,[]):
        if e.get("date","")>=cutoff:
            e.setdefault("id","m"+hashlib.sha1((e["url"]+e["date"]).encode()).hexdigest()[:12]); e["auto"]=False; found[e["id"]]=e
    events=sorted(found.values(),key=lambda x:(x["date"],x.get("time") or ""))
    with open(OUT,"w",encoding="utf-8") as f: json.dump({"updated":dt.datetime.now(HKT).isoformat(timespec="minutes"),"status":status,"events":events},f,ensure_ascii=False,indent=1)
    log("\n========== SUMMARY ==========")
    for s in status: log(("OK " if s["ok"] else "FAIL ")+s["source"]+(f": {s['n']} events" if s["ok"] else f": {s.get('err')}"))
    log(f"Total {len(events)} events")

if __name__=="__main__": main()
