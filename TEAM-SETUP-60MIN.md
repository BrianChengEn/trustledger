# Setup for four Macs

Official setup for the TrustLedger demo. Role details are in [TEAM_ROLES.md](TEAM_ROLES.md). Tool versions are in [TECH_STACK.md](TECH_STACK.md).

The older Chinese checklist in this file is replaced by the steps below so branch names and owners stay in one place. Kenny's personal command list remains in [docs/pr/mrkennylee.md](docs/pr/mrkennylee.md) and [docs/pr/mrkennylee.zh-TW.md](docs/pr/mrkennylee.zh-TW.md).

If Homebrew or Xcode Command Line Tools are missing, install them first. Do not block the other three people on one machine.

## Shared setup

These steps are the same for Brian, Benson, Ian, and Kenny.

### 1. Accounts and tools

Repository: https://github.com/BrianChengEn/trustledger

Collaborators already on the repo: `BrianChengEn` (admin), `benson5112`, `IanChou89`, `mrkennylee`.

```bash
git --version
brew --version
```

If `brew` is missing, install it from https://brew.sh/ and reopen Terminal. If `git` is missing, run `xcode-select --install`, finish the system dialog, and reopen Terminal.

```bash
brew install git gh
gh auth login
gh auth setup-git
```

Use your own GitHub account. Do not share a token.

### 2. Clone and install

```bash
git clone https://github.com/BrianChengEn/trustledger.git
cd trustledger
bash scripts/bootstrap-mac.sh
```

`scripts/bootstrap-mac.sh` is macOS-only. It installs Node 22, Python 3.12, and GitHub CLI when Homebrew can, creates `backend/.venv`, installs `backend/requirements.lock.txt`, runs `npm ci` in `frontend/`, and copies the example env files only when the destination is missing. It does not write vendor keys.

Check the toolchain:

```bash
bash scripts/doctor.sh
git check-ignore -v backend/.env frontend/.env.local
```

`doctor.sh` requires Node `>=22.12` and Python 3.12, or Python 3.11 or newer if `python3.12` is absent. Bootstrap itself creates the virtualenv with `python3.12`.

### 3. Run

From the repository root, use two terminals:

```bash
bash scripts/dev-backend.sh
```

```bash
bash scripts/dev-frontend.sh
```

- App: http://127.0.0.1:5173
- API docs: http://127.0.0.1:8000/docs

With the backend up:

```bash
backend/.venv/bin/python scripts/smoke.py
```

Expect 8 synthetic transactions and 3 alerts. Health shows `synthetic`, `rules-only`, and `local-fallback`. Open **Possible duplicate**, read the evidence and Privacy Inspector, confirm normal with the memory box checked, open **Confirmed memory**, then delete that row.

### 4. Test

```bash
bash scripts/check.sh
```

Backend: Ruff and pytest. Frontend: `tsc --noEmit`, Vitest, Vite build. The script exits non-zero if `backend/.venv` is missing. Do not report a pass from a partial run.

### 5. Environment files

| File | Who edits the real values | What belongs there |
|---|---|---|
| `backend/.env` | The person running a live call, on that machine only | Empty keys are correct for the synthetic demo |
| `frontend/.env.local` | Ian, only if the API is not on the Vite proxy | `VITE_API_BASE_URL` empty for local demo |

Loaded by the app from `backend/.env`: `APP_ENV`, `ALLOW_MEMORY_WRITE`, `DEMO_USER_ID`, `FRONTEND_ORIGIN`, `NESSIE_API_KEY`, `JEV_API_KEY`, `BACKBOARD_API_KEY`.

`docs/.env.example` lists extra URLs (`NESSIE_BASE_URL`, `JEV_BASE_URL`, `JEV_MODEL`, `BACKBOARD_ASSISTANT_ID`, `DATABASE_URL`). The running settings object ignores them. Do not add a key there and expect a live call.

Never put a real key in Git, chat, a screenshot, a prompt, or the frontend.

## Role-specific setup

Do this after the shared steps. None of it is required to run the synthetic demo.

