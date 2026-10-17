# mrkennylee — Quick pull requests

Account: `mrkennylee`. Git author and HTTPS authentication are configured locally
for this checkout. GitHub CLI reuses the existing account in the system keyring;
no token belongs in this document or the repository.

Repository: [BrianChengEn/trustledger](https://github.com/BrianChengEn/trustledger).
`origin` and the GitHub CLI default repository point here; `main` tracks
`origin/main`. These settings apply to this checkout, not a future clone.

## Next pull request

Start with a clean tracked working tree. Use an unused branch name and stage only
the files intended for this PR. Replace `short-topic` with the task's topic.

```sh
git status --short
git fetch origin
git switch -c docs/short-topic origin/main
# Edit the intended documentation, then stage its exact paths.
git add docs/pr/mrkennylee.md
git diff --cached --check
git diff --cached
bash scripts/check.sh
git commit -m "docs: update PR notes"
git push -u origin HEAD
gh pr create --fill
gh pr checks
```

Fill in Result, Checks, and Evidence from the repository's
[PR template](../../.github/PULL_REQUEST_TEMPLATE.md) before requesting review.
One other teammate must review, and required checks must pass before merging.
Opening a PR does not authorize deployment. Report unavailable local checks
explicitly; GitHub CI runs the backend and frontend suites on push and PR.

Local runtime limitation (2026-10-17): Homebrew Node 22 cannot load
`libsimdjson.33.dylib`, blocking `scripts/check.sh`. Equivalent frontend checks
use working Node 26; CI uses Node 22. Homebrew repair is separate work.

Reference: [GitHub CLI pull requests](https://cli.github.com/manual/gh_pr_create).
Companion: [Traditional Chinese](mrkennylee.zh-TW.md).
