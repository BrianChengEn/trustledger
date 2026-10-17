# Nessie 開發者測試台實作計畫

狀態：TrustLedger WORKSPACE → Admin 的初版設計計畫已完成（Q020／D008）。S0–S4 與 S5 本機／真實驗證已實作；PR 整合審查結果記於後文。對應：[English](Plan.md)。

**目標：** 實作 [ArchitectureDecisions](ArchitectureDecisions.zh-TW.md) 定義的六項本機查詢、持久歷史、快照比較及可續跑 baseline 設定。

**架構：** 擴充既有 React／TypeScript／Vite 外框、FastAPI 與 Settings／Store SQLite；Python 呼叫白名單 Nessie API，以 SQLite 保存安全歷史及獨立匯入進度。設定寫入與執行期間唯讀控制分開。

**路由：** `/Users/kenny/Desktop/project-development-workflow/SKILL.md` 及 `rule.md` 是唯一生命週期路由。完成並驗證一個 spike 才進下一個。主代理負責整合；本計畫不代表授權代理分工或發佈。

## 全域限制與檔案責任

- 保留 `idea.md`、Q001–Q020、AC01–AC12、P01–P10、DF01–DF06、UF01–UF05 與穩定前端 ID；初版雙語同步。
- 執行期間唯讀、每次即時查詢、key 僅後端、loopback、確切 `failed to write`、不自動過期、不盲目重試不明寫入。Admin 快照不進入 AI 或 confirmed-memory service。
- Integrator：`backend/app/api/admin_nessie.py`、`backend/app/schemas/admin_nessie.py`、`backend/app/services/nessie_console.py`、既有 `core/store.py`、`main.py` 及 `contracts/internal-api.openapi.yaml` 新增內容；實作前先同意契約，保留既有端點及同意語意。
- Data owner：擴充 `backend/app/adapters/nessie.py` 的 P02，新增 `seed_nessie.py` 的 P10；保留既有合成交易 adapter 及來源資料。
- Frontend owner：擴充 `main.tsx`、`api.ts`、`styles.css`，加入 `Admin.tsx` 與 `frontend/tests/admin-console.spec.mjs`；沿用 React state、typed client 及已安裝 Playwright，不增加框架或相依套件。
- 沿用 pytest／ruff、TypeScript／Vitest／build、既有鎖定套件、Settings secret、資料庫路徑及 ignore 規則。聚焦測試放在 `backend/tests/unit/data/test_nessie.py`、`test_seed.py`、`backend/tests/integration/test_admin_nessie.py`、`backend/tests/unit/test_compare.py`。
- 既有啟動／CI 指令可用；下列新的 Admin 端點、seed 模組、聚焦測試與瀏覽器指令需等對應 spike 實作。pytest 可由 `backend/` 執行，或由根目錄指令設定 `PYTHONPATH=backend`。本次設計不包含 bootstrap、升級、發佈或部署。

## 審查重點

1. 上游 POST 已提交但回覆／本機對應遺失：先核對，不重複建立（S1）。
2. API 成功但資料庫不可寫：保留資料及確切 `failed to write`（S2／S4）。
3. 相同本文僅排序或執行時間不同：無資料差異；業務日期變更仍計入（S3）。
4. 選取中歷史被刪除，或清除後 ID 被重用：不比較無關的新紀錄（S2／S4）。
5. 含憑證錯誤及類似 HTML 字串：不洩漏 key、不執行標記（S1／S4）。

## S0 — 需求、資料與可檢閱設計

結果：內部一致的雙語設計基準及可用本機參考。相依：Q020 已確認。範圍／負責：主代理，僅文件／參考及既有資料準備。

- [x] 準備五組可重現資料、32 筆歷史、七組比較案例與產生器／自我檢查（D003、AC11）。
- [x] 完成 Q001–Q020，記錄使用者選擇、timestamp 語意、失敗文字及可續跑匯入。
- [x] 草擬適用雙語設計及每畫面兩份參考，ID 一致、連結可用。
- [x] 驗證資料、雙語 ID／清單、連結、HTML 結構、JavaScript 語法及瀏覽器參考互動，證據記於 D007／D009。
- [x] 記錄 Q020 B，確定 WORKSPACE → Admin 整合與模組位置，驗證參考頁、雙語一致、既有契約保留及必要 CI（D008／D009）。

