# 2026-10-18 12:00 EDT 提交 Runbook

## 官方時間與規則快照

- Technica 2026 官方 Devpost 截止：**2026-10-18 12:00 EDT**。
- 有效作品須在 24 小時 hacking period 內完成；不可 cross-submit 至其他 hackathon。
- 一般隊伍最多 4 人。
- 需 credit 使用的 ChatGPT/AI；未揭露可能被取消資格。
- 最多 3 個一般 challenges，另加最多 3 個 sponsored challenges。
- 有 virtual member 或無法現場 Expo 時，需依官方說明透過 Gather live demo 才具得獎資格。
- Devpost overview 把 Sunday Expo 時間寫成 `1:00 pm EST`；請以活動當日 schedule/announcement確認 EDT/EST wording。

來源：[Devpost overview](https://technica-2026.devpost.com/)、[rules](https://technica-2026.devpost.com/rules)、[schedule](https://technica-2026.devpost.com/details/dates)。

## 務實里程碑（EDT）

### 2026-10-17

| 時間 | Gate | 必須完成 | 若未完成 |
|---|---|---|---|
| 12:00–12:30 | Scope lock | B2C、四功能、owner、channels、repo | 不討論 B2B/admin |
| 12:30–13:30 | Contract freeze | OpenAPI v0.1、fixture、env examples、branch | Integration owner裁決最小 contract |
| 13:30–16:00 | Vertical slice 1 | FastAPI health/transactions + React list，純 synthetic | 暫停 vendor exploration |
| 16:00–18:30 | Core behaviors | rules alert、detail、Privacy Inspector、confirmation no-memory | 砍 charts/動畫 |
| 18:30–19:00 | Integration 1 | main 可 demo list→confirm；CI baseline | 阻塞>20min用 mock |
| 19:00–21:00 | Vendor evidence | 一次接 Nessie/Jev/Backboard；每個都有 fallback | 只保留已成功者 |
| 21:00–22:00 | Integration 2 | live toggles、memory consent/delete、status badges | Memory 先 local/off |
| 22:00 | Feature freeze | 不加功能 | 只修 P0/P1 |
| 22:00–23:30 | Quality | security tests、mobile/keyboard、copy、errors | 用 synthetic 保穩定 |
| 23:30–00:30 | Demo alpha | 90 秒流程錄影、列 bug | 找最穩 commit |

### 2026-10-18

| 時間 | Gate | 必須完成 | 若未完成 |
|---|---|---|---|
| 07:30–08:30 | Main green | rebase/merge最後核心修正、full CI | revert last risky PR |
| 08:30–09:15 | Security gate | secret/PII scan、fallback、memory cleanup test | 關 live feature |
| 09:15–10:00 | Demo beta | 3 次 rehearsal、backup recording | 固定 synthetic demo |
| 10:00 | Deploy cutoff | public URL last-known-good，或 localhost plan | 停止 cloud debug |
| 10:00–10:45 | Submission assets | README、Devpost文案、slides/screenshots/video | 不再改核心 code |
| 10:45–11:15 | Submission QA | links、team、challenges、AI credit、access | 由第二人逐欄核對 |
| 11:15 | Submit candidate | Devpost先提交可用版本 | 不等「完美」 |
| 11:15–11:30 | Verify | confirmation、gallery/private preview、URL | 必要時最小修訂 |
| 11:30 | Stop code | 不 merge、不 redeploy | 只處理提交頁 blocker |
| 12:00 | Hard deadline | 完成 | — |

每 90 分鐘 sync；單一 blocker 超過 20 分鐘就走 fallback。

## 降級方案

| 失敗 | 立即行動 | Demo 說法 | 仍可參賽價值 |
|---|---|---|---|
| Nessie key/endpoint失敗 | `APP_MODE=synthetic`；保留已驗證 health evidence | 「核心情境用合成交易；Nessie sandbox adapter是可選來源」 | T. Rowe/一般 track；Capital One live evidence不足要誠實 |
| Nessie 只有部分 read | 用 accounts/bills/merchants context + synthetic transactions | 明確標每筆 source | 可展示實際 Nessie use，不假稱 purchase feed |
| Jev失敗/429 | rules-only，health degraded | 「可解釋 rules 保持功能，Jev 是 optional decision layer」 | 產品仍完整 |
| Backboard失敗 | memory off/local-fallback；confirmation照常保存 | 「持久記憶目前降級，不把 local state稱 Backboard」 | 非 Backboard獎仍可；若無 live evidence不要誇大 |
| Deploy失敗 | localhost + Gather screen share + backup video | 「live local prototype」 | 功能/UX仍可評審 |
| Frontend blocker | 用最少三頁、無動畫圖表 | 保持一條完整故事 | 勝過半成品功能 |
| CI blocker | revert至 last-known-good；記 known issue | Demo固定 commit SHA | main維持可重現 |
| Security concern | 關 live vendors/memory、rotate key、synthetic demo | 主動說明安全降級 | responsible design 加分 |

## 不可犧牲的五件事

1. 不放真實金融資料。
2. 不把 vendor key 放前端/Git/log。
3. Privacy Inspector 與實際 outbound payload一致。
4. 人工確認與 memory consent 明確。
5. Demo/status/pitch 不偽稱 live provider、fraud verdict 或合規。

## 90 秒 Demo 腳本

### 0–15 秒：問題

> 「銀行交易提醒常常只有一個紅色警告，使用者不知道原因，也不知道哪些資料被送給 AI。TrustLedger 是一個 privacy-first 的個人金融安全助手。」

### 15–35 秒：發現

- 打開 Dashboard，指出 source/mode badges。
- 點兩筆 USD 11.99 streaming duplicate alert。
- 說明「系統注意到同類別、同金額、六分鐘內出現兩次；這不是詐欺判定」。

### 35–55 秒：Privacy Inspector

- 顯示原始 account/merchant欄位被移除/泛化。
- 顯示 safe payload：category、amount bucket、time bucket、duplicate count。
- 說「TLS 保護傳輸；data minimization 才是降低 AI 看到敏感內容的關鍵」。

### 55–75 秒：Human confirmation + Memory

- 選 `正常交易`，勾選同意記憶。
- 顯示 written/pending/backboard-live 真實狀態。
- 顯示 sanitized memory summary 與 delete。

### 75–90 秒：Responsible design

- 提到 rules fallback、low confidence人工確認、no automatic action。
- 結尾：`Understand your spending without unnecessarily exposing your financial identity.`

## 3 分鐘 Q&A 準備

### 「為什麼需要 Jev？」

Rules 對已知 pattern 可解釋；Jev 對同一組安全 features 做 bounded classification/probability，且問題與輸出被限制。它不是用來生成金融建議；任何低信心都回人工確認。

### 「為什麼需要 Backboard？」

使用者不應重複回答同一類情境。Backboard保存經明確同意的抽象 confirmation；我們不把 raw transaction 放進 memory，且提供 delete。Memory 是 assistant-scoped，所以 Demo 使用單一 user專用 assistant。

### 「你們真的保護資料了嗎？」

Prototype 有 data minimization、allowlist、tokenization/bucketing、server-only keys、TLS、safe logs、human control；但不宣稱 production合規。正式上線仍需 auth、DPA/retention、滲透測試、監管/法律審查。

### 「資料是真實的嗎？」

不是。核心情境完全 synthetic；任何 Nessie 資料都是 sandbox/mock。UI 每筆標 source。

### 「AI 如果錯了？」

不自動封鎖或付款；顯示 evidence/confidence；low-confidence/degraded 都要求 user review；rules-only fallback 仍能完成流程。

## Challenge 選擇

建議 sponsored：

1. `[Capital One] The Best Use of Nessie` — 只有在有可證明 live Nessie call 時選；說清楚 synthetic/live邊界。
2. `[T. Rowe Price] NextGen Finance Innovation Challenge` — 強調 real problem、risk discovery、financial education、transparent/accessible/responsible design。
3. `[MLH] Best Use of Backboard` — 只有在 persistent memory live、可 refresh/retrieve/delete 時選。

一般 challenges 依 Devpost最新列表選最多三個。TrustLedger較適合 UI/UX、Startup、Education 或 Accessibility 中真正符合的項目，不為了數量硬投。

## Devpost 內容檢查表

### Project basics

- [ ] 專案名稱：TrustLedger。
- [ ] 一句話：`A privacy-first AI financial companion that explains unusual spending patterns and learns only from user-approved feedback.`
- [ ] 四位成員姓名/GitHub 正確。
- [ ] repo URL權限讓評審可看（依規則決定 public/private sharing）。
- [ ] Demo URL/影片可匿名或依評審要求存取。
- [ ] 所有 links 在無登入/incognito 測試。

### Story

- [ ] Inspiration：transaction alerts 缺 explainability/privacy/control。
- [ ] What it does：四核心功能。
- [ ] How built：React/Vite、FastAPI、synthetic/Nessie sandbox、Jev、Backboard。
- [ ] Challenges：schema inconsistency、privacy minimization、memory isolation。
- [ ] Accomplishments：end-to-end human-in-loop、exact Privacy Inspector、fallback。
- [ ] Learned：TLS不等於AI看不到、assistant-scoped memory isolation、contract-first協作。
- [ ] What's next：正式 auth、多租戶隔離、vendor DPA/retention、security testing。

### Honesty / rules

- [ ] 清楚寫 synthetic/Nessie sandbox，無真實金融資料。
- [ ] 清楚寫 prototype/non-advisory/non-fraud verdict。
- [ ] Credit ChatGPT/Codex/Cursor/GitHub Copilot等實際使用的 AI tools；不要列沒用過的。
- [ ] 說明哪些 provider integration live，哪些 fallback/mock。
- [ ] 不 cross-submit。
- [ ] challenges數量符合規則。

### Evidence

- [ ] 影片可看清 source/status、alert、Privacy Inspector、consent、memory。
- [ ] README setup可以照做；`.env.example` 無值。
- [ ] screenshots 無 key、真實個資、browser developer tools query URL。
- [ ] last-known-good commit tagged或記 SHA。
- [ ] security tests/CI green。

## Final technical checklist

- [ ] `git status` clean；main與 deployed SHA一致。
- [ ] backend tests pass。
- [ ] frontend lint/tests/build pass。
- [ ] synthetic offline full flow pass。
- [ ] live providers逐一 smoke；狀態真實。
- [ ] no-key/no-network mode可啟動。
- [ ] secret/PII scan 0 unexpected hits。
- [ ] CORS/TLS/production debug/logging正確。
- [ ] consent default false；delete works。
- [ ] mobile + keyboard pass。
- [ ] backup video、screenshots、PDF/notes本機可用。
- [ ] Demo後 key rotation/memory deletion owner已指派。

## Go / No-Go 決策

### Go live vendor

只有同時符合：

- 兩次連續 smoke success。
- 沒有 secrets/log/PII問題。
- timeout/fallback已測。
- live狀態不影響 synthetic baseline。
- 09:15 EDT 後不需新 contract。

### No-Go → fallback

任一情況立即降級：

- endpoint/schema仍不明。
- key疑似曝光。
- intermittent failure影響 90 秒 demo。
- memory cross-user/isolation疑慮。
- deploy需在 10:00 EDT 後大改。

**完成度高且誠實的 synthetic-first prototype，比不穩定但聲稱全 live 的 Demo 更有競爭力。**

