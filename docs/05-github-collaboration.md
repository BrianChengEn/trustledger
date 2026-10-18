# GitHub 四人協作手冊

## 目標

四個人可以平行開發，但任何時間 `main` 都能跑 synthetic vertical slice。協作的核心不是「大家都能改所有檔案」，而是清楚 owner、contract freeze、小 PR、早整合、零 secrets。

## 1. 建立 repository

由一位 Integration Engineer 建立 `trustledger` repository。

### GitHub UI

1. New repository → `trustledger`。
2. 比賽中建議 Private；若 sponsor/Devpost 要求 public，在提交前確認後再切換。
3. 不勾自動 README/.gitignore/license，若本機已初始化；避免第一次 push 衝突。
4. 建立後依 GitHub 顯示的 exact remote command 操作。

### GitHub CLI（若團隊已登入）

```bash
git init
git add .
git commit -m "chore: bootstrap TrustLedger"
gh repo create trustledger --private --source=. --remote=origin --push
```

不要在截止前花時間建立 organization，除非團隊本來就有。

## 2. 邀請協作者

Repository → Settings → Collaborators/Manage access → Add people → 輸入三位隊友的 exact GitHub username。每位隊友接受 email/GitHub 邀請後：

```bash
git clone https://github.com/<ORG_OR_USER>/trustledger.git
cd trustledger
git remote -v
git fetch origin
```

不要共享 GitHub 密碼、personal access token 或 deploy token。每人用自己的帳號/SSH key/credential manager。

## 3. 分支與 owner

| 角色 | 建議 branch | 主要目錄 |
|---|---|---|
| AI | `feat/ai-privacy-memory` | `backend/app/services/ai/**` |
| Frontend | `feat/frontend-dashboard` | `frontend/**` |
| Data | `feat/data-nessie-adapter` | `backend/app/adapters/**`、`fixtures/**` |
| Integration | `feat/api-vertical-slice` | `backend/app/api/**`、`core/**`、`contracts/**` |

其他命名：`fix/...`、`docs/...`、`chore/...`。不要用 `brian-final-final2`。

開始任務：

```bash
git switch main
git pull --ff-only
git switch -c feat/<scope>
```

每 30–60 分鐘做一個可理解 commit；commit message 示例：

```text
feat(ai): add allowlisted privacy payload
test(data): cover Nessie timeout fallback
fix(api): preserve confirmation when memory fails
docs: credit AI tools used for the project
```

## 4. Contract freeze

`contracts/internal-api.openapi.yaml` 由 Integration Engineer 擁有。流程：

1. 2026-10-17 13:30 EDT 前合併 v0.1。
2. Frontend 依 contract 寫 mock/client；Backend 依 contract 寫 routes。
3. Contract 變更 PR 必須標：breaking/non-breaking、影響 endpoint/type、migration。
4. Frontend + Backend 至少各一人 approve breaking change。
5. feature freeze 後只接受修 bug 所需的最小 contract 變更。

## 5. PR 流程

```bash
git status
git add <owned-files-only>
git commit -m "feat(scope): concise outcome"
git push -u origin feat/<scope>
gh pr create --fill
```

PR 必須小而可 review；理想 100–400 changed lines（fixture/generated lock 例外）。每個 PR 填：

- Outcome / scope。
- Files owned/touched。
- Contract impact。
- Tests command + result。
- Screenshots（UI only，零個資/key）。
- Security/privacy checks。
- Fallback/degraded behavior。
- Known limitations / next integration step。

Review 先看：secret/PII → contract → tests/fallback → code → style。

## 6. Main protection

若 GitHub plan/UI 可用，在 Settings → Branches/Rulesets 對 `main` 設：

- Require pull request before merge。
- Require 1 approval；最後 2 小時可由 integrator依團隊協議 emergency merge，但仍要 CI。
- Require status checks：backend tests、frontend lint/build。
- Block force push、block deletion。
- 啟用 conversation resolution。

不要把「admins 可 bypass」當日常流程。

## 7. Worktrees（給同一台電腦並行工作的成員）

每位隊友有自己電腦時用普通 clone 即可。Worktree 適合 integrator 在同一台機器同時保留 main 與多個 branch，不是共享檔案同步工具。

從 repo root：

```bash
git fetch origin
git worktree add ../trustledger-ai -b feat/ai-privacy-memory origin/main
git worktree add ../trustledger-api -b feat/api-vertical-slice origin/main
git worktree list
```

規則：

- 一個 branch 同時只能 checkout 在一個 worktree。
- 每個 worktree 都要獨立 `.venv`/`node_modules`/`.env`；不要 symlink secrets。
- 合併後用 `git worktree remove ../trustledger-ai` 前先確認 clean 且已 push；不要刪有未提交檔案的 worktree。
- 不把 worktree 目錄放進 repository 內。

