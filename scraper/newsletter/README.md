# CIC i-Club newsletter discovery pilot

Isolated fixture-based discovery path for CIC / i-Club CPD activities that may not appear on public CIC listings.

- Input: sanitized `.eml` / HTML / text fixtures only. **No live mailbox.**
- Output: a JSON report under `artifacts/` (gitignored). **Never writes `events.json` or `source_health.json`.**
- HTTP, if enabled with `--verify`, is **GET-only**. No POST, no registration, no tracking pixels, no remote email images.

## Run

From the repo root:

```bash
python3 scraper/newsletter/run_pilot.py --offline
python3 scraper/test_newsletter_cic_iclub.py
```

## Trusted senders

Allowlist domains (subdomains included): `cic.hk`, `cic.org.hk`.

Arbitrary forwarded promotional email is not authoritative. Provenance emitted is only:

`discovery=NEWSLETTER`, `source=CIC i-Club Newsletter`, `organisation=CIC`, plus the trusted `sender_domain`.

Subscriber identity is stripped and must not appear in the report.

## Life First example

The sanitized fixture `fixtures/life_first_work_at_height.eml` contains only the known titles, organisation, and Zoom registration URL (no invented date/time/hours). Official date, time, cancellation, and closed registration were taken from a sanitized snapshot of a passive GET of the public destination on 2026-11-24 (Asia/Hong_Kong):

`https://cic-hk.zoom.us/webinar/register/WN_-U1WusN5Tq2LAxe2o70Ujw`

The official page showed the event as cancelled and originally scheduled for 2026-11-19, 14:00–15:05 (Hong Kong time). It is therefore not production-eligible.

## Workflow

Prefer the manual `CIC Newsletter Pilot` GitHub Actions workflow (`workflow_dispatch` only, no schedule). If that workflow file could not be added (missing `workflow` scope), use the CLI runner above.
