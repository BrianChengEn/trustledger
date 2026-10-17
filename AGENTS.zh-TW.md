# TrustLedger 團隊實作規則

修改程式前，先讀 README.md、TEAM-SETUP-60MIN.md、docs/START-HERE.md、負責角色文件及 contracts/internal-api.openapi.yaml。英文原始規則見 [AGENTS.md](AGENTS.md)。

- 預設僅合成資料，不接真正銀行帳戶、真實財務資料或自動財務操作。
- API keys 留在 backend/.env 或執行環境 secrets；不將原始 ID 或商家文字送給 AI。
- AI owner：backend/app/services/ai/**、backend/tests/unit/ai/**。
- Frontend owner：frontend/**。Data owner：backend/app/adapters/**、backend/app/schemas/transaction.py、fixtures/**。
- Integrator owner：backend/app/api/**、backend/app/core/**、backend/app/main.py、共用相依套件、整合測試、CI、contracts/**。
- 實作前先同意契約變更，保留 synthetic baseline。
- Jev、Backboard、Nessie 檔案是明確的擴充點，不是已完成的 live 整合。
- 本機記憶標示 local-fallback，只有 normal 確認及明確同意後才能寫入。
- 執行 `bash scripts/check.sh`；無法安裝相依套件時，不宣稱測試通過。
- 不提交 node_modules、.venv、.env、資料庫或憑證。
- 提交作品時揭露 AI 工具使用；此骨架包含 AI 協助產生的程式與文件。

## 生命週期與 Nessie 設計工作

`/Users/kenny/Desktop/project-development-workflow/SKILL.md` 及 `rule.md` 是唯一生命週期路由；保留上述團隊所有權、安全、契約及 CI 要求。

Nessie 測試台設計索引為 [docs/v0.0.0/README.zh-TW.md](docs/v0.0.0/README.zh-TW.md)，[英文對應](docs/v0.0.0/README.md)。Q020 選定整合入口為左側 WORKSPACE → Admin。保留合成基準與同意後才寫入記憶的流程；實作前先同意新增 Admin 契約。資料檢查為 `python3 scripts/generate_synthetic_data.py --check`。
