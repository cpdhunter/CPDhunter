# CPD Hunter — Private Friends & Family Beta (Sprint 1)

> **Hosting / Access status: PLANNED / NOT DEPLOYED**
>
> Cloudflare Pages and Cloudflare Access remain a **future** private-beta plan. They are **not** live.
>
> **Local Registration Profile + Prepare Registration: IMPLEMENTED** on the public GitHub Pages site (device-local only; no autofill / no auto-submit).

## Current production (verified)

- Public GitHub Pages site: https://cpdhunter.github.io/CPDhunter/
- Public GitHub repository
- Full production frontend (`index.html`) with calendar, list, filters, event modal, My Progress, Settings, CSV export, Terms / Privacy
- Approximately 100 future events visible from the latest daily dataset
- **IMPLEMENTED:** Settings → Registration Profile (browser `localStorage` only)
- **IMPLEMENTED:** Event modal → Prepare Registration (opens organiser URL; Google Forms partial prefill when schema is present; no autofill of other sites; no submit)
- **IMPLEMENTED:** Local registration status (`not_started` | `opened` | `registered_manual` | `cancelled`)
- **IMPLEMENTED:** Local ICS “Add to Calendar” (`calendar_export.js`; official event URL only; no Profile PII)
- **IMPLEMENTED:** Post-event attendance prompt → review form → existing CPD log (`attendance.js` + `cpd_bridge.js`; duplicate-safe)
- **IMPLEMENTED:** Home / Events / My CPD / Settings navigation with My Events groups
- No autofill of organiser forms
- No auto-submit / automatic registration
- No Cloudflare Access
- No private email allowlist
- Cloudflare Pages is **not** deployed
- Cloudflare Access is **not** configured

## Implemented local registration helpers (connected)

These helpers live in `registration.js` and are loaded by the production frontend.

- `registration.js` (referenced by `index.html`; covered by `registration.test.js`)
- Browser-local registration profile (`localStorage` key `regProfile`, schema version `1`)
  - Allowed fields: `title`, `englishName`, `chineseName`, `email`, `phone`, `position`, `organisation`, `hkieNumber`, `primaryDiscipline`, `secondaryDiscipline`, `preferredLanguage`
  - Required for a complete profile: `englishName`, `email`, `organisation`, `position`, `primaryDiscipline` (`title` is optional)
  - Export / import / validation / delete helpers enforce allowlist, conservative email checks, exact per-field length limits (import/save reject oversized or invalid-typed fields), and a 100 KB UTF-8 import cap
- Browser-local registration-state helper (`localStorage` key `regState`)
  - Enforced state labels only: `not_started` | `opened` | `registered_manual` | `cancelled`
  - Rejects non-plain objects/arrays and unsafe keys (`__proto__`, `constructor`, `prototype`); `deleteProfile` and `clearRegState` remain separate
  - Local notes only; does not modify `events.json` and does not contact organisers
- Google Forms adapter on `window.RegistrationAdapter` (Sprint 2B2)
- Registration destination discovery on events (Sprint 2C): `registration.destination` / mechanism metadata from the daily scrape — still no autofill except Google Forms partial prefill; no submit
  - Daily scraper (`scraper/gforms.py`) attaches non-personal `event.registration` schema (entry IDs, labels, types, safe profileField mappings) — never profile values
  - On user confirmation, the browser builds a **temporary** prefilled Google Forms URL from the local Registration Profile and opens it with `noopener,noreferrer`
  - Consent, title/honorific, member Y/N, and other judgment fields are never prefilled; split surname/given-name fields stay manual
  - No `submit()`; no `formResponse` POST; URL is not stored in `localStorage`, `events.json`, or logs

## Target architecture (planned private hosting)

```
Private GitHub repository (future target only)
        |
        +--> GitHub Actions
        |      |
        |      +--> CPD scraper (scraper/fetch.py)
        |      +--> source health
        |      +--> events.json
        |
        +--> Cloudflare Pages (planned web hosting target)
               |
               +--> Cloudflare Access (planned)
               |      |
               |      +--> email OTP
               |      +--> explicit owner-approved email allowlist
               |
               +--> CPD Hunter private website
                      |
                      +--> calendar / list / CPD progress
                      +--> Settings → Registration Profile (local only; already on public Pages)
                      +--> Prepare Registration (no auto-submit; already on public Pages)
                      +--> local registration state
```

GitHub remains the source of truth and scraper executor. Cloudflare Pages would be the intended private web deployment target. Cloudflare Access would be the intended access control (email OTP + owner-approved allowlist). No custom username/password system.

## Remaining future plan (hosting only)

