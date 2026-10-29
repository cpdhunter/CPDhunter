# CPD Hunter：免費工程 CPD 月曆

每日香港時間朝早 6:00 自動搵香港及海外嘅免費工程 CPD 活動，以月曆顯示活動名稱同 CPD 時數，並按 DSTM / OTM / GPM / H&S 分類。

## 上線步驟（大約 15 分鐘）
1. 打開 `config.js`，改頭 3 行：營運者名稱、聯絡電郵、生效日期。
2. 去 github.com 開帳戶，撳 **＋ → New repository**：
   - 名稱填 `cpd-hunter`
   - 揀 **Public**
   - 剔 **Add a README file**
3. 喺 repo 撳 **Add file → Upload files**，將解壓後嘅**所有檔案同資料夾**一次過拖入去，然後撳 **Commit changes**。
   - Mac 用戶：Finder 按 **Cmd + Shift + .** 先見到 `.github` 同 `.nojekyll`。
   - 上載後確認 repo 有 `.github/workflows/update.yml`。
4. **Settings → Pages → Source** 揀 **GitHub Actions**。
5. **Settings → Actions → General → Workflow permissions** 揀 **Read and write permissions**，撳 **Save**。
6. **Actions** 頁：撳 *Daily CPD update* → **Run workflow**，等 3 至 10 分鐘見到綠剔。
7. 網址：`https://<你個username>.github.io/cpd-hunter/`

## 檔案說明
| 檔案 | 用途 |
|---|---|
| `index.html` | 主網站（月曆、列表、我的進度、設定） |
| `terms.html` / `privacy.html` | 使用條款 / 私隱政策（中英對照） |
| `config.js` | 營運者名稱、電郵、生效日期 |
| `assets/` | Logo 同網站 icon |
| `sources.json` | CPD 來源清單 |
| `manual.json` | 人手加嘅活動 |
| `events.json` | 程式每日自動更新，唔使改 |
| `scraper/fetch.py` | 每日搵 CPD 嘅程式 |
| `.github/workflows/update.yml` | 每日自動執行設定 |

## CPD 時數點嚟
1. 主辦方網頁有寫就照用。
2. 冇寫但有開始同結束時間，就按時長估算，顯示「~1.5h」。
3. 兩樣都冇就顯示「–」。

## 日常維護
- **加減來源**：改 `sources.json`。`region` 填 `HK` 或 `Overseas`；`type` 可填預設類別（例如 `H&S`）；`free: true` 代表全部免費；`disabled: true` 暫停。
- **人手加活動**：喺 `manual.json` 加，例如：
  `{"name":"...","org":"...","group":"...","date":"2026-12-01","time":"19:00-20:30","hrs":1.5,"type":"Technical","disc":["Civil"],"url":"https://...","region":"HK","online":true,"free":true}`
- **檢查來源**：網站「設定」頁或 `events.json` 嘅 `status`。某來源長期 0 個活動，即網站可能改咗版。
