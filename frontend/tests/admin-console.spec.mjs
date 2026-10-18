import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {existsSync, mkdirSync, mkdtempSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {chromium} from 'playwright';

const root = fileURLToPath(new URL('../..', import.meta.url));
const temp = mkdtempSync(join(tmpdir(), 'trustledger-admin-'));
const children = [];
function start(command, args, env = {}) {
  const child = spawn(command, args, {cwd: root, env: {...process.env, ...env}, stdio: 'pipe'});
  let logs = '';
  child.stdout.on('data', data => {logs += data;});
  child.stderr.on('data', data => {logs += data;});
  children.push(child);
  return () => logs;
}
async function ready(url, logs) {
  for (let i = 0; i < 100; i++) {
    try {if ((await fetch(url)).ok) return;} catch {}
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error(`Service did not start: ${logs()}`);
}
let browser, page;
const errors = [];
const apiStates = [];
try {
  const frontendLogs = start(process.execPath, ['frontend/node_modules/vite/bin/vite.js',
    'frontend', '--host', '127.0.0.1', '--port', '5174'],
    {API_PROXY_TARGET: 'http://127.0.0.1:8123'});
  const backendLogs = start(resolve(root, 'backend/.venv/bin/python'),
    ['backend/tests/admin_console_server.py'], {PYTHONPATH: 'backend',
      APP_ENV: 'test', TRANSACTION_PROVIDER: 'nessie', DATABASE_PATH: join(temp, 'test.db'), FRONTEND_ORIGIN: 'http://127.0.0.1:5174'});
  const connectedBackend = children.at(-1);
  await Promise.all([ready('http://127.0.0.1:5174', frontendLogs),
    ready('http://127.0.0.1:8123/api/v1/health', backendLogs)]);
  const chrome = process.env.PLAYWRIGHT_CHROME_PATH;
  browser = await chromium.launch({headless: true, ...(chrome ? {executablePath: chrome} :
    existsSync('/Applications/Google Chrome.app') ? {channel: 'chrome'} : {})});
  async function assertResponsiveBaseline() {
    const layout = await page.evaluate(() => {
      return {width: innerWidth, scroll: document.documentElement.scrollWidth};
    });
    assert(layout.scroll <= layout.width + 1, JSON.stringify(layout));
  }
  async function assertStableScale() {
    const sample = await page.evaluate(async()=>{
      const values = [];
      for (let frame=0;frame<20;frame++) {
        await new Promise(requestAnimationFrame);
        values.push(Number(document.documentElement.style.getPropertyValue('--stage-scale')));
      }
      return {scales:[...new Set(values)],expected:Math.min(innerHeight/920,innerWidth/1360,1.25)};
    });
    assert.deepEqual(sample.scales,[sample.expected],'data and button actions must not shrink the page');
  }
  // Shortcut menus open on click (the caret beside a tab), never on hover, so they cannot cover the workspace unexpectedly.
  async function openMenu(label) {
    await page.getByRole('button',{name:`Show ${label} shortcuts`,exact:true}).click();
    await page.getByRole('region',{name:`${label} features`,exact:true}).waitFor();
  }
  let queryCalls = 0;
  let deletes = 0;
  let analysisCalls = 0;
  let explanationCalls = 0;
  async function appPage() {
    const next = await browser.newPage({viewport: {width:1440,height:1000},reducedMotion:'reduce'});
    next.setDefaultTimeout(5000);
    // Same-origin through the Vite proxy so the sign-in cookie is sent; the browser session is an admin.
    const signedIn = await next.request.post('http://127.0.0.1:5174/api/v1/auth/login',
      {data: {role: 'admin', passcode: 'browser-admin-pass'}});
    assert.equal(signedIn.status(), 200, 'test admin sign-in');
    next.on('pageerror', error => errors.push(error.message));
    next.on('request', req => {
      if (req.url().endsWith('/admin/nessie/query')) queryCalls++;
      if (req.method()==='DELETE') deletes++;
      if (req.url().endsWith('/analyses')) analysisCalls++;
      if (req.url().endsWith('/explanation')) explanationCalls++;
    });
    next.on('response', response => {
      const path = new URL(response.url()).pathname;
      if (path.startsWith('/api/v1/')) apiStates.push({status:response.status(),
        path:path.replace(/(?:txn|acct|customer|memory)_[A-Za-z0-9_-]+/g,'{resource}')});
    });
    await next.route('**/*', route => ['127.0.0.1','localhost'].includes(
      new URL(route.request().url()).hostname) ? route.continue() : route.abort());
    return next;
  }
  // The admin console and the user's screens are different modes now; these helpers switch between them.
  async function toConsole() {
    const back = page.getByRole('button',{name:'Back to admin',exact:true});
    if (await back.count()) await back.click();
    await page.locator('#NAV-ADMIN').click();
  }
  async function toUser(name) {
    const preview = page.getByRole('button',{name:'Preview as user',exact:true});
    if (await preview.count()) await preview.click();
    await page.locator('.topbar').getByRole('link',name instanceof RegExp?{name}:{name,exact:true}).click();
  }
  async function toToday() {
    const preview = page.getByRole('button',{name:'Preview as user',exact:true});
    if (await preview.count()) await preview.click();
    await toUser(/^Today/);
  }
  // Pages that start on the user's screens open in the admin's "Preview as user" mode.
  async function userGoto(target, url) {
    await target.addInitScript(() => { try { if (!sessionStorage.getItem('e2e-init')) { sessionStorage.setItem('e2e-init', '1'); sessionStorage.setItem('trustledger.preview', '1'); } } catch {} });
    await target.goto(url);
    await target.evaluate(() => sessionStorage.setItem('e2e-init', '1'));
  }
  page = await appPage();
  await page.goto('http://127.0.0.1:5174');
  await page.getByRole('button',{name:'Preview as user',exact:true}).click();
  await page.getByRole('link', {name: /^Today/}).waitFor();
  await page.locator('.startcard').waitFor();
  await openMenu('Today');
  assert.equal(await page.locator('.scrim').count(),0,'hover menus must not blur or cover the workspace');
  await assertStableScale();
  mkdirSync(join(root,'artifacts'),{recursive:true});
  await page.screenshot({path:join(root,'artifacts/v031-menu-after.png')});
  await page.mouse.move(0,0);
  assert.equal(await page.locator('.workspacebar').count(), 0,
    'backend integration must preserve the approved UI without an added workspace toolbar');
  await toConsole();
  await page.locator('#V-QUERY').waitFor();
  await page.getByRole('heading',{name:'This workspace',exact:true}).waitFor();
  assert.equal(await page.locator('#Q-FUNC option').count(), 8);
  assert.equal(await page.locator('#NAV-C').count(), 0);
  assert.equal(queryCalls, 0);
  async function run(query, id) {
    await page.locator('#NAV-Q').click();
    await page.locator('#Q-FUNC').selectOption(query);
    if (id) {
      await page.locator('#Q-ID option[value="'+id+'"]').waitFor({state:'attached'});
      await page.locator('#Q-ID').selectOption(id);
    }
    const response = page.waitForResponse(r => r.url().endsWith('/admin/nessie/query'));
    await page.locator('#Q-RUN').click();
    const body = await (await response).json();
    await page.locator('#Q-SAVE').waitFor();
    return body;
  }
  const customerResult = await run('customers.list');
  const accountResult = await run('accounts.list');
  const customer = customerResult.response_body[0].resource_id;
  const account = accountResult.response_body[0].resource_id;
  assert.match(customer, /^customer_[0-9a-f]{32}$/);
  assert.match(account, /^acct_[0-9a-f]{32}$/);
  const overview = await (await page.request.post('http://127.0.0.1:5174/api/v1/workspace/refresh', {data:{}})).json();
  for (const row of overview.accounts) {
    assert(accountResult.response_body.some(account=>account.resource_id===row.account_token));
    assert.equal(overview.transactions.filter(tx=>tx.account_token===row.account_token&&tx.kind==='transfer').length,10);
  }
  for (const [query, id] of [['accounts.get',account], ['accounts.by_customer',customer],
    ['deposits.by_account',account], ['withdrawals.by_account',account],
    ['purchases.by_account',account], ['transfers.by_account',account]]) {
    const result = await run(query,id);
    assert.equal(result.http_status,200);
    assert(!JSON.stringify(result.response_body).includes('description'));
    assert(!JSON.stringify(result.response_body).includes('"_id"'));
    if (query==='transfers.by_account') assert.equal(result.response_body.length,10);
  }
  assert.equal(queryCalls,8);
  await page.locator('#Q-JSON').click();
  await page.locator('#Q-RESULT pre').waitFor();
  await page.locator('#Q-TABLE').click();
  assert.equal(queryCalls,8);
  const queryTable = page.locator('#Q-RESULT .tablewrap');
  await queryTable.evaluate(element=>{
    element.style.flex = 'none';
    element.style.height = Math.floor(element.scrollHeight / 1.3)+'px';
    element.parentElement.style.flex = 'none';
  });
  const queryPages = page.locator('#Q-RESULT').getByRole('group',{name:'Pages',exact:true});
  await queryPages.getByRole('button',{name:'Next page',exact:true}).click();
  await page.waitForFunction(()=>!document.querySelector('#Q-RESULT button[aria-label="Previous page"]').disabled);
  await queryPages.getByRole('button',{name:'Previous page',exact:true}).click();
  await queryTable.evaluate(element=>{
    element.removeAttribute('style'); element.parentElement.removeAttribute('style');
  });
  await toUser('Activity');
  await page.getByRole('heading',{name:'Every transaction.',exact:true}).waitFor();
  assert.equal(await page.locator('.account-context').count(),0);
  assert.equal(await page.locator('.inspect').count(),0);
  assert.deepEqual(await page.locator('.txtable th').allTextContents(),['Merchant','When','Check result','Amount']);
  assert.equal(await page.locator('.txtable tbody tr').count(),overview.transactions.length);
  async function checkLedgerPages() {
    const ledger = page.locator('.workspace').first();
    const pages = ledger.getByRole('group',{name:'Pages',exact:true});
    await pages.waitFor();
    await assertStableScale();
    const next = pages.getByRole('button',{name:'Next page',exact:true});
    for (let i=0;i<20 && !await next.isDisabled();i++) {
      const before = await pages.innerText();
      await next.click();
      await page.waitForFunction(text=>{
        const group = document.querySelector('.workspace .pager');
        return group && group.innerText !== text;
      },before);
    }
    assert(await next.isDisabled(),'all ledger pages must be reachable');
    assert(await pages.getByRole('button',{name:'Previous page',exact:true}).isEnabled());
    await page.waitForFunction(()=>{
      const table = document.querySelector('.workspace .tablewrap');
      const last = table.querySelector('tbody tr:last-child').getBoundingClientRect();
      return last.bottom <= table.getBoundingClientRect().bottom + 1;
    });
    const before = await pages.innerText();
    await pages.getByRole('button',{name:'Previous page',exact:true}).click();
    await page.waitForFunction(text=>document.querySelector('.workspace .pager').innerText !== text,before);
    await ledger.locator('.sortpick select').selectOption('largest');
    await page.waitForFunction(()=>document.querySelector('.workspace .tablewrap').scrollTop === 0);
    assert.equal(await ledger.locator('tbody tr').first().locator('td.amount').innerText(),'$849.00');
  }
  await checkLedgerPages();
  await toConsole();
  assert((await page.locator('#Q-RESULT').innerText()).includes('transfers.by_account'));
  await page.locator('#Q-FUNC').selectOption('accounts.get');
  assert.equal(await page.locator('#Q-ID').evaluate(element=>element.tagName),'SELECT');
  assert(await page.locator('#Q-RUN').isDisabled());
  const metadata = await (await page.request.get('http://127.0.0.1:5174/api/v1/admin/nessie/history')).json();
  assert(metadata.items.every(row=>!('response_body' in row)&&!('resource_id' in row)));
  await page.locator('#NAV-H').click();
  await page.locator('#H-MORE').click();
  await page.locator('#H-MORE').waitFor({state:'detached'});
  assert((await page.locator('#V-HISTORY tbody tr').count())>50);
  const target = page.locator('#H-DELETE-'+customerResult.history_id);
  await target.click();
  await page.locator('#D-CANCEL').click();
  assert.equal(deletes,0);
  assert(await target.evaluate(element=>element===document.activeElement));
  await target.click(); await page.keyboard.press('Escape');
  assert.equal(deletes,0);
  await target.click(); await page.locator('#D-CONFIRM').click();
  await target.waitFor({state:'detached'});
  assert.equal(deletes,1);

  let releaseOldHistory;
  const held = new Promise(resolve=>{releaseOldHistory=resolve;});
  let capturedOldHistory;
  const captured = new Promise(resolve=>{capturedOldHistory=resolve;});
  await page.route('**/admin/nessie/history',async route=>{
    const response = await route.fetch();
    capturedOldHistory();
    await held;
    await route.fulfill({response});
  },{times:1});
  await page.locator('#NAV-H').click();
  await captured;
  await page.locator('#H-CLEAR').click(); await page.locator('#D-CONFIRM').click();
  await page.getByText('尚無已儲存歷史。',{exact:true}).waitFor();
  const delayed = page.waitForResponse(r=>r.url().endsWith('/admin/nessie/history')&&r.request().method()==='GET');
  releaseOldHistory(); await delayed;
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  assert.equal(await page.locator('#V-HISTORY tbody tr').count(),0);

  async function fakeQuery(result) {
    await page.route('**/admin/nessie/query',route=>route.fulfill({json:result}),{times:1});
    return run('customers.list');
  }
  await fakeQuery({...customerResult,http_status:401,response_body:null,body_format:'none'});
  await page.getByText('Nessie API 錯誤：HTTP 401',{exact:true}).waitFor();
  await fakeQuery({...customerResult,http_status:null,response_body:null,body_format:'none',
    transport_error:{type:'timeout',message:'Nessie request did not complete.'}});
  await page.getByText('timeout',{exact:true}).waitFor();
  await fakeQuery({...customerResult,history_id:null,write_status:'failed',write_label:'failed to write'});
  await page.getByText('failed to write',{exact:true}).waitFor();
  await fakeQuery({...customerResult,response_body:[]});
  await page.getByText('查詢成功，沒有資料。',{exact:true}).waitFor();
  await fakeQuery({...customerResult,response_body:[{value:'<script>window.injected=true</script>'}]});
  assert.equal(await page.evaluate(()=>window.injected),undefined);

  await toToday();
  await page.getByRole('button',{name:/Unusual amount/}).first().click();
  await page.getByRole('heading',{name:'AI second opinion'}).waitFor();
  assert.equal(analysisCalls,0,'navigation must not call inference');
  await page.getByRole('button',{name:'Analyze with Jev'}).click();
  await page.getByText('Rules-only analysis',{exact:true}).waitFor();
  assert.equal(analysisCalls,1);
  await page.getByRole('link',{name:'Inspect exactly what is shared'}).click();
  await page.getByRole('heading',{name:'The complete payload'}).waitFor();
  assert.equal(await page.locator('.payload > div').count(),8);
  await page.goBack();
  await page.getByRole('radio',{name:/looks normal/}).click();
  assert.match(await page.locator('.consent').innerText(),/stored with Backboard when it is configured, otherwise in the local fallback/);
  assert(!(await page.getByRole('checkbox').isChecked()));
  await page.getByRole('checkbox').check();
  const confirmedCase = page.url();
  let releaseConfirmation, captureConfirmation;
  const confirmationHeld = new Promise(resolve=>{releaseConfirmation=resolve;});
  const confirmationCaptured = new Promise(resolve=>{captureConfirmation=resolve;});
  await page.route('**/api/v1/alerts/*/confirmations',async route=>{
    captureConfirmation(); await confirmationHeld; await route.continue();
  },{times:1});
  await page.getByRole('button',{name:'Confirm normal and remember',exact:true}).click();
  await confirmationCaptured;
  assert.equal(await page.getByRole('button',{name:'Refresh',exact:true}).count(),0);
  await toConsole();
  await page.locator('#NAV-CUSTOMERS').click();
  await page.locator('#C-SELECT option').nth(1).waitFor({state:'attached'});
  const firstCustomer = await page.locator('#C-SELECT option').nth(1).getAttribute('value');
  await page.locator('#C-SELECT').selectOption(firstCustomer);
  await page.locator('#V-CUSTOMERS .startcard').waitFor();
  await toToday();
  releaseConfirmation();
  await userGoto(page, confirmedCase);
  await page.getByText('Memory saved',{exact:true}).waitFor();
  const memoryEntry = page.waitForResponse(response=>response.url().endsWith('/api/v1/workspace/refresh'));
  await toUser(/^Memory/);
  await memoryEntry;
  await page.getByRole('button',{name:'Delete memory',exact:true}).click();
  await page.getByRole('button',{name:'Keep it',exact:true}).click();
  assert.equal(await page.locator('.memory').count(),1);
  await page.getByRole('button',{name:'Delete memory',exact:true}).click();
  let releaseMemoryDelete, captureMemoryDelete;
  const deleteHeld = new Promise(resolve=>{releaseMemoryDelete=resolve;});
  const deleteCaptured = new Promise(resolve=>{captureMemoryDelete=resolve;});
  await page.route('**/api/v1/memories/*',async route=>{
    captureMemoryDelete(); await deleteHeld; await route.continue();
  },{times:1});
  await page.getByRole('button',{name:'Yes, delete this memory',exact:true}).click();
  await deleteCaptured;
  assert.equal(await page.getByRole('button',{name:'Refresh',exact:true}).count(),0);
  await toUser('Activity');
  await page.getByRole('heading',{name:'Every transaction.',exact:true}).waitFor();
  await toUser(/^Memory/);
  releaseMemoryDelete();
  await page.getByText('Nothing is remembered yet.',{exact:true}).waitFor();
  assert.equal(analysisCalls,1);
  await toConsole();
  const sourceMemoryEntry = page.waitForResponse(response=>response.url().endsWith('/api/v1/workspace/refresh'));
  await toUser('Memory');
  await sourceMemoryEntry;
  await page.getByText('Nothing is remembered yet.',{exact:true}).waitFor();
  const manualRefresh = page.waitForResponse(response=>response.url().endsWith('/api/v1/workspace/refresh'));
  await page.getByRole('button',{name:'Refresh memories',exact:true}).click();
  await manualRefresh;
  await toConsole();
  let releaseRefresh, captureRefresh;
  const refreshHeld = new Promise(resolve=>{releaseRefresh=resolve;});
  const refreshCaptured = new Promise(resolve=>{captureRefresh=resolve;});
  await page.route('**/api/v1/workspace/refresh',async route=>{
    captureRefresh(); await refreshHeld; await route.continue();
  },{times:1});
  // Hold the navigation refresh; holding an earlier automatic read can disable the manual button.
  await toUser(/^Memory/);
  await refreshCaptured;
  await toConsole();
  await toUser(/^Memory/);
  const memoryAfterLoading = page.waitForRequest(request=>request.url().endsWith('/api/v1/workspace/refresh'));
  releaseRefresh();
  await memoryAfterLoading;
  await page.waitForFunction(()=>!document.querySelector('button[aria-label="Refresh memories"]').disabled);
  await toConsole();
  await run('accounts.list');
  mkdirSync(join(root,'artifacts'),{recursive:true});
  await page.screenshot({path:join(root,'artifacts/admin-desktop.png'),fullPage:true});
  for (const width of [1024,320,390,768]) {
    await page.setViewportSize({width,height:900});
    for (const view of ['#NAV-Q','#NAV-H']) {
      await page.locator(view).click();
      await assertResponsiveBaseline();
    }
  }
  await page.screenshot({path:join(root,'artifacts/admin-mobile.png'),fullPage:true});
  await page.setViewportSize({width:1440,height:1000});
  await page.locator('#NAV-CUSTOMERS').click();
  await page.locator('#C-SELECT option').nth(1).waitFor({state:'attached'});
  const customerCodes = await page.locator('#C-SELECT option').evaluateAll(rows=>rows.map(row=>row.value).filter(Boolean));
  await page.locator('#C-SELECT').selectOption(customerCodes[0]);
  const workspace = page.locator('#V-CUSTOMERS .workspace');
  const customerNav = page.getByRole('navigation',{name:'Customer workspace',exact:true});
  await workspace.getByRole('button',{name:/^Spending/}).getByText(/Nessie sandbox transactions/).waitFor();
  await workspace.getByRole('button',{name:/^Subscriptions/}).click();
  await workspace.getByRole('button',{name:/^Recurring/}).waitFor();
  assert(page.url().endsWith('/sources/'+customerCodes[0]+'/activity/recurring'));
  assert.equal(await workspace.getByRole('button',{name:/^Recurring/}).getAttribute('aria-pressed'),'true');
  await customerNav.getByRole('link',{name:'Today',exact:true}).click();
  await workspace.getByRole('button',{name:/^Spending/}).click();
  assert(page.url().endsWith('/sources/'+customerCodes[0]+'/activity'));
  await customerNav.getByRole('link',{name:'Activity',exact:true}).click();
  await workspace.getByRole('heading',{name:'Every transaction.',exact:true}).waitFor();
  assert.equal(await workspace.locator('tbody tr').count(),overview.transactions.length);
  await workspace.getByText('Unusual amount',{exact:true}).first().waitFor();
  await workspace.locator('tbody tr').filter({has:page.getByText('Unusual amount',{exact:true})}).getByRole('button').first().click();
  assert.equal(explanationCalls,0,'browsing must not request explanations');
  const customerExplanation = page.waitForResponse(response=>response.url().endsWith('/explanation'));
  await workspace.getByRole('button',{name:'Explain this alert',exact:true}).click();
  const explained = await customerExplanation;
  assert(explained.url().includes('/customers/'+customerCodes[0]+'/transactions/'));
  assert.equal(explained.status(),200);
  assert.equal((await explained.json()).explanation_mode,'template');
  await workspace.getByText('Rules explanation',{exact:true}).waitFor();
  await assertStableScale();
  assert.equal(explanationCalls,1);
  await workspace.getByRole('radio',{name:/looks normal/}).click();
  const customerConsent = workspace.getByRole('checkbox');
  assert(!(await customerConsent.isChecked()));
  assert.equal(await customerConsent.evaluate(element=>getComputedStyle(element).width),'18px',
    'customer review must retain the shared consent checkbox size');
  await workspace.getByRole('radio',{name:'Needs further review',exact:false}).click();
  await workspace.getByRole('button',{name:'Confirm needs review',exact:true}).click();
  await workspace.getByText('You marked this for review',{exact:true}).waitFor();
  await customerNav.getByRole('link',{name:'Activity',exact:true}).click();
  await workspace.locator('tbody tr').filter({hasText:'Unusual amount · review'}).getByRole('button').first().click();
  await workspace.getByText('You marked this for review',{exact:true}).waitFor();
  await customerNav.getByRole('link',{name:'Activity',exact:true}).click();
  await workspace.locator('tbody tr').filter({hasText:'No rule triggered'}).getByRole('button').first().click();
  await workspace.getByRole('heading',{name:'AI second opinion',exact:true}).waitFor();
  assert(page.url().includes('/sources/'+customerCodes[0]+'/case/'));
  await workspace.getByRole('link',{name:'Inspect exactly what is shared'}).click();
  await workspace.getByRole('heading',{name:'The complete payload'}).waitFor();
  assert.equal(await workspace.locator('.payload > div').count(),8);
  assert.equal(await page.locator('#V-CUSTOMERS').evaluate(element=>element.scrollTop),0,
    'customer navigation must return to the top without changing scale');
  await assertStableScale();
  await page.screenshot({path:join(root,'artifacts/v031-customer-privacy-after.png')});
  await page.locator('#C-SELECT').selectOption(customerCodes[1]);
  await customerNav.getByRole('link',{name:'Activity',exact:true}).click();
  await workspace.getByRole('heading',{name:'Every transaction.',exact:true}).waitFor();
  assert.equal(await workspace.getByText('Unusual amount · review',{exact:true}).count(),0);
  const customerMemoryEntry = page.waitForResponse(response=>response.url().includes('/customers/'+customerCodes[1]+'/workspace/refresh'));
  await customerNav.getByRole('link',{name:'Memory',exact:true}).click();
  await customerMemoryEntry;
  await workspace.getByText('Nothing is remembered yet.',{exact:true}).waitFor();
  await page.locator('#C-SELECT').selectOption(customerCodes[0]);
  await customerNav.getByRole('link',{name:'Activity',exact:true}).click();
  await workspace.locator('tbody tr').filter({hasText:'Unusual amount · review'}).getByRole('button').first().waitFor();
  for (const width of [1024,320,390,768]) {
    await page.setViewportSize({width,height:900});
    await assertResponsiveBaseline();
  }
  await page.screenshot({path:join(root,'artifacts/customer-workspace.png'),fullPage:true});
  await page.setViewportSize({width:1440,height:1000});
  await page.reload();
  await workspace.getByRole('heading',{name:'Every transaction.',exact:true}).waitFor();
  await page.locator('.sourcegrid').getByText('Nessie sandbox',{exact:true}).waitFor();
  assert.match(await page.locator('.statusbtn').innerText(),/Nessie sandbox/);
  await toUser('Activity');
  await page.locator('.workspace:visible').getByText('Unusual amount · normal',{exact:true}).first().waitFor();
  for (const width of [1024,320,390,768]) {
    await page.setViewportSize({width,height:900});
    await assertResponsiveBaseline();
  }
  await page.setViewportSize({width:1440,height:1000});
  await page.screenshot({path:join(root,'artifacts/connected-overview.png'),fullPage:true});
  await page.route('**/api/v1/alerts',route=>route.fulfill({status:503,json:{error:{code:'unavailable'}}}),{times:1});
  await page.reload();
  const unavailable = page.locator('.workspace:visible');
  await unavailable.getByText('Analysis unavailable',{exact:true}).first().waitFor();
  assert.equal(await unavailable.getByText('No rule triggered',{exact:true}).count(),0);
  await unavailable.locator('.rowlink').first().click();
  assert.equal(await unavailable.getByText('No applicable rule was triggered',{exact:false}).count(),0);
  assert.equal(await unavailable.getByRole('radio').count(),0);
  assert(await unavailable.getByRole('button',{name:'Analyze with Jev',exact:true}).isDisabled());
  assert(await unavailable.getByRole('button',{name:'Explain this alert',exact:true}).isDisabled());
  await page.locator('.toasts').getByRole('button',{name:'Retry',exact:true}).click();
  await toUser('Activity');
  await unavailable.getByText('No rule triggered',{exact:true}).first().waitFor();
  const cachedCount = await unavailable.locator('tbody tr').count();
  await page.route('**/api/v1/workspace/refresh',route=>route.fulfill({status:502,
    json:{error:{code:'nessie_unavailable'}}}),{times:1});
  await toUser(/^Memory/);
  await page.locator('.toasts').getByRole('button',{name:'Retry',exact:true}).waitFor();
  await toUser('Activity');
  await unavailable.getByText('Analysis unavailable',{exact:true}).first().waitFor();
  assert.equal(await unavailable.locator('tbody tr').count(),cachedCount);
  assert.equal(await unavailable.getByText('No rule triggered',{exact:true}).count(),0);
  await page.locator('.toasts').getByRole('button',{name:'Retry',exact:true}).click();
  await unavailable.getByText('Unusual amount',{exact:true}).first().waitFor();
  await unavailable.locator('tbody tr').filter({has:page.getByText('Unusual amount',{exact:true})}).getByRole('button').first().click();
  await unavailable.getByRole('radio',{name:/Needs further review/}).click();
  await page.route('**/api/v1/workspace/refresh',route=>route.fulfill({status:502,
    json:{error:{code:'nessie_unavailable'}}}),{times:1});
  await unavailable.getByRole('button',{name:'Confirm needs review',exact:true}).click();
  await page.locator('.toasts').getByText('Your decision was recorded. Refresh to load its current state.',{exact:true}).waitFor();
  assert.equal(await unavailable.getByText('Nothing was recorded',{exact:false}).count(),0);
  await page.locator('.toasts').getByRole('button',{name:'Retry',exact:true}).click();
  await unavailable.getByText('You marked this for review',{exact:true}).waitFor();

  await page.close();
  await new Promise(resolve=>{connectedBackend.once('exit',resolve);connectedBackend.kill('SIGTERM');});
  const syntheticLogs = start(resolve(root, 'backend/.venv/bin/python'),
    ['backend/tests/admin_console_server.py'], {PYTHONPATH:'backend', APP_ENV: 'test', TRANSACTION_PROVIDER:'synthetic',
      DATABASE_PATH:join(temp,'synthetic.db'), FRONTEND_ORIGIN:'http://127.0.0.1:5174'});
  const syntheticBackend = children.at(-1);
  await ready('http://127.0.0.1:8123/api/v1/health',syntheticLogs);
  // The restarted synthetic server gets a fresh context, with no previous faults or connections.
  page = await appPage();
  await userGoto(page, 'http://127.0.0.1:5174/#/activity');
  await page.reload();
  await page.getByText('Synthetic demo data.',{exact:true}).waitFor();
  assert.equal(await page.locator('.txtable tbody tr').count(),18);
  const offline = await (await page.request.post('http://127.0.0.1:5174/api/v1/workspace/refresh', {data:{}})).json();
  assert.equal(offline.data_mode,'synthetic');
  assert.equal(offline.transactions.filter(row=>row.kind==='transfer').length,10);
  await toToday();
  await page.locator('.queuerow').first().waitFor();
  assert.equal(await page.locator('.queuerow').count(),3);
  const widgets = page.getByRole('region',{name:'Widgets',exact:true});
  await widgets.getByRole('button',{name:'Edit',exact:true}).click();
  await widgets.getByRole('button',{name:'Remove Privacy',exact:true}).click();
  await widgets.getByRole('button',{name:'Move Spending later',exact:true}).click();
  await widgets.getByRole('button',{name:'Done',exact:true}).click();
  await assertStableScale();
  await page.reload();
  await page.locator('.queuerow').first().waitFor();
  assert.equal(await widgets.getByRole('button',{name:/^Privacy/}).count(),0);
  assert.equal(await widgets.locator('.wlabel').first().innerText(),'Memory');
  await assertStableScale();
  await widgets.getByRole('button',{name:'Edit',exact:true}).click();
  await widgets.getByRole('button',{name:'Reset',exact:true}).click();
  await widgets.getByRole('button',{name:'Done',exact:true}).click();
  await widgets.getByRole('button',{name:/^Privacy/}).waitFor();
  for (const [name, theme] of [['Dark mode','dark'],['Light mode','light'],['Match my device',null]]) {
    await page.getByRole('button',{name,exact:true}).click();
    assert.equal(await page.locator('html').getAttribute('data-theme'),theme);
    assert.equal(await page.getByRole('button',{name,exact:true}).getAttribute('aria-pressed'),'true');
  }
  await openMenu('Activity');
  await page.getByRole('button',{name:/Flagged only/}).click();
  await page.waitForURL('**/#/activity/flagged');
  await page.locator('.txtable tbody tr').nth(2).waitFor();
  assert.equal(await page.locator('.txtable tbody tr').count(),3);
  await openMenu('Activity');
  await page.getByRole('button',{name:/Recurring charges/}).click();
  await page.waitForURL('**/#/activity/recurring');
  await page.getByRole('button',{name:/^Recurring/,pressed:true}).waitFor();
  assert.equal(await page.getByRole('button',{name:/^Recurring/}).getAttribute('aria-pressed'),'true');
  await toToday();
  await page.getByRole('button',{name:/Possible duplicate/}).click();
  await page.getByRole('heading',{name:'AI second opinion',exact:true}).waitFor();
  assert.equal(analysisCalls,1,'neither customer browsing nor synthetic navigation invokes inference');
  assert.equal(explanationCalls,1,'only the explicit customer explanation requested text');
  const syntheticExplanation = page.waitForResponse(response=>response.url().endsWith('/explanation'));
  await page.getByRole('button',{name:'Explain this alert',exact:true}).click();
  const explanation = await syntheticExplanation;
  assert(explanation.url().includes('/api/v1/transactions/txn_syn_004/explanation'));
  assert.equal((await explanation.json()).sent_to_provider,false);
  await page.getByText('Rules explanation',{exact:true}).waitFor();
  await assertStableScale();
  await toToday();
  await page.route('**/api/v1/workspace/refresh',async route=>{
    const response = await route.fetch();
    const snapshot = await response.json();
    snapshot.transactions.push(
      {...snapshot.transactions[0],id:'txn_widget_credit',kind:'transfer',direction:'credit',amount:10000},
      {...snapshot.transactions[0],id:'txn_widget_unknown',kind:'transfer',direction:'unknown',amount:20000});
    await route.fulfill({response,json:snapshot});
  });
  await page.reload();
  await widgets.getByRole('button',{name:/^Spending/}).getByText(/20 synthetic transactions/).waitFor();
  await widgets.getByRole('button',{name:/^Largest charge/}).getByText('$849.00',{exact:true}).waitFor();
  await page.route('**/api/v1/workspace/refresh',async route=>{
    const response = await route.fetch();
    const snapshot = await response.json();
    snapshot.transactions = Array.from({length:100},(_,index)=>({
      ...snapshot.transactions[index % snapshot.transactions.length],id:'txn_page_'+index}));
    await route.fulfill({response,json:snapshot});
  });
  await userGoto(page, 'http://127.0.0.1:5174/#/activity');
  await page.reload();
  await page.locator('.txtable tbody tr').nth(99).waitFor({state:'attached'});
  await checkLedgerPages();
  const phone = await browser.newPage({viewport:{width:390,height:844},hasTouch:true,isMobile:true,reducedMotion:'reduce'});
  phone.on('pageerror',error=>errors.push(error.message));
  await phone.route('**/*',route=>['127.0.0.1','localhost'].includes(new URL(route.request().url()).hostname)
    ? route.continue() : route.abort());
  const phoneIn = await phone.request.post('http://127.0.0.1:5174/api/v1/auth/login',
    {data: {role: 'user', passcode: 'browser-user-pass'}});
  assert.equal(phoneIn.status(), 200, 'test user sign-in');
  await phone.goto('http://127.0.0.1:5174/#/activity');
  await phone.locator('.txtable tbody tr').nth(17).waitFor({state:'attached'});
  assert.equal(await phone.locator('html').getAttribute('data-stage'),null);
  assert(await phone.evaluate(()=>document.documentElement.scrollWidth <= innerWidth+1));
  await phone.locator('.rowlink').last().click();
  await phone.getByRole('heading',{name:'AI second opinion',exact:true}).waitFor();
  await phone.getByRole('link',{name:'Inspect exactly what is shared',exact:true}).click();
  await phone.locator('.payload > div').nth(7).waitFor();
  await phone.screenshot({path:join(root,'artifacts/v031-phone.png'),fullPage:true});
  await phone.close();
  // Real source API/SQLite integration; source selection never changes product or inference state.
  const previousAnalysis = analysisCalls, previousExplanation = explanationCalls;
  await toConsole();
  await page.locator('#NAV-DATA').click();
  const sourceLedger = page.locator('#V-SOURCES');
  await sourceLedger.getByText('No imported transactions for this source.',{exact:true}).waitFor();
  const firstSourceRefresh = page.waitForResponse(response=>response.url().endsWith('/data-sources/nessie/refresh'));
  await sourceLedger.locator('#S-REFRESH').click();
  assert.equal((await firstSourceRefresh).status(),200);
  await sourceLedger.locator('tbody tr').first().waitFor();
  assert((await sourceLedger.innerText()).includes('Unknown merchant'));
  assert.equal(await sourceLedger.locator('#S-NESSIE').getAttribute('aria-pressed'),'true');
  await sourceLedger.locator('#S-BANKSIM').click();
  await sourceLedger.getByText('30 transactions',{exact:true}).waitFor();
  assert((await sourceLedger.locator('tbody').innerText()).includes('€180.01'));
  assert((await sourceLedger.locator('tbody').innerText()).includes('Simulation day 120'));
  assert.equal(await sourceLedger.getByRole('link',{name:'Review transaction'}).count(),0);
  assert.equal(await sourceLedger.locator('tbody tr').count(),25);
  await assertStableScale();
  await page.screenshot({path:join(root,'artifacts/v050-source-banksim.png'),fullPage:true});
  await sourceLedger.locator('#S-NEXT').click();
  await sourceLedger.getByText('26–30 of 30',{exact:true}).waitFor();
  assert.equal(await sourceLedger.locator('tbody tr').count(),5);
  await sourceLedger.locator('#S-NESSIE').click();
  await sourceLedger.locator('tbody tr').first().waitFor();
  const sourceRefresh = page.waitForResponse(response=>response.url().endsWith('/data-sources/nessie/refresh'));
  await sourceLedger.locator('#S-REFRESH').click();
  const sourceResult = await (await sourceRefresh).json();
  assert.equal(sourceResult.source,'nessie');
  assert(sourceResult.items.every(row=>row.source==='nessie' && row.currency==='USD' && !('owner' in row) && !('fraud' in row)));
  await sourceLedger.locator('tbody tr').first().waitFor();
  let releaseBankSim, captureBankSim;
  const heldBankSim = new Promise(resolve=>{releaseBankSim=resolve;});
  const capturedBankSim = new Promise(resolve=>{captureBankSim=resolve;});
  await page.route('**/data-sources/banksim/transactions?*',async route=>{
    const response = await route.fetch();
    captureBankSim(); await heldBankSim; await route.fulfill({response});
  },{times:1});
  await sourceLedger.locator('#S-BANKSIM').click();
  await capturedBankSim;
  assert.equal(await sourceLedger.locator('tbody tr').count(),0,'switch clears the previous source immediately');
  await sourceLedger.locator('#S-NESSIE').click();
  await sourceLedger.locator('tbody tr').first().waitFor();
  const lateBankSim = page.waitForResponse(response=>response.url().includes('/data-sources/banksim/transactions'));
  releaseBankSim(); await lateBankSim;
  assert.equal(await sourceLedger.locator('#S-NESSIE').getAttribute('aria-pressed'),'true');
  assert(!(await sourceLedger.locator('tbody').innerText()).includes('Simulation day'));
  assert.equal(analysisCalls,previousAnalysis,'source browsing does not invoke Jev');
  assert.equal(explanationCalls,previousExplanation,'source browsing does not invoke Gemini');
  await assertStableScale();
  await page.screenshot({path:join(root,'artifacts/v050-source-nessie.png'),fullPage:true});
  await sourceLedger.getByRole('link',{name:'Review current Nessie transactions',exact:true}).click();
  await page.locator('#V-CUSTOMERS .today').waitFor();
  assert.equal(analysisCalls,previousAnalysis);
  assert.equal(explanationCalls,previousExplanation);
  // Generated source accounts reuse this table and cannot change source/owner on a late response.
  await toConsole();
  await page.locator('#NAV-DATA').click();
  await page.locator('#S-BANKSIM').click();
  await page.locator('#S-ACCOUNT').waitFor();
  await page.waitForFunction(()=>document.querySelectorAll('#S-ACCOUNT option').length===26);
  const bankOptions = await page.locator('#S-ACCOUNT option').evaluateAll(nodes=>nodes.map(n=>n.value).filter(Boolean));
  await page.locator('#S-ACCOUNT').selectOption(bankOptions[0]);
  await sourceLedger.getByText('110 transactions',{exact:true}).waitFor();
  assert((await sourceLedger.innerText()).includes('synthetic-derived'));
  assert((await sourceLedger.locator('tbody').innerText()).includes('€180.01'));
  for (let offset=25;offset<=100;offset+=25) {
    await page.locator('#S-NEXT').click();
    await sourceLedger.getByText(`${offset+1}–${Math.min(offset+25,110)} of 110`,{exact:true}).waitFor();
  }
  assert(await page.locator('#S-NEXT').isDisabled());
  await page.locator('#S-ACCOUNT-NEXT').click();
  await page.waitForFunction(()=>document.querySelectorAll('#S-ACCOUNT option').length===7);
  const lastBank = await page.locator('#S-ACCOUNT option').last().getAttribute('value');
  await page.locator('#S-ACCOUNT').selectOption(lastBank);
  await sourceLedger.getByText('1–25 of 110',{exact:true}).waitFor();
  await page.locator('#S-ACCOUNT-PREV').click();
  await page.waitForFunction(()=>document.querySelectorAll('#S-ACCOUNT option').length===27);
  let releaseAccount, captureAccount;
  const heldAccount = new Promise(resolve=>{releaseAccount=resolve;});
  const capturedAccount = new Promise(resolve=>{captureAccount=resolve;});
  await page.route('**/data-sources/banksim/transactions?*account_token=*',async route=>{
    const response=await route.fetch(); captureAccount(); await heldAccount; await route.fulfill({response});
  },{times:1});
  await page.locator('#S-ACCOUNT').selectOption(bankOptions[1]);
  await capturedAccount;
  assert.equal(await sourceLedger.locator('tbody tr').count(),0);
  await page.locator('#S-ACCOUNT').selectOption(bankOptions[0]);
  await sourceLedger.getByText('110 transactions',{exact:true}).waitFor();
  const lateAccount=page.waitForResponse(response=>response.url().includes('account_token='+bankOptions[1]));
  releaseAccount(); await lateAccount;
  assert.equal(await page.locator('#S-ACCOUNT').inputValue(),bankOptions[0]);
  await page.locator('#S-NESSIE').click();
  await page.waitForFunction(()=>document.querySelectorAll('#S-ACCOUNT option').length===3);
  const nessieCode=await page.locator('#S-ACCOUNT option').last().getAttribute('value');
  await page.locator('#S-ACCOUNT').selectOption(nessieCode);
  await sourceLedger.getByText('100 transactions',{exact:true}).waitFor();
  assert((await sourceLedger.locator('tbody').innerText()).includes('$1.24'));
  assert((await sourceLedger.locator('tbody').innerText()).includes('Date only'));
  const sourceKinds = new Set();
  let sourceRows = 0;
  for (let offset=0;offset<100;offset+=25) {
    if (offset) await sourceLedger.locator('#S-NEXT').click();
    await sourceLedger.getByText(`${offset+1}–${offset+25} of 100`,{exact:true}).waitFor();
    const kinds = await sourceLedger.locator('tbody tr td:first-child small').allTextContents();
    kinds.forEach(text=>sourceKinds.add(text.split(' · ').at(-1)));
    sourceRows += kinds.length;
  }
  assert.equal(sourceRows,100);
  assert.deepEqual([...sourceKinds].sort(),['deposit','purchase','transfer','withdrawal']);
  assert(await sourceLedger.locator('#S-NEXT').isDisabled());
  assert.equal(analysisCalls,previousAnalysis);
  assert.equal(explanationCalls,previousExplanation);
  await page.screenshot({path:join(root,'artifacts/account-demo-nessie.png'),fullPage:true});
  // A user's generated history must be the same account/IDs as the source table, not the 18-row fixture.
  await page.close();
  await new Promise(resolve=>{syntheticBackend.once('exit',resolve);syntheticBackend.kill('SIGTERM');});
  const userAccount = 'acct_' + '0'.repeat(32);
  const accountLogs = start(resolve(root, 'backend/.venv/bin/python'),
    ['backend/tests/admin_console_server.py'], {PYTHONPATH:'backend', APP_ENV: 'test', TRANSACTION_PROVIDER:'account-demo',
      DEMO_ACCOUNT_TOKEN:userAccount, DATABASE_PATH:join(temp,'account-user.db'),
      FRONTEND_ORIGIN:'http://127.0.0.1:5174'});
  await ready('http://127.0.0.1:8123/api/v1/health',accountLogs);
  page = await appPage();
  await userGoto(page, 'http://127.0.0.1:5174/#/activity');
  await page.getByText('Synthetic demo data.',{exact:true}).waitFor();
  await page.waitForFunction(()=>document.querySelectorAll('.txtable tbody tr').length===100);
  const view = await (await page.request.post('http://127.0.0.1:5174/api/v1/workspace/refresh',{data:{}})).json();
  const source = await (await page.request.get('http://127.0.0.1:5174/api/v1/data-sources/nessie/transactions?limit=100&account_token='+userAccount)).json();
  assert.equal(view.data_mode,'synthetic');
  assert.deepEqual(view.transactions.map(row=>row.id).sort(),source.items.map(row=>row.id).sort());
  assert(view.transactions.every(row=>row.account_token===userAccount && row.date_only && row.currency==='USD'));
  assert.equal(await page.locator('.txtable tbody tr').count(),100);
  await page.locator('.txtable tbody tr button').evaluateAll(nodes=>nodes.forEach((node,index)=>node.setAttribute('data-history-index',String(index))));
  const visited = new Set();
  const next = page.locator('.activity .pager').getByRole('button',{name:'Next page',exact:true});
  for (let count=0;count<100;count++) {
    const visible = await page.locator('.txtable tbody tr').evaluateAll(rows=>rows.filter(row=>{
      const r=row.getBoundingClientRect(),c=row.closest('.tablewrap').getBoundingClientRect();
      return r.top+r.height/2>=c.top && r.top+r.height/2<=c.bottom;
    }).map(row=>row.querySelector('button').getAttribute('data-history-index')));
    visible.forEach(index=>visited.add(index));
    if (await next.isDisabled()) break;
    const before = await page.locator('.activity .pager span').innerText();
    const target = await page.locator('.activity .tablewrap').evaluate((el, page) =>
      Math.min(el.scrollHeight - el.clientHeight, page * el.clientHeight), Number(before.split('/')[0]));
    await next.click();
    await page.waitForFunction(before=>document.querySelector('.activity .pager span').textContent!==before,before);
    // The page label rounds during smooth scrolling; inspect rows only at the destination.
    await page.waitForFunction(target=>Math.abs(document.querySelector('.activity .tablewrap').scrollTop-target)<=1,target);
  }
  assert(await next.isDisabled(),'all history pages terminate');
  assert.equal(visited.size,100,'each history row is reachable through the physical Pager');
  await page.locator('.txtable tbody tr').last().getByRole('button').click();
  await page.locator('.facts').getByText(view.transactions.at(-1).id,{exact:true}).waitFor();
  await page.locator('.facts').getByText(view.transactions.at(-1).direction === 'unknown'
    ? 'Direction unknown' : view.transactions.at(-1).direction,{exact:false}).waitFor();
  await page.getByRole('button',{name:'Activity',exact:true}).click();
  await page.getByRole('searchbox').fill('not-a-merchant');
  await page.getByText('No transactions match',{exact:false}).waitFor();
  await page.getByRole('button',{name:'Clear filters',exact:true}).click();
  assert.equal(await page.locator('.txtable tbody tr').count(),100);
  await page.getByRole('button',{name:/^Flagged/}).click();
  await page.getByText('No transactions match',{exact:false}).waitFor();
  await page.getByRole('button',{name:'Clear filters',exact:true}).click();
  await page.getByRole('combobox').selectOption('largest');
  assert.equal(await page.locator('.txtable tbody tr').count(),100);
  await toToday();
  await page.getByText(/100 transactions checked by the rules/).waitFor();
  await assertStableScale();
  assert.deepEqual(errors,[]);
  console.log('PASS: existing UI/Admin/review/privacy/memory baseline, synthetic 18 rows/3 alerts, Nessie/BankSim source isolation and generated 100-row user history with identical source IDs, physical paging, details, filters and sorting.');
} catch (error) {
  if (page) {
    console.error('Browser failure:', {url:page.url(),errors});
    console.error('API status:',apiStates.slice(-12));
    console.error('Workspace state:', (await page.locator('main').innerText().catch(()=>'<unavailable>')).slice(0,1000));
  }
  throw error;
} finally {
  await browser?.close();
  for (const child of children) child.kill('SIGTERM');
}