## 8. 同步與衝突

每天/每次 PR 前：

```bash
git fetch origin
git rebase origin/main
```

衝突時：

1. 先讀 `<<<<<<<`、`=======`、`>>>>>>>` 兩邊語意。
2. 找檔案 owner；不要直接選「ours/theirs」覆蓋未知改動。
3. 手動整合、執行相關 tests。
4. `git add <resolved-files>` → `git rebase --continue`。
5. 已 push 的 feature branch 如需更新，用 `git push --force-with-lease`，絕不用 plain `--force`；若團隊不熟 rebase，改用 merge main。

### 高衝突檔案

- `contracts/internal-api.openapi.yaml`：Integration owner only。
- dependency lock：Frontend/Backend 各自單一 owner。
- `README.md`/Devpost text：最後由 integrator 整理。
- `.env.example`：任何新增變數先審安全與 owner。

## 9. CI

CI 不應有 live vendor keys，也不應 call Nessie/Jev/Backboard。使用 mocks/contracts，避免 fork PR 或 log 洩漏。

建議 checks：

```text
backend: install → pytest
frontend: npm ci → lint → test (若有) → build
security: ensure no tracked .env; optional secret scanner
contract: parse OpenAPI/YAML; optional snapshot diff
```

可複製草案：[templates/ci.example.yml](templates/ci.example.yml)。把它複製成 `.github/workflows/ci.yml` 前，確認 repo 的 Python dependency file、npm scripts 與 GitHub Actions major versions。範例故意沒有 vendor secrets。

## 10. Secret management

### 本機

- 真實值只在 ignored `backend/.env` 或 process environment。
- `frontend/.env.local` 只能有 public `VITE_API_BASE_URL`。
- `.env.example` 永遠空值/placeholder。
- 每人各自取得 dev key；無法做到就由一位 backend owner執行 live integration，其他人用 mocks。

### GitHub Actions

Prototype CI 不需要 vendor secrets。若真的需要 deploy secret：Repository Settings → Secrets and variables → Actions，使用最小權限、環境限制與短期 credential；不得在 `pull_request` from fork 執行會取得 secret 的工作。

### Push protection

啟用 GitHub secret scanning/push protection（方案允許時）。GitHub [官方文件](https://docs.github.com/en/code-security/how-tos/secure-your-secrets/work-with-leak-prevention/push-protection-in-the-github-ui) 說明可阻擋支援格式的 secrets，但偵測不是完整保證；不可因有 scanner 就提交 `.env`。

### Secret 誤提交事件

順序不能顛倒：

1. 立刻在 vendor 撤銷/rotate。
2. 通知 integrator；暫停 deploy。
3. 檢查 Git history、PR diff、Actions logs/artifacts、screenshots。
4. 依 GitHub 官方程序移除 history；協調隊友重新同步。
5. 記錄事件，不在公開 issue 重貼 secret。

只刪最新 commit 不足以保護已曝光 key。

## 11. 合併順序

1. `chore/bootstrap`：目錄、env examples、fixture、CI skeleton。
2. `contracts/v0.1`。
3. Backend synthetic health/transactions。
4. Frontend contract mock vertical slice。
5. AI privacy/rules。
6. Data synthetic adapter。
7. Full synthetic integration。
8. Nessie live read（optional flag）。
9. Jev live（optional flag）。
10. Backboard live memory（optional flag）。
11. Security fixes、accessibility、copy、submission docs。

每個 live integration 都是可單獨 rollback 的 PR。

## 12. 最後 3 小時規則

- 09:00 EDT：只接受 P0/P1 bug、提交素材、accessibility fixes。
- 10:00 EDT：部署 cutoff；記 last known good URL/SHA。
- 10:30 EDT：Devpost draft 和影片完成。
- 11:15 EDT：submit candidate。
- 11:30 EDT：停止 merge；只做 submission verification。

## 13. Team sync 模板

每 90 分鐘，四人各用 30 秒回答：

```text
Done:
Next:
Blocked:
Contract/security change:
Branch/PR:
```

阻塞超過 20 分鐘就切 fallback，不把全隊綁在一個外部 API。

## 合併前總檢查

- [ ] 只改 owned files，或已取得 owner同意。
- [ ] 無 `.env`、keys、raw vendor body/URL、PII。
- [ ] contract change 已同步。
- [ ] tests/lint/build 通過。
- [ ] fallback 已測。
- [ ] UI change 有 keyboard/mobile check。
- [ ] logging/error 不洩漏。
- [ ] PR 描述列已知限制。
- [ ] 合併後 `main` 仍可完成 synthetic Demo。

