# 任務書 4 — FastAPI Integration / Deployment Engineer

## 任務結果

你是 integrator。交付 internal API、configuration、request identity、safe errors/logging、四個 subsystem 的組裝、CI green 與可重現部署。你不重寫其他三人的實作；你建立穩定介面、mocks、fallbacks 和 vertical slice。

## 你的檔案所有權

```text
backend/app/main.py
backend/app/api/**
backend/app/core/**
backend/app/schemas/api.py
backend/tests/integration/**
backend/requirements*.txt 或 pyproject/lock（單一 owner）
deployment files
contracts/**（contract owner）
```

不要直接改 `frontend/**`、AI service internals、data adapter internals；以接口整合。

## 從零建立環境

先看 [START-HERE.md](START-HERE.md)。本套件沒有完整 FastAPI 程式；你需先建立 repo、後端骨架與共用依賴，再讓隊友執行啟動／測試指令。macOS `brew` 指令預設已安裝 Homebrew。

### 必要版本

- Git 2.40+。
- Python 3.11/3.12 建議；FastAPI 官方目前使用 Python 3.10+ 範例。
- Node 22 LTS（只為 integration build 前端；日常 backend 可不跑）。
- GitHub CLI 可選但建議。

### macOS

```bash
xcode-select --install
brew install git python@3.12 node@22 gh
git --version
python3 --version
node --version
```

### Windows 11 PowerShell

```powershell
winget install --id Git.Git -e
winget install --id Python.Python.3.12 -e
winget install --id OpenJS.NodeJS.LTS -e
winget install --id GitHub.cli -e
git --version
python --version
node --version
```

### Ubuntu/Debian

```bash
sudo apt-get update
sudo apt-get install -y git python3 python3-venv python3-pip nodejs npm
git --version
python3 --version
node --version
```

Node 若低於 Vite 官方最低要求，改用 Node 22 的團隊標準安裝方式。

### Clone 與 backend

```bash
git clone https://github.com/<ORG_OR_USER>/trustledger.git
cd trustledger/backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp ../.env.example .env
fastapi dev app/main.py
```

Windows：

```powershell
git clone https://github.com/<ORG_OR_USER>/trustledger.git
Set-Location trustledger\backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item ..\.env.example .env
fastapi dev app/main.py
```

預期：`http://127.0.0.1:8000/docs` 顯示 internal endpoints；`/api/v1/health` 在無 vendor keys 時仍回 `200`，狀態為 synthetic/rules-only/off 或 degraded。

## Configuration ownership

用 `pydantic-settings` 或 repo 既有設定層，啟動時驗證：

- `APP_MODE=synthetic|live`，預設 synthetic。
- `ALLOW_MEMORY_WRITE=false`，預設 false。
- exact `FRONTEND_ORIGIN`，不可 `*` + credentials。
- timeouts 是合理正數。
- live mode 缺必要 key 時不要 crash loop；轉 degraded 並在 health 顯示。
- production 不啟用 debug/stack traces。

Secrets 只在 backend runtime。`/health` 只能回「configured/reachable/mode」，不能回 key prefix、length、account id 或 upstream body。

## Internal API 實作順序

依 [contracts/internal-api.openapi.yaml](contracts/internal-api.openapi.yaml)；contract freeze 後不任意加 field。

### 1. Health

`GET /api/v1/health`

- 永不主動洩漏 secret/raw upstream error。
- 供應商 health call 要短 timeout、cache 30–60 秒；不可每個 page render 打 vendor。
- 整體核心可用但 vendor failure → 200 + `status=degraded`。

### 2. Transactions

`GET /api/v1/transactions`

- user identity 由 server context 決定；MVP 固定 `demo-user-001`，不接受 browser 傳 user id。
- 使用 data adapter，`APP_MODE=synthetic` 永遠可靠。
- limit 1–100、穩定排序。

### 3. Analysis + alerts

`POST /api/v1/analyses`、`GET /api/v1/alerts`

- transaction 必須由 current user adapter 查到；不存在與不屬於使用者一律 safe 404。
- 先 rules，Jev optional；Jev failure 仍回 rules result + provider_mode degraded/rules-only。
- request id 貫穿，log 不記 transaction id/body。

### 4. Privacy preview

`GET /api/v1/privacy/preview/{transaction_id}`

- 直接回 AI owner 的 serializer output。
- 不在 route 或 frontend 重建 safe payload。
- response header 建議 `Cache-Control: no-store`。

### 5. Confirmation + memory

`POST /api/v1/alerts/{alert_id}/confirmations`

- body 僅 `decision`、`consent_to_memory`；拒絕 additional fields。
- 以 alert/user ownership 驗證，不信任前端 transaction/account reference。
- idempotent：同 decision 重送可回現有結果；矛盾 decision → 409。
- 先保存 confirmation，再依 gate 嘗試 memory；memory failure 不回滾 user decision。

### 6. Memory inspect/delete

`GET /api/v1/memories`、`DELETE /api/v1/memories/{memory_id}`

- 只回 sanitized summary。
- delete 驗證 current demo assistant ownership。
- upstream async delete 必須回誠實狀態；若 internal contract 僅 204，只有確認完成後才回 204，否則調整 contract需團隊同意。

## Request identity / isolation

MVP 沒有真實 authentication，因此：

- 所有 endpoints 使用 server-side `DEMO_USER_ID=demo-user-001`。
- UI 顯示 Demo account，不讓觀眾誤認已登入真實銀行。
- 不接受 `X-User-Id`、query `user_id` 或 body owner id。
- raw Nessie customer/account id 只在 backend mapping。

正式版才需 OIDC/session、subject claim、row-level ownership、CSRF policy、rate limit、account linking 與 authorization tests。不要用「未做 auth」假裝已做 user isolation；文件清楚寫 demo limitation。

