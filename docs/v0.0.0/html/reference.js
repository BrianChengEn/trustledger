"use strict";
const demo = window.NESSIE_REFERENCE;
const byId = Object.fromEntries(demo.records.map(record => [record.id, record]));
const option = document.body.dataset.option;
const view = document.body.dataset.view;
const $ = id => document.getElementById(id);
const node = (tag, text, className) => {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
};
const textValue = value => typeof value === "object" ? JSON.stringify(value) : String(value);

function metadata(target, record, failedWrite = false) {
  target.replaceChildren();
  for (const text of [record.id, `source: ${record.source}`, record.requested_at,
    record.http_status === null ? "沒有 HTTP 回應" : `Nessie HTTP ${record.http_status}`,
    `${record.duration_ms} ms`]) target.append(node("span", text));
  if (view === "query") {
    const save = node("span", failedWrite ? "failed to write" : `已保存 · ${record.id}`, `badge${failedWrite ? " failed" : ""}`);
    save.id = "Q-SAVE";
    target.append(save);
  }
}

function bodyView(target, record, mode, marks = {}) {
  target.replaceChildren();
  const body = record.response_body;
  if (mode === "json" || record.http_status === null || record.http_status >= 400 || body === null || typeof body !== "object") {
    const value = record.transport_error || body;
    target.append(node("pre", typeof value === "string" ? value : JSON.stringify(value, null, 2)));
    return;
  }
  const rows = Array.isArray(body) ? body : [body];
  if (!rows.length) {
    target.append(node("p", "查詢成功，沒有資料。", "empty"));
    return;
  }
  const keys = [...new Set(rows.flatMap(row => Object.keys(row)))];
  const columns = keys.includes("_id") ? ["_id", ...keys.filter(key => key !== "_id")] : keys;
  const wrap = node("div", undefined, "table-wrap");
  const table = node("table");
  const head = node("tr");
  columns.forEach(key => head.append(node("th", key)));
  const thead = node("thead"); thead.append(head); table.append(thead);
  const tbody = node("tbody");
  for (const row of rows) {
    const tr = node("tr");
    const mark = marks[row._id];
    if (mark) tr.className = mark === "新增" ? "added" : mark === "移除" ? "removed" : "changed";
    columns.forEach((key, index) => {
      const td = node("td", Object.hasOwn(row, key) ? textValue(row[key]) : "—");
      if (mark && index === 0) td.append(node("span", mark, "marker"));
      tr.append(td);
    });
    tbody.append(tr);
  }
  table.append(tbody); wrap.append(table); target.append(wrap);
}

function toggles(tableId, jsonId, render) {
  let mode = "table";
  const update = next => {
    mode = next;
    $(tableId).setAttribute("aria-pressed", String(mode === "table"));
    $(jsonId).setAttribute("aria-pressed", String(mode === "json"));
    render(mode);
  };
  $(tableId).onclick = () => update("table");
  $(jsonId).onclick = () => update("json");
  return () => update(mode);
}

function queryView() {
  let current = byId.H003;
  let failed = false;
  const render = toggles("Q-TABLE", "Q-JSON", mode => {
    metadata($("query-meta"), current, failed);
    bodyView($("Q-RESULT"), current, mode);
  });
  const updateFunction = () => {
    const sample = demo.records.find(record => record.dataset_id === "baseline" && record.query === $("Q-FUNC").value && record.http_status === 200);
    const needsId = !$("Q-FUNC").value.endsWith(".list");
    $("id-field").hidden = !needsId;
    $("Q-ID").disabled = !needsId;
    $("id-label").textContent = $("Q-FUNC").value === "accounts.by_customer" ? "Customer ID" : "Account ID";
    $("Q-ID").value = sample.resource_id || "";
    $("query-status").textContent = "";
  };
  $("Q-FUNC").onchange = updateFunction;
  $("query-form").onsubmit = event => {
    event.preventDefault();
    const query = $("Q-FUNC").value;
    const resourceId = query.endsWith(".list") ? null : $("Q-ID").value.trim().toLowerCase();
    if (resourceId !== null && !/^[0-9a-f]{24}$/.test(resourceId)) {
      $("query-status").textContent = "請輸入 24 位十六進位 ID。";
      $("query-status").className = "status error";
      $("Q-ID").focus(); return;
    }
    $("Q-RUN").disabled = true;
    $("query-status").textContent = "正在載入合成範例…";
    setTimeout(() => {
      const sample = demo.records.find(record => record.dataset_id === "baseline" && record.query === query && record.resource_id === resourceId && record.http_status === 200);
      current = structuredClone(sample || { ...byId.H003, query, resource_id: resourceId, http_status: 404, response_body: {code:404,message:"合成範例沒有此資源"} });
      failed = $("P-STATE").value === "write-failed";
      const state = $("P-STATE").value;
      if (state === "empty") current.response_body = [];
      if (state === "api-error") { current.http_status = 401; current.response_body = "unauthorized"; }
      if (state === "timeout") { current.http_status = null; current.response_body = null; current.transport_error = {type:"timeout",message:"合成連線逾時"}; }
      $("query-status").textContent = current.http_status === null || current.http_status >= 400 ? "查詢失敗；可檢視錯誤內容。" : "合成查詢完成。";
      $("query-status").className = current.http_status === null || current.http_status >= 400 ? "status error" : "status";
      $("Q-RUN").disabled = false;
      render();
    }, 80);
  };
  updateFunction(); render();
}

