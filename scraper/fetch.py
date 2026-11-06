"""
CPD Hunter - daily CPD collector v2.1
- Source-family parsers (HKIE, CIC, ICE, HKGBC, CSB/Labour, OSHC)
- Better date parsing for common formats
- Status: OK_WITH_EVENTS / VERIFIED_EMPTY / EMPTY_UNVERIFIED / FAIL
- Per-source diagnostics + source_health.json
- Auto GitHub Issue after 3 consecutive FAIL/EMPTY_UNVERIFIED
- Cloudflare AI only for ambiguous classification
- Playwright for JS/SSL cases
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
HEALTH = os.path.join(ROOT, "source_health.json")

BOT = "CPDHunterBot"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36 (compatible; CPDHunterBot/2.2; free CPD calendar)",
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

MONTHS = {"jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,"jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12,
          "january":1,"february":2,"march":3,"april":4,"june":6,"july":7,"august":8,"september":9,"october":10,"november":11,"december":12}

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
                page.goto(url, timeout=50000, wait_until="domcontentloaded")
                page.wait_for_timeout(3000)
                html = page.content()
                browser.close()
                return html
        except Exception as ex:
            raise StepError(f"Playwright 失敗：{type(ex).__name__}")
    last = None
    for attempt in range(2):
        try:
            r = requests.get(url, headers=HEADERS, timeout=40, verify=True)
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

def parse_date(s):
    if not s: return None
    s = str(s).strip()
    m = re.search(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", s)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try: return dt.date(y, mo, d).isoformat()
        except: pass
    m = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", s)
    if m:
        try: return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        except: pass
    m = re.search(r"(\d{1,2})(?:[-\u2013]\d{1,2})?\s+([A-Za-z]+)\s+(\d{4})", s)
    if m:
        day, mon, year = int(m.group(1)), m.group(2).lower()[:3], int(m.group(3))
        if mon in MONTHS:
            try: return dt.date(year, MONTHS[mon], day).isoformat()
            except: pass
    m = re.search(r"(\d{1,2})\s+([A-Za-z]+),?\s+(\d{4})", s)
    if m:
        day, mon, year = int(m.group(1)), m.group(2).lower()[:3], int(m.group(3))
        if mon in MONTHS:
            try: return dt.date(year, MONTHS[mon], day).isoformat()
            except: pass
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

def extract_hkie_cpd(soup, base):
    out = []
    lines = soup.get_text("\n", strip=True).splitlines()
    for i, line in enumerate(lines):
        if not line or len(line) < 15: continue
        for j in range(1, 5):
            if i + j >= len(lines): break
            d = parse_date(lines[i + j])
            if d:
                title = line.strip()
                if re.match(r"CPD\d", title) or len(title) < 20: continue
                a = None
                for h in soup.find_all(["h2", "h3"]):
                    if title[:30] in h.get_text():
                        a = h.find("a")
                        break
                url = urljoin(base, a["href"]) if a and a.get("href") else base
                out.append({"title": title, "date": d, "url": url, "organizer": "HKIE"})
                break
    return out[:25]

def extract_labour(soup, base):
    out = []
    lines = soup.get_text("\n", strip=True).splitlines()
    for i, line in enumerate(lines):
        d = parse_date(line)
        if not d: continue
        for j in range(1, 6):
            if i + j >= len(lines): break
            title = lines[i + j].strip()
            if title and len(title) > 6 and not parse_date(title) and "報名" not in title:
                out.append({"title": title, "date": d, "url": base, "organizer": "Labour Dept"})
                break
    return out[:15]

def extract_ice(soup, base):
    out = []
    for art in soup.find_all(["article", "div", "li"]):
        text = art.get_text("\n", strip=True)
        if "Date" not in text and "date" not in text.lower(): continue
        title_el = art.find(["h2", "h3", "h4", "a"])
        title = title_el.get_text(strip=True) if title_el else ""
        if len(title) < 10: continue
        d = parse_date(text)
        if d:
            a = art.find("a", href=True)
            url = urljoin(base, a["href"]) if a else base
            online = "Online" in text or "Webinar" in text
            free = "Free" in text and "From £" not in text and "$" not in text
            out.append({"title": title, "date": d, "url": url, "organizer": "ICE", "is_online": online, "is_free": free or None})
    seen = set()
    uniq = []
    for e in out:
        k = e["title"][:80]
        if k not in seen:
            seen.add(k)
            uniq.append(e)
    return uniq[:40]

def extract_cic(soup, base):
    out = []
    text = soup.get_text("\n", strip=True)
    for m in re.finditer(r"(\d{2}\.\d{2}\.\d{4}(?:\s*-\s*\d{2}\.\d{2}\.\d{4})?)\s+(.+?)(?:\n|$)", text):
        d = parse_date(m.group(1).split("-")[0].strip())
        title = m.group(2).strip()
        if d and title and len(title) > 5:
            out.append({"title": title, "date": d, "url": base, "organizer": "CIC"})
    return out

def extract_csb(soup, base):
    out = []
    for table in soup.find_all("table"):
        for tr in table.find_all("tr")[1:]:
            tds = tr.find_all(["td", "th"])
            if len(tds) < 2: continue
            date_s = tds[0].get_text(strip=True)
            title = tds[1].get_text(strip=True)
            d = parse_date(date_s)
            if d and title:
                a = tds[1].find("a")
                url = urljoin(base, a["href"]) if a and a.get("href") else base
                out.append({"title": title, "date": d, "url": url, "organizer": tds[2].get_text(strip=True) if len(tds)>2 else "CSB/Labour"})
    return out

def extract_hkgbc(soup, base):
    out = []
    text = soup.get_text("\n", strip=True)
    for m in re.finditer(r"(\d{1,2}\s+[A-Za-z]+\s+\d{4}|\d{4}年\d{1,2}月\d{1,2}日)\s*\|\s*(.+?)(?:\n|$)", text):
        d = parse_date(m.group(1))
        title = m.group(2).strip()
        if d and title and len(title) > 8:
            out.append({"title": title, "date": d, "url": base, "organizer": "HKGBC"})
    if not out:
        for a in soup.find_all("a", href=True):
            parent = a.find_parent(["div", "li", "article"])
            ctx = (parent.get_text(" ", strip=True) if parent else "") + " " + a.get_text()
            d = parse_date(ctx)
            if d and len(a.get_text(strip=True)) > 10:
                out.append({"title": a.get_text(strip=True)[:200], "date": d, "url": urljoin(base, a["href"]), "organizer": "HKGBC"})
    return out[:30]

def extract_hkie_div(soup, base):
    out = []
    for art in soup.find_all(["article", "div", "li"]):
        title_el = art.find(["h2", "h3", "a"])
        if not title_el: continue
        title = title_el.get_text(strip=True)
        if len(title) < 15: continue
        text = art.get_text(" ", strip=True)
        d = parse_date(text)
        if d:
            a = art.find("a", href=True)
            url = urljoin(base, a["href"]) if a else base
            out.append({"title": title, "date": d, "url": url, "organizer": "HKIE Division"})
    return out[:20]

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
    return out[:20]

def classify_rule(title):
    if HS_KW.search(title): return "H&S"
    if GPM_KW.search(title): return "GPM"
    return "Technical"

def ai_classify(title, org):
    if not CF_API or not CF_TOKEN: return None
    prompt = f'Return strict JSON only: {{"type":"Technical|GPM|H&S","disciplines":["one of {DISCS}"]}}. Event: {title} by {org}. No other text.'
    try:
        r = requests.post(CF_API, headers={"Authorization": f"Bearer {CF_TOKEN}", "Content-Type": "application/json"},
                          json={"messages": [{"role": "user", "content": prompt}]}, timeout=25)
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

def clean(e, src, rejects):
    try:
        title = (e.get("title") or "").strip()
        date = parse_date(e.get("date")) or e.get("date")
        if not date:
            rejects["no_date"] = rejects.get("no_date", 0) + 1
            return None
        e["date"] = dt.date.fromisoformat(str(date)[:10]).isoformat()
        url = e.get("url") or src["url"]
        if not title or not str(url).startswith("http"):
            rejects["bad_title_url"] = rejects.get("bad_title_url", 0) + 1
            return None
        d = dt.date.fromisoformat(e["date"])
        if d < TODAY or d > TODAY + dt.timedelta(days=KEEP_DAYS_AHEAD):
            rejects["date_range"] = rejects.get("date_range", 0) + 1
            return None
        if e.get("is_free") is False:
            rejects["paid"] = rejects.get("paid", 0) + 1
            return None
        if src["region"] != "HK" and e.get("is_online") is False:
            rejects["overseas_physical"] = rejects.get("overseas_physical", 0) + 1
            return None
        if any(x in title.lower() for x in ["dinner", "agm", "sport", "social", "gala", "banquet"]):
            rejects["social"] = rejects.get("social", 0) + 1
            return None
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
            "id": "a" + hashlib.sha1((re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", title.lower()) + "|" + e["date"]).encode()).hexdigest()[:12],
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
        rejects["exception"] = rejects.get("exception", 0) + 1
        return None

def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def process_source(src):
    url = src["url"]
    use_pw = False
    if "localevents.theiet" in url or "istructe" in url or "sms.oshc" in url:
        use_pw = True
    html = fetch_html(url, use_playwright=use_pw)
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else ""
    raw = []
    method = "generic"
    if "oshc.org.hk" in url or "csb.gov.hk" in url:
        if "oshc" in url:
            raw = extract_oshc(soup, url)
            method = "oshc-table"
        else:
            raw = extract_csb(soup, url)
            method = "csb-table"
    elif "oshsreg.gov.hk" in url or "labour.gov.hk" in url:
        raw = extract_labour(soup, url)
        method = "labour-list"
    elif "hkie.org.hk" in url and "cpd-calendar" in url:
        raw = extract_hkie_cpd(soup, url)
        method = "hkie-cpd"
    elif "hkie" in url and ("bd.hkie" in url or "hkie-st" in url or "hkie-fe" in url):
        raw = extract_hkie_div(soup, url)
        method = "hkie-div"
    elif "ice.org.uk" in url:
        raw = extract_ice(soup, url)
        method = "ice-cards"
    elif "cic.hk" in url or "bim.cic" in url or "citac" in url or "rstc.cic" in url:
        raw = extract_cic(soup, url)
        method = "cic-list"
    elif "hkgbc" in url:
        raw = extract_hkgbc(soup, url)
        method = "hkgbc"
    else:
        raw = generic_extract(soup, url)
        method = "generic"
    if not raw and PLAYWRIGHT_OK and not use_pw and ("hkie" in url or "ice" in url or "cic" in url):
        try:
            html2 = fetch_html(url, use_playwright=True)
            soup2 = BeautifulSoup(html2, "html.parser")
            if "hkie.org.hk" in url and "cpd" in url:
                raw = extract_hkie_cpd(soup2, url)
            elif "ice" in url:
                raw = extract_ice(soup2, url)
            elif "cic" in url:
                raw = extract_cic(soup2, url)
            else:
                raw = generic_extract(soup2, url)
            if raw:
                method = "playwright+" + method
        except Exception:
            pass
    return raw, method, title

def _norm_org(org):
    o = (org or "").lower()
    if "oshc" in o or "職安局" in o:
        return "oshc"
    if "csb" in o or "公務員" in o or "civil service" in o:
        return "csb"
    return re.sub(r"[^a-z0-9]", "", o)[:40]

def _norm_title(t):
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", (t or "").lower())

def _title_sim(a, b):
    na, nb = _norm_title(a), _norm_title(b)
    if not na or not nb:
        return 0.0
    from difflib import SequenceMatcher
    return SequenceMatcher(None, na, nb).ratio()

def _strong_signal(a, b):
    ua, ub = a.get("url",""), b.get("url","")
    if ua and ub and ua == ub and ("event" in ua.lower() or "activity" in ua.lower() or "detail" in ua.lower()):
        return True
    if a.get("time") and a.get("time") == b.get("time") and a.get("hrs") and a.get("hrs") == b.get("hrs"):
        return True
    if a.get("hrs") and not a.get("hrs_est") and a.get("hrs") == b.get("hrs") and not b.get("hrs_est"):
        na, nb = _norm_title(a.get("name")), _norm_title(b.get("name"))
        for i in range(len(na)-19):
            phrase = na[i:i+20]
            if phrase in nb and len(set(phrase)) > 8:
                return True
    na, nb = _norm_title(a.get("name")), _norm_title(b.get("name"))
    campaigns = ["heartcaring", "joyfulhealthyworkplace", "joyful@healthy"]
    if any(c in na and c in nb for c in campaigns):
        subjects = ["cardiovascular", "mentalhealth", "breaks your heart", "breaksyourheart"]
        if any(s in na and s in nb for s in subjects):
            return True
    return False

def _prefer_source(a, b):
    sa = (a.get("source") or "").lower()
    sb = (b.get("source") or "").lower()
    if "oshc seminars" in sa and ("公務員" in sb or "csb" in sb or "civil service" in sb):
        return a
    if "oshc seminars" in sb and ("公務員" in sa or "csb" in sa or "civil service" in sa):
        return b
    def score(x):
        s = 0
        url = x.get("url","")
        if url and ("event-detail" in url or "/events/" in url or "activity" in url) and not url.endswith("/"):
            s += 2
        if x.get("hrs") is not None and not x.get("hrs_est"):
            s += 1
        s += len(x.get("name","")) / 100
        return s
    return a if score(a) >= score(b) else b

def dedup_events(events):
    from difflib import SequenceMatcher
    out = []
    used = set()
    for i, e in enumerate(events):
        if i in used:
            continue
        best = e
        for j in range(i+1, len(events)):
            if j in used:
                continue
            o = events[j]
            if e.get("date") != o.get("date"):
                continue
            if _norm_org(e.get("org")) != _norm_org(o.get("org")):
                continue
            sim = _title_sim(e.get("name"), o.get("name"))
            if sim < 0.90:
                continue
            if not _strong_signal(e, o):
                continue
            best = _prefer_source(best, o)
            used.add(j)
        out.append(best)
        used.add(i)
    return out

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
            raw, method, page_title = process_source(src)
            rejects = {}
            n = 0
            for e in raw:
                c = clean(e, src, rejects)
                if c:
                    found[c["id"]] = c
                    n += 1
            if n > 0:
                st = "OK_WITH_EVENTS"
            elif rejects and all(k in ("date_range", "overseas_physical", "paid", "social") for k in rejects):
                st = "VERIFIED_EMPTY"
            else:
                st = "EMPTY_UNVERIFIED"
            log(f"  {st} {method}: raw={len(raw)} kept={n} rejects={rejects} title={page_title[:60]}")
            status.append({
                "source": src["name"], "status": st, "ok": st == "OK_WITH_EVENTS", "n": n,
                "method": method, "page_title": page_title[:80],
                "raw_candidates": len(raw), "rejects": rejects
            })
        except StepError as ex:
            log(f"  FAIL {ex}")
            status.append({"source": src["name"], "status": "FAIL", "ok": False, "n": 0, "err": str(ex)[:200]})
        except Exception as ex:
            log(f"  FAIL {type(ex).__name__}: {ex}")
            status.append({"source": src["name"], "status": "FAIL", "ok": False, "n": 0, "err": f"{type(ex).__name__}: {str(ex)[:150]}"})
        time.sleep(2)

    health = load(HEALTH, {})
    today_iso = TODAY.isoformat()
    for s in status:
        name = s["source"]
        prev = health.get(name, {})
        consec = prev.get("consecutive_fail", 0)
        if s["status"] in ("FAIL", "EMPTY_UNVERIFIED"):
            consec += 1
        else:
            consec = 0
        health[name] = {
            "last_status": s["status"],
            "last_n": s.get("n", 0),
            "last_method": s.get("method"),
            "last_error": s.get("err"),
            "raw_candidates": s.get("raw_candidates"),
            "rejects": s.get("rejects"),
            "consecutive_fail": consec,
            "last_success": today_iso if s["status"] == "OK_WITH_EVENTS" else prev.get("last_success"),
            "updated": today_iso,
        }
    with open(HEALTH, "w", encoding="utf-8") as f:
        json.dump(health, f, ensure_ascii=False, indent=1)

    token = os.getenv("GITHUB_TOKEN")
    repo = os.getenv("GITHUB_REPOSITORY")
    if token and repo:
        try:
            headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
            r = requests.get(f"https://api.github.com/repos/{repo}/issues", params={"state": "open", "labels": "cpd-source-maintenance"}, headers=headers, timeout=20)
            open_issues = {i["title"]: i["number"] for i in r.json()} if r.status_code == 200 else {}
            for name, h in health.items():
                title = f"[CPD Source] {name} needs maintenance"
                if h["consecutive_fail"] >= 3 and h["last_status"] in ("FAIL", "EMPTY_UNVERIFIED"):
                    body = f"""Source: {name}\nStatus: {h['last_status']}\nMethod: {h.get('last_method')}\nLast success: {h.get('last_success') or 'never'}\nConsecutive failures: {h['consecutive_fail']}\nRaw candidates: {h.get('raw_candidates')}\nRejects: {h.get('rejects')}\nError: {h.get('last_error') or ''}\n"""
                    if title not in open_issues:
                        requests.post(f"https://api.github.com/repos/{repo}/issues", json={"title": title, "body": body, "labels": ["cpd-source-maintenance"]}, headers=headers, timeout=20)
                elif h["last_status"] in ("OK_WITH_EVENTS", "VERIFIED_EMPTY") and title in open_issues:
                    requests.patch(f"https://api.github.com/repos/{repo}/issues/{open_issues[title]}", json={"state": "closed", "state_reason": "completed"}, headers=headers, timeout=20)
        except Exception as ex:
            log(f"Issue sync skipped: {ex}")

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
    raw_count = len(events)
    events = dedup_events(events)
    log(f"Dedup: {raw_count} -> {len(events)}")
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"updated": dt.datetime.now(HKT).isoformat(timespec="minutes"), "status": status, "events": events}, f, ensure_ascii=False, indent=1)
    log("\n========== SUMMARY ==========")
    for s in status:
        log(f"{s.get('status','?')} {s['source']}: n={s.get('n',0)} via {s.get('method','')} raw={s.get('raw_candidates','-')}")
    log(f"Total events: {len(events)}")

if __name__ == "__main__":
    main()