整合：[前端](Frontend.zh-TW.md)、[後端](Backend.zh-TW.md)、[資料流](DataFlow.zh-TW.md)、[使用者流程](UserFlow.zh-TW.md)、[資料庫](Database.zh-TW.md)。現有資料指令：`python3 scripts/generate_synthetic_data.py --check`。

## S1 — 正式整合切片及可續跑 baseline 設定

結果：已驗證上游轉接與可續跑設定，具有確認遠端 ID 對應。相依：S0、實作前由 Integrator 同意新增 Admin 契約、安全可用的後端 key。範圍：`backend/app/adapters/nessie.py`、`backend/app/core/store.py`、`backend/app/adapters/seed_nessie.py`、既有 Settings／Store／ignore 規則、`backend/tests/unit/data/test_nessie.py`、`backend/tests/unit/data/test_seed.py`。介面：P02 `call_nessie(spec) -> UpstreamResult`；P10 `seed_baseline(probe=False) -> SeedSummary`；T-SEED-RUN／T-SEED-RECORD。

- [x] 先寫失敗 transport 測試：合成 401 本文保留狀態 401；逾時狀態／本文為 null；任何結果／錯誤／日誌均無 sentinel key；只呼叫白名單路徑。
- [x] 先寫失敗匯入測試：父 confirmed 才建立子；本機 ID 不當遠端路徑；POST 前提交 pending；回覆遺失不再 POST；完成重跑零新增；清歷史保留對應。
- [x] 依 DF05 實作 P02、新增 Store 資料表與進度，保留 confirmations／memories，以及 P10。保留為有測試的正式整合程式，不直接沿用未檢查的一次性探測。
- [x] 執行規劃的 `PYTHONPATH=backend backend/.venv/bin/python -m pytest backend/tests/unit/data/test_nessie.py` 與 `PYTHONPATH=backend backend/.venv/bin/python -m pytest backend/tests/unit/data/test_seed.py`，通過才做線上寫入。
- [x] 執行規劃的 `cd backend && .venv/bin/python -m app.adapters.seed_nessie --probe`：建立並讀回一個客戶、一個帳戶及其六筆交易，驗證 ID、狀態／餘額與文字回覆。遇不相容先停止；需求需改變時更新問題紀錄。
- [x] 探測通過後執行規劃的 `cd backend && .venv/bin/python -m app.adapters.seed_nessie`，於伺服器支援時完成全部 124 筆 baseline 實體；驗證唯一對應及父子歸屬，重跑證明零新增 POST，保留無憑證證據。

驗收：AC02／AC09／AC10／AC12、P02／P10、DF05／UF05。整合點：確認的遠端 ID 可供六項即時驗收使用；來源資料保持原樣。

## S2 — 查詢與歷史 API

結果：P01／P03–P06／P08／P09 具正確即時／錯誤／保存語意。相依：S1。範圍：`backend/app/api/admin_nessie.py`、`backend/app/core/store.py` 歷史部分及 `backend/tests/integration/test_admin_nessie.py`。

- [x] 先寫六項 ID 驗證、未知欄位、缺 key、重複按查詢仍新 GET，以及成功／空／401／404／500／逾時的失敗測試。
- [x] 撰寫 `test_history_write_failure_preserves_result`：上游 200／本文仍顯示，`history_id is None`、`write_status == 'failed'`、`write_label == 'failed to write'`，不存在部分歷史列。
- [x] 撰寫持久及刪除測試：重啟後本文相同；游標不重複 ID；未確認不刪除；清空只改 T-HISTORY；失效 ID 為 404 且不重用。
- [x] 實作本機 HTTP 契約及 Admin Host／Origin／JSON 邊界，沿用安全錯誤／request ID，所有 Store 操作限定伺服器選定 owner；拒絕額外欄位但不回傳提交原文，區分 JSON、文字與無本文。
- [x] 執行規劃的 `PYTHONPATH=backend backend/.venv/bin/python -m pytest backend/tests/integration/test_admin_nessie.py`，驗證 AC01–AC05／AC07–AC08／AC10／AC12 及 DF01／DF02／DF04。

整合：前端使用封裝；P06 為 S3 提供完整快照。資料庫錯誤不聲稱保存或刪除成功。

## S3 — 已保存快照比較

結果：P07 計算回應差異，不重新查詢或保存比較。相依：S2。範圍：`backend/app/services/nessie_console.py`、`backend/app/api/admin_nessie.py` 比較路由及 `backend/tests/unit/test_compare.py`。

