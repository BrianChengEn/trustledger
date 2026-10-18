# TrustLedger — Technica 2026 四人黑客松文件套件

> **產品定位：** B2C、privacy-first 的個人金融安全助手。只使用合成資料或 Capital One Nessie sandbox/mock data；不接觸真實金融帳戶。
>
> **硬截止：** 2026-10-18 12:00 EDT。建議團隊在 11:15 EDT 完成提交、11:30 EDT 停止改碼。

## 先讀這三件事

**立即開始：** 應用程式已經在倉庫根目錄。現況、技術清單與四人分工看 [../README.md](../README.md)、[../TECH_STACK.md](../TECH_STACK.md)、[../TEAM_ROLES.md](../TEAM_ROLES.md)、[../ARCHITECTURE.md](../ARCHITECTURE.md)。本目錄的 `index.html` 是離線快照，可能落後 Markdown。

1. TrustLedger 的 MVP 只有四個產品能力：交易分析、經使用者確認後才寫入的 Backboard 記憶、Privacy Inspector、人工確認。
2. 原始帳號、姓名、地址、API key 與完整原始交易不得送到 Jev 或 Backboard。所有供應商 key 只存在 FastAPI 後端。
3. 任何供應商故障都不得讓 Demo 全毀：合成資料 + deterministic rules 是永遠可運作的 baseline；畫面必須誠實顯示 `live`、`mock` 或 `degraded`。

## 文件導覽

| 文件 | 用途 | 主要讀者 |
|---|---|---|
| [00-overall-architecture-report.md](00-overall-architecture-report.md) | 範圍、架構、資料流、API 契約、整合順序與決策 | 全隊 |
| [01-ai-engineer-jev-backboard.md](01-ai-engineer-jev-backboard.md) | Jev、Backboard、規則引擎、隱私層與測試 | AI Engineer |
| [02-frontend-react-vite.md](02-frontend-react-vite.md) | React/Vite Dashboard、Privacy Inspector、互動與無障礙 | Frontend Engineer |
| [03-nessie-data.md](03-nessie-data.md) | 合成資料、Nessie sandbox adapter、schema mapping | Data/Nessie Engineer |
| [04-fastapi-integration-deployment.md](04-fastapi-integration-deployment.md) | FastAPI、設定、整合、CORS、部署與降級 | Backend/Integration Engineer |
| [05-github-collaboration.md](05-github-collaboration.md) | Repo、邀請、branches、PR、worktrees、conflict、CI、secrets | 全隊／Integrator |
| [06-security-privacy-threat-model.md](06-security-privacy-threat-model.md) | 詳細威脅模型、控制措施、驗證與殘餘風險 | 全隊 |
| [07-submission-runbook.md](07-submission-runbook.md) | 時程、降級、Demo、Devpost 與最終檢查表 | 全隊 |
| [SOURCES.md](SOURCES.md) | 官方資料來源、核對狀態與待驗證清單 | 全隊 |
| [contracts/internal-api.openapi.yaml](contracts/internal-api.openapi.yaml) | 團隊內部 FastAPI ↔ React 契約 | Frontend + Backend |
| [diagrams/index.md](diagrams/index.md) | 六張 Mermaid 圖的說明與編輯方式 | 全隊 |
| [index.html](index.html) | 離線文件閱讀器、六張 SVG 圖、放大與全螢幕 | 全隊 |

## 四人分工與檔案所有權

| 角色 | 唯一寫入區域 | 第一個可合併產出 |
|---|---|---|
| AI Engineer | `backend/app/services/ai/**`、`backend/tests/unit/ai/**` | `privacy.py` + rules baseline + vendor clients 的 mock tests |
| Frontend Engineer | `frontend/**` | 三頁可用 mock JSON 操作的 UI |
| Data/Nessie Engineer | `backend/app/adapters/**`、`backend/app/schemas/transaction.py`、`fixtures/**` | synthetic adapter + 可靠 fixture + Nessie health probe |
| Backend/Integration Engineer | `backend/app/main.py`、`backend/app/api/**`、`backend/app/core/**`、整合測試與部署 | 依 OpenAPI 契約回傳 fixture 的 FastAPI vertical slice |

`contracts/**` 由 Integration Engineer 維護。任何 contract 變更須先在 PR 說明破壞性影響，Frontend 與相關 owner 同意後才合併。

