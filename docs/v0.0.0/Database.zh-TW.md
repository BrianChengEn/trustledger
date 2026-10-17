# 本機資料庫設計

狀態：新增 Admin schema 已實作，保留既有 SQLite 資料表；Q023 將僅支援 24 字元的歷史 schema 遷移為 24／36 字元，保留紀錄及 AUTOINCREMENT 最高序號。依據：[D008](ArchitectureDecisions.zh-TW.md)。對應：[English](Database.md)。

沿用 `Settings.database_path` 與 `Store`，透過 Python `sqlite3` 使用預設 `backend/data/trustledger-demo.db`。僅新增以下三個表，保留 `confirmations`、`memories` 及同意語意。沿用既有 `backend/data/` ignore 規則，憑證不進版本控制；目錄及檔案權限限制為本機使用者。每條連線啟用外鍵、使用參數化 SQL，寫入交易提交成功後才回報成功。歷史跨重啟保留、不自動過期。不另建資料庫服務或客戶／帳戶／交易資料表：Nessie 為權威來源，保存內容為回應快照。

## T-HISTORY — `query_history`

每列代表一次已成功提交歷史的上游查詢嘗試。無效前端請求不是上游嘗試；新增失敗不產生紀錄。

| 欄位 | SQLite 型別／限制 | 意義 |
| --- | --- | --- |
| `id` | INTEGER PRIMARY KEY AUTOINCREMENT | 穩定本機歷史 ID，清除後不重用 |
| `owner` | TEXT NOT NULL | 伺服器選定 demo user；所有歷史讀寫刪除條件均包含此欄 |
| `source` | TEXT NOT NULL；`nessie` 或 `synthetic` | 合成列只用於隔離測試資料庫 |
| `query_name` | TEXT NOT NULL；六項白名單 | 對應 API 欄位 `query` |
| `resource_id` | TEXT NULL；存在時長度 24 或 36 | 正規化客戶／帳戶 ID；清單為 null |
| `requested_at` | TEXT NOT NULL | UTC ISO 時間 |
| `http_status` | INTEGER NULL；存在時 100–599 | 真正上游狀態 |
| `duration_ms` | INTEGER NOT NULL；>= 0 | 實測毫秒耗時 |
| `body_format` | TEXT NOT NULL；`json`、`text`、`none` | 本文解碼方式 |
| `response_body` | TEXT NULL | 序列化 JSON 或純文字；JSON null 存為文字 `null` |
| `transport_error` | TEXT NULL | 安全 JSON `{type,message}` |

應用驗證查詢／ID 一致性及24 位十六進位或標準 UUID 格式。無 HTTP 狀態的列必須為 `body_format=none`、SQL NULL 本文及連線錯誤；有 HTTP 狀態時不帶連線錯誤。資料庫 CHECK 保護這些組合。不保存 key、含憑證 URL、不安全例外文字，也不建立持久 `write_status` 欄位：只有已提交列才是已保存，`write_status=failed` 屬於暫時回應狀態。

增加 `(owner,id)` 索引；以 `owner=? AND id < before_id ORDER BY id DESC LIMIT 51` 讀取，首頁省略游標條件。回傳 50 筆，只有存在第 51 筆時才以最後一筆已回傳紀錄 ID 作為 `next_cursor`，避免漏掉資料。P06 讀取單筆完整本文；P08／P09 只刪除此 owner 的歷史。AUTOINCREMENT 避免清除後瀏覽器舊選取指向新資料。

## T-SEED-RUN — `seed_runs`

每列代表特定 baseline 匯入一組憑證／環境的範圍。

