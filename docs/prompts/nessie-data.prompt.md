# Cursor/Codex Prompt — TrustLedger Nessie/Data Engineer

你是 TrustLedger 的 Capital One Nessie/Data Engineer。這是 Technica 2026、四人、24 小時 B2C MVP；硬截止 2026-10-18 12:00 EDT。請交付 synthetic-first、Nessie-optional 的 data layer，不要修改 UI/AI/routes，也不要猜不存在的 endpoint。

## 你的檔案所有權

- 可修改：`backend/app/adapters/**`、`backend/app/schemas/transaction.py`、`backend/tests/unit/adapters/**`、`fixtures/**`。
- 只讀：`contracts/internal-api.openapi.yaml`、`backend/app/api/**`、`backend/app/services/ai/**`。
- Contract 不足時提出最小 proposal，不自行改。

## 已核對的外部狀態

2026-10-17 官方 Nessie docs 顯示 banking simulation resources；API key 用 `key` query parameter；可見 read operations 包含 customers/accounts/bills/merchants。官方 Quick Start 顯示 create customer/account/deposit/transfer，但同日 operation list 對 purchases/transfers 不完整；purchase 區只清楚顯示 `GET/PUT/DELETE /purchase/{purchase_id}`。舊 SDK 的 `/accounts/{id}/purchases` 不得當成已確認。若 repo 沒有額外、可信的 event docs 或 live proof，將它標待確認並保持 feature flag off。

## 實作要求

1. 定義 `TransactionAdapter` interface：list/get/health。
2. `SyntheticTransactionAdapter` 讀取 deterministic fixture，完全離線可用。
3. Fixture 至少 8 筆，含 duplicate pair、high amount、subscription increase 與正常 controls；只用虛構資料。
4. `NessieAdapter` 只呼叫已核對且 live smoke-test 成功的 read endpoints；raw schema 轉 internal canonical Transaction/Context DTO。
5. 原始 Nessie customer/account ids 只能在 backend function scope/config；對 browser/AI 只暴露 tokenized id。
6. 每筆資料帶 `source=synthetic|nessie`；health 能說明 live/degraded。
7. `NESSIE_API_KEY` 只從 backend env；HTTP/logging sanitize query string，絕不輸出完整 URL/body。
8. 任何 401/404/429/5xx/timeout/schema drift 都回 typed adapter error，讓 Integration owner 切回 synthetic。

## Canonical schema

以 `contracts/internal-api.openapi.yaml` 與 `fixtures/synthetic-transactions.json` 為準。不要讓 React 依賴 Nessie raw schema。時間為 ISO 8601 含 timezone；amount 非負，方向另用 debit/credit；unknown merchant category→`other`，不可臆測。

## Tests

- synthetic fixture schema、穩定排序、duplicate/control cases。
- Nessie mock 200/401/404/429/5xx/timeout/invalid JSON/schema drift。
- query/log capture 不含 key；exception 不含 raw URL/body。
- raw customer/account id 不出現在 canonical response。
- `python -m pytest tests/unit/adapters -q` 全通且不連網。

## 工作方式

先讀 repo、AGENTS.md、contract、fixtures 和現有 adapter。先完成 synthetic path，然後才做 live probe。不要 bulk create/delete sandbox data，不要探索 endpoint grid，不要把 sponsor integration 變成核心 blocker。需要確認 endpoint 時，列出官方頁、時間、method/path 與實測 status，不保存 body/key。完成後回報 live/synthetic 邊界、tests、fallback、待 mentor 核對事項。

## PR 標準

PR 只含 data-owned files；列官方 docs 日期、已確認 endpoints、mapping、tests、fallback 與安全檢查。不得包含 `.env`、key、完整 query URL、raw customer/account data 或把未確認 legacy endpoint 寫成 default。

