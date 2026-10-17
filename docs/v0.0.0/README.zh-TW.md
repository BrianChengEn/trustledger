# Nessie 開發者測試台文件

TrustLedger Admin 測試台協助一位本機開發者執行六項 Nessie 唯讀查詢、檢視表格／JSON、保存歷史並比較兩筆快照。入口為 **左側欄 → WORKSPACE → Admin**，查詢、歷史與比較位於內部分頁。原始[構想](../../idea.md)由使用者撰寫且保持唯讀。對應：[English](README.md)。

Q020 已確認整合既有 TrustLedger，沿用 React／TypeScript 外框、FastAPI、typed API client、Settings 與 SQLite Store。既有團隊所有權、合成展示、同意後才寫入記憶、CI 及契約審查保持有效。Admin API 於 `/api/v1/admin/nessie` 下以新增方式實作，已依 Q021 同意納入 OpenAPI。

## 目前狀態

v0.0.0 已實作 Admin、歷史與匯入資料表、baseline 匯入器及已存快照比較。Q001–Q024 已釐清；真實 sandbox 確認 124 筆，六種查詢均回 200，匯入重跑零次 POST。[驗證紀錄](Verification.zh-TW.md) 分列本機、瀏覽器、真實與 PR 證據。

## 有效版本文件

| 文件 | 英文 | 繁體中文 |
| --- | --- | --- |
| 需求與決策 | [ArchitectureDecisions](ArchitectureDecisions.md) | [決策紀錄](ArchitectureDecisions.zh-TW.md) |
| 畫面與控制項 | [Frontend](Frontend.md) | [前端](Frontend.zh-TW.md) |
| API 與偽碼 | [Backend](Backend.md) | [後端](Backend.zh-TW.md) |
| 資料移動 | [DataFlow](DataFlow.md) | [資料流](DataFlow.zh-TW.md) |
| 使用者轉換 | [UserFlow](UserFlow.md) | [使用者流程](UserFlow.zh-TW.md) |
| 持久儲存 | [Database](Database.md) | [資料庫](Database.zh-TW.md) |
| 初版工作切片 | [Plan](Plan.md) | [計畫](Plan.zh-TW.md) |
| 驗證 | [Verification](Verification.md) | [驗證紀錄](Verification.zh-TW.md) |

## 視覺參考

| 畫面 | 選定工作版 | 替代版 |
| --- | --- | --- |
| 查詢 | [Option 1](html/view-query/option-1.html) | [Option 2](html/view-query/option-2.html) |
| 歷史 | [Option 1](html/view-history/option-1.html) | [Option 2](html/view-history/option-2.html) |
| 比較 | [Option 1](html/view-compare/option-1.html) | [Option 2](html/view-compare/option-2.html) |

可直接於本機開啟 HTML，資產均在本機，內容明確標為合成。這些頁面示範控制項及狀態，不代表網路整合或真正持久保存。主代理選擇 option 1 作為工作版型。

## 現有指令

在專案根目錄使用 Python 3，無須額外相依套件：

```sh
python3 scripts/generate_synthetic_data.py --check
python3 scripts/generate_synthetic_data.py
```

第一項唯讀驗證既有資料；第二項重新產生並覆寫七個 JSON。[資料說明](../../datasets/nessie/README.zh-TW.md)記錄五種情境、32 筆模擬執行與七組比較案例。資料不包含真正 key 或個人紀錄。

沿用[啟動指令](../../README.md)與[團隊設定](../../TEAM-SETUP-60MIN.md)。`bash scripts/check.sh` 已包含隔離瀏覽器測試；保留鎖定套件、`Settings.database_path`、確認與同意後的 local-fallback 記憶。`NESSIE_API_KEY` 只放被忽略的 `backend/.env` 或執行環境 secrets。Admin 接受 24 位十六進位與標準 UUID；Q024 實測建立獨立交易不改變 opening balance，離線計算餘額保留為 fixture 慣例。

```sh
bash scripts/check.sh
node frontend/tests/admin-console.spec.mjs
cd backend
.venv/bin/python -m app.adapters.seed_nessie --probe
.venv/bin/python -m app.adapters.seed_nessie
```

seed 指令會建立合成 sandbox 資源並保存進度，完整匯入前先跑 probe；不確定結果會停止，不盲目重試。歷史刪除不影響匯入進度或遠端資料。瀏覽器測試使用隔離合成上游／資料庫，不呼叫供應商。

## 省略元件與紀錄

不需要 MCP server、自然語言解析、公開託管、獨立 Swagger 前端、遠端資料庫服務、重複客戶／帳戶帳本、自動清理歷史或執行期間匯入 UI。未要求 release tag 或部署；PR 狀態記於 Verification。[CHANGELOG](../CHANGELOG.zh-TW.md)記錄實際變更，[MISTAKE](../MISTAKE.zh-TW.md)記錄真實流程修正。專案操作指引見 [AGENTS.md](../../AGENTS.zh-TW.md)。
