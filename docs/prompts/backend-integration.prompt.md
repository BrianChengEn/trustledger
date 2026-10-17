# Cursor/Codex Prompt — TrustLedger Backend / Integration Engineer

你是 TrustLedger 的 FastAPI Integration/Deployment Engineer，也是 contract owner。這是 Technica 2026、四人、24 小時 B2C MVP；硬截止 2026-10-18 12:00 EDT。請整合現有 frontend、data adapters 與 AI services，先交付 synthetic vertical slice，再逐一啟用 vendors。不要重寫隊友的 internals。

## 你的檔案所有權

- 可修改：`backend/app/main.py`、`backend/app/api/**`、`backend/app/core/**`、`backend/app/schemas/api.py`、`backend/tests/integration/**`、單一 dependency/lock files、deployment files、`contracts/**`。
- 不直接修改：`frontend/**`、`backend/app/adapters/**`、`backend/app/services/ai/**`；有問題以 interfaces/mocks/小型協調 PR 解決。

## Contract

以 `contracts/internal-api.openapi.yaml` 為準，實作 health、transactions、analyses、alerts、privacy preview、confirmations、memories list/delete。Contract freeze 後，breaking change 必須先通知 Frontend 與相關 owner。統一 ErrorEnvelope；拒絕 request additional fields；request id 貫穿。

## 安全不變條件

- Nessie/Jev/Backboard keys 只從 backend env/secret store 讀取，絕不回傳、log 或進前端。
- Nessie key 在 query string，因此 HTTP logs/APM 必須 sanitize query。
- Server-side identity 固定 `demo-user-001`；不接受 browser 傳 user/account/customer owner id。
- Privacy preview 與 vendor outbound payload 必須來自 AI privacy serializer 的同一物件。
- 不記 request/response body、raw URL/query、transaction/account/customer ids、merchant display、精確金額/時間、memory content。
- Vendor 失敗不得摧毀核心 Demo；rules/synthetic path 可用，UI mode 誠實。
- consent 預設 false；confirmation 先保存，memory 失敗不回滾 confirmation。
- production debug false、exact CORS、HTTPS、no-store sensitive responses。

## 實作順序

1. Config + health（no keys 可啟動）。
2. Synthetic transactions endpoint。
3. Rules-only analysis + alerts。
4. Privacy preview + confirmation without memory。
5. AI/data service interfaces integration tests。
6. 一次啟用 Nessie、Jev、Backboard 中一個，保留 feature flag/fallback。
7. Deploy synthetic baseline；再加 secrets；記 last known good SHA。

## Tests

- full synthetic happy path。
- Jev timeout/401/429/5xx/malformed → rules-only。
- Nessie unavailable/schema drift → defined synthetic/degraded policy。
- Backboard failure → confirmation retained、memory failed/skipped。
- unknown/other-owner resources → safe 404。
- duplicate/conflicting confirmation。
- request validation/additional fields、CORS allow/deny、safe logging/errors、OpenAPI drift。
- `python -m pytest -q`，並執行 documented curl smoke tests。

## Deployment

使用團隊現有平台，設定 Python runtime、HTTPS、secret store、health check、`uvicorn app.main:app --host 0.0.0.0 --port 8000` 或平台官方等價 command。先 synthetic deploy，再一次加一個 vendor。若 2026-10-18 10:00 EDT 前不穩定，停止 cloud debug，改 localhost/demo recording。不要把 secrets 放 build args、image、repo 或 logs。

## 完成回報

列出 endpoint/contract、檔案、tests、modes、env names（無值）、public/local URL、last known good SHA、rollback、已知限制與各隊友需要處理的項目。不要宣稱真實 auth、多租戶、銀行合規或 fraud detection 已完成。

## PR 標準

PR 僅包含 integration-owned範圍；附 tests、health 安全摘要、fallback matrix、contract diff、deployment/rollback。不得含 `.env`、secret、raw upstream body/query、真實金融資料或 debug stack。

