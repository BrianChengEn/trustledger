# TrustLedger · Technica 2026

可執行的四人 B2C MVP 起始專案。含 React/Vite/TypeScript、FastAPI、8 筆合成交易、3 種規則警示、Privacy Inspector、人工確認、明確同意後的本機 SQLite 記憶與刪除。

**GitHub：** https://github.com/BrianChengEn/trustledger （私人；隊友需先接受邀請）

**先讀 [TEAM-SETUP-60MIN.md](TEAM-SETUP-60MIN.md)。** 文件網頁：下載／clone 後雙擊 `docs/index.html`，可離線閱讀與放大六張圖。Markdown 與 SVG 原始檔都保留。

## macOS 啟動

先安裝 Xcode Command Line Tools、[Homebrew](https://brew.sh/)。若已安裝不要重複。首次安裝可能要等待系統視窗與下載。

```bash
xcode-select --install
```

接著重開 Terminal，確定 `brew --version` 正常，再執行：

```bash
brew install git gh
gh auth login
gh auth setup-git
git clone https://github.com/BrianChengEn/trustledger.git
cd trustledger
bash scripts/bootstrap-mac.sh
bash scripts/check.sh
```

`gh auth login` 請各自使用自己的 GitHub 帳號；不要共用 token。clone 404 通常是邀請未接受或帳號錯誤。

在 repo 根目錄開兩個 Terminal：

```bash
# Terminal A
bash scripts/dev-backend.sh
```

```bash
# Terminal B
bash scripts/dev-frontend.sh
```

打開 http://127.0.0.1:5173 。API docs：http://127.0.0.1:8000/docs 。第三個 Terminal 可跑：

```bash
backend/.venv/bin/python scripts/smoke.py
```

預期：8 筆 synthetic transactions、3 個警示；health 顯示 `synthetic`、`rules-only`、`local-fallback`。點「Possible duplicate」，查看 evidence 與 Privacy Inspector，勾選記憶同意並確認 normal，再到 Confirmed memory 查看／刪除本機紀錄。

## 已實作與擴充點

| 已可操作 | 留給角色 owner 實作 |
|---|---|
| Synthetic adapter、canonical DTO、rules | Nessie live adapter |
| 白名單、分類枚舉、金額時間分桶 | Jev verified client、timeout/retry/schema parser |
| 人工確認、SQLite、idempotency、list/delete | Backboard confirmed memory、隔離、非同步狀態 |
| API、UI、PR workflow、CI、測試 | 正式部署、身分驗證、rate limiting |

API keys 即使填入環境也不會自動啟用 live client。骨架不假稱已完成 sponsor integration；開發期間先保持 synthetic baseline 可展示。`confidence=1.0` 是規則確定匹配，不是詐欺機率。

## 安全與資料

- 只綁定 localhost、單一固定 demo identity，沒有正式登入。不要透過 tunnel 或公網直接暴露此骨架。
- `.env` 只在後端，bootstrap 不覆蓋已存在的檔案。所有 vendor key 預設空白。
- `ALLOW_MEMORY_WRITE=true` 只開啟本機記憶 gate；仍須使用者 normal + explicit consent。
- 本機 SQLite 位於 `backend/data/`，不會進 Git。重開 server 後 confirmation 與 memory 仍在。
- unknown request fields 被拒絕；錯誤不回傳 Pydantic raw input；日誌不記 body／供應商 query。
- API 契約在 `contracts/internal-api.openapi.yaml`。這是團隊契約，不是供應商 schema。
- 正式安全、合規與 real financial data 不在此 starter 範圍，詳見 `docs/06-security-privacy-threat-model.md`。

## 依賴與 CI

本環境無法下載依賴，因此初始清單使用受限版本範圍。首次成功安裝後，Integrator 應提交 `frontend/package-lock.json` 和後端 lock（可用 `backend/.venv/bin/pip freeze > backend/requirements.lock.txt`），其他人再用相同 lock 安裝。CI 有 lock 時用 `npm ci`，沒有時用 `npm install`。

`.github/workflows/ci.yml` 會在 push／PR 執行後端 lint/tests 與前端 typecheck/tests/build。沒有供應商 secrets，也不會呼叫 live APIs。CI 的 install/test 實際結果以 GitHub Actions 頁為準；不要把測試檔的存在當成測試已通過。

## 四人所有權

| 角色 | 主要範圍 | 分支 |
|---|---|---|
| AI | `backend/app/services/ai/`、`backend/tests/unit/ai/` | `feat/ai` |
| Frontend | `frontend/` | `feat/frontend` |
| Data | `backend/app/adapters/`、`backend/app/schemas/transaction.py`、`fixtures/` | `feat/data` |
| Backend | API/core、整合測試、CI、契約、共用依賴 | `feat/api` |

每人讀 `AGENTS.md` 與 `docs/prompts/` 中自己的 Prompt，先拉最新 main 再開 branch。不要四人一起改依賴檔、API contract 或 main。

## AI 使用揭露

此 starter 與文件含 OpenAI Codex 協助生成的程式與內容。團隊需理解、測試與 credit 使用的 AI 工具，並依 Technica 規則揭露。未實測供應商成本、準確率或合規，不做相關宣稱。
