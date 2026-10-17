# 任務書 3 — Capital One Nessie / Data Engineer

目前負責人是 Kenny（`mrkennylee`）。Nessie client 仍是 stub。狀態見 [../ARCHITECTURE.md](../ARCHITECTURE.md) 與 [../TEAM_ROLES.md](../TEAM_ROLES.md)。

## 任務結果

交付兩個遵守同一 canonical schema 的 adapters：`SyntheticTransactionAdapter` 永遠可用；`NessieAdapter` 只使用當日官方文件與 sandbox 實測已確認的 read operations。任何 schema/endpoint 不一致都 fail safe 並切回 synthetic，不拖垮整個 Demo。

## 你的檔案所有權

```text
backend/app/adapters/
├── base.py
├── synthetic.py
└── nessie.py
backend/app/schemas/transaction.py
backend/tests/unit/adapters/
fixtures/**
```

不要直接改 API routes、AI services 或 frontend。`contracts/**` 變更需 Integration Engineer 同意。

## 從零建立環境

先看 [START-HERE.md](START-HERE.md)。可立即安裝系統工具；Clone、安裝依賴及 adapter tests 要等真正的 repo、共用依賴與程式建立後執行。macOS `brew` 指令預設已安裝 Homebrew。

### 必要版本

- Git 2.40+。
- Python 3.11/3.12 建議。
- Nessie sandbox account/API key（可稍後取得，不阻塞 synthetic path）。

### macOS

```bash
xcode-select --install
brew install git python@3.12 gh
git --version
python3 --version
```

### Windows 11 PowerShell

```powershell
winget install --id Git.Git -e
winget install --id Python.Python.3.12 -e
winget install --id GitHub.cli -e
git --version
python --version
```

### Ubuntu/Debian

```bash
sudo apt-get update
sudo apt-get install -y git python3 python3-venv python3-pip
git --version
python3 --version
```

### Clone 與安裝

```bash
git clone https://github.com/<ORG_OR_USER>/trustledger.git
cd trustledger/backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Windows：

```powershell
git clone https://github.com/<ORG_OR_USER>/trustledger.git
Set-Location trustledger\backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## 官方 contract 核對狀態（2026-10-17）

