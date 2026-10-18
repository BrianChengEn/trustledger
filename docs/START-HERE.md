# 現在開始：文件與可執行專案的差別

這個 ZIP 是開發文件、API 契約、合成資料與協作範本。它沒有完整的 `backend/app`、`frontend/package.json`、`requirements.txt` 或測試實作。可以立即開始安裝工具與分工；應用程式啟動和 smoke tests 要等相應程式建立後執行。

## 前 15 分鐘：四人一起做

1. 解壓縮完整 ZIP，雙擊 `index.html`。網頁閱讀與流程圖不需要網路或本機伺服器。要分享單一檔也可傳 `index.html`，內容與圖表均已內嵌；要保留 Markdown、SVG 和範本下載，請傳完整 ZIP。
2. 確定四個角色：AI、Frontend、Nessie/Data、Backend/Integration。
3. Integrator 依 [GitHub 協作手冊](05-github-collaboration.md) 建立真正的 GitHub repo，邀請其他三人；將 `<ORG_OR_USER>` 換成實際帳號或 organization。
4. 全隊確認 [內部 OpenAPI 契約](contracts/internal-api.openapi.yaml)。各自讀任務書與對應 Prompt。
5. 先維持 synthetic 模式與空白供應商 key；先做可運作的 mock/rules 流程。

## 現在就可以安裝

| 角色 | 現在安裝／準備 | 程式建立後才執行 |
|---|---|---|
| AI | Git、Python 3.11/3.12、編輯器、Jev/Backboard 帳號 | `pip install -r requirements.txt`、AI unit tests |
| Frontend | Git、相容的 Node.js 與 npm、編輯器 | `npm ci`、`npm run dev`、UI tests |
| Nessie/Data | Git、Python、Nessie sandbox 帳號 | adapter tests、資料 seed／health probe |
| Backend/Integration | Git、Python、GitHub repo 與 collaborators | FastAPI 啟動、HTTP smoke tests、部署 |

每個作業系統的指令在各角色任務書。macOS 的 `brew install` 預設已裝好 Homebrew；若尚未安裝，可從 [Homebrew 官方網站](https://brew.sh/) 安裝，或使用 Git/Python/Node 的官方安裝程式。裝完後重開終端機，先檢查版本。

## 專案骨架的建立順序

1. **Integrator：** 建立 `backend/`、依賴清單、設定與 logging、`/api/v1/health`、mock routes；集中管理後端依賴與 lock files。
2. **Frontend：** 只由一位 owner 在 repo 根目錄建立 Vite scaffold，提交 `package.json` 與 lock file。已有 scaffold 時不要再執行 create 指令。`npm ci` 必須等 lock file 存在後使用。
3. **Data：** 建立 synthetic adapter，使用套件中的 fixture，依內部契約輸出交易。
4. **AI：** 建立 privacy allowlist、rules baseline 與 mock clients，接上 adapter 與 API。
5. **全隊：** 合併第一個 synthetic vertical slice，先讓「交易 → 警示 → Privacy Inspector → 人工確認」走通，再接 live provider。

## 給 Cursor / Codex 的第一個輸入

把 README、總體架構、自己角色的任務書、對應 `prompts/*.prompt.md`、內部 OpenAPI，以及 fixture 一起提供給編輯器。請它先檢查 repo 現況，再依檔案所有權實作。

不要只貼安裝指令就假設 repo 已存在。Prompt 中的 test paths、service methods 和 acceptance tests 是要實作的交付要求；套件並未附上那些程式。

## 常見的「現在還不能跑」

- `repository not found`：repo 尚未建立、邀請未接受，或仍使用佔位 URL。
- `requirements.txt not found`：Integrator 還沒建立後端依賴檔；先安裝 Python 並建立 `.venv`，等共用依賴清單合併。
- `npm ci` 找不到 lock file：Frontend owner 要先 scaffold 並跑一次 `npm install`、提交 lock file。
- `No module named app`：FastAPI 程式還沒實作，或終端機不在 `backend/`。
- `tests not found`／health endpoint 404：任務書要求的程式與測試尚未建立。
- 沒有 API key：先完成 synthetic + rules + mock tests；UI 清楚顯示模式。

## Key 的第一步

`cp .env.example backend/.env` 要等 `backend/` 已存在。先啟用 `.gitignore`，驗證 `backend/.env` 被忽略，再在本機填 key。四人不在聊天、PR、Prompt、前端或 Git 交換真實 key。
