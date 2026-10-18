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
      DATABASE_PATH: join(temp, 'test.db'), FRONTEND_ORIGIN: 'http://127.0.0.1:5174'});
  await Promise.all([ready('http://127.0.0.1:5174', frontendLogs),
    ready('http://127.0.0.1:8123/api/v1/health', backendLogs)]);
  const chrome = process.env.PLAYWRIGHT_CHROME_PATH;
  browser = await chromium.launch({headless: true, ...(chrome ? {executablePath: chrome} :
    existsSync('/Applications/Google Chrome.app') ? {channel: 'chrome'} : {})});
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
  page.setDefaultTimeout(5000);
  const errors = [];
  let queryCalls = 0;
  let deletes = 0;
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', req => {
    if (req.url().endsWith('/admin/nessie/query')) queryCalls++;
    if (req.method()==='DELETE') deletes++;
  });
  await page.route('**/*', route => ['127.0.0.1', 'localhost'].includes(
    new URL(route.request().url()).hostname) ? route.continue() : route.abort());
  await page.goto('http://127.0.0.1:5174');
  await page.locator('#NAV-ADMIN').click();
  await page.locator('#V-QUERY').waitFor();
  assert.equal(await page.locator('#Q-FUNC option').count(), 6);
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
  assert.match(account, /^account_[0-9a-f]{32}$/);
  for (const [query, id] of [['accounts.get',account], ['accounts.by_customer',customer],
    ['deposits.by_account',account], ['withdrawals.by_account',account]]) {
    const result = await run(query,id);
    assert.equal(result.http_status,200);
    assert(!JSON.stringify(result.response_body).includes('description'));
    assert(!JSON.stringify(result.response_body).includes('"_id"'));
  }
  assert.equal(queryCalls,6);
  await page.locator('#Q-JSON').click();
  await page.locator('#Q-RESULT pre').waitFor();
  await page.locator('#Q-TABLE').click();
  assert.equal(queryCalls,6);
  await page.getByRole('link',{name:/^Today/}).click();
  await page.locator('#NAV-ADMIN').click();
  assert((await page.locator('#Q-RESULT').innerText()).includes('withdrawals.by_account'));
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

  // Core journey: alert -> evidence -> explicit AI request -> human decision -> consented memory -> delete.
  let analysisCalls = 0;
  page.on('request', req => {if (req.url().endsWith('/analyses')) analysisCalls++;});
  await page.getByRole('link',{name:/^Today/}).click();
  await page.getByRole('button',{name:/Possible duplicate/}).click();
  await page.getByRole('heading',{name:'AI second opinion'}).waitFor();
  assert.equal(analysisCalls,0,'opening a case must never call analysis');
  await page.getByRole('button',{name:'Analyze with Jev'}).click();
  await page.getByText('Rules-only analysis',{exact:true}).waitFor();
  assert.equal(analysisCalls,1);
  await page.getByRole('link',{name:/Inspect exactly what is shared/}).click();
  await page.getByRole('heading',{name:'The complete payload'}).waitFor();
  assert.equal(await page.locator('.payload > div').count(),8);
  await page.goBack();
  await page.getByRole('radio',{name:/looks normal/}).click();
  assert.match(await page.locator('.consent').innerText(),/stored with Backboard when it is configured, otherwise in the local fallback/);
  assert(!(await page.getByRole('checkbox').isChecked()));
  await page.getByRole('checkbox').check();
  await page.getByRole('button',{name:/Confirm normal and remember/}).click();
  await page.getByText('Memory saved',{exact:true}).waitFor();
  assert.match(await page.locator('.callout',{hasText:'Memory saved'}).innerText(),/local fallback database, not on Backboard/);
  await page.getByRole('link',{name:/^Memory/}).click();
  await page.getByRole('button',{name:'Delete memory',exact:true}).click();
  await page.getByRole('button',{name:'Keep it'}).click();
  assert.equal(await page.locator('.memory').count(),1);
  await page.getByRole('button',{name:'Delete memory',exact:true}).click();
  await page.getByRole('button',{name:/Yes, delete/}).click();
  await page.getByText('Nothing is remembered yet.',{exact:true}).waitFor();
  assert.equal(analysisCalls,1);
  await page.locator('#NAV-ADMIN').click();
  await run('accounts.list');
  mkdirSync(join(root,'artifacts'),{recursive:true});
  await page.screenshot({path:join(root,'artifacts/admin-desktop.png'),fullPage:true});
  for (const width of [320,390,768]) {
    await page.setViewportSize({width,height:900});
    for (const view of ['#NAV-Q','#NAV-H']) {
      await page.locator(view).click();
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    }
  }
  await page.screenshot({path:join(root,'artifacts/admin-mobile.png'),fullPage:true});
  assert.deepEqual(errors,[]);
  console.log('PASS: six local-code queries, de-identified results, metadata-only history, disabled comparison, paging, delete/cancel/Escape/focus, stale-response protection, errors, consent/memory confirmation and responsive widths.');
} finally {
  await browser?.close();
  for (const child of children) child.kill('SIGTERM');
}