| Person | Extra local step | Not required for the demo |
|---|---|---|
| Brian | Put a Backboard key in `BACKBOARD_API_KEY` and set `ALLOW_MEMORY_WRITE=true` to store consented memory. Jev uses that same key. Do not add a TypeSafe bearer token | An empty key keeps memory in SQLite as `local-fallback` and analysis at `rules-only`. Do not buy System One credits |
| Benson | Confirm `bash scripts/check.sh` and the Actions tab on your PR | No deploy target is configured |
| Ian | Open http://127.0.0.1:5173 after both servers start | Playwright's browser is only needed for `node scripts/browser-smoke.mjs` |
| Kenny | Create a Nessie sandbox key at [api.nessieisreal.com](http://api.nessieisreal.com/) and keep it in `backend/.env` | `nessie.py` still raises `NessieNotConfigured` after the key is present |

Selected Jev call: Backboard `POST https://app.backboard.io/api/threads/messages` with header `X-API-Key`. See [ARCHITECTURE.md](ARCHITECTURE.md). The direct TypeSafe URL and `jev-ai.org` are not the selected route.

## Branches

Fetch first. Create a branch only when that name is not already on the remote. Do not `reset`, delete, or force-push someone else's branch.

```bash
git switch main
git pull --ff-only
git switch -c feat/ai-engine
```

Use `feat/backend-integration`, `feat/frontend`, or `feat/nessie-data` for the other roles. Existing remote names to leave alone:

| Branch | State on 17 October 2026 |
|---|---|
| `backend` | Benson. One unmerged commit: shell line endings and `backend/README.md` |
| `ianthechou` | No unique commits. Behind `main` |
| `mrkennylee` | Guide already merged through PR #2 |
| `feat/local-memory-feedback` | Memory feedback merged through PR #3 |

Push and open a pull request:

```bash
git status
git add path/to/file
git commit -m "feat(ai): short outcome"
git push -u origin feat/ai-engine
gh pr create --base main --fill
```

Replace the path and the branch name. Do not stage `.env`, `backend/data/`, `.venv`, or `node_modules`.

## Fixes

| What you see | What to do |
|---|---|
| `brew: command not found` | Finish the Homebrew shell setup and open a new Terminal |
| Clone returns 404 | Accept the repo invite. Run `gh auth status`. Do not paste a token into chat |
| `npm: command not found` | Re-run bootstrap, or add `$(brew --prefix node@22)/bin` to `PATH` |
| Python is 3.10 | Bootstrap uses `python3.12`. Do not point the venv at the older system Python |
| Port 8000 or 5173 is in use | Stop the dev server you started. Do not kill unknown processes |
| `requirements.txt` or `package.json` missing | Clone the repository root, not an old docs-only zip |
| Download or TLS error | Check the network. Do not disable TLS verification |
| Memory is still there after restart | Expected. Backboard keeps a `source=backboard` row, and SQLite keeps the local index. Delete it in the UI. Tests use a temporary database |
| Memory did not appear in Backboard | Check `BACKBOARD_API_KEY`, `ALLOW_MEMORY_WRITE=true`, decision `normal`, and consent. An empty key is SQLite only. Repeating an old confirmation does not write again. `GET /api/v1/memories` shows `source` |
| `check.sh` fails on Node | `doctor.sh` requires Node >= 22.12. CI uses Node 22. Fix the local Node before calling the suite green |
| CI is red | Open the first failed job. Push the fix to the same branch. Do not each edit the lockfiles |

## First-hour check

- [ ] You can see the private repo with your own GitHub user.
- [ ] Backend and frontend start on ports 8000 and 5173.
- [ ] `bash scripts/check.sh` prints `PASS: backend tests/lint and frontend typecheck/tests/build.`
- [ ] Health is `synthetic` / `rules-only` / `local-fallback`.
- [ ] Your branch is one of the new names above, or an existing branch you already own.
- [ ] `docs/index.html` opens offline. The six diagrams are listed in [docs/diagrams/index.md](docs/diagrams/index.md). For current behavior, read [ARCHITECTURE.md](ARCHITECTURE.md) when the snapshot disagrees.
