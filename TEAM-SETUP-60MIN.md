# 四台 Mac · 60 分鐘協作設定

目標：每人都能 clone、安裝、跑前後端與測試，建立自己的分支，提交一個小 PR。這是環境與協作驗收；live providers 於後續分工接入。

如果尚未安裝 Homebrew 或 Xcode Command Line Tools，下載時間可能超過一小時，先平行安裝。有人卡住時先 pair 在能啟動的 Mac 上確認契約，不要全隊等同一台。

## 00–10 分鐘：帳號與共同基礎

- Repo owner：BrianChengEn；repo 為 `https://github.com/BrianChengEn/trustledger`。
- 隊友帳號：benson5112、ianthechou89、mrkennylee；三人各自接受私人 repo 邀請。
- 決定角色，將下列姓名空格換成實際 owner。不要假設 GitHub username 已代表角色。

| 角色 | 同一時間只負責自己的主要範圍 | 自己填姓名 |
|---|---|---|
| AI | privacy / rules / Jev / Backboard | ____ |
| Frontend | React / Vite UI | ____ |
| Data | fixture / Nessie adapter | ____ |
| Backend/Integrator | API / core / dependencies / CI | ____ |

每人檢查：

```bash
git --version
brew --version
```

Homebrew 尚未安裝時，先從 https://brew.sh/ 安裝並依提示設定 shell PATH。Git tools 缺少時跑 `xcode-select --install`，完成後重開 Terminal。

## 10–25 分鐘：clone 與安裝

```bash
brew install git gh
gh auth login
gh auth setup-git
git clone https://github.com/BrianChengEn/trustledger.git
cd trustledger
bash scripts/bootstrap-mac.sh
```

腳本會安裝 Node 22、Python 3.12，建立 `backend/.venv`、安裝後端及前端依賴，從安全範本建立 `.env`。它不建立／傳送 vendor keys，也不覆蓋既有 `.env`。

首次還沒有 dependency lock 時，由 Integrator 先成功安裝、提交 lock files，再讓另外三人同步。若想四人並行安裝，之後仍要以 Integrator 合併的 lock 重新同步一次。

## 25–40 分鐘：每人啟動與檢查

在 repo 根目錄各開兩個 Terminal：

```bash
bash scripts/dev-backend.sh
```

```bash
bash scripts/dev-frontend.sh
```

前端：http://127.0.0.1:5173 。後端：http://127.0.0.1:8000/docs 。第三個 Terminal：

```bash
bash scripts/check.sh
backend/.venv/bin/python scripts/smoke.py
git check-ignore backend/.env frontend/.env.local
```

預期畫面包含 8 筆交易、3 個警示。點 duplicate → inspect → normal + opt-in → memory list → delete。所有模式都要誠實顯示 synthetic/rules-only/local-fallback。

## 40–55 分鐘：第一個 PR

各自只使用自己的角色分支；以下以 AI 為例，其他人改用 `feat/frontend`、`feat/data`、`feat/api`：

```bash
git switch main
git pull --ff-only
git switch -c feat/ai
```

每人先在自己的 owner 區域加入一個有意義的小改善或測試，再提交：

```bash
git status
git add <你實際修改的檔案>
git commit -m "chore(ai): verify local development setup"
git push -u origin feat/ai
gh pr create --base main --fill
```

不要照字面執行 `<你實際修改的檔案>`；先確認沒把 `.env`、SQLite、`.venv` 或 node_modules 加入 staging。若 branch 已存在，`git switch feat/ai`，不要強制覆寫。

## 55–60 分鐘：共同驗收

- [ ] 四人看得到 repo，且使用各自 GitHub 帳號。
- [ ] 每台 Mac 的前後端可啟動，ports 8000/5173 未衝突。
- [ ] `check.sh` 通過；如果尚未通過，記錄實際錯誤與 owner。
- [ ] health 回 `synthetic / rules-only / local-fallback`。
- [ ] 第一個小 PR 已開，另一人 review，GitHub CI 結果可見。
- [ ] 各角色的寫入範圍明確；共用依賴／契約只有 Integrator 管理。
- [ ] `docs/index.html` 可離線閱讀；六個流程圖都可放大。

## 問題速查

| 問題 | 處理 |
|---|---|
| `brew: command not found` | 依 Homebrew 安裝後提示設定 shellenv，重開 Terminal |
| clone 404 | 接受邀請；`gh auth status` 檢查自己帳號；不要貼 token |
| `npm: command not found` | 重跑 bootstrap 或將 `$(brew --prefix node@22)/bin` 加進 PATH |
| Python 指到 3.10 | 使用 `python3.12`；bootstrap 不會用系統舊版建立 venv |
| port 被占用 | 關閉自己舊的 dev server；不要直接亂殺其他程序 |
| requirements／package 缺少 | 確認 clone 的是 starter repo 根目錄，而不是只有舊文件 ZIP |
| download／registry 失敗 | 檢查 Wi-Fi／proxy；不要關閉 TLS 檢查 |
| memory 重開還存在 | SQLite 正常持久化；使用 UI 刪除記憶，測試用獨立 DB |
| 記憶未進 Backboard | starter 只實作 local-fallback，需 AI owner 接 live client |
| CI 紅燈 | 先開最先失敗的 step；修正後 push 到同一 branch，不在四人機器各自改依賴 |