## 建議 repository 結構

```text
trustledger/
├── frontend/                         # React + TypeScript + Vite
├── backend/
│   ├── app/
│   │   ├── api/                      # FastAPI routers
│   │   ├── adapters/                 # synthetic.py, nessie.py
│   │   ├── core/                     # config, safe logging, request identity
│   │   ├── schemas/                  # internal Pydantic DTOs
│   │   └── services/ai/              # privacy, rules, jev, backboard, memory
│   └── tests/
├── contracts/                        # internal API contract; review before change
├── fixtures/                          # synthetic data only
├── diagrams/                          # editable Mermaid sources
├── .env.example                       # placeholders only
└── README.md
```

## 10 分鐘團隊啟動

```bash
git clone https://github.com/<ORG_OR_USER>/trustledger.git
cd trustledger
cp .env.example .env
git switch -c chore/<your-name>-bootstrap
```

Windows PowerShell：

```powershell
git clone https://github.com/<ORG_OR_USER>/trustledger.git
Set-Location trustledger
Copy-Item .env.example .env
git switch -c chore/<your-name>-bootstrap
```

接著依角色任務書操作。`<ORG_OR_USER>` 是佔位符，不是可執行 URL。

## 安全 key 流程

1. 每位負責人自行在供應商 dashboard 取得 key；不要貼到 Slack、Issue、PR、截圖或前端。
2. key 只填入本機 `backend/.env` 或部署平台的 secret store。
3. `.env`、`.env.*` 預設被忽略；只有 `.env.example` 可以提交。
4. CI 不跑 live vendor calls；所有 vendor client 在 CI 以 mocks/contracts 測試。
5. 若 key 曾進入 Git history，不是「刪掉那一行」就完成：先撤銷/輪替 key，再處理 history，並檢查 Actions logs 與 artifacts。

## 完成定義

- `GET /api/v1/health` 可辨識 `synthetic`、`live`、`degraded`。
- Dashboard 可載入至少 8 筆合成交易，明確包含 duplicate 與 high-amount 案例。
- 使用者可開啟 alert、查看證據與 Privacy Inspector、選擇 `normal` 或 `review`。
- 只有 `consent_to_memory=true` 且 confirmation 成功後，才可寫入最小化的 Backboard memory。
- Jev/Backboard/Nessie 任一不可用時，核心 Demo 仍可完成，且不偽稱使用了 live provider。
- 測試證明 outbound AI payload 不含姓名、地址、帳號、原始 merchant 字串、API key。
- repo、Devpost 描述與簡報清楚揭露 AI 工具使用；官方規則要求 credit AI usage。

## 重要限制

Versioned implementation updates are maintained locally under `docs/vx.x.x/`, using guides 00–07 as constraints. The current local update is [v0.3.1](v0.3.1/ArchitectureDecisions.md): integrate Ian's selected `ianthechou` frontend (`9c40b01`) with the existing v0.3.0 backend, retaining its palette, menus, widgets, themes and window fitting. The user approved existing pagination only when Activity overflows. Effective designs: [Frontend](v0.3.1/Frontend.md), unchanged [Backend](v0.3.0/Backend.md), [DataFlow](v0.3.0/DataFlow.md), [UserFlow](v0.3.0/UserFlow.md), [Database](v0.2.1/Database.md); the new decision map records filter/paging/data-presentation adaptations. [v0.2.1](v0.2.1/ArchitectureDecisions.md) records the 180 connected transfers, 10 offline transfers and canonical account codes; earlier version directories remain historical. Every original merchant-row control opens details; customer state is isolated. Integration preserves the selected frontend's views, controls, styling and interactions while adapting backend data at existing API/client boundaries. Newly added Markdown design notes are excluded from PRs; JSON files remain offline compatibility fixtures. No additional generator, global customer switch, banking write, dependency or deployment is part of v0.3.1.

這是黑客松 prototype，不是銀行產品、投資建議、詐欺判定系統或合規認證。不要使用真實金融資料，不要宣稱 PCI DSS、SOC 2、GLBA、CCPA/GDPR 或銀行安全合規已完成。正式上線前仍需法律/隱私評估、供應商 DPA 與 retention 審查、正式身分驗證/授權、滲透測試、監控與事件應變。

