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
let browser;
try {
  const frontendLogs = start(process.execPath, ['frontend/node_modules/vite/bin/vite.js',
    'frontend', '--host', '127.0.0.1', '--port', '5174'],
    {VITE_API_BASE_URL: 'http://127.0.0.1:8123'});
  const backendLogs = start(resolve(root, 'backend/.venv/bin/python'),
    ['backend/tests/admin_console_server.py'], {PYTHONPATH: 'backend',
      TRANSACTION_PROVIDER: 'nessie', DATABASE_PATH: join(temp, 'test.db'), FRONTEND_ORIGIN: 'http://127.0.0.1:5174'});
  const connectedBackend = children.at(-1);
  await Promise.all([ready('http://127.0.0.1:5174', frontendLogs),
    ready('http://127.0.0.1:8123/api/v1/health', backendLogs)]);
  const chrome = process.env.PLAYWRIGHT_CHROME_PATH;
  browser = await chromium.launch({headless: true, ...(chrome ? {executablePath: chrome} :
    existsSync('/Applications/Google Chrome.app') ? {channel: 'chrome'} : {})});
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
  page.setDefaultTimeout(5000);
  // The selected UI already overflows its unchanged filter group at 320px.
  async function assertResponsiveBaseline() {
    const layout = await page.evaluate(() => {
      const overflowing = [...document.querySelectorAll('body *')].filter(element => {
        const box = element.getBoundingClientRect();
        return box.width > 0 && box.right > innerWidth + 1;
      });
      return {width: innerWidth, scroll: document.documentElement.scrollWidth,
        inheritedFilterOnly: innerWidth === 320 && overflowing.length > 0 &&
          overflowing.every(element => element.closest('.seg')),
        elements: overflowing.map(element => ({tag: element.tagName, class: element.className}))};
    });
    assert(layout.scroll <= layout.width + 1 || layout.inheritedFilterOnly, JSON.stringify(layout));
  }
  const errors = [];
  let queryCalls = 0;
  let deletes = 0;
  let analysisCalls = 0;
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', req => {
    if (req.url().endsWith('/admin/nessie/query')) queryCalls++;
    if (req.method()==='DELETE') deletes++;
    if (req.url().endsWith('/analyses')) analysisCalls++;
  });
  await page.route('**/*', route => ['127.0.0.1', 'localhost'].includes(
    new URL(route.request().url()).hostname) ? route.continue() : route.abort());
  await page.goto('http://127.0.0.1:5174');
  await page.getByRole('link', {name: /^Today/}).waitFor();
  await page.locator('.startcard').waitFor();
  assert.equal(await page.locator('.workspacebar').count(), 0,
    'backend integration must preserve the approved UI without an added workspace toolbar');
  await page.locator('#NAV-ADMIN').click();
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
  const overview = await (await fetch('http://127.0.0.1:8123/api/v1/workspace/refresh', {
    method:'POST',headers:{'content-type':'application/json','origin':'http://127.0.0.1:5174'},body:'{}',
  })).json();
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
  await page.locator('.topbar').getByRole('link',{name:'Activity',exact:true}).click();
  await page.getByRole('heading',{name:'Every transaction.',exact:true}).waitFor();
  assert.equal(await page.locator('.account-context').count(),0);
  assert.equal(await page.locator('.inspect').count(),0);
  assert.deepEqual(await page.locator('.txtable th').allTextContents(),['Merchant','When','Check result','Amount']);
  assert.equal(await page.locator('.txtable tbody tr').count(),overview.transactions.length);
  await page.locator('#NAV-ADMIN').click();
  assert((await page.locator('#Q-RESULT').innerText()).includes('transfers.by_account'));
  await page.locator('#Q-FUNC').selectOption('accounts.get');
  assert.equal(await page.locator('#Q-ID').evaluate(element=>element.tagName),'SELECT');
  assert(await page.locator('#Q-RUN').isDisabled());
  const metadata = await (await fetch('http://127.0.0.1:8123/api/v1/admin/nessie/history')).json();
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

  await page.locator('.topbar').getByRole('link',{name:/^Today/}).click();
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
  await page.locator('#NAV-ADMIN').click();
  await page.locator('#NAV-CUSTOMERS').click();
  await page.locator('#C-SELECT option').nth(1).waitFor({state:'attached'});
  const firstCustomer = await page.locator('#C-SELECT option').nth(1).getAttribute('value');
  await page.locator('#C-SELECT').selectOption(firstCustomer);
  await page.locator('#V-CUSTOMERS .startcard').waitFor();
  await page.locator('.topbar').getByRole('link',{name:/^Today/}).click();
  releaseConfirmation();
  await page.goto(confirmedCase);
  await page.getByText('Memory saved',{exact:true}).waitFor();
  const memoryEntry = page.waitForResponse(response=>response.url().endsWith('/api/v1/workspace/refresh'));
  await page.locator('.topbar').getByRole('link',{name:/^Memory/}).click();
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
  await page.locator('.topbar').getByRole('link',{name:'Activity',exact:true}).click();
  await page.getByRole('heading',{name:'Every transaction.',exact:true}).waitFor();
  await page.locator('.topbar').getByRole('link',{name:/^Memory/}).click();
  releaseMemoryDelete();
  await page.getByText('Nothing is remembered yet.',{exact:true}).waitFor();
  assert.equal(analysisCalls,1);
  await page.locator('#NAV-ADMIN').click();
  const sourceMemoryEntry = page.waitForResponse(response=>response.url().endsWith('/api/v1/workspace/refresh'));
  await page.locator('.topbar').getByRole('link',{name:/^Memory/}).click();
  await sourceMemoryEntry;
  await page.getByText('Nothing is remembered yet.',{exact:true}).waitFor();
  let releaseRefresh, captureRefresh;
  const refreshHeld = new Promise(resolve=>{releaseRefresh=resolve;});
  const refreshCaptured = new Promise(resolve=>{captureRefresh=resolve;});
  await page.route('**/api/v1/workspace/refresh',async route=>{
    captureRefresh(); await refreshHeld; await route.continue();
  },{times:1});
  await page.getByRole('button',{name:'Refresh memories',exact:true}).click();
  await refreshCaptured;
  await page.locator('#NAV-ADMIN').click();
  await page.locator('.topbar').getByRole('link',{name:/^Memory/}).click();
  const memoryAfterLoading = page.waitForRequest(request=>request.url().endsWith('/api/v1/workspace/refresh'));
  releaseRefresh();
  await memoryAfterLoading;
  await page.waitForFunction(()=>!document.querySelector('button[aria-label="Refresh memories"]').disabled);
  await page.locator('#NAV-ADMIN').click();
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
  await customerNav.getByRole('link',{name:'Activity',exact:true}).click();
  await workspace.getByRole('heading',{name:'Every transaction.',exact:true}).waitFor();
  assert.equal(await workspace.locator('tbody tr').count(),overview.transactions.length);
  await workspace.getByText('Unusual amount',{exact:true}).first().waitFor();
  await workspace.locator('tbody tr').filter({has:page.getByText('Unusual amount',{exact:true})}).getByRole('button').first().click();
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
  await page.locator('.topbar').getByRole('link',{name:'Activity',exact:true}).click();
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
  await unavailable.getByRole('button',{name:'Retry',exact:true}).click();
  await page.locator('.topbar').getByRole('link',{name:'Activity',exact:true}).click();
  await unavailable.getByText('No rule triggered',{exact:true}).first().waitFor();
  const cachedCount = await unavailable.locator('tbody tr').count();
  await page.route('**/api/v1/workspace/refresh',route=>route.fulfill({status:502,
    json:{error:{code:'nessie_unavailable'}}}),{times:1});
  await page.locator('.topbar').getByRole('link',{name:/^Memory/}).click();
  await unavailable.getByRole('button',{name:'Retry',exact:true}).waitFor();
  await page.locator('.topbar').getByRole('link',{name:'Activity',exact:true}).click();
  await unavailable.getByText('Analysis unavailable',{exact:true}).first().waitFor();
  assert.equal(await unavailable.locator('tbody tr').count(),cachedCount);
  assert.equal(await unavailable.getByText('No rule triggered',{exact:true}).count(),0);
  await unavailable.getByRole('button',{name:'Retry',exact:true}).click();
  await unavailable.getByText('Unusual amount',{exact:true}).first().waitFor();
  await unavailable.locator('tbody tr').filter({has:page.getByText('Unusual amount',{exact:true})}).getByRole('button').first().click();
  await unavailable.getByRole('radio',{name:/Needs further review/}).click();
  await page.route('**/api/v1/workspace/refresh',route=>route.fulfill({status:502,
    json:{error:{code:'nessie_unavailable'}}}),{times:1});
  await unavailable.getByRole('button',{name:'Confirm needs review',exact:true}).click();
  await unavailable.getByText('Your decision was recorded. Refresh to load its current state.',{exact:true}).waitFor();
  assert.equal(await unavailable.getByText('Nothing was recorded',{exact:false}).count(),0);
  await unavailable.getByRole('button',{name:'Retry',exact:true}).click();
  await unavailable.getByText('You marked this for review',{exact:true}).waitFor();

  await new Promise(resolve=>{connectedBackend.once('exit',resolve);connectedBackend.kill('SIGTERM');});
  const syntheticLogs = start(resolve(root, 'backend/.venv/bin/python'),
    ['backend/tests/admin_console_server.py'], {PYTHONPATH:'backend', TRANSACTION_PROVIDER:'synthetic',
      DATABASE_PATH:join(temp,'synthetic.db'), FRONTEND_ORIGIN:'http://127.0.0.1:5174'});
  await ready('http://127.0.0.1:8123/api/v1/health',syntheticLogs);
  await page.goto('http://127.0.0.1:5174/#/activity');
  await page.reload();
  await page.getByText('Synthetic demo data.',{exact:true}).waitFor();
  assert.equal(await page.locator('.txtable tbody tr').count(),18);
  const offline = await (await fetch('http://127.0.0.1:8123/api/v1/workspace/refresh', {
    method:'POST',headers:{'content-type':'application/json','origin':'http://127.0.0.1:5174'},body:'{}',
  })).json();
  assert.equal(offline.data_mode,'synthetic');
  assert.equal(offline.transactions.filter(row=>row.kind==='transfer').length,10);
  await page.locator('.topbar').getByRole('link',{name:/^Today/}).click();
  await page.locator('.queuerow').first().waitFor();
  assert.equal(await page.locator('.queuerow').count(),3);
  await page.getByRole('button',{name:/Possible duplicate/}).click();
  await page.getByRole('heading',{name:'AI second opinion',exact:true}).waitFor();
  assert.equal(analysisCalls,1,'neither customer browsing nor synthetic navigation invokes inference');
  assert.deepEqual(errors,[]);
  console.log('PASS: new UI, eight safe queries/history, original ledger controls, scoped customers, consent/memory, cached failures, recorded-decision recovery, synthetic 18 rows/3 alerts and responsive checks (inherited 320px filter overflow only).');
} finally {
  await browser?.close();
  for (const child of children) child.kill('SIGTERM');
}
