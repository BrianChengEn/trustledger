# 變更紀錄

對應：[English](CHANGELOG.md)。僅記錄實際工作，不將未來計畫視為完成。

## v0.0.0 — 未發佈的 Nessie 設計提案

- [2026/10/17 18:24] 記錄 Q001–Q019，草擬雙語前端、後端、資料流、使用者流程、資料庫及初始計畫，附[版本索引](v0.0.0/README.zh-TW.md)。
- [2026/10/17 18:24] 新增六份本機 HTML 參考，每畫面兩份，均使用明確標示的合成資料。兩種版型的無頭 Chrome 檢查通過，涵蓋六項查詢、JSON／表格、保存失敗、逾時／空狀態、歷史檢視／取消／單筆刪除／清空、比較、排序／timestamp 排除、結果變更及窄視窗溢出。八組檢查通過，無頁面錯誤；證據與截圖位於 `/var/folders/m9/_c877nqx7x96qvrk297jjhzr0000gn/T/hackerton-design-evidence-5LJ8z9/`。
- [2026/10/17 18:24] 保留五組可重現資料、32 筆合成執行、七組比較案例及標準函式庫產生器／自我檢查。
- [2026/10/17 18:24] 保留同期出現的 TrustLedger 應用、團隊所有權與契約；恢復追蹤的 AGENTS 及文件索引後，只增加獨立 Nessie 連結。Q020 仍待確認獨立或整合範圍。
- [2026/10/17 18:24] 既有 TrustLedger `bash scripts/check.sh` 通過：後端 lint、15 個後端測試、前端 typecheck、三個前端測試及 build。出現一項相依套件棄用警告；本提案未變更相依套件。
- [2026/10/17 18:24] 未執行新的 Nessie 程式、SQLite 應用 schema、線上 baseline 匯入或 API 驗證。本次未 commit、PR、merge、tag、發佈或部署；既有 TrustLedger 執行程式與本提案分開。

- [2026/10/17 18:35] Q020 B 已確認：測試台整合至 TrustLedger 左側 WORKSPACE → Admin，內含查詢／歷史／比較分頁。完成新增 API／模組／Store 設計，保留合成／同意／AI 邊界與既有契約審查。S0 完成，S1–S5 待後續實作。
- [2026/10/17 18:35] 六份 HTML 已改為整合側欄；12 組瀏覽器檢查通過，涵蓋兩種版型及全部畫面 320px／390px。雙語 ID／清單、自撰 Markdown 連結、資料檢查、JavaScript 語法及共用原文保留通過。證據：`/var/folders/m9/_c877nqx7x96qvrk297jjhzr0000gn/T/hackerton-design-evidence-i110PE/`。必要的 `bash scripts/check.sh` 再次通過 lint、15 個後端測試、typecheck、三個前端測試與 build，保留一項既有棄用警告。未修改執行來源／契約、呼叫或匯入 Nessie、發佈或部署。

## v0.0.0 — Nessie Admin 實作

- [2026/10/17 18:59] 實作 WORKSPACE → Admin 查詢／歷史／比較、新增 OpenAPI、本機 Host／Origin／JSON 防護、持久歷史與 baseline 專用可續跑初始化；保留 #3 記憶回饋與合成 dashboard。
- [2026/10/17 18:59] Q021 同意契約；真實 ID 不符後 Q023 同意 UUID 與 24 位十六進位；Q024 同意 opening balance 與獨立交易。歷史遷移保留紀錄及已刪 ID 序號。
- [2026/10/17 18:59] 真實確認 124 筆、六查詢回 200；歷史重啟一致，比較無上游呼叫。完整重跑 142 次 GET、零次 POST，未更新既有遠端餘額。
- [2026/10/17 18:59] 獨立安全審查確認重複標記及 probe 前置查證修正。本機涵蓋 46 後端、3 前端測試、build／型別、fixture 與瀏覽器流程；完整 PR 審查／CI 待執行，未合併、tag 或部署。[證據](v0.0.0/Verification.zh-TW.md)。AI 協助：OpenAI Codex。

- [2026/10/17 19:05] 建立 [PR #4](https://github.com/BrianChengEn/trustledger/pull/4)；修正舊歷史回應與各帳戶 opening-balance 回歸後，完整獨立 AI 整合審查通過。最後本機 47 後端與瀏覽器檢查通過，真實唯讀重跑驗證全部餘額且零 POST。首輪 GitHub CI 通過，最後更新將重跑；待真人隊友審查，未合併／tag／部署。
