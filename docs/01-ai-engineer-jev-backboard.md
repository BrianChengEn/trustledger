# 任務書 1 — AI Engineer（Jev + Backboard + Privacy）

## 任務結果

交付一個可被 FastAPI 呼叫、可單元測試、fail-closed 的 AI service layer：先將交易轉成 allowlisted features，再跑 deterministic rules；若 Jev 可用，加入 bounded decision；只有使用者明確確認與同意後，才把 sanitized fact 寫入 Backboard。

## 你的檔案所有權

```text
backend/app/services/ai/
├── privacy.py
├── rules.py
├── jev_client.py
├── backboard_client.py
├── memory_policy.py
└── models.py
backend/tests/unit/ai/
```

不要直接改 `frontend/**`、data adapters 或 API route contract。需要 contract 變更時先開 issue/PR，讓 Integration Engineer 與 Frontend owner 同意。

## 從零建立環境

先看 [START-HERE.md](START-HERE.md)。可立即安裝下列系統工具；Clone、安裝共用依賴、啟動及測試指令，都需要先由團隊建立真正的 repo 與對應檔案。macOS `brew` 指令預設已安裝 Homebrew。

### 必要版本

- Git 2.40+。
- Python 3.11 或 3.12 建議；FastAPI 官方範例支援 Python 3.10+。
- 可選：Cursor、VS Code 或 Codex。
- Jev 與 Backboard 帳號/key；沒有 key 也必須能完成 mock/rules-only 工作。

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

安裝後重新開啟 PowerShell。若 `python` 指向 Microsoft Store alias，使用 `py -3.12`。

### Ubuntu/Debian

```bash
sudo apt-get update
sudo apt-get install -y git python3 python3-venv python3-pip
git --version
python3 --version
```

### Clone 與 virtual environment

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

若 repository 尚無 `requirements.txt`，與 Backend owner 同意後用下列最小集合建立 lock/requirements，不要各自提交不同依賴檔：

```bash
python -m pip install "fastapi[standard]" httpx pydantic-settings pytest pytest-asyncio respx
```

## 安全 API key 流程

1. 從 `.env.example` 複製到 `backend/.env`。
2. `JEV_API_KEY` 與 `BACKBOARD_API_KEY` 只填在本機 `backend/.env`。
3. 確認 `git check-ignore backend/.env` 有輸出；若沒有，先修 `.gitignore`，不要 commit。
4. 不把 key 放在 curl command history。手動 smoke test 前先在目前 shell 暫時匯入，完成後關閉 shell。
5. deploy 時用平台 secret store；不要把 key 設成 `VITE_*`。

PowerShell 可用：

```powershell
$env:JEV_API_KEY = "<paste-locally>"
$env:BACKBOARD_API_KEY = "<paste-locally>"
```

macOS/Linux 可用：

```bash
export JEV_API_KEY='<paste-locally>'
export BACKBOARD_API_KEY='<paste-locally>'
```

上述 `<paste-locally>` 是佔位符，絕對不要提交。

## 交付順序

### A. Privacy guard（先做）

輸入 canonical transaction + safe aggregates，輸出：

- `safe_payload`：只能含 allowlisted keys。
- `inspection`：每個原始欄位的 `allowed/dropped/tokenized/generalized/bucketed` action 與 reason。
- `schema_version="safe-ai-payload-v1"`。

Allowlist：

```text
merchant_category
amount_bucket
currency
local_day_part
same_category_same_amount_24h_count
is_subscription
subscription_delta_bucket
prior_user_confirmation
```

Forbidden field names 與值樣式：

```text
name, first_name, last_name, email, phone, address, account_number,
routing_number, card_number, ssn, api_key, token, secret,
merchant_display, raw_description, transaction_id, account_token
```

測試要遞迴掃描 nested dictionaries/lists，並測類似 16 位數、email、`sk-`/`key=` 等值樣式。不依賴 redaction 作第一層；第一層是 allowlist construction。

### B. Deterministic rules

- pure functions，不讀 environment、不 call network。
- 輸出固定 `Analysis` DTO。
- evidence 是可對使用者展示的短句，不含敏感值。
- rules thresholds 集中設定，可測邊界。

最低測試：

- 兩筆相同 category/amount 在 24 小時內 → duplicate。
- 相同交易超過 24 小時 → 不視為 duplicate。
- 849 USD electronics 相較 demo baseline → high amount。
- 24.99 → 34.99 subscription → change >20%。
- 空歷史資料不 crash。

### C. Jev client

官方已核對 contract：

- `POST https://jev-ai.org/api/v1/systemone/`（保留 trailing slash）。
- `Authorization: Bearer ...`。
- body：`model`、`state`、`questions`。
- `choice.criteria` 是 object；`score.criteria` 是 array；`noul` 沒有 criteria。
- 回應含 `answers`、`model_version`、`usage`、`latency_ms`。
- MVP 鎖 `jev-1.13`。

送出的 `state` 只能是 `safe_payload`。建議一次問：

```json
{
  "model": "jev-1.13",
  "state": {
    "merchant_category": "streaming",
    "amount_bucket": "10-25",
    "currency": "USD",
    "local_day_part": "afternoon",
    "same_category_same_amount_24h_count": 2,
    "is_subscription": true,
    "subscription_delta_bucket": "none",
    "prior_user_confirmation": "unknown"
  },
  "questions": {
    "alert_type": {
      "type": "choice",
      "instructions": "Classify the most relevant user-facing transaction alert.",
      "criteria": {
        "duplicate": "Multiple same-category same-amount charges occur in a short window.",
        "amount_anomaly": "The amount pattern is unusually large for the supplied safe features.",
        "subscription_change": "A recurring charge increased materially.",
        "none": "The safe features do not support another alert type."
      }
    },
    "needs_human": {
      "type": "noul",
      "instructions": "Should the user review this transaction rather than the system taking an automatic action?"
    },
    "severity": {
      "type": "score",
      "instructions": "Rate the urgency for user review.",
      "criteria": ["Low", "Medium", "High"]
    }
  }
}
```