| 欄位 | SQLite 型別／限制 | 意義 |
| --- | --- | --- |
| `id` | INTEGER PRIMARY KEY | 進度紀錄的父列 |
| `owner` | TEXT NOT NULL | 伺服器選定 demo user，與歷史範圍一致 |
| `dataset_sha256` | TEXT NOT NULL | Baseline 身分 |
| `api_base_url` | TEXT NOT NULL | 不含憑證的核准上游 |
| `credential_fingerprint` | TEXT NOT NULL | SHA-256 範圍指紋，不是 key 本身；僅後端使用 |
| `state` | TEXT NOT NULL；`active`、`complete`、`blocked` | 匯入狀態 |
| `created_at`, `updated_at` | TEXT NOT NULL | UTC 時間 |

`(owner, dataset_sha256, api_base_url, credential_fingerprint)` 唯一。不同範圍不代表可刪除或靜默重用舊遠端資源。前端歷史回應不包含這些欄位。

## T-SEED-RECORD — `seed_records`

每列追蹤一筆合成來源紀錄及其遠端建立結果。

| 欄位 | SQLite 型別／限制 | 意義 |
| --- | --- | --- |
| `run_id` | INTEGER NOT NULL；FK `seed_runs.id` | 匯入範圍 |
| `kind` | TEXT NOT NULL；`customer`、`account`、`deposit`、`withdrawal` | 資源類型 |
| `local_id` | TEXT NOT NULL；24 字元 | 原始合成 ID |
| `parent_kind`, `parent_local_id` | TEXT NULL | 帳戶的客戶父紀錄；交易的帳戶父紀錄 |
| `remote_id` | TEXT NULL | 已確認的伺服器 ID |
| `request_fingerprint` | TEXT NOT NULL | 真正允許建立本文的雜湊，不包含 API key |
| `state` | TEXT NOT NULL；`pending`、`confirmed`、`failed`、`uncertain` | 建立／核對狀態 |
| `safe_error` | TEXT NULL | 不含憑證的錯誤說明 |
| `updated_at` | TEXT NOT NULL | UTC 時間 |

主鍵為 `(run_id, kind, local_id)`；非 null 的 `(run_id, kind, remote_id)` 唯一。複合外鍵 `(run_id,parent_kind,parent_local_id)` 參照父進度列。只有客戶的兩個父欄位皆為 null。confirmed 列必須有遠端 ID；只有父列 confirmed 才能提交子紀錄。外鍵一致性不能替代這項應用前置條件。

新增上游請求前先提交 `pending`；驗證遠端 ID 與關聯後才記為 `confirmed`。回應或後續本機提交使結果不明時，保留 `pending`／`uncertain`，重試前先以遠端讀取核對。不以重設資料表解決不明匯入。

## 關聯與存取鏈

```text
seed_runs.id 1 ── N seed_records.run_id
                    └─ 客戶進度 1 ── N 帳戶進度
                                        └─ 1 ── N 存款／提款進度

query_history 與匯入進度彼此獨立。
```

| DataFlow 鏈 | 讀寫方式 |
| --- | --- |
| DF01 即時查詢 | P04 新增 T-HISTORY，包含已擷取回應或連線結果的失敗 |
| DF02 檢視 | P05 讀中繼資料；P06 從 T-HISTORY 讀本文及格式 |
| DF03 比較 | P06／P07 讀兩筆 T-HISTORY，不另建持久比較資料表 |
| DF04 刪除 | P08／P09 刪除指定／全部 owner 範圍 T-HISTORY；匯入表、confirmations 與 memories 保持完整 |
| DF05 匯入 | P10 讀寫 T-SEED-RUN 與 T-SEED-RECORD，轉換父 ID 並驗證遠端結果 |

API 封裝以成功提交的新增結果產生 `history_id` 及保存狀態。資料庫無法使用時依 Q018 回傳擷取結果及 `failed to write`。既有 JSON 測試資料的封裝不等於應用資料庫結構；測試轉接將 H003 等案例標籤對應到暫存資料庫 ID。

驗證須涵蓋 rollback、跨重啟、來源身分、不存在／null 本文解碼、刪除後游標、父子限制，以及清除歷史仍保留匯入對應。另見[後端](Backend.zh-TW.md)、[資料流](DataFlow.zh-TW.md)及[計畫](Plan.zh-TW.md)。
