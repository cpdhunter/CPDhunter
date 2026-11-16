# Scrapling shadow pilot (experimental)

This directory is an **isolated shadow path**. It evaluates whether
[Scrapling](https://github.com/D4Vinci/Scrapling) adaptive selectors can reduce
maintenance when CIC, HKIE CPD Calendar, or HKGBC listing markup drifts.

It is **not** a production scraper.

## Non-negotiable rules

- Shadow events **never** flow into `events.json`, `source_health.json`,
  recommendations, registration metadata, production dedup, or GitHub Pages data.
- Existing production fetch/parsers remain the source of truth.
- This pilot does **not** use Scrapling for CAPTCHA solving, Cloudflare
  challenge bypass, access-control bypass, proxy rotation, residential proxies,
  login/session bypass, or stealth scraping of blocked sources.
- HKIS 403 is out of scope.
- Daily CPD (`.github/workflows/update.yml`) is **not** wired to this pilot.
  Adaptive state is never auto-committed from a scheduled run.

## Architecture

```
Official source  →  current production fetch/parser  →  clean/filter/dedup  →  events.json

Official source  →  Scrapling (shadow parser)  →  normalize  →  comparison only  →  artifacts/scrapling-shadow.json
```

## Dependency

Isolated requirements file: `requirements-shadow.txt`.

| Item | Value |
| --- | --- |
| Package | `scrapling==0.5.1` (PyPI, parser-only install) |
| Python | `>=3.10` (classifiers 3.10–3.13). Tested in this pilot on CPython 3.13. Production CI uses 3.12, which is compatible. |
| Extra browser dependency | **None** for this pilot. JS rendering would require `scrapling[fetchers]` plus `scrapling install` (Playwright/Patchright). That extra was **not** installed: it pulls stealth/Cloudflare tooling that is out of scope, and production already has a Playwright fallback. |
| Additional install size | About **18 MB** in a fresh venv (Scrapling + `lxml`, `cssselect`, `orjson`, `tld`, `w3lib`, `frostwork`). `lxml` is already a system package in some environments, so the *new* unique weight can be smaller. |
| Additional install time | About **2 seconds** for `pip install scrapling==0.5.1` on a warm network (venv creation + pip upgrade is a few seconds more). |
| Paid services | None. |

Do **not** add Scrapling to `scraper/requirements.txt`. Production continues to use `requests`, `BeautifulSoup`, and `Playwright`.

Install for local shadow work only:

```bash
python3 -m venv scraper/shadow/.venv
scraper/shadow/.venv/bin/pip install -r scraper/requirements.txt
scraper/shadow/.venv/bin/pip install -r scraper/shadow/requirements-shadow.txt
```

## How to run

```bash
# Shadow tests only
scraper/shadow/.venv/bin/python scraper/shadow/tests/run_tests.py

# Fixture comparison + adaptive experiment + optional polite live GET
scraper/shadow/.venv/bin/python scraper/shadow/scrapling_shadow.py --no-live
scraper/shadow/.venv/bin/python scraper/shadow/scrapling_shadow.py   # tries one HTTP GET per source
```

The report is written to `scraper/shadow/artifacts/scrapling-shadow.json`. It is diagnostic only.

## Adaptive matching

Scrapling's current API uses `auto_save` / `adaptive` (formerly automatch):

```python
page = Selector(html, adaptive=True, url=..., storage=JsonFileStorage, storage_args={...})
page.css("article.event-card", auto_save=True, identifier="cic_event_card")
# after a layout change:
page.css("article.event-card", adaptive=True, identifier="cic_event_card")
```

Known library limitation (documented by Scrapling): **only the first matched element's fingerprint is saved**. Adaptive relocate is therefore evaluated as "can we recover the intended card after a class/wrapper change?", not as "re-list every sibling card automatically".

## Persistence experiment

Default Scrapling storage is SQLite at `site-packages/scrapling/elements_storage.db` — a binary file in an ephemeral location on GitHub Actions, and a poor fit for review.

This pilot uses a custom `JsonFileStorage` (`json_storage.py`) that writes small, source-specific, UTF-8 JSON fingerprints under `adaptive_state/`.

| Option | Verdict |
| --- | --- |
| **A. Checked-in JSON artefact** | **Preferred.** Each source file is hundreds of bytes, text-readable, keyed by `(domain, identifier)`, overwritten in place (no unbounded growth). Total experimental state must stay under 1 MB (this pilot is well under). |
| **B. GitHub Actions cache** | Possible later, but runners are ephemeral and cache is not auditable in PRs. Not the primary mechanism, and not wired into Daily CPD. |
| **C. Regenerate from fixtures** | **Backup.** `establish_fingerprint()` can rebuild state from the committed official fixtures at any time. |

Do not commit Scrapling's SQLite database. Do not auto-commit changing live adaptive data.

## JavaScript rendering

Evaluated only where a source genuinely needs JS. This pilot parses official **fixtures** (and a single optional HTTP GET) with the Scrapling **parser**. It does not launch a browser.

- CIC: fixtures contain event cards; a live listing may be JS-rendered (production already has a Playwright retry).
- HKIE CPD: official fixture HTML already contains `.e-loop-item` course cards.
- HKGBC: official fixture HTML already contains `.event-card` / `.eventpost` listings.
