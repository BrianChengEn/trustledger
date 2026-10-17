# 前端設計

狀態：TrustLedger Admin 執行功能已實作，以這些參考頁為工作基準。依據：[Q020／D008](ArchitectureDecisions.zh-TW.md)。對應：[English](Frontend.md)。

沿用既有 TrustLedger React／TypeScript 外框。左側 WORKSPACE 的 Confirmed memory 下方加入 NAV-ADMIN，名稱固定為 `Admin`。保留既有總覽及同意後才寫入記憶的畫面。Admin 內部以 NAV-Q（查詢）、NAV-H（歷史）、NAV-C（比較）分頁切換。本次單人本機範圍不另建應用、服務、router 相依套件或登入頁；Admin 是導覽名稱，不代表身分驗證。

```text
TrustLedger 左側欄           既有主內容區
WORKSPACE                    Admin · Nessie 開發者測試台
  Overview & transactions    ┌ NAV-Q ─ NAV-H ─ NAV-C ────────┐
  Confirmed memory           │ V-QUERY / V-HISTORY /         │
  NAV-ADMIN [Admin] ◀         │ V-COMPARE                     │
                             └──────────────────────────────┘
```

NAV-ADMIN 首次開啟 V-QUERY，不呼叫 Nessie；返回時恢復本次工作階段的內部分頁、表單、結果及歷史選取。離開至其他 WORKSPACE 入口時保留 Admin 狀態，只有 Q-RUN 發起新的上游請求。進行中的請求保有原身分，不因導覽而自動重送。呈現狀態由 React 管理，保存與比較由後端負責。Admin 內容使用繁體中文，固定的 `Admin`、`failed to write` 與技術欄位除外；既有外框保留原語言。

於 `frontend/src/main.tsx` 擴充既有 tab 入口，以 `frontend/src/Admin.tsx` 放置測試台，沿用 `api.ts` typed client 及 `styles.css`。Client 已加 `/api/v1`，因此傳入 `/admin/nessie/...`，避免重複前綴。Admin 查詢使用 Backend 所列 25 秒逾時。Provider 資料一律以文字呈現，不送入 AI 或 confirmed-memory 流程。

## V-QUERY — 查詢及結果

選定參考：[option 1](html/view-query/option-1.html)。替代：[option 2](html/view-query/option-2.html)。

```text
┌ NAV-Q：查詢 ─ NAV-H：歷史 ─ NAV-C：比較 ──────────┐
│ Q-FUNC [六項功能選單                             ▼] │
│ Q-ID   [需要時輸入客戶／帳戶 ID                   ] │
│ Q-RUN  [查詢]                                      │
├ Nessie HTTP 狀態 · UTC 時間 · 耗時 · Q-SAVE ──────┤
│ Q-TABLE [表格]    Q-JSON [JSON]                     │
│ Q-RESULT                                           │
│ ┌ _id ── 欄位 ── 欄位 ── … ─────────────────────┐ │
│ │ 結構化回應清單，或單一物件一列                  │ │
│ └────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────┘
```

| ID | 互動／狀態 |
| --- | --- |
| Q-FUNC | 使用 Backend 六項查詢值；切換時更新必要 ID 標籤，清除失效驗證。 |
| Q-ID | 有標籤的客戶／帳戶文字欄位；清單查詢隱藏並停用，驗證與 P01 相同。 |
| Q-RUN | 送出一次查詢；等待期間停用，避免誤送重複請求。 |
| Q-TABLE、Q-JSON | 帶 pressed 狀態的原生切換按鈕，不重新抓資料。 |
| Q-RESULT | 有名稱的結果區域；載入使用 polite 即時狀態，錯誤使用 alert。 |
| Q-SAVE | 保存成功的歷史 ID，或確切文字 `failed to write`；與 Nessie 狀態獨立。 |

必要狀態：初始提示、無效／缺漏 ID、載入、成功物件、成功清單、成功空結果、非 2xx、沒有 HTTP 狀態的連線錯誤、後端缺 key、後端無法連線，以及已取得資料但保存失敗。寫入失敗仍可檢視結果。新請求等待期間不可將舊結果標為本次資料；若保留舊結果，須附其原始時間，直到新結果抵達。

表格顯示回應現有欄位，`_id` 優先；巢狀值為安全的精簡 JSON，單一物件顯示一列。純量、文字及錯誤使用可讀文字／JSON 區域，不偽裝成銀行資料列。JSON 保留所有處理過憑證的欄位與原始清單順序。金額按原始數字呈現，不自行指定幣別或轉換整數單位。

## V-HISTORY — 持久歷史與單筆內容

選定參考：[option 1](html/view-history/option-1.html)。替代：[option 2](html/view-history/option-2.html)。

