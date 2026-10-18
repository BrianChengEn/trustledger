# 任務書 2 — Frontend Engineer（React + TypeScript + Vite）

## 任務結果

交付一個精緻、可鍵盤操作、對金融初學者友善的 B2C Demo。三個核心 surface：Overview/Transactions、Alert Detail + Human Confirmation、Privacy & Memory。前端只呼叫自家 FastAPI，從不接觸 Nessie/Jev/Backboard key。

## 你的檔案所有權

```text
frontend/**
```

`contracts/internal-api.openapi.yaml` 為只讀；需要變更先向 Integration Engineer 提案。不要在 UI 直接 call vendors，不要在 Vite env 放 secrets。

## 從零建立環境

先看 [START-HERE.md](START-HERE.md)。可立即安裝 Git 與 Node；`npm ci`、啟動及測試要等 Frontend owner 建立 scaffold、提交 package 與 lock files。macOS `brew` 指令預設已安裝 Homebrew。

### 必要版本

- Git 2.40+。
- Node.js 符合目前 Vite 官方要求：20.19+ 或 22.12+。建議 Node 22 LTS。
- npm 隨 Node 安裝。

### macOS

```bash
xcode-select --install
brew install git node@22 gh
git --version
node --version
npm --version
```

### Windows 11 PowerShell

```powershell
winget install --id Git.Git -e
winget install --id OpenJS.NodeJS.LTS -e
winget install --id GitHub.cli -e
git --version
node --version
npm --version
```

重新開啟 PowerShell 後再檢查版本。

### Ubuntu/Debian

```bash
sudo apt-get update
sudo apt-get install -y git nodejs npm
git --version
node --version
npm --version
```

若 `node --version` 低於 Vite 要求，不要硬跑；改用 Node 官方/團隊既定的 Node 22 安裝方式，再重新檢查。

### Clone 與安裝

```bash
git clone https://github.com/<ORG_OR_USER>/trustledger.git
cd trustledger/frontend
npm ci
cp ../frontend.env.example .env.local
npm run dev
```

Windows：

```powershell
git clone https://github.com/<ORG_OR_USER>/trustledger.git
Set-Location trustledger\frontend
npm ci
Copy-Item ..\frontend.env.example .env.local
npm run dev
```

若 repo 尚未 scaffold，由 Frontend owner 執行一次，其他人不要重複：

```bash
npm create vite@latest frontend -- --template react-ts --no-interactive
cd frontend
npm install
```

## Vite env 安全規則

只有下列 public config 可以是 `VITE_*`：

```text
VITE_API_BASE_URL=http://127.0.0.1:8000
VITE_DEMO_USER_LABEL=Demo user
```

Vite 會把 `VITE_*` 編進 browser bundle，所以 Nessie/Jev/Backboard key、database URL、deploy token 永遠不可以放進前端 env。PR 前執行：

```bash
rg -n "NESSIE|JEV_API|BACKBOARD|sk-|api[_-]?key|secret" src . --glob '!node_modules/**'
```

只允許 UI label、type name 或安全文件文字命中；任何真實值立即 rotate。

## 資訊架構

### 1. Overview / Transactions

- Header：TrustLedger、demo mode badge、Data/Analysis/Memory status。
- Summary：月支出、open alerts、已確認件數。只放真正有資料來源的 2–3 個數字。
- Transaction list：日期、merchant display、category、amount、source badge、alert state。
- `synthetic`/`nessie` 必須明確；不可用模糊「Bank connected」。
- Empty/loading/error/degraded 狀態齊全。

### 2. Alert Detail

- 明確標題：`可能的重複扣款`、`金額明顯不同`、`訂閱金額變動`。
- 顯示 evidence、confidence、provider mode。
- 文案避免「詐欺」「被盜」等斷言：使用「建議確認」「系統注意到」。
- 主要 actions：`這是正常交易`、`我想進一步檢查`。
- 確認前用 checkbox：`允許 TrustLedger 記住這項確認，以改善未來提醒`。預設不勾。
- vendor unavailable 時顯示 rules-only，不把技術 error/stack 暴露給使用者。

### 3. Privacy Inspector / Memory

- Field transformation table：原始欄位名稱、action、output、reason。
- Safe payload JSON viewer 只呈現 backend 回傳 `safe_payload`；不要在 browser 自行重新建構。
- 顯示目的地 Jev 或 Backboard memory。
- 記憶列表含 summary、建立時間、source、刪除按鈕。
- 刪除需二次確認，但不能做深色迷惑式設計。

## 視覺與無障礙