- [x] 先寫 CMP001–CMP007 失敗斷言。CMP004／CMP005 須 `data_changed is False`；CMP006 回報 200→404；`/transaction_date` 改變須計入，`requested_at`／`duration_ms` 不計入。
- [x] 測試不存在與 null、查詢／資源／來源不相容、同一歷史 ID、紀錄不存在及成功清單 `_id` 缺漏／重複；斷言無上游請求及新歷史。
- [x] 實作 P07 的存在旗標、JSON Pointer 路徑、紀錄配對、狀態／連線比較與安全錯誤，保留原始本文。
- [x] 執行規劃的 `PYTHONPATH=backend backend/.venv/bin/python -m pytest backend/tests/unit/test_compare.py`，全部通過（AC05–AC06；DF03）。

整合：回傳 `{left,right,comparison}` 至 V-COMPARE，不另建比較資料表。

## S4 — React 畫面與本機瀏覽器流程

結果：V-QUERY／V-HISTORY／V-COMPARE／V-CONFIRM 實現 UF01–UF04。相依：S2、S3。範圍：`frontend/` 及瀏覽器測試；左側 WORKSPACE 加入 Admin，保留總覽／記憶流程與 Admin 工作階段狀態；工作版採 option 1。

- [x] 先寫六功能、條件 ID、表格／JSON 切換不新增請求、載入／空／錯誤狀態，以及資料仍可見且確切顯示 `failed to write` 的瀏覽器測試。
- [x] 加入歷史／重啟顯示、游標載入、相容雙筆選取、比較、timestamp 不同但本文相同，以及紀錄消失恢復流程。
- [x] 加入確認單筆／全部刪除及取消測試，斷言不重設匯入進度、不發上游寫入。
- [x] 所有來源字串以文字呈現；斷言 HTML 邊界資料不建立可執行 script，驗證鍵盤標籤、確認後焦點及窄視窗閱讀。
- [x] 依穩定 ID 實作 NAV-ADMIN 與畫面，沿用 typed API client，Admin 查詢可等 25 秒，原有呼叫維持 8 秒；正式版呼叫真正後端，不載入參考資料 JavaScript，不提供 P-STATE／P-CASE 預覽控制。
- [x] 執行規劃的 `npm --prefix frontend run build` 及 `node frontend/tests/admin-console.spec.mjs`；S4 必須以既有 Playwright 加入該瀏覽器指令，使用本機隔離上游／資料庫；驗證 Admin 進入／返回、導覽不重查，以及總覽／記憶／同意流程回歸。

驗收：AC01／AC03–AC08／AC10–AC12，全部前端／使用者流程控制。整合：沿用既有本機前端／API 開發程序，不公開託管。

## S5 — 實際驗證與收尾

結果：實作、設計及證據一致。相依：S4 及聚焦檢查通過。主代理整合，依實作風險做有界獨立審查；PR／發佈須另在範圍內。

- [x] 用已對應 baseline ID 驗證六項真正 GET，確認歷史跨重啟、完成匯入重跑仍零新增。憑證及資料保持私人，保存安全證據。
- [x] 執行 `python3 scripts/generate_synthetic_data.py --check`、必要的 `bash scripts/check.sh`（ruff、pytest、typecheck、Vitest、build）及新增瀏覽器測試，保留既有 CI／安全／獨立 PR 審查要求，不以合成測試替代線上證據。
- [x] 審查不明匯入恢復、憑證處理、保存失敗、失效選取、比較邊界及可及性；修正後先重跑受影響檢查，再做最終閘門。
- [x] 依實際結果更新雙語設計、Plan 勾選、README、帶時間 CHANGELOG 及真實 MISTAKE，不虛構 tag、發佈、部署或通過測試。

實作與真實驗證已完成，獨立 PR 整合審查已通過，真人隊友核准仍為合併關卡，詳見 Verification.zh-TW.md。

## 執行紀錄 — [2026/10/17 18:59]

S1 transport／匯入通過，真實 probe 確認八筆，完整 124 筆，重跑零 POST。S2／S3 API／歷史、遷移及七比較案例通過。S4 瀏覽器與響應式截圖通過。S5 完整本機 CI 與六真實 GET 通過；同一審查者的 PR 整合審查通過。詳見[驗證紀錄](Verification.zh-TW.md)。

- [2026/10/17 19:05] PR #4 獨立整合審查通過，四項發現均已修正並複驗。最後本機 CI 通過 47 後端測試，最後遠端更新等待 CI。未合併或部署。
