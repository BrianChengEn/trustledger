# TrustLedger Mermaid 圖表

所有 `.mmd` 都是可編輯純文字。可在支援 Mermaid 的 Markdown viewer、GitHub 或 [Mermaid Live Editor](https://mermaid.live/) 檢視。不要把含真實 key、帳號、個資的內容貼進外部 editor。

| 圖 | 用途 | Source of truth |
|---|---|---|
| [architecture.mmd](architecture.mmd) | 系統元件、owners、外部 vendors、fallback | 總體架構 |
| [data-flow.mmd](data-flow.mmd) | raw → canonical → safe payload → human/memory | 隱私資料流 |
| [review-sequence.mmd](review-sequence.mmd) | 一次 alert review 的完整 sequence | Demo/backend contract |
| [git-collaboration.mmd](git-collaboration.mmd) | 四人分支、contract、PR、CI、merge | GitHub手冊 |
| [threat-boundaries.mmd](threat-boundaries.mmd) | trust boundaries 與敏感流向 | 威脅模型 |
| [integration-order.mmd](integration-order.mmd) | 截止前的 gate 與降級決策 | 提交 runbook |

## 編輯規則

- Node 名稱保持產品語言，不放真實 URL query、key、account/customer id。
- `live` 與 `fallback` edge 樣式分開；不要把 optional vendor 畫成核心單點。
- 修改 diagram 後同步相關 Markdown 與 `index.html` 中的 embedded diagram。
- 圖只做架構溝通，不等於已完成的安全控制；實際 tests 才是 evidence。

