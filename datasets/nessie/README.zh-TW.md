# Nessie 合成資料集

這些可重現的 JSON 測試資料全部為虛構內容，用於六項已確認的唯讀查詢，以及表格、JSON 檢視、歷史與比較的本機測試。它們是本機 fixture 快照，不是擷取的 API 回應或模擬服務；已同意的 baseline CLI 已匯入轉換後的合成紀錄，其他資料集仍離線。歷史中的耗時與時間戳記均為模擬值。

對應文件：[English](README.md)。

## 檔案

| 資料集 | 客戶 | 帳戶 | 存款 | 提款 | 用途 |
| --- | ---: | ---: | ---: | ---: | --- |
| [baseline.json](baseline.json) | 10 | 18 | 48 | 48 | 正常關聯、多種帳戶類型與交易狀態。客戶 `c0000000000000000000000a` 沒有帳戶；ID 結尾為 `11` 與 `12` 的帳戶沒有交易紀錄。 |
| [changed.json](changed.json) | 10 | 17 | 51 | 52 | 較晚的合成狀態，包含新增、移除、欄位變更與餘額更新。 |
| [empty.json](empty.json) | 0 | 0 | 0 | 0 | 成功回傳空的客戶與帳戶清單。 |
| [boundary.json](boundary.json) | 3 | 4 | 2 | 1 | 零餘額與零金額、大整數餘額、Unicode、長字串、引號、換行與類似 HTML 的文字。 |
| [volume.json](volume.json) | 50 | 100 | 300 | 300 | 較多筆數的本機資料，供測試表格呈現；不是效能基準測試。 |

[history.json](history.json) 包含 32 筆模擬執行與七組比較案例，涵蓋成功空結果、無效 ID、未授權、帳戶不存在、伺服器錯誤及連線逾時。錯誤本文為合成範例，不代表伺服器確切訊息或所有可能狀態碼。逾時沒有上游 HTTP 狀態碼或回應本文。

[manifest.json](manifest.json) 列出筆數、來源依據，以及六項查詢各一筆對應的歷史範例。

## 快照結構與查詢

每個快照包含 `synthetic: true`、`dataset_id`、`customers`、`accounts`、`deposits_by_account`、`withdrawals_by_account` 與 `opening_balances`。這是本機資料集的封裝，不是上游 API 的回應結構。交易歸屬使用帳戶 ID 作為字典鍵；不在交易本文中新增未經定義的 `account_id` 欄位。

| GET 查詢 | 回應本文所使用的本機資料 |
| --- | --- |
| `/customers` | `customers` |
| `/accounts` | `accounts` |
| `/accounts/{id}` | `_id` 符合輸入 ID 的帳戶 |
| `/customers/{id}/accounts` | `customer_id` 符合輸入 ID 的帳戶清單 |
| `/accounts/{id}/deposits` | `deposits_by_account[id]` |
| `/accounts/{id}/withdrawals` | `withdrawals_by_account[id]` |

客戶、帳戶與存款欄位依循需求研究時取得的[官方 OpenAPI 1.0.0](https://prod.nessieisreal.com/nessie-openapi-spec.yaml)。規格僅將提款清單元素描述為一般物件；其合成欄位依循[官方文件](https://prod.nessieisreal.com/docs)的資源範例。Context7 未提供相符的銀行 API 文件。

本資料集約定只有 `completed` 交易影響餘額；每個帳戶的 `balance = opening_balances[id] + 已完成存款 - 已完成提款`。期初餘額是本機記帳中繼資料。金額採取得規格中的整數表示法；資料集不定義幣別或換算規則。零金額交易與虛構地址等屬於邊界測試資料，並非已驗證可供線上建立紀錄的內容。

姓名與地址刻意使用合成內容。24 字元十六進位 ID 與 16 位數帳號字串均為虛構測試值，並非使用者 Nessie 帳戶中有效的資源參照。明確執行的 baseline CLI 會對應伺服器 ID 並移除回應專用欄位，這些檔案不是可直接送出的 POST 本文。Q024 的真實帳戶保留 opening balance，fixture 計算餘額仍屬離線慣例。

## 歷史與比較

每筆歷史皆有 `source: synthetic`、查詢功能與資源 ID、不含憑證的方法與路徑、模擬時間與耗時、可選 HTTP 狀態碼、回應本文，以及可選的連線錯誤。`manifest.json` 將六項基準查詢對應至 `H001` 到 `H006`。

比較案例參照同一查詢與資源 ID 的兩筆歷史：

- `CMP001`：帳戶欄位變更。
- `CMP002`：存款新增、移除與修改。
- `CMP003`：客戶新增、移除與修改，包含巢狀地址欄位。
- `CMP004`：帳戶資料相同，排列順序不同。
- `CMP005`：回應本文完全相同。
- `CMP006`：帳戶於較早狀態存在、較晚狀態不存在，HTTP 狀態由 200 改為 404。
- `CMP007`：提款新增、欄位修改與交易狀態變更。

已實作的比較測試使用這些預期值，Admin 前端將 HTML 類字串以純文字呈現。[驗證紀錄](../../docs/v0.0.0/Verification.zh-TW.md) 分列 fixture、瀏覽器與真實證據。

## 重新產生與驗證

在專案根目錄使用 Python 3 執行，不需第三方套件：

```sh
python3 scripts/generate_synthetic_data.py
python3 scripts/generate_synthetic_data.py --check
```

重新產生會覆寫七個自動生成的 JSON 檔案，不讀取憑證、不發出網路請求。檢查模式只讀取既有檔案，不寫入，並驗證規格相關欄位、ID 唯一性、關聯、整數金額、餘額一致性、清單筆數、查詢覆蓋、歷史中繼資料、比較預期與輸出可重現性。

本機檢查通過不代表已驗證線上 API 認證、伺服器行為、UI 行為或遠端資料可用性。既有的每次應用程式查詢都呼叫 Nessie 需求仍適用；這些資料集不會默默替代該行為。
