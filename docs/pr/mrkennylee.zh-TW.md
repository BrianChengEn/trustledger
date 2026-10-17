# mrkennylee — 快速建立 PR

帳號：`mrkennylee`。本工作目錄已設定專案內的 Git 提交身分及 HTTPS 驗證。
GitHub CLI 沿用系統鑰匙圈中的既有登入；文件及 repository 不得存放 token。

Repository：[BrianChengEn/trustledger](https://github.com/BrianChengEn/trustledger)。
`origin` 及 GitHub CLI 預設 repository 已指向此處；`main` 追蹤 `origin/main`。
這些設定適用於目前的工作目錄，未來重新 clone 時仍須個別設定。

## 下次建立 PR

開始前，確認已追蹤檔案沒有未提交的變更。使用尚未存在的分支名稱，且只加入
本次 PR 要提交的檔案。將 `short-topic` 換成本次任務的主題。

```sh
git status --short
git fetch origin
git switch -c docs/short-topic origin/main
# 編輯文件後，明確指定本次要加入的檔案路徑。
git add docs/pr/mrkennylee.md
git diff --cached --check
git diff --cached
bash scripts/check.sh
git commit -m "docs: update PR notes"
git push -u origin HEAD
gh pr create --fill
gh pr checks
```

請依 repository 的 [PR 範本](../../.github/PULL_REQUEST_TEMPLATE.md) 填寫
Result、Checks 與 Evidence，再交付審查。合併前必須有另一位隊友審查，並通過
必要檢查。建立 PR 不代表授權部署。本機檢查若無法執行，應明確註明；
GitHub CI 會在 push 與 PR 時執行後端及前端測試。

本機環境限制（2026-10-17）：Homebrew Node 22 無法載入
`libsimdjson.33.dylib`，導致 `scripts/check.sh` 無法完成。相同的前端檢查
使用可運作的 Node 26 執行；CI 使用 Node 22。Homebrew 修復另行處理。

參考：[GitHub CLI pull requests](https://cli.github.com/manual/gh_pr_create)。
英文版本：[mrkennylee.md](mrkennylee.md)。