官方 [Nessie docs](https://prod.nessieisreal.com/docs) 已確認：

- Banking simulation resources：customers、accounts、deposits、withdrawals、transfers、purchases、bills、loans、merchants、ATMs、branches、enterprise。
- API key 經 GitHub login 取得，以 `key` query parameter 傳入。
- 當日互動文件可見：`GET /customers`、`GET /customers/{id}/accounts`、`GET /accounts/{id}/bills`、`GET /merchants` 等。
- Quick Start 顯示 create customer/account/deposit/transfer。

### 必須保守處理的不一致

當日 OpenAPI operation list 的 purchase 區只顯示：

```text
GET    /purchase/{purchase_id}
PUT    /purchase/{purchase_id}
DELETE /purchase/{purchase_id}
```

舊 Nessie SDK/文件常見 `/accounts/{id}/purchases`，但這次不得把 legacy endpoint 當成已確認。Quick Start 顯示 create transfer，但同頁 operation list 未完整顯示 create/list transfer。你的做法：

1. 不猜 endpoint。
2. 在 sponsor office hours/官方互動文件 Try it 核對後才新增。
3. 未確認前，交易 alert 使用 synthetic fixture。
4. Capital One live evidence 優先用已確認的 customers/accounts/bills/merchants read path；UI 誠實標記哪些資料是 Nessie、哪些是 synthetic。

## 安全 key 流程

- `NESSIE_API_KEY` 只放 `backend/.env` 或 deploy secret store。
- 任何 log/error 都不得輸出完整 request URL，因 key 在 query string。
- http client logging 必須關閉或 sanitize query；APM/analytics 不收 query string。
- GitHub Issue/PR 不貼互動文件產生的完整 URL。
- 若 URL 曾曝光，立即重設 key，並檢查 terminal recording、Actions logs、screenshot。

## Canonical transaction schema

以 internal OpenAPI 與 `fixtures/synthetic-transactions.json` 為準：

```text
id, occurred_at, amount, currency, direction,
merchant_display, merchant_category, source,
account_token, is_subscription
```

規則：

- `amount` 是非負 decimal/number；方向用 `direction`，不要混用負數。
- `occurred_at` 是 ISO 8601、有 timezone。
- 原始 account/customer id 經後端 deterministic tokenization 後才進 canonical output；browser 不需要真實 sandbox id。
- `source` 只能 `synthetic` 或 `nessie`。
- merchant category 建立一個小型、可審查 mapping；未知值→`other`，不要猜高風險類別。
- raw response 僅存在 function scope，不落盤、不 log。

## Adapter interface

```text
list_transactions(user_context, limit=25) -> list[Transaction]
get_transaction(user_context, transaction_id) -> Transaction | None
health() -> AdapterHealth
```

`user_context` 由 Backend 提供，不接受前端任意傳 account/customer id。MVP 固定 synthetic demo identity；Nessie sandbox ids 只在 backend config/mapping。

## Synthetic dataset 要求

使用本套件 [fixtures/synthetic-transactions.json](fixtures/synthetic-transactions.json) 作起點：

- 至少 8 筆。
- 明確的同類別同金額、6 分鐘差 duplicate pair。
- 一筆 USD 849 electronics high amount。
- 一組 USD 24.99 → 34.99 subscription change。
- 正常 groceries、dining、transportation control cases。
- 名稱都是虛構品牌，不使用真實個人、帳號或銀行資料。
- ordering 穩定，tests 可重現。

## Nessie integration 策略

### Phase 1 — health/read proof

- 使用 configured `NESSIE_BASE_URL`，先核對官方文件當日值。
- GET `/customers`，確認 auth 與 response shape。
- 選 team sandbox 擁有的 customer，GET `/customers/{id}/accounts`。
- 視 response 再讀 bills/merchants；只讀，不在 final stabilization 期間寫資料。
- adapter 只暴露 canonical DTO，不暴露 raw Nessie schema。

### Phase 2 — 可證明的 UI value

最佳方案：使用 Nessie account metadata/bills/merchants 作 Dashboard 的 live context，再以 synthetic transactions 做 alert story。UI 顯示：

```text
Account context: Nessie sandbox
Transaction scenario: synthetic demo data
```

如果 sponsor mentor 確認並現場實測 list purchases/transactions endpoint，再把該 mapping 放 feature flag；不要刪除 synthetic fallback。

## Smoke tests

### Synthetic（必須先通）

```bash
cd backend
python -m pytest tests/unit/adapters/test_synthetic.py -q
```

預期：8+ 筆、schema validation 通過、duplicate pair/controls 都存在、穩定排序。

### Nessie auth/read probe

不要把 key 放在 command URL。使用已啟用的 venv 與 `httpx`，從 environment 讀取：

```bash
python -c 'import os,httpx; base=os.environ["NESSIE_BASE_URL"].rstrip("/"); key=os.environ["NESSIE_API_KEY"]; r=httpx.get(base+"/customers",params={"key":key},timeout=5); print(r.status_code, r.headers.get("content-type")); r.raise_for_status()'
```

預期：`200` 與 JSON content type。命令故意不列印 body/customer data。PowerShell 同樣可執行；先設定 process-scoped environment variables。

### Contract tests

```bash
python -m pytest tests/unit/adapters -q
```

用 recorded synthetic-shaped mock responses，不錄製含 key 的 URL。測 200、401/403、404、429、5xx、timeout、invalid JSON、schema drift。

## 常見錯誤

| 症狀 | 原因 | 修正 |
|---|---|---|
| 401/403 | key 缺失、錯誤或 sandbox permission | 重新登入官方頁、確認 process env；不貼 URL |
| 404 | legacy endpoint 或 singular/plural 不一致 | 回官方當日 docs；標待確認，不猜 |
| 200 但 mapping crash | schema drift/null field | strict-but-tolerant parser；unknown→safe default，記 schema error class |
| key 出現在 log | logging raw URL/query | sanitize query，關閉 http client debug |
| UI 顯示 Nessie 但其實 fixture | source label 被覆蓋 | source 每筆保存，health 與 UI 一致 |
| 沒有 purchase list endpoint | 官方 contract 不一致 | synthetic core + 已確認 Nessie context；找 mentor核對 |
| 429 | rate limit | cache demo read、backoff；不要 loop polling |
| 測試不穩 | fixture 依現在時間 | 固定 2026-10-17 timestamps，不用 `now()` |

## 驗收測試

- [ ] synthetic adapter 在完全離線時可運作。
- [ ] 所有 fixture 是合成資料且 schema valid。
- [ ] Nessie key 不在 raw URL logs、exceptions、fixtures、tests、screenshots。
- [ ] 未確認 endpoint 不存在程式 default path。
- [ ] 每筆資料都有正確 `source`。
- [ ] raw Nessie ids 不進 browser，也不進 Jev/Backboard。
- [ ] 200/401/404/429/5xx/timeout/schema drift 有 mock tests。
- [ ] live probe 成功時保存只有 status、timestamp、endpoint name 的安全證據；不保存 body/key。
- [ ] adapter health 可被 `/api/v1/health` 使用。

## PR 標準

PR title：`feat(data): add synthetic-first Nessie adapter`。

PR 描述：

- 使用的官方 docs 日期與已確認 endpoints。
- 哪些資料 live、哪些 synthetic。
- mapping table 與未知欄位策略。
- tests command/result。
- failure/fallback behavior。
- 不附 raw response、customer id、account id、key 或完整 query URL。

## 可直接貼到 Cursor/Codex 的 Prompt

完整可複製版本：[prompts/nessie-data.prompt.md](prompts/nessie-data.prompt.md)。

