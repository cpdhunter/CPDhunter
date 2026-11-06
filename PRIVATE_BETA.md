# CPD Hunter — Private Friends & Family Beta (Sprint 1)

> **Status: PLANNED / NOT DEPLOYED**
>
> This document is a **future implementation plan**. None of the private-beta hosting or registration UI described below is live in production today.

## Current production (verified)

- Public GitHub Pages site: https://cpdhunter.github.io/CPDhunter/
- Public GitHub repository
- Restored full production frontend (`index.html`) with calendar, list, filters, My Progress, Settings, and CSV export
- Approximately 100 future events visible from the latest daily dataset
- No Cloudflare Access
- No private email allowlist
- No Registration Profile UI
- No Prepare Registration UI
- No autofill
- No auto-submit / automatic registration
- Cloudflare Pages is **not** deployed
- Cloudflare Access is **not** configured

## Already implemented but not connected

These helpers exist in the repository as an experimental Sprint 1 module. They are **not** loaded by the live frontend and must not be described as production features.

- `registration.js` (unconnected; not referenced by `index.html`)
- Browser-local registration profile helper (`localStorage` key `regProfile`, schema version `1`)
  - Allowed fields: `title`, `englishName`, `chineseName`, `email`, `phone`, `position`, `organisation`, `hkieNumber`, `primaryDiscipline`, `secondaryDiscipline`, `preferredLanguage`
  - Required for a complete profile: `title`, `englishName`, `email`, `organisation`, `primaryDiscipline`
  - Export / import / validation / delete helpers are present in the module
- Browser-local registration-state helper (`localStorage` key `regState`)
  - Documented state labels: `not_started` | `opened` | `registered_manual` | `cancelled`; the helper stores caller-provided state strings and does not enforce this list
  - Local notes only; does not modify `events.json` and does not contact organisers
- Disabled adapter interface on `window.RegistrationAdapter`
  - Contract stubs: `canHandle`, `inspect`, `matchFields`, `fill`, `validate`, `getUnsupportedFields`
  - `canHandle` always returns `false`; `fill` is disabled; `validate` reports no auto-fill
  - No `submit()` implementation; automatic form submission is out of scope

## Target architecture (planned)

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
                      +--> Settings → Registration Profile (local only; planned UI)
                      +--> Prepare Registration (no auto-submit; planned UI)
                      +--> local registration state
```

GitHub remains the source of truth and scraper executor. Cloudflare Pages would be the intended private web deployment target. Cloudflare Access would be the intended access control (email OTP + owner-approved allowlist). No custom username/password system.

## Planned ordered work

Do this sequence only after production documentation and legal wording match reality:

1. Review and harden `registration.js` (validation, export/import edge cases, adapter safety).
2. Update `privacy.html` / `terms.html` **before** activating any registration-profile UI, so legal text matches actual collection behaviour.
3. Safely integrate Registration Profile / Prepare Registration into the restored production frontend without regressing calendar, list, filters, My Progress, or Settings.
4. Add automated tests covering profile completeness, import validation, registration-state transitions, and disabled adapter behaviour.
5. Deploy Cloudflare Pages for a private beta host (free-tier target).
6. Configure Cloudflare Access with email OTP and an owner-approved allowlist only.
7. Verify the private deployment end-to-end (access gate, public Pages still healthy until cutover is intentional).
8. Only then consider making the repository private and retiring public GitHub Pages.

## Registration Profile (planned UI over existing helper)

When integrated later, profile data would remain device-local only under `regProfile`.

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

- Export would create a local JSON file.
- Import would validate structure / version / required fields before saving.
- Delete would remove the local profile.
- No profile data would be sent to GitHub, Cloudflare, `events.json`, or any API.

## Registration State (planned UI over existing helper)

Stored only in `localStorage` under key `regState`.

States: `not_started` | `opened` | `registered_manual` | `cancelled`

Marking "Registered manually" would be a local note only. It would not mean the organiser has confirmed registration, and it would not modify `events.json`.

## Prepare Registration (planned; not deployed)

Intended event-detail flow after safe frontend integration:

1. Official organiser link is preserved.
2. "準備報名" opens a preparation panel if the local profile is complete.
3. If the profile is incomplete, Settings → Registration Profile is shown.
4. The panel shows event details, official URL, and profile completeness.
5. "Open official registration page" opens the organiser URL. It does not submit any form.
6. No automatic form submission in Sprint 1.

## Future adapter model (framework only; currently disabled)

`window.RegistrationAdapter` already exists as a disabled placeholder with:

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
4. Any later local registration-profile features would continue to work without Access; they are optional and device-local.

## How to leave private beta undeployed (current safe state)

- Leave Cloudflare Access unconfigured / disabled.
- Keep serving the restored public GitHub Pages site.
- Leave `registration.js` unconnected until review, legal updates, frontend integration, and tests are complete.

## Zero-cost assumptions

- GitHub free tier (Actions + Pages, or private repo with Actions later).
- Cloudflare free tier (Pages + Access email OTP, within free limits) **if/when** private beta hosting is deployed.
- No paid Workers, D1, identity provider, or AI dependency required for Sprint 1 private beta.
- Mandatory monthly infrastructure cost target: HK$0.

## Recovery

- Scraper recovery: see [MAINTENANCE.md](MAINTENANCE.md).
- Until Cloudflare Pages is intentionally adopted, GitHub Pages remains the operational public site.
- If a future Cloudflare deployment fails, keep GitHub Pages healthy as the fallback.
- Any future profile data would live only in the user's browser; export before clearing browser data.

## Out of scope (Sprint 1)

Automatic form submission, unattended auto-registration, subscriptions, payments, public account creation, password database, remote profile storage, browser extension, CAPTCHA automation, scraping behind login.
