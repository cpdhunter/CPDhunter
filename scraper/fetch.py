"""
CPD Hunter - daily CPD collector v2.0
- Structured extraction first (JSON-LD, source-specific, generic)
- Playwright fallback for JS-rendered pages
- Rule-based classification; Cloudflare Workers AI only for ambiguous cases
- Isolated source failures
"""
import json, os, re, sys, time, hashlib, datetime as dt
from urllib.parse import urljoin, urlparse
import urllib.robotparser

import requests
from bs4 import BeautifulSoup

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_OK = True
except ImportError:
    PLAYWRIGHT_OK = False

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "events.json")
SOURCES = os.path.join(ROOT, "sources.json")
MANUAL = os.path.join(ROOT, "manual.json")

BOT = "CPDHunterBot"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36 (compatible; CPDHunterBot/2.0; free CPD calendar)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9,zh-HK;q=0.8",
}
HKT = dt.timezone(dt.timedelta(hours=8))
TODAY = dt.datetime.now(HKT).date()
KEEP_DAYS_AHEAD = 180
KEEP_DAYS_PAST = 31

TYPES = ["Technical", "GPM", "H&S"]
DISCS = ["Aircraft", "Biomedical", "Building", "Building Services", "Chemical", "Civil",
         "Control, Automation & Instrumentation", "Electrical", "Electronics", "Energy",
         "Environmental", "Fire", "Gas", "Geotechnical", "Information", "Logistics & Transportation",
         "Manufacturing, Industrial & Systems", "Marine & Naval Architecture", "Materials",
         "Mechanical", "Nuclear", "Structural", "General"]

HS_KW = re.compile(r"safety|health|hazard|accident|risk assessment|confined space|lifting|crane|scaffold|work at height|heat stress|職安|安全|健康|意外|吊運|棚架|高空工作", re.I)
GPM_KW = re.compile(r"contract|NEC|management|law|legal|ethics|integrity|leadership|communication|dispute|arbitration|procurement|合約|管理|法律|道德|誠信|溝通|仲裁|採購", re.I)

_robots = {}
CF_ACCOUNT = os.getenv("CLOUDFLARE_ACCOUNT_ID")
CF_TOKEN = os.getenv("CLOUDFLARE_AI_TOKEN")
CF_API = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT}/ai/run/@cf/meta/llama-3.1-8b-instruct-fast" if CF_ACCOUNT else None

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

def fetch_html(url, use_playwright=False):
    if not allowed(url):
        raise StepError("robots.txt 唔准讀取")
    if use_playwright and PLAYWRIGHT_OK:
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.set_extra_http_headers(HEADERS)
                page.goto(url, timeout=45000, wait_until="networkidle")
                html = page.content()
                browser.close()
                return html
        except Exception as ex:
            raise StepError(f"Playwright 失敗：{type(ex).__name__}")
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

def walk_jsonld(o):
    if isinstance(o, list):
        for x in o: yield from walk_jsonld(x)
    elif isinstance(o, dict):
        t = o.get("@type")
        t = t if isinstance(t, list) else [t]
        if any(str(x).endswith("Event") for x in t if x):
            yield o
        for k in ("@graph", "itemListElement", "item", "subEvent"):
            if k in o: yield from walk_jsonld(o[k])

def jsonld_events(soup, base):
    out = []
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(s.string or "")
        except Exception:
            continue
        for e in walk_jsonld(data):
            m = re.match(r"(\d{4}-\d{2}-\d{2})(?:T(\d{2}:\d{2}))?(?::\d{2})?(?:\.\d+)?(Z|[+-]\d{2}:?\d{2})?", str(e.get("startDate", "")))
            if not m: continue
            em = re.search(r"T(\d{2}:\d{2})", str(e.get("endDate", "")))
            offers = e.get("offers") or {}
            if isinstance(offers, list): offers = offers[0] if offers else {}
            price = str(offers.get("price", "")) if isinstance(offers, dict) else ""
            org = e.get("organizer") or {}
            out.append({
                "title": e.get("name"),
                "organizer": org.get("name") if isinstance(org, dict) else str(org),
                "date": m.group(1),
                "start_time": m.group(2),
                "end_time": em.group(1) if em else None,
                "url": urljoin(base, e.get("url") or base),
                "is_online": ("Online" in str(e.get("eventAttendanceMode", ""))) or None,
                "is_free": (price in ("0", "0.0", "0.00")) if price else None,
                "cpd_hours": None,
            })
    return out

