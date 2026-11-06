# CPD Hunter：免費工程 CPD 月曆

每日香港時間朝早 6:00 自動搵香港及海外嘅免費工程 CPD 活動，以月曆顯示活動名稱同 CPD 時數，並按 DSTM / OTM / GPM / H&S 分類。

**Live site (public):** https://cpdhunter.github.io/CPDhunter/

Current production serves the restored full frontend and shows approximately **100 future events** from the latest daily dataset (about 110 unique events in `events.json`).

**Zero mandatory cost.** Core system runs on free GitHub Pages + Actions. No paid APIs required. Cloudflare Workers AI is an optional classification fallback only. Cloudflare Pages and Cloudflare Access are **not** deployed.

See [MAINTENANCE.md](MAINTENANCE.md) for architecture, source management, health tracking, and recovery. See [PRIVATE_BETA.md](PRIVATE_BETA.md) for the **planned / not deployed** private beta roadmap.

## Current production architecture

- **Hosting:** public GitHub Pages (`index.html` calendar, list, My Progress, Settings).
- **Repository / site visibility:** public.
- **Daily update:** GitHub Actions workflow `Daily CPD update` at **06:00 HKT** (`cron: 0 22 * * *` UTC); manual run available.
- **Scraper:** `scraper/fetch.py` using `requests` + BeautifulSoup.
- **Extraction order:** official API/feed → JSON-LD → source-specific parsers → Playwright Chromium fallback → generic extraction.
- **Classification:** deterministic keyword rules first; optional Cloudflare Workers AI only for ambiguous / low-confidence cases.
- **Deduplication:** conservative strong-signal merge (same or near-identical events with corroborating signals only; Phase 1 frozen behaviour).
- **Health:** `source_health.json` plus automatic GitHub Issues titled `[CPD Source] … needs maintenance` after 3 consecutive daily `FAIL` / `EMPTY_UNVERIFIED` results (closed on recovery).
- **Source status model:**
  - `OK_WITH_EVENTS`
  - `VERIFIED_EMPTY`
  - `EMPTY_UNVERIFIED`
  - `FAIL`
- **Local features in the live frontend:** CPD progress tracking and CSV export (browser `localStorage` only).

## What is NOT live

- `registration.js` is an **unconnected experimental Sprint 1 module** in the repository. It is **not** loaded by `index.html`.
- Registration Profile UI is **not** deployed.
- Prepare Registration UI is **not** deployed.
- Automatic registration / autofill / auto-submit do **not** exist.
- Cloudflare Pages hosting is **not** deployed.
- Cloudflare Access (email OTP / allowlist) is **not** configured.
- The repository and GitHub Pages site remain **public**.

Do not treat planned private-beta features in [PRIVATE_BETA.md](PRIVATE_BETA.md) as completed production behaviour.

## 上線步驟（大約 15 分鐘）
1. 打開 `config.js`，改頭 3 行：營運者名稱、聯絡電郵、生效日期。
2. 去 github.com 開帳戶，撐 **＋ → New repository**：
   - 名稱填 `CPDhunter`（或你自己嘅 repo 名）
   - 揀 **Public**
   - 剔 **Add a README file**
3. 喺 repo 撐 **Add file → Upload files**，將解壓後嘅**所有檔案同資料夾**一次過拖入去，然後撐 **Commit changes**。
   - Mac 用戶：Finder 按 **Cmd + Shift + .** 先見到 `.github` 同 `.nojekyll`。
   - 上載後確認 repo 有 `.github/workflows/update.yml`。
4. **Settings → Pages → Source** 揀 **GitHub Actions**。
5. **Settings → Actions → General → Workflow permissions** 揀 **Read and write permissions**，撐 **Save**。
6. **Actions** 頁：撐 *Daily CPD update* → **Run workflow**，等 3 至 10 分鐘見到綠剔。
7. 網址：`https://<你個username>.github.io/<repo>/`
   本專案正式公開網址：`https://cpdhunter.github.io/CPDhunter/`

## 檔案說明
| 檔案 | 用途 |
|---|---|
| `index.html` | 主網站（月曆、列表、我的進度、設定）— 目前**未**連接 `registration.js` |
| `registration.js` | Sprint 1 實驗模組（本機 profile / registration-state helpers + disabled adapter）。**未連接前端，未上線** |
| `terms.html` / `privacy.html` | 使用條款 / 私隱政策（中英對照；描述目前公開 GitHub Pages 行為） |
| `config.js` | 營運者名稱、電郵、生效日期 |
| `assets/` | Logo 同網站 icon |
| `sources.json` | CPD 來源清單 |
| `manual.json` | 人手加嘅活動 |
| `events.json` | 程式每日自動更新，唔使改 |
| `source_health.json` | 來源健康狀態（連續失敗計數、診斷） |
| `scraper/fetch.py` | 每日搵 CPD 嘅程式（requests/BeautifulSoup、source parsers、Playwright fallback、conservative dedup） |
| `scraper/test_parsers.py` | Parser / classification / dedup regression tests |
| `.github/workflows/update.yml` | 每日自動執行設定 |
| `MAINTENANCE.md` | 維護指南 |
| `PRIVATE_BETA.md` | 私人 beta **計劃**（Status: PLANNED / NOT DEPLOYED） |

## CPD 時數點計
1. 主辦方網頁有寫就照用。
2. 唔寫但有開始同結束時間，就按時長估算，顯示「~1.5h」。
3. 兩樣都唔就顯示「–」。

## 日常維護
- **加減來源**：改 `sources.json`。`region` 填 `HK` 或 `Overseas`；`type` 可填預設類別（例如 `H&S`）；`free: true` 代表全部免費；`disabled: true` 暫停。
- **人手加活動**：喺 `manual.json` 加。
- **檢查來源**：`events.json` 嘅 `status` 或 `source_health.json`。連續 3 次 `FAIL` / `EMPTY_UNVERIFIED` 會自動開 `[CPD Source]` GitHub Issue。
- 詳見 [MAINTENANCE.md](MAINTENANCE.md)。
