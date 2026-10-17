# 官方來源與核對紀錄

**核對日期：2026-10-17（America/New_York）**

本套件只把下列官方頁面中能直接確認的名稱、endpoint、schema 或規則寫成「已核對」。文件頁面間若有不一致，採保守做法並列入待驗證，不推測不存在的功能。

## Technica 2026 / Devpost

- [Technica 2026 官方網站](https://gotechnica.org/)：活動日期 2026-10-17～18、hybrid 形式、一般 tracks 與活動資訊。
- [Technica 2026 官方 Devpost overview](https://technica-2026.devpost.com/)：2026-10-18 12:00 EDT 截止；一般隊伍最多 4 人；24 小時 hacking period；評分面向；最多 3 個一般 challenges 外加最多 3 個 sponsored challenges；需現場或 Gather live demo 才具得獎資格。
- [Technica 2026 官方規則](https://technica-2026.devpost.com/rules)：一般隊伍最多 4 人；需 credit 使用的 ChatGPT/AI，未揭露可能導致取消資格。
- [Devpost schedule](https://technica-2026.devpost.com/details/dates)：提交截止顯示 2026-10-18 12:00 EDT。
- 官方 sponsored challenge 名稱已核對：`[Capital One] The Best Use of Nessie`、`[T. Rowe Price] NextGen Finance Innovation Challenge`、`[MLH] Best Use of Backboard`。

### 活動現場必查

- Devpost overview 把 Sunday Expo 寫成 `1:00 pm EST`；10 月 18 日美東通常仍為 EDT。以 Technica 現場 schedule、Slack/Gather announcement 為準。
- 是否需要公開 GitHub repository、影片長度、Devpost 必填欄位與 sponsor 額外提交材料，公開 rules 頁未完整列出，提交前向 organizer/sponsor mentor 確認。

## Jev

- [Introduction](https://jev-ai.org/docs/)：Jev 是 decision model；`POST /api/v1/systemone/`；每次最多 20 個 questions；問題類型為 `noul`、`choice`、`score`。
- [Authentication](https://jev-ai.org/docs/authentication/)：`Authorization: Bearer` 或 `x-api-key`；key 僅可放 server；建議每個環境一把 key。
- [Decisions contract](https://jev-ai.org/docs/decisions/)：`state`、`questions`、可選 `model`；optional `Idempotency-Key`；回應含 `id`、`model_version`、`answers`、`usage`、`latency_ms`。
- [Question types](https://jev-ai.org/docs/question-types/)：`choice.criteria` 是 label → description object；`score.criteria` 是由低到高的 array；`score` 回傳 decimal。
- [Models](https://jev-ai.org/docs/models/)：已列出 `jev-1.13` 與 rolling `jev-latest`。MVP 鎖定 `jev-1.13`，避免比賽中行為漂移。

## Backboard

- [Authentication](https://docs.backboard.io/authentication)：`X-API-Key`；key 只能存在 server-side environment variable。
- [Architecture](https://docs.backboard.io/concepts/architecture)：Assistant 包含 threads；Memory 位於 assistant scope，會跨同 assistant 的 threads 使用。
- [Send Message](https://docs.backboard.io/concepts/messages)：`POST https://app.backboard.io/api/threads/messages`；常用欄位為 `content`、`thread_id`、`assistant_id`、`memory`、`stream`。
- [Memory](https://docs.backboard.io/concepts/memory)：`memory="Auto"` 寫入與讀取、`Readonly` 只讀、`off` 停用；提供 list/add/search/get/update/delete memory endpoints；memory operation 可能非同步。
- [Create Assistant](https://docs.backboard.io/api-reference/assistants/create)：`POST /assistants`，至少需要 `name`；可設定 `system_prompt` 與 custom memory prompts。

**安全推論：** 因 memory 是 assistant-scoped 且跨 threads，共用一個 assistant 給多位終端使用者可能造成跨使用者記憶混用。MVP 僅使用單一合成 demo user；未來多使用者版應採每位使用者獨立 assistant，或先取得 Backboard 明確支援的 isolation design，再做 adversarial test。這是架構推論，不是 Backboard 的合規保證。

## Capital One Nessie

- [Nessie 官方文件](https://prod.nessieisreal.com/docs)：Nessie 是 banking simulation REST API；資源包含 customers、accounts、deposits、withdrawals、transfers、purchases、bills、loans、merchants、ATMs、branches、enterprise。
- [Nessie Getting Started](https://nessieisreal.com/getting-started)：GitHub login 取得 API key；key 以 `key` query parameter 傳入；enterprise endpoints 只讀。
- 2026-10-17 直接檢查官方互動文件可見：`GET /customers`、`GET /customers/{id}/accounts`、`GET /accounts/{id}/bills`、`GET /merchants` 等；Authentication 頁顯示 OpenAPI 1.0.0 / OAS 3.0。
- 官方 Quick Start 顯示 `POST /customers`、`POST /customers/{id}/accounts`、`POST /accounts/{id}/deposits`、`POST /accounts/{id}/transfers`。

### Nessie 不一致與保守決策

同日官方 OpenAPI operation list 的 purchases 區只顯示 `GET/PUT/DELETE /purchase/{purchase_id}`，但舊 SDK/文件常見 `/accounts/{id}/purchases`；Quick Start 也顯示 create transfer，但 operation list 的 Transfers 區未完整顯示 create/list。這可能是網站/OpenAPI 更新不同步。

因此本套件：

1. 不把未確認的 list/create purchase/transfer endpoints 寫成必定可執行的程式。
2. Demo 核心交易流以合成 fixture 為準。
3. Nessie integration 先做官方頁面當下可見的 read endpoints 與 health probe。
4. 活動現場若 sponsor mentor 確認新 contract，再更新 adapter；不要讓 contract investigation 阻塞 vertical slice。

## 工具鏈與安全參考

- [Vite Getting Started](https://vite.dev/guide/)：目前要求 Node.js 20.19+ 或 22.12+；`react-ts` template 可用。
- [FastAPI Tutorial](https://fastapi.tiangolo.com/tutorial/)：建議 `pip install "fastapi[standard]"`；Python 3.10+ 範例。
- [GitHub push protection](https://docs.github.com/en/code-security/how-tos/secure-your-secrets/work-with-leak-prevention/push-protection-in-the-github-ui)：GitHub 可阻擋支援格式的 secret；這是最後防線，不是可以提交 `.env` 的理由。
- [OWASP Top 10 for LLM Applications 2025](https://owasp.org/www-project-top-10-for-large-language-model-applications/assets/PDF/OWASP-Top-10-for-LLMs-v2025.pdf)：敏感資訊揭露、prompt injection、過度代理、misinformation 等風險。

## 尚未確認，不得宣稱

- Jev 或 Backboard 對輸入資料的確切保留期、訓練用途、資料所在地、DPA/SOC 2 狀態。
- Nessie 所有 legacy SDK endpoint 在目前 event sandbox 都可用。
- TrustLedger 符合 PCI DSS、GLBA、SOC 2、GDPR、CCPA 或任何銀行正式安全/合規要求。
- Jev 分類是詐欺判定、金融建議或銀行授權決策。
- Backboard memory 自動具備終端使用者隔離或刪除 SLA。