這是依官方 schema 製作的 test fixture，不是金融判定真理。程式必須：

- 5 秒 timeout，最多一次安全 retry；POST retry 必須使用新或穩定的 `Idempotency-Key` policy。
- 驗證 content type/status/schema；`score` 以 float 解析。
- 保存 `model_version`，不記錄完整 request/response。
- `noul` 使用兩側 threshold；中間區間永遠 `needs_human=true`。
- 401/402/429/5xx/timeout/malformed JSON → `rules-only` degraded，不把 upstream body 傳前端。

### D. Backboard memory

官方已核對：

- `POST https://app.backboard.io/api/threads/messages`。
- header `X-API-Key`。
- `memory="Auto"` 寫入+讀取、`Readonly` 只讀、`off` 停用。
- memory 位於 assistant scope，跨同 assistant threads。
- memory 可 list/add/search/get/update/delete。

MVP 建議不要把完整交易內容交給 Auto extraction。確認後由 `memory_policy.py` 先建立 sanitized sentence，再使用官方 Add Memory endpoint；之後分析可用 semantic search 或 `Readonly`。禁止將多個 demo users 放進同一 assistant。

Memory write gate：

```text
decision == normal
AND consent_to_memory == true
AND ALLOW_MEMORY_WRITE == true
AND privacy validation passes
AND assistant belongs to demo-user-001
```

如果 operation 為 async，回 `memory_status=pending`，不要假稱已保存。

## Internal API contract

你實作 service methods，Backend owner負責 HTTP route：

```text
analyze(transaction, history) -> Analysis
privacy_preview(transaction, history, destination) -> PrivacyPreview
write_confirmation_memory(alert, confirmation) -> MemoryWriteResult
list_memories() -> list[MemorySummary]
delete_memory(memory_id) -> None
```

精確 HTTP schema 參考 [contracts/internal-api.openapi.yaml](contracts/internal-api.openapi.yaml)。

## Smoke tests

### 離線、必須先通

```bash
cd backend
python -m pytest tests/unit/ai -q
```

預期：所有測試通過；沒有 network；沒有真實 key。至少看到 privacy forbidden-field tests、rules cases、Jev response parser、Backboard write gate。

### Jev authentication/readiness（不跑 decision）

```bash
curl --fail-with-body --silent --show-error \
  https://jev-ai.org/api/v1/models/ \
  -H "Authorization: Bearer $JEV_API_KEY"
```

預期：HTTP 200、model list 含 decision model。官方文件說 GET models 不執行模型且不收費。不要把輸出貼進公開 issue。

### Backboard readiness

```bash
curl --fail-with-body --silent --show-error \
  https://app.backboard.io/api/assistants \
  -H "X-API-Key: $BACKBOARD_API_KEY"
```

預期：HTTP 200 與 assistant list。若無 assistant，由一位 owner 建立一個 `TrustLedger Demo User` assistant；避免四人各建一個造成 ID 混亂。

## 常見錯誤

| 症狀 | 原因 | 修正 |
|---|---|---|
| Jev 308 | 少了 trailing slash | 使用 `/systemone/` |
| Jev 400 | `choice`/`score` criteria shape 交換 | choice=object、score=array |
| Jev parser 拒絕 1.89 | 把 score 寫成 integer | 使用 float |
| Jev 401 | key 缺失、masked key、revoke 或 header 錯 | 檢查 Bearer 與 key rotation |
| Backboard 401 | `X-API-Key` 缺失/錯誤 | key 只放後端、重新載入環境 |
| 記憶跨 thread 出現 | 這是 assistant-scoped 的官方行為 | 不要跨使用者共用 assistant |
| Memory 顯示成功但稍後才出現 | operation 非同步 | 回 pending 並 polling/status check |
| Privacy Inspector 與實際 payload 不同 | 前端手寫示意 | 只顯示 backend serializer 回傳值 |
| Tests accidentally call network | client 未 dependency-injected | mock transport；CI 禁止 vendor secrets |

## 驗收測試

- [ ] `privacy.py` 用 allowlist 建構，不是把 raw dict「刪幾個欄位」。
- [ ] recursive test 證明 forbidden names/values 不出現在 outbound payload。
- [ ] rules-only path 能完成整個 Demo。
- [ ] Jev success、timeout、401、429、5xx、malformed schema 都有 tests。
- [ ] confidence/score parsing 符合官方 schema。
- [ ] confirmation without consent 不寫任何 memory。
- [ ] `ALLOW_MEMORY_WRITE=false` 時即使 consent=true 也安全跳過。
- [ ] memory text 沒有 transaction id、account token、精確金額/日期、merchant display。
- [ ] delete memory path 已 mock 驗證；live cleanup checklist 有 owner。
- [ ] log assertions 證明 keys/raw payload 不出現。

## PR 標準

PR title：`feat(ai): add privacy-first analysis pipeline`。描述需包含：

- 做了什麼與未做什麼。
- outbound allowlist 與 sample sanitized payload。
- tests command + result。
- live calls 是否實際執行、使用哪個 model version；不要附 key/request body。
- 任何 contract change。
- fallback behavior。
- security checklist。

## 可直接貼到 Cursor/Codex 的 Prompt

完整可複製版本：[prompts/ai-engineer.prompt.md](prompts/ai-engineer.prompt.md)。

