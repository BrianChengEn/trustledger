# 後端設計

狀態：已依 Q020／D008 與 Q021 契約同意實作；Q023 支援標準 UUID 與 24 位十六進位 ID，Q024 採實測的 opening-balance sandbox 行為。依據：[D008 與 AC01–AC12](ArchitectureDecisions.zh-TW.md)。對應：[English](Backend.md)。

## 邊界與檔案

擴充既有 FastAPI，不建立第二個服務。`backend/app/api/admin_nessie.py` 負責新路由；`backend/app/schemas/admin_nessie.py` 沿用既有 strict model 模式實作 P01。`backend/app/services/nessie_console.py` 負責 P03／P07；`backend/app/adapters/nessie.py` 加入 P02，保留既有交易擴充點。擴充 `backend/app/core/store.py` 的既有 `Store`，負責 P04–P06／P08–P09 與匯入進度；`backend/app/adapters/seed_nessie.py` 負責 P10。Integrator 負責路由／schema／service／store，Data owner 負責 adapter／seed。不建立通用代理或新帳本。

`NESSIE_API_KEY` 僅由 Python 讀取。固定上游為已取得的[官方規格](https://prod.nessieisreal.com/nessie-openapi-spec.yaml)所列 `https://prod-api.nessieisreal.com`；僅於上游呼叫邊界附加 `key` 查詢參數，不記錄或回傳含憑證 URL。服務綁定 `127.0.0.1`，只接受本機 Host 與確切的本機應用 Origin。JSON 變更請求須有允許的 Origin 及 `application/json`，不開放帶憑證的萬用來源存取。沿用 Vite `/api` proxy 與 Settings 的 secret 欄位。於 `create_app` 註冊新路由，保留 request-ID、安全錯誤、origin 與 no-store middleware；針對 Admin 補上 loopback Host／Origin／JSON 驗證，維持既有端點行為。沿用 `frontend/src/api.ts`：目前 8 秒逾時短於 P02，因此加入每次呼叫的逾時設定，僅 Admin 查詢允許 25 秒（15 秒上游等待，加上 SQLite 提交與回傳餘裕）。其他呼叫維持既有行為。沿用目前兩個本機開發程序；靜態託管不在本次範圍。

## 查詢白名單

| 查詢名稱 | 必要資源 ID | Nessie GET 路徑 |
| --- | --- | --- |
| `customers.list` | 無 | `/customers` |
| `accounts.list` | 無 | `/accounts` |
| `accounts.get` | 帳戶 | `/accounts/{id}` |
| `accounts.by_customer` | 客戶 | `/customers/{id}/accounts` |
| `deposits.by_account` | 帳戶 | `/accounts/{id}/deposits` |
| `withdrawals.by_account` | 帳戶 | `/accounts/{id}/withdrawals` |

`QueryRequest = {query, resource_id?}`。拒絕未知欄位及查詢名稱。ID 去除前後空白，接受 24 位十六進位或標準 UUID，皆轉為小寫。四項查詢須提供 ID，兩項清單查詢拒絕非空 ID。驗證失敗不呼叫上游、不建立執行歷史。前端不提供 key 輸入。

## 本機 HTTP 契約

| 方法及路徑 | 輸入 | 輸出／本機狀態 |
| --- | --- | --- |
| `POST /api/v1/admin/nessie/query` | `QueryRequest` | 擷取的執行封裝，HTTP 200；輸入錯誤 422；設定缺漏 503 |
| `GET /api/v1/admin/nessie/history?before_id=…` | 可選正整數游標 | `{items, next_cursor}`；ID 由新到舊，最多 50 筆中繼資料 |
| `GET /api/v1/admin/nessie/history/{id}` | 正整數歷史 ID | 完整已保存執行，200；不存在 404 |
| `POST /api/v1/admin/nessie/compare` | `{left_id, right_id}`，兩個相異正整數 | `{left, right, comparison}`，200；不存在 404；不相容或無法配對清單 409 |
| `DELETE /api/v1/admin/nessie/history/{id}` | JSON `{confirm:true}` | `{deleted:1}`，200；不存在 404；未確認 422 |
| `DELETE /api/v1/admin/nessie/history` | JSON `{confirm:true}` | `{deleted:count}`，200；未確認 422 |

Origin／Host 拒絕為 403。歷史讀取、比較讀取或刪除失敗回傳安全的本機錯誤 500。沿用既有錯誤格式 `{error:{code,message,request_id}}` 及 `X-Request-ID`，不包含 traceback、SQL、環境值或無效請求原文。即使框架預設可能回傳提交欄位，無效請求也必須改為安全的 422。設定錯誤不嘗試呼叫 Nessie。

執行封裝欄位如下：

| 欄位 | 型別／意義 |
| --- | --- |
| `source` | 執行期間為 `nessie`；隔離的測試資料才可為 `synthetic` |
| `query`, `resource_id` | 已驗證的查詢身分；清單 ID 可為 null |
| `requested_at`, `duration_ms` | UTC ISO 時間；以單調時鐘計算的非負毫秒耗時 |
| `http_status` | 真正上游狀態整數；沒有 HTTP 回應時為 null |
| `body_format` | `json`、`text` 或 `none` |
| `response_body` | 已處理憑證的解析 JSON、純文字或 null；JSON null 以 `body_format=json` 區分 |
| `transport_error` | null，或逾時／連線失敗的安全 `{type,message}` |
| `history_id` | 已保存的正整數 ID，或 null |
| `write_status`, `write_label` | `saved` 與 null，或 `failed` 與確切的 `failed to write` |

本機 HTTP 200 表示查詢嘗試已結束，不代表上游成功。前端明確以 **Nessie HTTP 狀態** 顯示 `http_status`，非 2xx 視為錯誤。連線失敗為 `http_status=null`、`body_format=none`，不虛構本文；非 JSON HTTP 本文保留為文字。不自動重試；使用者再次按查詢代表新的執行。

## 偽碼與函式邊界

| ID | 預定函式 | 行為 |
| --- | --- | --- |
| P01 | `QueryRequest.validate_id() -> QueryRequest` | 驗證六項 enum、額外欄位及 ID 規則。 |
| P02 | `NessieClient.query(query, resource_id) -> UpstreamResult` | 僅發出一次白名單 GET，15 秒逾時；擷取狀態／本文或安全連線錯誤，所有字串及錯誤路徑皆處理憑證。 |
| P03 | `nessie_console.execute_query(payload) -> ExecutionEnvelope` | P01；缺 key 則拒絕；P02；嘗試 P04。提交成功才回傳保存 ID；儲存失敗則回傳相同擷取結果、null ID 及 `failed to write`。 |
| P04 | `Store.append_history(owner,result) -> int` | 參數化 INSERT 及 commit；成功後才回傳 ID，失敗 rollback。 |
| P05 | `Store.list_history(owner,before_id=None) -> HistoryPage` | 依 ID 遞減讀取接下來 50 筆，清單省略回應本文。 |
| P06 | `Store.get_history(owner,id) -> SavedExecution` | 讀取單筆並依格式解碼本文；明確回報不存在。 |
| P07 | `nessie_console.compare_history(owner,left_id,right_id) -> ComparisonResult` | P06 兩次，驗證相容性，再依下方規則計算差異。 |
| P08 | `Store.delete_history(owner,id) -> int` | 必須確認，刪除單筆歷史，commit 或 rollback。 |
| P09 | `Store.delete_history(owner) -> int` | 必須確認，只刪除 `query_history`，commit 或 rollback。 |
| P10 | `seed_nessie.seed_baseline(probe=False) -> SeedSummary` | 驗證 baseline 與範圍、延續已驗證對應、先建立父再建立子、核對不明結果並回報進度。 |

所有保存／讀取／刪除／比較使用伺服器選定的 `Settings.demo_user_id`，呼叫端不能指定 owner。Admin 快照及匯入對應與 confirmations／memories 分開，也不進入 AI service。TrustLedger dashboard 繼續載入 synthetic adapter。Admin 是本機導覽名稱，不代表正式環境身分驗證。

## 比較契約

要求相同 `query`、正規化 `resource_id` 及來源，保留原始本文。成功的頂層資源清單必須有唯一 `_id`；缺漏或重複時回傳 409，不靜默覆寫紀錄。其他 JSON 物件逐鍵遞迴比較，巢狀非資源陣列依位置比較，純量／文字依值比較。以 `before_present`、`after_present` 區分不存在欄位與明確 null。儲存及比較前先處理憑證。

`comparison = {data_changed, changes, status_change, transport_change}`。單項差異為 `{kind, record_id?, path, before_present, after_present, before, after}`；`kind` 為 `added`、`removed` 或 `changed`，`path` 採 JSON Pointer。回應狀態與連線錯誤分開比較。查詢時間、耗時及本機歷史 ID 顯示於標頭，不放入 `changes`。`/transaction_date` 等業務欄位仍比較。相同資料只有排序或查詢時間不同時，若回應結果也相同，`data_changed=false`。

## Baseline 設定協定

P10 是本機 CLI，不是執行期間 HTTP 端點。來源僅限 `datasets/nessie/baseline.json`；寫入前驗證校驗值、關聯與整數值。每次 POST 前，先持久保存批次身分與待執行項目。進度綁定上游 base URL 及不可逆 key 指紋；key、資料集或環境變更時先核對，不靜默重用對應。

以 `CustomerCreate` 欄位建立客戶；於已對應客戶下使用期初餘額建立帳戶，再於已對應帳戶下建立存款／提款。移除本機 `_id`、封裝欄位與自造帳號。於既有文字欄位放入依來源 ID 及資料集身分產生的確定性合成標記，供核對使用；記錄真正送出本文的指紋。不將合成 ID 當遠端 ID。

首次探測先建立一個客戶、一個帳戶及其六筆交易，讀回驗證後才繼續大量建立。驗證實際伺服器正規化及餘額行為，本機資料約定不代表伺服器財務語意。建立成功回應可能沒有 ID，尤其目前規格將提款回應描述為文字；此時讀取已對應父紀錄的清單，以合成標記及本文核對，只有唯一確認結果才可記下遠端 ID。

逾時、5xx、無法解析的回覆，或遠端建立後本機失敗，都可能留下不明寫入。先核對；找不到或有歧義時標示批次 blocked 並停止。不盲目重送 POST，也不刪遠端既有資料。確認遠端身分及父子關聯後，才略過已完成紀錄。正常完成後重跑不發出 POST。不提供自動遠端清空／重設指令。

## 前端動作對應

| 控制項／動作 | 本機操作 | 函式 |
| --- | --- | --- |
| NAV-ADMIN | 開啟保留的 Admin 畫面，首次為 V-QUERY | 本機導覽，不呼叫上游 |
| NAV-Q、NAV-H、NAV-C | 導覽；開啟歷史時讀第一頁 | NAV-H 為 P05，其餘本機 |
| H-TABLE、H-JSON | 切換已保存回應呈現 | 無請求 |
| Q-FUNC、Q-ID | 本機表單狀態及驗證 | P01 規則 |
| Q-RUN | `POST /api/v1/admin/nessie/query` | P01–P04 |
| Q-TABLE、Q-JSON | 本機呈現切換 | 無請求 |
| H-MORE | 帶游標的 `GET /api/v1/admin/nessie/history` | P05 |
| H-VIEW-{id} | `GET /api/v1/admin/nessie/history/{id}` | P06 |
| H-L-{id}、H-R-{id} | 選擇相異且相容的 ID | 本機選擇 |
| H-COMPARE | `POST /api/v1/admin/nessie/compare`，開啟 V-COMPARE | P07 |
| H-DELETE-{id}、D-CONFIRM | 確認後刪除單筆 | P08 |
| H-CLEAR、D-CONFIRM | 確認後清除歷史 | P09 |
| D-CANCEL、C-BACK | 取消或返回 | 無請求 |
| C-TABLE、C-JSON | 切換兩份快照呈現 | 無請求 |
| 設定指令 | 獨立匯入 baseline | P10 |

另見[前端](Frontend.zh-TW.md)、[資料流](DataFlow.zh-TW.md)、[資料庫](Database.zh-TW.md)與[計畫](Plan.zh-TW.md)。新增契約已納入 OpenAPI；驗證見 [Verification](Verification.zh-TW.md)。

Q024 實測：建立這批交易後，Nessie 餘額仍為 opening balance；probe 與完整匯入前皆重驗八筆資料及該餘額，不改寫既有遠端餘額。離線 fixture 的計算餘額保留為測試慣例。