- 以清楚、可信任、低壓力為主：深海 navy + teal accent，可配合 Technica 2026 `Dare to Dive`，但不要冒充官方品牌。
- status 不只靠顏色；搭配文字與 icon。
- contrast 達 WCAG AA；focus ring 清楚。
- semantic `button`/`table`/headings/landmarks；modal 有 focus management。
- 金額使用 `Intl.NumberFormat`；日期明確顯示 local timezone。
- confidence 顯示百分比 + 說明，不能像信用分數。
- 320px 寬不水平破版；transaction table 在窄螢幕改 stacked rows。
- loading 使用 `aria-live="polite"`，error 使用可閱讀的 alert；避免不停 announce 動畫。
- 尊重 `prefers-reduced-motion`。

## Contract-first API client

只實作一層 typed API client：

```text
GET    /api/v1/health
GET    /api/v1/transactions
POST   /api/v1/analyses
GET    /api/v1/alerts
GET    /api/v1/privacy/preview/{transaction_id}
POST   /api/v1/alerts/{alert_id}/confirmations
GET    /api/v1/memories
DELETE /api/v1/memories/{memory_id}
```

精確 schema：[contracts/internal-api.openapi.yaml](contracts/internal-api.openapi.yaml)。

要求：

- `AbortController` timeout/cancel。
- HTTP non-2xx 解析統一 `ErrorEnvelope`；不直接顯示 upstream body。
- dev mock 與 real API 使用相同 TypeScript interfaces。
- component 不直接呼叫 `fetch`；只能透過 API client/hooks。
- mutation 後只 invalidates 必要 data，不全頁 reload。

## 先用 mock 打通的 Demo story

1. 開啟 dashboard 看見 8 筆 synthetic transactions。
2. `txn_syn_004` 有 duplicate alert。
3. 開啟 detail，看到兩筆 streaming 同金額與 6 分鐘間隔的 evidence。
4. Privacy Inspector 顯示 merchant 被 generalized、amount bucketed、account field dropped。
5. 選 `正常交易`，不勾 consent → memory status `not-requested`。
6. 再次示範勾 consent → `written` 或 `pending`；如果 provider unavailable，誠實顯示 skipped/failed。

## Smoke tests

```bash
cd frontend
npm run lint
npm run build
npm run dev
```

預期：

- lint 0 errors。
- build 成功產生 `dist/`，沒有 unresolved env/key warning。
- `http://localhost:5173` 可載入；backend 沒開時顯示清楚 offline state，不是 blank screen。

若 repo 有 Vitest/Testing Library：

```bash
npm test -- --run
```

最低 component tests：

- Health badges 三種 mode。
- Alert detail evidence 與 confidence。
- consent 預設 false，未勾不得送 true。
- confirmation success/error/degraded。
- Privacy Inspector 完全顯示 API 的 safe payload。
- keyboard focus 回到觸發按鈕；delete confirmation 可取消。

## 常見錯誤

| 症狀 | 原因 | 修正 |
|---|---|---|
| Vite 要求較新 Node | Node 低於 20.19/22.12 | 安裝 Node 22 LTS，刪除 node_modules 後 `npm ci` |
| `npm ci` 失敗 | lock file 與 package.json 不一致 | 由 frontend owner 修 lock；不要各自刪 lock |
| CORS blocked | backend 未允許 5173 | 回報 Backend owner；不要用 `mode:no-cors` |
| `VITE_API_BASE_URL` undefined | env file 放錯位置/未重啟 dev server | 放 `frontend/.env.local`，重啟 Vite |
| key 出現在 Network tab | 前端直接 call vendor 或 `VITE_*` 放 secret | 立即移除、rotate key、改走 FastAPI |
| Privacy UI 與 payload 不一致 | 前端自行推算 | 顯示 backend `PrivacyPreview` |
| 409 confirmation | double-click/重送 | disable in-flight action，顯示已確認狀態 |
| mobile table 爆版 | 固定寬度欄位 | 使用 stacked rows/可換行，不縮小到不可讀 |

## 驗收測試

- [ ] 只需滑鼠以外，Tab/Enter/Space/Escape 可完成核心 flow。
- [ ] 320px、768px、1440px 無重疊/截斷。
- [ ] empty/loading/error/degraded/success state 齊全。
- [ ] UI 不稱 fraud confirmed 或 bank connected（除非 live status 證明）。
- [ ] source、provider mode、memory status 可見。
- [ ] consent 預設 false，提交值與 UI 一致。
- [ ] frontend bundle 搜不到任何真實 vendor key。
- [ ] `npm run lint && npm run build` 通過。
- [ ] 完成一次真人 90 秒 demo rehearsal。

## PR 標準

PR title：`feat(frontend): build privacy-first transaction review flow`。

附上：

- 三個 viewport 截圖或短錄影。
- 已測的 keyboard flow。
- mock/live data source 說明。
- `npm run lint`、`npm run build`、tests 結果。
- contract 版本與任何 assumption。
- 不含任何個資、key 或真實財務畫面。

## 可直接貼到 Cursor/Codex 的 Prompt

完整可複製版本：[prompts/frontend.prompt.md](prompts/frontend.prompt.md)。

