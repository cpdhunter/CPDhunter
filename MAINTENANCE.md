# MAINTENANCE.md — CPD Hunter

## Architecture
- **Frontend**: Static HTML/JS on GitHub Pages (`index.html`). No server-side user data.
- **Data**: `events.json` (generated daily), `sources.json` (source list), `manual.json` (manual events).
- **Scraper**: `scraper/fetch.py` runs via GitHub Actions (`Daily CPD update` workflow).
  - After dedup: `reg_discover.py` attaches non-PII registration destination metadata; then `gforms.py` parses public Google Forms schemas.
  - Priority: official API/feed → JSON-LD → source-specific BeautifulSoup parser → Playwright → generic.
  - Classification: deterministic keyword rules first; optional Cloudflare Workers AI only for low-confidence cases.
  - Playwright Chromium used for JS-rendered pages.
- **Schedule**: Daily at 06:00 HKT (`cron: 0 22 * * *` UTC). Manual trigger available.
- **Zero mandatory cost**: No paid APIs required. Cloudflare AI is optional within free tier.

## Source statuses
- `OK_WITH_EVENTS`: Parser extracted one or more valid upcoming events.
- `VERIFIED_EMPTY`: Page loaded and independently confirmed to have no upcoming events.
- `EMPTY_UNVERIFIED`: Page loaded but zero events extracted; absence not confirmed.
- `FAIL`: Access, runtime, or parser error.

A 0-event result is `EMPTY_UNVERIFIED` unless positively verified empty.

## Adding / disabling a source
Edit `sources.json`. Example entry:
```json
{"name": "Example Org", "group": "Example", "region": "HK", "url": "https://example.org/events", "type": "Technical"}
```
- `region`: `HK` or `Overseas`
- `type`: optional default (`Technical` / `GPM` / `H&S`)
- `free: true`: treat all events as free
- `disabled: true`: skip source

## Source parsers
Located in `scraper/fetch.py`:
- `extract_oshc` — OSHC seminars table
- `extract_hkie_cpd` — HKIE CPD Calendar
- `extract_hkie_div` — HKIE division pages
- `extract_ice` — ICE event cards
- `extract_cic` — CIC date lists
- `extract_csb` — CSB/Labour tables
- `extract_hkgbc` — HKGBC listings
- Fallback: `generic_extract` or Playwright

## Running locally
```bash
cd scraper
pip install -r requirements.txt
python -m playwright install chromium
python fetch.py
```
Requires network. Outputs `../events.json` and `../source_health.json`.

## Running the GitHub workflow
Actions → **Daily CPD update** → **Run workflow**.

## Source health
`source_health.json` tracks per source:
- last successful extraction date
- latest status / event count
- consecutive failure count
- method, error, candidate/valid counts, rejection reasons

## Automated maintenance issues
If a source is `FAIL` or `EMPTY_UNVERIFIED` for **3 consecutive daily runs**, the scraper (when run in Actions with `GITHUB_TOKEN`) opens or updates one issue:
**Title**: `[CPD Source] <source name> needs maintenance`

Issue body includes URL, status, method, last success, consecutive failures, diagnostics.

When the source recovers (`OK_WITH_EVENTS` or `VERIFIED_EMPTY`), the open maintenance issue is closed.

## Manual events
Add objects to `manual.json`. They are preserved across runs if the date is still upcoming.

## Cloudflare fallback
Optional. Set secrets `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_AI_TOKEN` in repo Settings → Secrets. Used only for ambiguous classification. If unavailable or quota exceeded, deterministic rules are used.

## Recovering a failed deployment
1. Check Actions run logs.
2. If `events.json` was not updated, previous healthy data is retained.
3. Fix parser / source URL if needed.
4. Re-run workflow.

## events.json schema
```json
{
  "updated": "ISO-8601 HKT",
  "status": [ { "source": "...", "status": "OK_WITH_EVENTS|VERIFIED_EMPTY|EMPTY_UNVERIFIED|FAIL", "n": 0, "method": "...", "raw_candidates": 0, "rejects": {} } ],
  "events": [ { "id", "name", "org", "date", "time", "hrs", "hrs_est", "type", "disc", "url", "region", "online", "free", "source", "group", "auto" } ]
}
```
