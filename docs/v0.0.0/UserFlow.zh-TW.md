# 使用者流程

狀態：已實作；本機瀏覽器與真實 API 證據見 [Verification](Verification.zh-TW.md)。對應：[English](UserFlow.md)。畫面 ID 見[前端](Frontend.zh-TW.md)，函式 ID 見[後端](Backend.zh-TW.md)。

## UF01 — 導覽及查詢

```text
WORKSPACE → NAV-ADMIN（Admin）→ NAV-Q → V-QUERY 待機 → 選 Q-FUNC → 必要時 Q-ID → Q-RUN
  ├ 輸入無效：欄位錯誤 → 修正 → Q-RUN
  └ 有效：載入（Q-RUN 停用）→ API 結果及獨立保存結果
        ├ 成功物件／清單 → 表格 ↔ JSON
        ├ 成功空清單 → 明確空狀態
        ├ 上游 HTTP 失敗 → 狀態及安全錯誤本文
        ├ 連線失敗 → 無 HTTP 狀態及安全錯誤
        └ 任何已擷取結果保存失敗 → failed to write
```

Q-FUNC 更新 ID 要求，切換功能清除失效欄位錯誤。Q-TABLE／Q-JSON 只切換呈現。成功資料即使 `failed to write` 仍可檢視，但不在持久歷史中。設定缺漏或本機 API 無法連線顯示本機錯誤，不混作 Nessie 狀態。重試是再次按 Q-RUN，產生一筆新請求；不加入自動重試或背景更新。保留等待請求的身分，避免延遲回應被顯示成另一個查詢的結果。

NAV-ADMIN 首次開啟 V-QUERY，返回時恢復先前的內部分頁。切換至 Overview & transactions 或 Confirmed memory 時保留 Admin 表單／結果及選取，不重新查詢。進行中的查詢可完成並更新保留的 Admin 狀態；導覽不自動重送。既有 dashboard 來源與記憶同意流程維持不變。

NAV-H 開啟歷史並透過 P05 載入第一頁；NAV-C 開啟已保留比較，或顯示可返回歷史的無選取提示。導覽本身不發出新的 Nessie 查詢。

## UF02 — 檢視及選取歷史

NAV-H：載入後轉為有資料、空清單或讀取錯誤。H-MORE 載入下一頁並保留舊列及選取。H-VIEW-{id} 於 H-DETAIL 開啟已保存回應、來源及原始時間；H-TABLE／H-JSON 切換呈現。檢視已存資料不新增查詢紀錄。

H-L-{id}／H-R-{id} 選兩筆相異紀錄；查詢、資源 ID、來源相同前，H-COMPARE 保持停用並說明原因。有效選取呼叫 P07，切換 V-COMPARE。伺服器仍獨立驗證選取：404 清除失效選取並回到歷史；409 保留紀錄並說明不相容；資料庫錯誤保留選取，供之後重試。

## UF03 — 比較及返回

V-COMPARE：載入後轉為有變更、無變更、結果狀態改變或錯誤。兩側各自顯示原始 UTC 時間及耗時，不當作資料變更。C-TABLE／C-JSON 在本機切換兩份本文。C-DIFF 標示新增／移除／欄位變更，區分不存在與 null。C-BACK 返回 V-HISTORY，保留選取及已載入列。沒有選取時提供歷史入口，不虛構比較結果。

## UF04 — 刪除歷史

```text
H-DELETE-{id}／H-CLEAR → V-CONFIRM（顯示範圍）
  ├ D-CANCEL／Escape → 關閉、返回焦點、零請求
  └ D-CONFIRM → 刪除中
        ├ 提交成功 → 移除指定歷史，清除失效選取／內容
        └ 錯誤 → 顯示失敗，保留列及選取，可重試
```

確認以 `{confirm:true}` 呼叫 P08／P09，僅授權畫面上顯示的本機歷史範圍。清空歷史不清匯入進度、不刪資料集、不發上游 DELETE。紀錄已不存在則回報 404 並更新清單。刪除在應用內不可復原，本版不建立復原系統。

## UF05 — UI 外的初始 baseline 設定

開發者於後端環境安全提供 `NESSIE_API_KEY`，執行未來的 seed 指令。上游寫入前先驗證及檢查進度。整合探測涵蓋一個客戶／帳戶及六筆交易；伺服器行為不相容時在大量寫入前停止。成功對應提供查詢表單可用的真正 ID。

```text
baseline 驗證 → 批次範圍 → pending 已保存 → 遠端建立／讀回
  ├ 已確認 → 保存對應 → 下一筆相依紀錄
  ├ 確定拒絕 → 安全錯誤，停止
  └ 結果不明 → 核對
        ├ 唯一已驗證結果 → confirmed
        └ 找不到／有歧義 → blocked，不盲目重送 POST
完成後重跑 → 驗證對應 → 略過已確認 → 零新增紀錄
```

唯讀查詢 UI 不加入匯入／重設按鈕。範圍、key 或資料集不符時停止並核對，不靜默重建或刪除資源。清除本機歷史不影響設定進度。

## 覆蓋範圍

UF01 涵蓋 NAV-ADMIN／Q-FUNC／Q-ID／Q-RUN／Q-TABLE／Q-JSON 及 AC01–AC04／AC08／AC12。UF02 涵蓋 NAV-H／H-MORE／H-VIEW／H-TABLE／H-JSON／H-L／H-R／H-COMPARE 及 AC04–AC06。UF03 涵蓋 NAV-C／C-BACK／C-TABLE／C-JSON 及 AC05–AC06。UF04 涵蓋 H-DELETE／H-CLEAR／D-CANCEL／D-CONFIRM 及 AC07。UF05 涵蓋設定及 AC02／AC09–AC10。每個畫面皆有可用的載入、空狀態及錯誤返回路徑。參考頁專用 P-STATE／P-CASE 不屬於產品流程。
