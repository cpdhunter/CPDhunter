# CPD Hunter \u2014 Private Friends & Family Beta (Sprint 1)

## Architecture

```
Private GitHub repository (target)
        |
        +--> GitHub Actions
        |      |
        |      +--> CPD scraper (scraper/fetch.py)
        |      +--> source health
        |      +--> events.json
        |
        +--> Cloudflare Pages (web hosting target)
               |
               +--> Cloudflare Access
               |      |
               |      +--> email OTP
               |      +--> explicit email allowlist
               |
               +--> CPD Hunter private website
                      |
                      +--> calendar / list / CPD progress
                      +--> Settings \u2192 Registration Profile (local only)
                      +--> Prepare Registration (no auto-submit)
                      +--> local registration state
```

GitHub remains the source of truth and scraper executor. Cloudflare Pages is the intended web deployment target. Cloudflare Access is the intended access control (email OTP + allowlist). No custom username/password system.

## Current status (Sprint 1 implementation)

- Frontend features for private beta are implemented in this repository.
- Registration profile, export/import, local registration state, and Prepare Registration are device-local only.
- Scraper architecture is unchanged.
- Cloudflare Pages deployment and Cloudflare Access configuration require a connected Cloudflare account (not available via current integrations).
- Repository visibility remains public until Cloudflare Pages private deployment is verified.

## Registration Profile

Stored only in the browser via `localStorage` under key `regProfile`.

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

- Export creates a local JSON file.
- Import validates structure and required fields before saving.
- Delete removes the local profile.
- No profile data is sent to GitHub, Cloudflare, events.json, or any API.

## Registration State

Stored only in `localStorage` under key `regState`.

States: `not_started` | `opened` | `registered_manual` | `cancelled`

Marking "Registered manually" is a local note only. It does not mean the organiser has confirmed registration, and it does not modify events.json.

## Prepare Registration

On an event detail view:

1. Official organiser link is preserved.
2. "\u6e96\u5099\u5831\u540d" opens a preparation panel if the local profile is complete.
3. If the profile is incomplete, Settings \u2192 Registration Profile is shown.
4. The panel shows event details, official URL, and profile completeness.
5. "Open official registration page" opens the organiser URL. It does not submit any form.
6. No automatic form submission exists in Sprint 1.

## Future adapter model (framework only)

A placeholder `window.RegistrationAdapter` exists with the contract:

- `canHandle(url)`
- `inspect()`
- `matchFields()`
- `fill()`
- `validate()`
- `getUnsupportedFields()`

`submit()` is intentionally not implemented and unreachable. Sprint 2 may add form detection, field matching, autofill, and user-confirmed submission. Unattended submission is not the default.

## How to add/remove a beta user (Cloudflare Access)

When Cloudflare Access is configured:

1. Open Cloudflare Zero Trust \u2192 Access \u2192 Applications.
2. Select the CPD Hunter application.
3. Edit the Allow policy.
4. Add or remove email addresses in the include rule.
5. Save. Only listed emails can pass the email OTP challenge.

Do not invent email addresses. The operator must supply the approved list.

## How to migrate back to public

1. Remove or disable the Cloudflare Access application.
2. Optionally point DNS or the custom domain back to GitHub Pages.
3. Keep the repository public if public access is desired.
4. The local registration profile features continue to work; they do not require Access.

## How to disable private beta

- Leave Cloudflare Access disabled or remove the application.
- The site remains usable on GitHub Pages with the existing features.
- Registration profile features are optional and local.

## Zero-cost assumptions

- GitHub free tier (Actions + Pages or private repo with Actions).
- Cloudflare free tier (Pages + Access email OTP, within free limits).
- No paid Workers, D1, identity provider, or AI dependency for Sprint 1.
- Mandatory monthly infrastructure cost target: HK$0.

## Recovery

- Scraper recovery: see MAINTENANCE.md.
- If Cloudflare deployment fails, GitHub Pages remains the operational site.
- Profile data lives only in the user's browser; export before clearing browser data.

## Out of scope (Sprint 1)

Automatic form submission, unattended auto-registration, subscriptions, payments, public account creation, password database, remote profile storage, browser extension, CAPTCHA automation, scraping behind login.