Local registration UI and legal updates for it are done. Remaining ordered work for private beta hosting:

1. Deploy Cloudflare Pages for a private beta host (free-tier target).
2. Configure Cloudflare Access with email OTP and an owner-approved allowlist only.
3. Verify the private deployment end-to-end (access gate, public Pages still healthy until cutover is intentional).
4. Only then consider making the repository private and retiring public GitHub Pages.

## Registration Profile (implemented UI)

Profile data remains device-local only under `regProfile`.

Schema (version 1):

```json
{
  "version": 1,
  "title": "",
  "englishName": "",
  "chineseName": "",
  "email": "",
  "phone": "",
  "position": "",
  "organisation": "",
  "hkieNumber": "",
  "primaryDiscipline": "",
  "secondaryDiscipline": "",
  "preferredLanguage": ""
}
```

- Export creates a local JSON file controlled by the user.
- Import validates structure / version / required fields before saving.
- Delete removes the local profile.
- No profile data is sent to GitHub, Cloudflare, `events.json`, or any API by CPD Hunter.

## Registration State (implemented UI)

Stored only in `localStorage` under key `regState`.

States: `not_started` | `opened` | `registered_manual` | `cancelled`

Marking "Registered manually" is a local note only. It does not mean the organiser has confirmed registration, and it does not modify `events.json`.

## Prepare Registration (implemented; no auto-submit)

Event-detail flow:

1. Official organiser link is preserved.
2. "準備報名 / Prepare Registration" shows a preparation panel if the local profile is complete.
3. If the profile is incomplete, Settings → Registration Profile is shown with missing required fields listed.
4. The panel shows event name, organiser, date/time, CPD hours, official URL, and the message "You are not registered yet."
5. "Open official registration page" opens `event.url` in a new tab (`noopener,noreferrer`). It does not put profile data in the URL, does not autofill, and does not submit any form. Local state becomes `opened`.
6. When `event.registration.mechanism` is `GOOGLE_FORMS` and status is `OPEN`, Prepare Registration may offer **Open prefilled Google Form** after a one-time confirmation. Selected local profile values are placed only in a temporary Google Forms URL (may appear in browser history / be sent to Google). Consent and questionnaire answers are not filled. Local state becomes `opened` (not registered). You must review and submit on Google Forms yourself.
6. No automatic form submission in Sprint 1.

## Future adapter model (framework only; currently disabled)

`window.RegistrationAdapter` exists as a disabled placeholder with:

- `canHandle(url)`
- `inspect()`
- `matchFields()`
- `fill()`
- `validate()`
- `getUnsupportedFields()`

`submit()` is intentionally not implemented and unreachable. A later sprint may add form detection, field matching, autofill, and user-confirmed submission. Unattended submission is not the default and is not planned as the Sprint 1 outcome.

## How to add/remove a beta user (Cloudflare Access) — when configured later

When Cloudflare Access is configured:

1. Open Cloudflare Zero Trust → Access → Applications.
2. Select the CPD Hunter application.
3. Edit the Allow policy.
4. Add or remove email addresses in the include rule.
5. Save. Only listed emails can pass the email OTP challenge.

Do not invent email addresses. The operator must supply the approved list.

## How to migrate back to public (future)

1. Remove or disable the Cloudflare Access application.
2. Optionally point DNS or the custom domain back to GitHub Pages.
3. Keep the repository public if public access is desired.
4. Local registration-profile features continue to work without Access; they are optional and device-local.

## How to leave private hosting undeployed (current safe state)

- Leave Cloudflare Access unconfigured / disabled.
- Keep serving the public GitHub Pages site (including local Registration Profile / Prepare Registration).
- Do not claim Cloudflare / private-access deployment until it is actually configured.

## Zero-cost assumptions

- GitHub free tier (Actions + Pages, or private repo with Actions later).
- Cloudflare free tier (Pages + Access email OTP, within free limits) **if/when** private beta hosting is deployed.
- No paid Workers, D1, identity provider, or AI dependency required for Sprint 1 private beta.
- Mandatory monthly infrastructure cost target: HK$0.

## Recovery

- Scraper recovery: see [MAINTENANCE.md](MAINTENANCE.md).
- Until Cloudflare Pages is intentionally adopted, GitHub Pages remains the operational public site.
- If a future Cloudflare deployment fails, keep GitHub Pages healthy as the fallback.
- Profile data lives only in the user's browser; export before clearing browser data.

## Out of scope (Sprint 1)

Automatic form submission, unattended auto-registration, subscriptions, payments, public account creation, password database, remote profile storage, browser extension, CAPTCHA automation, scraping behind login.