def parse_date(s):
    if not s: return None
    s = re.sub(r"[^\d/-]", "", str(s).strip())
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y"):
        try:
            return dt.datetime.strptime(s[:10], fmt).date().isoformat()
        except Exception:
            pass
    m = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", s)
    if m: return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.search(r"(\d{1,2})[-/](\d{1,2})[-/](\d{4})", s)
    if m: return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return None

def extract_oshc(soup, base):
    out = []
    for table in soup.find_all("table"):
        for tr in table.find_all("tr")[1:]:
            tds = tr.find_all("td")
            if len(tds) < 2: continue
            date_s = tds[0].get_text(strip=True)
            title = tds[1].get_text(strip=True)
            d = parse_date(date_s)
            if d and title:
                out.append({"title": title, "date": d, "url": base, "organizer": "OSHC", "is_online": "Online" in title or None})
    return out

def extract_cic(soup, base):
    out = []
    text = soup.get_text("\n", strip=True)
    for m in re.finditer(r"(\d{2}\.\d{2}\.\d{4})\s+(.+?)(?:\n|$)", text):
        d = parse_date(m.group(1).replace(".", "/"))
        title = m.group(2).strip()
        if d and title and len(title) > 5:
            out.append({"title": title, "date": d, "url": base, "organizer": "CIC"})
    return out

def generic_extract(soup, base):
    out = []
    for a in soup.find_all("a", href=True):
        txt = a.get_text(" ", strip=True)
        if not txt or len(txt) < 8: continue
        parent = a.find_parent(["li", "div", "article", "tr", "p"])
        ctx = parent.get_text(" ", strip=True) if parent else txt
        d = parse_date(ctx) or parse_date(txt)
        if d:
            out.append({"title": txt[:200], "date": d, "url": urljoin(base, a["href"]), "organizer": None})
    return out[:30]  # limit

def classify_rule(title, desc=""):
    text = f"{title} {desc}".lower()
    if HS_KW.search(text): return "H&S"
    if GPM_KW.search(text): return "GPM"
    return "Technical"

def ai_classify(title, org):
    if not CF_API or not CF_TOKEN: return None
    prompt = f'Return strict JSON only: {{"type":"Technical|GPM|H&S","disciplines":["one of {DISCS}"]}}. Event: {title} by {org}. No other text.'
    try:
        r = requests.post(CF_API, headers={"Authorization": f"Bearer {CF_TOKEN}", "Content-Type": "application/json"},
                          json={"messages": [{"role": "user", "content": prompt}]}, timeout=30)
        if r.status_code != 200: return None
        content = r.json().get("result", {}).get("response", "") or r.text
        m = re.search(r"\{.*\}", content, re.S)
        if m:
            data = json.loads(m.group(0))
            typ = data.get("type") if data.get("type") in TYPES else None
            discs = [x for x in (data.get("disciplines") or []) if x in DISCS]
            return typ, discs or ["General"]
    except Exception:
        pass
    return None

def clean(e, src):
    try:
        title = (e.get("title") or "").strip()
        date = parse_date(e.get("date")) or e.get("date")
        if not date: return None
        e["date"] = dt.date.fromisoformat(str(date)[:10]).isoformat()
        url = e.get("url") or src["url"]
        if not title or not str(url).startswith("http"): return None
        d = dt.date.fromisoformat(e["date"])
        if d < TODAY or d > TODAY + dt.timedelta(days=KEEP_DAYS_AHEAD): return None
        if e.get("is_free") is False: return None
        if src["region"] != "HK" and e.get("is_online") is False: return None
        if any(x in title.lower() for x in ["dinner", "agm", "sport", "social", "gala", "banquet"]): return None
        typ = e.get("type") or classify_rule(title)
        discs = e.get("disciplines") or ["General"]
        if typ not in TYPES or not any(x in DISCS for x in discs):
            ai = ai_classify(title, e.get("organizer") or src["name"])
            if ai:
                typ, discs = ai
            else:
                typ = typ if typ in TYPES else (src.get("type") or "Technical")
                discs = [x for x in discs if x in DISCS] or ["General"]
        hrs = e.get("cpd_hours")
        hrs = hrs if isinstance(hrs, (int, float)) and 0 < hrs < 50 else None
        est = False
        s_hkt, e_hkt = e.get("start_time"), e.get("end_time")
        if hrs is None and s_hkt and e_hkt:
            try:
                mins = (dt.datetime.strptime(e_hkt, "%H:%M") - dt.datetime.strptime(s_hkt, "%H:%M")).seconds / 60
                if 20 <= mins <= 480:
                    hrs = round(mins / 30) / 2
                    est = True
            except Exception:
                pass
        return {
            "id": "a" + hashlib.sha1(f"{re.sub(r'[^a-z0-9\\u4e00-\\u9fff]', '', title.lower())}|{e['date']}".encode()).hexdigest()[:12],
            "name": title[:200],
            "org": (e.get("organizer") or src["name"])[:120],
            "date": e["date"],
            "time": f"{s_hkt}-{e_hkt}" if s_hkt and e_hkt else (s_hkt or ""),
            "hrs": hrs,
            "hrs_est": est,
            "type": typ,
            "disc": discs,
            "url": url,
            "region": src["region"],
            "online": e.get("is_online"),
            "free": e.get("is_free") if e.get("is_free") is not None else src.get("free"),
            "source": src["name"],
            "group": src.get("group") or src["name"],
            "auto": True,
        }
    except Exception:
        return None

