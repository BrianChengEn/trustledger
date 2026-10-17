# Benson 的 Backend 開發環境

工作分支：`backend`（GitHub：`benson5112`）。從專案根目錄執行以下指令。

## 安裝與啟動

使用 Python 3.12、Node 22，以及已提交的 dependency locks：

```bash
bash scripts/bootstrap-mac.sh
bash scripts/check.sh
```

在兩個 Terminal 分別啟動：

```bash
bash scripts/dev-backend.sh
```

```bash
bash scripts/dev-frontend.sh
```

前端：http://127.0.0.1:5173；API 文件：http://127.0.0.1:8000/docs。
後端啟動後可執行 `backend/.venv/bin/python scripts/smoke.py`。
預設使用 synthetic 資料、rules-only 分析與 local-fallback 記憶。
`backend/.env`、`.venv`、前端依賴與 SQLite 資料只留在本機。

## 提交與推送

```bash
git switch backend
bash scripts/check.sh
git status --short
# 只 stage 本次修改的檔案，再 commit。
git push origin backend
```

Backend 負責 API/core、整合測試、CI、共用依賴與契約；詳細分工見
`AGENTS.md` 與 `docs/04-fastapi-integration-deployment.md`。
契約變更先與隊友確認；合併 main 走團隊 review 流程。

本環境設定與 shell 換行修正由 OpenAI Codex 協助完成。