## Safe logging / errors

允許 log：

```text
timestamp, level, request_id, route template, method, status,
latency_ms, provider name, provider status, model_version,
payload schema version, error class
```

禁止 log：

```text
request/response body, query string, Authorization/X-API-Key,
Nessie key, names, addresses, account/customer/transaction ids,
merchant display, precise amount/time, memory content, stack in production response
```

統一 `ErrorEnvelope`。上游 401 對前端只顯示 vendor configuration unavailable；不要把 upstream error body/URL 轉送。

## CORS / TLS / headers

- dev origins 明列 `http://localhost:5173` 與 `http://127.0.0.1:5173`（若兩者都用）。
- production 只允許確切 frontend origin。
- 不用 `allow_origins=["*"]` 搭 credentials。
- 外部部署必須 HTTPS；TLS 由可信平台 termination，HTTP redirect HTTPS。
- 建議安全 headers：`X-Content-Type-Options: nosniff`、合理 CSP 由 frontend host 設定、`Referrer-Policy: no-referrer`、敏感 responses `Cache-Control: no-store`。
- request body size limit；不要讓大型任意 JSON 進 AI。

## Deployment

選團隊已有帳號/credits 的平台，避免截止前學新雲。平台需求：Python runtime、HTTPS、environment secrets、health check、log access、可 pin start command。

建議 start command：

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

若平台要求動態 `PORT`，在平台設定中使用其官方語法；不要在文件中假設每個平台相同。部署步驟：

1. 先 synthetic/rules-only/off 部署並驗證。
2. 設 exact frontend origin。
3. 一次只加入一個 vendor key，跑 health + one smoke flow。
4. secrets 設在平台 dashboard，不進 build args/image layer。
5. 關 debug、限制 logs、確認 HTTPS。
6. 記錄 last known good commit SHA；live failure 可立即切回 synthetic。

若 10:00 EDT 前無穩定 public deployment，停止雲端 debug，改用 localhost + 螢幕錄影/現場 demo。

## Smoke tests

```bash
cd backend
python -m pytest -q
fastapi dev app/main.py
curl --fail-with-body http://127.0.0.1:8000/api/v1/health
curl --fail-with-body http://127.0.0.1:8000/api/v1/transactions
```

分析：

```bash
curl --fail-with-body \
  -X POST http://127.0.0.1:8000/api/v1/analyses \
  -H 'Content-Type: application/json' \
  -d '{"transaction_id":"txn_syn_004"}'
```

預期：duplicate-related result；provider_mode 至少 rules-only；不含 account token/raw merchant/key。

確認但不寫 memory：

```bash
curl --fail-with-body \
  -X POST http://127.0.0.1:8000/api/v1/alerts/alert_syn_duplicate/confirmations \
  -H 'Content-Type: application/json' \
  -d '{"decision":"normal","consent_to_memory":false}'
```

預期：`memory_status=not-requested`。Alert id 以實際 list response 為準；上方是 fixture convention，不是保證存在的 hard-coded production id。

## Integration tests

- 全 synthetic happy path。
- Jev timeout → rules result。
- Nessie fail → synthetic/degraded（依 app mode policy）。
- Backboard fail → confirmation preserved + memory failed/skipped。
- unknown/other-user transaction → 404，不洩漏是否存在。
- malformed/extra confirmation fields → 422。
- duplicate confirmation、conflicting confirmation → defined behavior。
- CORS allowed/disallowed origins。
- error/log redaction。
- OpenAPI snapshot/diff，防止 contract drift。

## 常見錯誤

| 症狀 | 原因 | 修正 |
|---|---|---|
| app import error | 在錯誤目錄啟動 | `cd backend` 後 `fastapi dev app/main.py` |
| CORS blocked | origin 拼字/port 不同 | exact allowlist；不要 `no-cors` |
| 500 暴露 stack | debug/exception handler | production debug false + ErrorEnvelope |
| 全 app 因 vendor 失敗 500 | client exception 未隔離 | timeout/circuit/fallback boundary |
| confirmation 寫了不該有的 memory | route 自行呼叫 client | 所有寫入經 memory policy gate |
| deploy health 很慢 | 每次同步 call 三個 vendors | cache health、短 timeout、lazy probe |
| SQLite lock | 多 worker/同時寫 | demo 單 worker或 in-memory；正式版另選 DB |
| `/docs` 外網暴露 | production 未關/未保護 | prototype 可評估保留；正式版需 policy，不含 secrets/examples |

## 驗收測試

- [ ] contract endpoints 與 schemas 一致。
- [ ] no-key synthetic mode 完整可用。
- [ ] 每個 vendor 有 timeout/fallback，無 request hang。
- [ ] confirmation 与 memory write 解耦。
- [ ] logs/error responses 無 PII/secrets/raw query。
- [ ] user/account ownership 不由 browser 決定。
- [ ] CORS exact origins；public endpoint HTTPS。
- [ ] `pytest -q`、frontend build、integration smoke 全 green。
- [ ] last known good commit/deploy URL/rollback 方法已記錄。
- [ ] 10:00 EDT deployment cutoff 被遵守。

## PR 標準

PR title：`feat(api): integrate TrustLedger vertical slice`。

PR 描述包含 endpoint table、contract version、test result、env names（無值）、health snapshot（無 sensitive data）、fallback matrix、deploy URL、rollback SHA、已知限制。不得含 `.env`、secret、raw upstream response 或 production debug log。

## 可直接貼到 Cursor/Codex 的 Prompt

完整可複製版本：[prompts/backend-integration.prompt.md](prompts/backend-integration.prompt.md)。