```text
┌ NAV-Q ─ NAV-H ─ NAV-C ─────────────────────────────┐
│ [H-COMPARE：比較選取] [H-CLEAR：清空全部]            │
│ 左側  右側   時間 · 查詢 · 資源 · 狀態              │
│ (L)   (R)    …                    [檢視] [刪除]     │
│ H-L-{id} H-R-{id}   H-VIEW-{id} H-DELETE-{id}       │
│ [H-MORE：載入更多]                                 │
├ H-DETAIL：原始時間 · 來源 · 回應狀態 ──────────────┤
│ H-TABLE [表格] H-JSON [JSON] · 保存的回應本文        │
└────────────────────────────────────────────────────┘
```

| ID | 互動／狀態 |
| --- | --- |
| H-L-{id}、H-R-{id} | 兩組有標籤的 radio；跨游標載入保留選取。須為不同 ID 且相同查詢／資源／來源。 |
| H-COMPARE | 選取相容才啟用；呼叫 P07 後顯示 V-COMPARE。不相容在本機說明。 |
| H-VIEW-{id} | 讀取單筆保存本文至 H-DETAIL，不發新 Nessie 請求。 |
| H-TABLE、H-JSON | 重用結果呈現，不發請求。 |
| H-DELETE-{id} | 開啟該筆 V-CONFIRM。 |
| H-CLEAR | 開啟全部本機歷史的 V-CONFIRM。 |
| H-MORE | 載入下一頁中繼資料；載入中停用，結束後隱藏。 |

必要狀態：載入、有資料、空清單、清單讀取錯誤、單筆載入／錯誤、已刪紀錄 404、不相容選取及刪除失敗。重新開啟 NAV-H 可重試清單讀取。已保存失敗仍可檢視；每列顯示原始時間、查詢、資源 ID、來源、上游狀態或連線錯誤類別與耗時。刪除成功移除相關列、單筆內容與選取；失敗保留畫面資料。

## V-COMPARE — 兩份已保存回應

選定參考：[option 1](html/view-compare/option-1.html)。替代：[option 2](html/view-compare/option-2.html)。

```text
┌ NAV-Q ─ NAV-H ─ NAV-C ─────────────────────────────┐
│ C-BACK [返回歷史]     C-TABLE [表格] C-JSON         │
├ 左側歷史資訊 ──────────────┬ 右側歷史資訊 ─────────┤
│ ID／來源／UTC 時間          │ ID／來源／UTC 時間      │
│ Nessie HTTP／耗時           │ Nessie HTTP／耗時       │
│ C-LEFT：原始快照            │ C-RIGHT：原始資料       │
├────────────────────────────┴───────────────────────┤
│ C-DIFF：新增／移除／變更，或無差異                  │
│ 紀錄 ID · 欄位路徑 · 變更前 · 變更後               │
└────────────────────────────────────────────────────┘
```

C-BACK 返回原有歷史選取；C-TABLE／C-JSON 在本機切換兩側。C-LEFT／C-RIGHT 及 C-DIFF 是輸出區域，不可編輯。新增、移除、變更同時以文字及視覺標記呈現，不僅依賴顏色。區分不存在值與 null。查詢時間／耗時保持可見但不產生差異標示，業務日期及回應結果仍比較。

必要狀態：無選取、載入、相容且有變更、無變更、API 結果改變、選定歷史不存在、不相容與比較／資料庫錯誤。錯誤提供返回歷史路徑，重複操作不重新查詢 Nessie。窄視窗將左右快照上下排列，保留清楚身分標示。

## V-CONFIRM — 刪除歷史確認

```text
┌ D-CONFIRMATION：刪除本機歷史？ ────────────────────┐
│ 單筆指定紀錄或全部歷史，不影響遠端資料              │
│ [D-CANCEL：取消]        [D-CONFIRM：刪除]            │
└────────────────────────────────────────────────────┘
```

使用有名稱的 modal dialog，管理焦點並於關閉後返回觸發控制項。Escape／取消不發請求；確認後停用重複送出，直到回應。說明刪除範圍與不可復原性。只影響歷史，匯入對應保留；API 也依 P08／P09 驗證確認。

## 參考範圍與可及性

每份 HTML 可本機開啟，使用本機 CSS／JavaScript 及合成資料，不呼叫網路 API。兩版桌面配置均保留左側 WORKSPACE → Admin；option 1 的表單與結果並排，option 2 上下排列並使用另一種內部卡片樣式，差異僅限 Admin 內容。參考頁專用 P-ALT 連結切換版型。查詢預覽的 P-STATE 與比較預覽的 P-CASE 選單，只用於參考頁示範狀態與預先計算案例，不是新增的產品功能或後端動作。

兩種版型的產品控制項 ID 保持一致。參考頁使用 [history.json](../../datasets/nessie/history.json) 的實際合成值，來源清楚標為 synthetic。參考頁刪除只改變記憶體清單，不改動資料集、SQLite 或 Nessie。參考頁與正式應用均須使用原生選單／按鈕、明確標籤、可見焦點、可水平捲動表格、安全文字呈現與有意義的空／錯誤訊息。全部狀態轉換見[使用者流程](UserFlow.zh-TW.md)，動作對應見[後端](Backend.zh-TW.md)。
