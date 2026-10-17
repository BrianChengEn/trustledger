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
  assert.equal(await page.locator('#Q-ID').count(), 0);
  assert.equal(queryCalls, 0);
  const firstResults = [];
  async function run(query, id) {
    await page.locator('#NAV-Q').click();
    await page.locator('#Q-FUNC').selectOption(query);
    if (id) await page.locator('#Q-ID').fill(id);
    const response = page.waitForResponse(r => r.url().endsWith('/admin/nessie/query'));
    await page.locator('#Q-RUN').click();
    const body = await (await response).json();
    await page.locator('#Q-SAVE').waitFor();
    return body;
  }
  for (const [query, id] of [
    ['customers.list'], ['accounts.list'], ['accounts.get', 'a00000000000000000000001'],
    ['accounts.by_customer', 'c00000000000000000000001'],
    ['deposits.by_account', 'a00000000000000000000001'],
    ['withdrawals.by_account', 'a00000000000000000000001'],
  ]) {
    const body = await run(query, id);
    assert.equal(body.http_status, 200); firstResults.push(body);
    await page.locator('#Q-JSON').click();
    await page.locator('#Q-RESULT pre').waitFor();
    await page.locator('#Q-TABLE').click();
  }
  assert.equal(queryCalls, 6);
  await page.getByRole('button', {name:'Overview & transactions', exact:true}).click();
  await page.locator('#NAV-ADMIN').click();
  assert.equal(queryCalls, 6);
  assert((await page.locator('#Q-RESULT').innerText()).includes('withdrawals.by_account'));
  await page.locator('#Q-FUNC').selectOption('accounts.get');
  await page.locator('#Q-ID').fill('invalid');
  await page.locator('#Q-RUN').click();
  await page.getByRole('alert').filter({hasText:'24 位'}).waitFor();
  assert.equal(queryCalls, 6);
  const reordered = await run('accounts.list');
  const compareCalls = queryCalls;
  await page.locator('#NAV-H').click();
  await page.locator('#H-MORE').click();
  await page.locator('#H-MORE').waitFor({state:'detached'});
  assert((await page.locator('#V-HISTORY tbody tr').count())>50);
  await page.locator('#H-L-'+firstResults[1].history_id).check();
  await page.locator('#H-R-'+reordered.history_id).check();
  await page.locator('#H-COMPARE').click();
  await page.locator('#C-DIFF').getByRole('heading', {name:'資料未變更'}).waitFor();
  await page.locator('#C-JSON').click();
  assert.equal(await page.locator('#V-COMPARE pre').count(), 2);
  assert.equal(queryCalls, compareCalls);
  await page.locator('#C-BACK').click();
  await page.locator('#H-VIEW-'+firstResults[0].history_id).click();
  await page.locator('#H-DETAIL').waitFor();
  await page.locator('#H-JSON').click();
  assert.equal(queryCalls, compareCalls);
  await fetch('http://127.0.0.1:8123/api/v1/admin/nessie/history/'+reordered.history_id, {
    method:'DELETE', headers:{Origin:'http://127.0.0.1:5174', 'Content-Type':'application/json'},
    body:JSON.stringify({confirm:true}),
  });
  await page.locator('#H-COMPARE').click();
  await page.getByRole('alert').filter({hasText:'已刪除，請重新選擇'}).waitFor();
  assert(await page.locator('#H-COMPARE').isDisabled());
  const deleteButton = page.locator('#H-DELETE-'+firstResults[0].history_id);
  await deleteButton.click(); await page.locator('#D-CANCEL').click();
  assert.equal(deletes, 0);
  assert(await deleteButton.evaluate(el => el===document.activeElement));
  await deleteButton.click(); await page.keyboard.press('Escape');
  assert.equal(deletes, 0);
  await deleteButton.click(); await page.locator('#D-CONFIRM').click();
  await deleteButton.waitFor({state:'detached'});
  assert.equal(deletes, 1);
  const failedWrite = await run('accounts.get', 'e'.repeat(24));
  assert.equal(failedWrite.write_status, 'failed');
  assert.equal(await page.locator('#Q-SAVE').innerText(), 'failed to write');
  assert((await page.locator('#Q-RESULT').innerText()).includes('<script>'));
  assert.equal(await page.evaluate(() => window.injected), undefined);
  await run('deposits.by_account', 'a00000000000000000000011');
  await page.locator('#Q-TABLE').click();
  await page.getByText('查詢成功，沒有資料。', {exact:true}).waitFor();
  await run('accounts.get', 'd'.repeat(24));
  await page.getByText('Nessie API 錯誤：HTTP 401', {exact:true}).waitFor();
  const timeout = await run('accounts.get', 'f'.repeat(24));
  assert.equal(timeout.http_status, null);
  await page.getByText('未收到 HTTP 回應，沒有回應內容。', {exact:true}).waitFor();
  await page.reload(); await page.locator('#NAV-ADMIN').click(); await page.locator('#NAV-H').click();
  await page.locator('#H-VIEW-'+firstResults[1].history_id).waitFor();
  await page.locator('#H-CLEAR').click(); await page.locator('#D-CONFIRM').click();
  await page.getByText('尚無已儲存歷史。', {exact:true}).waitFor();
  await page.getByRole('button', {name:'Overview & transactions', exact:true}).click();
  await page.getByRole('button', {name:/Possible duplicate/}).click();
  await page.getByRole('heading', {name:'Privacy Inspector'}).waitFor();
  await page.locator('label.check input').check();
  await page.getByRole('button', {name:'This is normal', exact:true}).click();
  await page.getByRole('status').filter({hasText:'Confirmed normal'}).waitFor();
  await page.getByRole('button', {name:/Confirmed memory/}).click();
  await page.getByRole('button', {name:'Delete memory', exact:true}).click();
  await page.getByText('No stored facts.', {exact:false}).waitFor();
  await page.locator('#NAV-ADMIN').click();
  const screenshotLeft = await run('accounts.list');
  const screenshotRight = await run('accounts.list');
  mkdirSync(join(root, 'artifacts'), {recursive:true});
  await page.screenshot({path:join(root,'artifacts/admin-desktop.png'),fullPage:true});
  await page.locator('#NAV-H').click();
  await page.locator('#H-L-'+screenshotLeft.history_id).check();
  await page.locator('#H-R-'+screenshotRight.history_id).check();
  await page.locator('#H-COMPARE').click();
  await page.locator('#C-DIFF').waitFor();
  for (const width of [320, 390, 768]) {
    await page.setViewportSize({width, height:900});
    for (const nav of ['NAV-Q', 'NAV-H', 'NAV-C']) {
      await page.locator('#'+nav).click();
      assert(await page.evaluate(() => document.documentElement.scrollWidth<=innerWidth+2),
        `${nav} overflows ${width}px`);
    }
  }
  await page.setViewportSize({width:390, height:844});
  await page.screenshot({path:join(root,'artifacts/admin-mobile.png')});
  assert.deepEqual(errors, []);
  console.log('PASS: six queries, validation, retained state, table/JSON, saved comparison, history, deletion/cancel/focus, failed writes, empty/401/timeout, text safety, consent/memory regression and three responsive widths.');
} finally {
  await browser?.close();
  for (const child of children) child.kill('SIGTERM');
}
