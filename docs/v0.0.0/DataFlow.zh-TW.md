# 資料流

狀態：已實作；[驗證紀錄](Verification.zh-TW.md) 分列隔離與真實證據。對應：[English](DataFlow.md)。契約：[後端 P01–P10](Backend.zh-TW.md)、[資料表](Database.zh-TW.md)、[驗收條件](ArchitectureDecisions.zh-TW.md)。

## DF01 — 即時查詢與獨立保存

```text
Q-FUNC + 可選 Q-ID + Q-RUN
  → POST /api/v1/admin/nessie/query → P01 驗證
  → P02 使用後端 key 呼叫白名單 Nessie GET
  → 擷取真正狀態／本文或連線錯誤，移除憑證
  → P04 INSERT query_history 並 COMMIT
  → P03 回應封裝 → Q-RESULT 表格／JSON 與中繼資料
```

DF01 位於 TrustLedger Admin。API 沿用伺服器選定 demo owner 與 Store，不改變 dashboard 的 synthetic adapter，也不將原始快照送入 AI／memory。

輸入是六項查詢名稱及必要的正規化資源 ID。上游 JSON 保持結構，非 JSON 以安全文字呈現。擷取結果加入 UTC 時間與單調時鐘耗時，不虛構上游欄位。歷史新增成功後，T-HISTORY 保存 `query_name`、`resource_id`、`source`、時間、狀態、耗時、本文格式／本文及連線錯誤，再產生 `history_id`。

前端於保存嘗試後取得同一份安全擷取結果，不必為顯示即時結果再讀 SQLite。本機新增失敗則 rollback、回傳 null `history_id`，並於保留回應的同時顯示 `failed to write`。此例外路徑實現 Q018，避免丟失成功 API 結果。上游非 2xx 顯示為 API 錯誤，仍可保存歷史。沒有 HTTP 回應時狀態／本文為 null，附連線錯誤。無效輸入或設定缺漏在上游步驟前停止，不記作已執行上游查詢。

預期輸出為有來源標示的新結果、正確 API 結果、獨立儲存狀態且無憑證。以成功、空成功、401／404／500、逾時、無效輸入及注入的資料庫寫入失敗，驗證 AC01–AC04、AC08、AC10、AC12。

## DF02 — 歷史清單與單筆檢視

```text
開啟 V-HISTORY／H-MORE → GET /api/v1/admin/nessie/history → P05
  → 讀 T-HISTORY 中繼資料（ID 遞減游標）→ 歷史列
H-VIEW-{id} → GET /api/v1/admin/nessie/history/{id} → P06
  → 讀本文格式、本文及中繼資料 → H-DETAIL
```

僅在保存格式為 JSON 時解析，保留 JSON null 與不存在本文的差異。顯示原始查詢時間及來源，不呼叫 API、不新增執行歷史、不覆寫舊資料。已刪除 ID 回傳 404 並更新清單；資料庫失敗顯示讀取錯誤，保留既有狀態。驗證跨重啟、游標分頁、無上游請求的舊紀錄檢視及 AC04–AC05。

## DF03 — 快照比較

```text
H-L-{id} + H-R-{id} + H-COMPARE → POST /api/v1/admin/nessie/compare → P07
  → P06 讀兩筆 T-HISTORY
  → 驗證查詢／資源／來源相同
  → 成功清單依唯一 _id 配對，比較本文及回應結果
  → 差異與左右原始快照 → V-COMPARE
```

輸入 ID 指向兩筆已保存執行，不代表新 Nessie 請求。轉換產生帶存在旗標的 JSON Pointer 差異、紀錄新增／移除，以及獨立狀態／連線變更。查詢時間、耗時與歷史 ID 保持可見，但不列入資料差異。原始本文順序及業務日期保留。比較不寫入持久資料。

紀錄不存在回傳 404；選取不相容或成功清單 ID 有歧義回傳 409。無變更須有明確狀態。驗證 CMP001–CMP007、不存在與 null、`transaction_date` 變更及 AC05–AC06。CMP004 僅排序不同不產生資料差異；CMP005 即使查詢時間與耗時不同也不產生資料差異。

## DF04 — 手動刪除歷史

```text
H-DELETE-{id}／H-CLEAR → 確認狀態
  → D-CANCEL：無請求，直接返回
  → D-CONFIRM：confirm=true 的本機 DELETE → P08／P09
  → 交易內刪除 T-HISTORY → commit → 更新清單／選取
```

API 另行驗證確認，不只依賴瀏覽器。資料庫失敗 rollback 並回報錯誤；成功確認前保留畫面上的紀錄。紀錄刪除後清除失效選取及比較內容。T-SEED-RUN、T-SEED-RECORD、資料集檔案及所有遠端 Nessie 資源保持完整。驗證取消無請求、確認只刪指定範圍、過期 ID 回傳 404 及 AC07。

## DF05 — Baseline 設定與續跑

```text
baseline.json + 後端環境 key → P10 驗證及批次身分
  → 讀寫 seed_runs、seed_records（POST 前提交 pending）
  → CustomerCreate → 已確認客戶遠端 ID
  → AccountCreate 使用客戶對應及期初餘額 → 已確認帳戶 ID
  → Deposit／Withdrawal 使用帳戶對應 → 已確認交易 ID
  → 上游讀回驗證 → 保存 confirmed 對應及完成狀態
  → 提供安全的遠端 ID 範例，供開發者填入查詢表單
```

建立本文移除僅回應／本機欄位；於允許文字欄位加入確定性合成標記，並對真正本文計算指紋。來源檔案保持原樣。T-SEED-RECORD 的父對應提供遠端 ID，本機合成 ID 不進入遠端資源路徑。先探測一個客戶／帳戶及六筆交易，才繼續大量建立。驗證真正伺服器行為後才宣稱線上餘額正確；使用來源期初餘額避免一開始重複計入已完成交易。

回覆缺少 ID 或寫入結果不明時，以合成標記及本文核對父紀錄清單；只有唯一結果才能 confirmed，找不到或不唯一則停止後續寫入。無法持久保存進度時，在新的 POST 前停止。重跑讀取並驗證既有對應，跳過已確認項目，只補真正缺漏。不刪除遠端既有資料，不靜默重設進度。驗證 AC09、伺服器 ID 關聯、伺服器接受時全部 124 筆 baseline 實體，以及完成後重跑零新增 POST。合成資料本身不能證明線上行為。

## DF06 — 離線資料與證據

`generate_synthetic_data.py` 將確定性虛構輸入轉為五組本機快照、32 筆合成執行、七組比較預期與清單。自我檢查讀取 JSON，驗證 ID、歸屬、整數、餘額約定、筆數及比較事實。暫存測試資料庫可透過轉接使用 `source=synthetic`；產品啟動不自動把假執行載入線上歷史。本機資料模擬失敗，不改動真正 Nessie。以 `python3 scripts/generate_synthetic_data.py --check` 驗證；線上探測與資料集測試證據分開記錄（AC11–AC12）。

Q024：真實帳戶保留 opening balance，交易獨立建立。完整寫入前重驗 probe 八筆與餘額；離線計算餘額不當作真實餘額預期。