def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def process_source(src):
    url = src["url"]
    html = fetch_html(url)
    soup = BeautifulSoup(html, "html.parser")
    raw = jsonld_events(soup, url)
    method = "jsonld"
    if not raw:
        if "oshc" in url.lower() or "sms.oshc" in url:
            raw = extract_oshc(soup, url)
            method = "oshc-table"
        elif "cic.hk" in url or "bim.cic" in url or "citac" in url or "rstc.cic" in url:
            raw = extract_cic(soup, url)
            method = "cic-list"
        else:
            raw = generic_extract(soup, url)
            method = "generic"
    if not raw and PLAYWRIGHT_OK and ("sms.oshc" in url or "istructe" in url or "localevents.theiet" in url):
        try:
            html = fetch_html(url, use_playwright=True)
            soup = BeautifulSoup(html, "html.parser")
            raw = jsonld_events(soup, url) or generic_extract(soup, url)
            method = "playwright"
        except StepError:
            pass
    return raw, method

def main():
    sources = load(SOURCES, [])
    old = load(OUT, {}).get("events", [])
    found = {}
    status = []
    log(f"Playwright: {'yes' if PLAYWRIGHT_OK else 'no'}; CF AI: {'yes' if CF_API and CF_TOKEN else 'no'}")
    for src in sources:
        if src.get("disabled"): continue
        log(f"▶ {src['name']}")
        try:
            raw, method = process_source(src)
            n = 0
            for e in raw:
                c = clean(e, src)
                if c:
                    found[c["id"]] = c
                    n += 1
            log(f"  OK {method}: extracted {len(raw)}, kept {n}")
            status.append({"source": src["name"], "ok": True, "n": n, "method": method})
        except StepError as ex:
            log(f"  FAIL {ex}")
            status.append({"source": src["name"], "ok": False, "n": 0, "err": str(ex)[:200]})
        except Exception as ex:
            log(f"  FAIL {type(ex).__name__}: {ex}")
            status.append({"source": src["name"], "ok": False, "n": 0, "err": f"{type(ex).__name__}: {str(ex)[:150]}"})
        time.sleep(3)
    cutoff = (TODAY - dt.timedelta(days=KEEP_DAYS_PAST)).isoformat()
    for e in old:
        if e.get("auto") and e.get("date", "") >= cutoff and e.get("id") not in found:
            found[e["id"]] = e
    for e in load(MANUAL, []):
        if e.get("date", "") >= cutoff:
            e.setdefault("id", "m" + hashlib.sha1((e.get("url", "") + e["date"]).encode()).hexdigest()[:12])
            e["auto"] = False
            found[e["id"]] = e
    events = sorted(found.values(), key=lambda x: (x["date"], x.get("time") or ""))
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"updated": dt.datetime.now(HKT).isoformat(timespec="minutes"), "status": status, "events": events}, f, ensure_ascii=False, indent=1)
    log("\n========== SUMMARY ==========")
    ok_count = sum(1 for s in status if s["ok"])
    for s in status:
        log(("OK " if s["ok"] else "FAIL ") + s["source"] + (f": {s['n']} events via {s.get('method','')}" if s["ok"] else f": {s.get('err')}"))
    log(f"Sources OK: {ok_count}/{len(status)}; Total {len(events)} events")

if __name__ == "__main__":
    main()