function historyView() {
  let records = [...demo.records].reverse();
  let left = "H003", right = "H009", current = byId.H003;
  let pending, opener;
  const renderDetail = toggles("H-TABLE", "H-JSON", mode => {
    metadata($("history-meta"), current);
    bodyView($("history-body"), current, mode);
  });
  const selection = () => {
    const a = byId[left], b = byId[right];
    const compatible = a && b && left !== right && a.query === b.query && a.resource_id === b.resource_id && a.source === b.source;
    $("H-COMPARE").disabled = !compatible;
    $("history-status").textContent = compatible ? `已選取 ${left} 與 ${right}。` : "請選取同一查詢／ID 的兩筆相異歷史。";
  };
  const openDialog = (id, button) => {
    pending = id; opener = button;
    $("delete-scope").textContent = id ? `刪除本機歷史 ${id}？` : "清空全部本機歷史？";
    $("D-CONFIRMATION").showModal();
  };
  function renderRows() {
    $("history-rows").replaceChildren();
    for (const record of records) {
      const tr = node("tr");
      for (const side of ["L", "R"]) {
        const td = node("td"), input = node("input");
        input.type = "radio"; input.name = `history-${side}`; input.id = `H-${side}-${record.id}`;
        input.setAttribute("aria-label", `${side === "L" ? "左側" : "右側"} ${record.id}`);
        input.checked = (side === "L" ? left : right) === record.id;
        input.onchange = () => { if (side === "L") left = record.id; else right = record.id; selection(); };
        td.append(input); tr.append(td);
      }
      for (const value of [record.id,record.requested_at,record.query,record.resource_id || "—",record.source,record.http_status ?? "timeout",`${record.duration_ms} ms`]) tr.append(node("td",String(value)));
      const actions = node("td", undefined, "actions");
      const inspect = node("button", "檢視"); inspect.id = `H-VIEW-${record.id}`;
      inspect.onclick = () => { current = record; $("H-DETAIL").hidden = false; renderDetail(); };
      const remove = node("button", "刪除", "danger"); remove.id = `H-DELETE-${record.id}`;
      remove.onclick = () => openDialog(record.id, remove);
      actions.append(inspect, remove); tr.append(actions); $("history-rows").append(tr);
    }
    $("history-empty").hidden = records.length !== 0;
    $("H-CLEAR").disabled = records.length === 0;
    selection();
  }
  $("H-CLEAR").onclick = () => openDialog(null, $("H-CLEAR"));
  $("D-CANCEL").onclick = () => $("D-CONFIRMATION").close();
  $("D-CONFIRMATION").addEventListener("close", () => { if (opener?.isConnected) opener.focus(); });
  $("D-CONFIRM").onclick = () => {
    records = pending ? records.filter(record => record.id !== pending) : [];
    const remaining = new Set(records.map(record => record.id));
    if (!remaining.has(left)) left = null;
    if (!remaining.has(right)) right = null;
    if (!remaining.has(current.id)) $("H-DETAIL").hidden = true;
    $("D-CONFIRMATION").close(); renderRows();
  };
  $("H-COMPARE").onclick = () => {
    location.href = `../view-compare/option-${option}.html?left=${encodeURIComponent(left)}&right=${encodeURIComponent(right)}`;
  };
  $("H-MORE").hidden = true;
  renderRows(); renderDetail();
}

function compareView() {
  let currentCase = demo.comparisons[0];
  const params = new URLSearchParams(location.search);
  if (params.has("left")) currentCase = demo.comparisons.find(c => c.left_id === params.get("left") && c.right_id === params.get("right")) || null;
  for (const entry of demo.comparisons) {
    const item = node("option", `${entry.id} · ${entry.expected.kind}`); item.value = entry.id; $("P-CASE").append(item);
  }
  const render = toggles("C-TABLE", "C-JSON", mode => {
    const target = $("C-DIFF"); target.replaceChildren();
    if (!currentCase) { target.append(node("p", "此參考頁未預先計算這組差異；可選下方示範案例。", "empty")); return; }
    const left = byId[currentCase.left_id], right = byId[currentCase.right_id], expected = currentCase.expected;
    metadata($("compare-left-meta"), left); metadata($("compare-right-meta"), right);
    const marks = {};
    for (const id of expected.added_ids || []) marks[id] = "新增";
    for (const id of expected.removed_ids || []) marks[id] = "移除";
    for (const id of Object.keys(expected.updated_fields || {})) marks[id] = "變更";
    if (expected.kind === "object_changed") marks[left.response_body._id] = "變更";
    bodyView($("C-LEFT"), left, mode, marks); bodyView($("C-RIGHT"), right, mode, marks);
    if (["identical_body","same_records_different_order"].includes(expected.kind)) {
      target.append(node("p", "沒有資料差異。查詢時間與耗時僅供參考。", "empty")); return;
    }
    const list = node("ul", undefined, "diff-list");
    for (const field of expected.changed_fields || []) list.append(node("li", `變更 /${field}：${textValue(left.response_body[field])} → ${textValue(right.response_body[field])}`));
    for (const id of expected.added_ids || []) list.append(node("li", `新增 ${id}`));
    for (const id of expected.removed_ids || []) list.append(node("li", `移除 ${id}`));
    for (const [id, fields] of Object.entries(expected.updated_fields || {})) list.append(node("li", `變更 ${id}：${fields.join("、")}`));
    if (expected.kind === "account_removed") list.append(node("li", "回應結果變更：Nessie HTTP 200 → 404，帳戶已不存在。"));
    target.append(list);
  });
  $("P-CASE").value = currentCase?.id || demo.comparisons[0].id;
  $("P-CASE").onchange = () => { currentCase = demo.comparisons.find(c => c.id === $("P-CASE").value); render(); };
  render();
}

if (view === "query") queryView();
if (view === "history") historyView();
if (view === "compare") compareView();
window.REFERENCE_READY = true;
