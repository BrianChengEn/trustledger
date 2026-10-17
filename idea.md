此為mcp的第一階段，遵守奧坎剃刀原則並寫一個最小程式，flow為：
python->swagger ui(https://prod.nessieisreal.com/)->database->frontend(react)
目的為：
1.frontend可以選擇功能和輸入指令來抓取資料
2.python負責將這些功能轉為nessie api呼叫
3.database為敏感資料和暫存回傳的資料
4.最後將資料show在frontend上
開始v0.0.0問題集