# v0.0.0 實作驗證

記錄：[2026/10/17 18:59] America/New_York。對應：[English](Verification.md)。

基線：最新已合併 [PR #3](https://github.com/BrianChengEn/trustledger/pull/3)，`5be26c1`。實作前已檢查其同意後記憶變更，未發現既有契約衝突。Q021 同意新增 Admin 端點；Q023 支援 24 位十六進位與標準 UUID；Q024 採實測 opening-balance 行為。

## 本機及瀏覽器檢查

- `bash scripts/check.sh`：ruff、46 項後端測試、TypeScript、3 項 Vitest、Vite build 與隔離瀏覽器測試；最後執行與 PR 檢查記於後文。
- `python3 scripts/generate_synthetic_data.py --check`：七個確定性 JSON、六項查詢與七組比較案例通過。
- 瀏覽器涵蓋六表單、驗證、表格／JSON 不新增查詢、導覽狀態保留、歷史分頁、已存比較、失效選取、取消／Escape／焦點返回、單筆／全部刪除、寫入失敗、空／401／timeout、安全呈現 HTML 文字、原有同意／記憶回歸及 320／390／768px。已目視檢查截圖；本機產物為被忽略的 `artifacts/admin-desktop.png`、`artifacts/admin-mobile.png`。
- 測試使用合成上游與隔離 SQLite；GitHub CI 新增相同瀏覽器測試，不使用供應商金鑰，保留原有檢查。

## 真實 sandbox 證據

於 `2026-10-17T22:56:41Z` 驗證，與合成測試分開：

| 檢查 | 實際結果 |
| --- | --- |
| baseline 匯入 | 確認 124 筆：10 客戶、18 帳戶、48 存款、48 提款 |
| 六種查詢 | 皆透過 Admin 回 HTTP 200 並儲存歷史 |
| 應用重啟 | 可讀回相同已存回應 |
| 已存比較 | 本文未變更；沒有新上游請求 |
| 完整匯入重跑 | 142 次 GET、**0 次 POST**，保留 124 筆確認 |
| ID | 遠端產生標準 UUID，仍接受舊 24 位十六進位 |
| 餘額 | 交易建立後仍保留 opening balance；離線 fixture 總額另列 |

初版驗證拒絕 UUID 時，首筆客戶維持 pending；Q023 後查證沿用，未再次建立。完整續跑前已讀回八筆 probe。Q024 同意實際餘額語意，未更新既有遠端餘額。本機無憑證 JSON 證據位於 `artifacts/nessie-live-verification.json`；遠端 ID、key、回應內容、資料庫與憑證指紋皆不提交。

## 審查及交付

獨立安全審查找到兩項匯入缺陷：既有標記的欄位改動可避開檢查；probe 交易改動可避開只查餘額的前置驗證。回歸測試先失敗後通過，同一審查者以 14 項聚焦測試確認修正，之後才真實續跑。後續 UUID／遷移與餘額測試通過。

完整 PR 整合審查與 GitHub CI 等待建立 PR。尚未合併、建立 release tag 或部署；依專案 PR 清單，仍須真人隊友審查。實作協助：OpenAI Codex 與獨立 AI 審查者，提交參賽作品時請保留此揭露。

- [2026/10/17 18:59] 最後本機關卡通過：ruff、46 後端、型別檢查、3 Vitest、build、隔離瀏覽器、fixture 自檢、雙語 ID／清單／連結及 Git 空白檢查。既有 Starlette／httpx 淘汰警告仍在，未修改套件。
