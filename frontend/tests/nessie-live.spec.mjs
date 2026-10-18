// Opt-in true live E2E: no response interception, no MockTransport, no upstream writes.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createServer} from 'node:net';
import {existsSync, mkdtempSync, writeFileSync} from 'node:fs';
import {randomBytes} from 'node:crypto';
import {tmpdir} from 'node:os';
import {join, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {chromium} from 'playwright';

if (process.env.NESSIE_LIVE_TEST !== '1') throw new Error('Set NESSIE_LIVE_TEST=1 for live E2E');
const root = fileURLToPath(new URL('../..', import.meta.url));
const temp = mkdtempSync(join(tmpdir(), 'trustledger-nessie-live-'));
const passcode = randomBytes(24).toString('hex');
const children = [];
async function freePort() {
  const server = createServer();
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;
  await new Promise(resolve => server.close(resolve));
  return port;
}
const frontendPort = await freePort();
const backendPort = await freePort();
const base = `http://127.0.0.1:${frontendPort}`;
function start(command, args, env) {
  const child = spawn(command, args, {cwd: root, env: {...process.env, ...env}, stdio: 'pipe'});
  // Keep diagnostic output in memory; never dump potentially sensitive server tracebacks.
  child.stdout.resume(); child.stderr.resume(); children.push(child);
}
async function ready(url) {
  for (let i = 0; i < 100; i++) {
    if (children.some(child => child.exitCode !== null)) throw new Error('Isolated service exited unexpectedly');
    try { if ((await fetch(url)).ok) return; } catch {}
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error('Isolated local service failed to start');
}
let browser;
try {
  start(resolve(root, 'backend/.venv/bin/python'), ['backend/tests/nessie_live_server.py'], {
    PYTHONPATH: 'backend', NESSIE_LOCAL_PORT: String(backendPort), NESSIE_LOCAL_PASSCODE: passcode, TRANSACTION_PROVIDER: 'nessie',
    APP_ENV: 'development', DATABASE_PATH: join(temp, 'live.db'), SOURCE_DATABASE_DIR: join(temp, 'sources'),
    FRONTEND_ORIGIN: base,
  });
  start(process.execPath, ['frontend/node_modules/vite/bin/vite.js', 'frontend', '--host', '127.0.0.1', '--port', String(frontendPort), '--strictPort'],
    {API_PROXY_TARGET: `http://127.0.0.1:${backendPort}`});
  await Promise.all([ready(base), ready(`http://127.0.0.1:${backendPort}/api/v1/auth/me`)]);
  const chrome = process.env.PLAYWRIGHT_CHROME_PATH;
  browser = await chromium.launch({headless: true, ...(chrome ? {executablePath: chrome} :
    existsSync('/Applications/Google Chrome.app') ? {channel: 'chrome'} : {})});
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}, locale: 'en-US'});
  page.setDefaultTimeout(20000);
  const errors = [];
  page.on('pageerror', () => errors.push('browser error'));
  let liveAlertCount = null;
  page.on('response', async response => {
    if (response.request().method() === 'GET' && response.url().endsWith('/api/v1/alerts') && response.status() === 200) {
      liveAlertCount = (await response.json()).length;
    }
  });
  await page.goto(base);
  await page.getByLabel('Passcode', {exact: true}).fill(passcode);
  const workspaceResponse = page.waitForResponse(r => r.url().endsWith('/api/v1/workspace/refresh') && r.request().method() === 'POST' && r.status() === 200);
  await page.getByRole('button', {name: 'Sign in', exact: true}).click();
  const response = await workspaceResponse;
  assert.equal((await response.allHeaders())['x-transaction-provider'], 'nessie-live');
  assert.equal(response.headers()['x-transaction-upstream-status'], 'live');
  assert.equal(response.headers()['x-transaction-fallback-used'], 'false');
  const snapshot = await response.json();
  assert(snapshot.transactions.length > 0);
  assert(snapshot.transactions.every(t => t.source === 'nessie' && !t.id.startsWith('txn_syn')));
  await page.getByRole('link', {name: 'Activity', exact: true}).click();
  await page.locator('table.txtable tbody tr').first().waitFor();
  // Compare every rendered transaction to the actual backend snapshot, without exporting rows.
  const rendered = page.locator('table.txtable tbody tr');
  assert.equal(await rendered.count(), snapshot.transactions.length);
  for (let index = 0; index < snapshot.transactions.length; index++) {
    const tx = snapshot.transactions[index];
    const text = await rendered.nth(index).textContent();
    assert(text.includes(tx.merchant_display));
    assert(text.includes(tx.occurred_at.slice(0, 10)));
    const formatted = new Intl.NumberFormat('en-US', {style:'currency', currency:'USD'}).format(tx.amount);
    assert(text.includes(formatted));
  }
  // The table's newest-first ordering equals the backend workspace order.
  const first = snapshot.transactions[0];
  const row = page.locator('table.txtable tbody tr').first();
  assert((await row.textContent()).includes(first.merchant_display));
  assert((await row.textContent()).includes(first.occurred_at.slice(0, 10)));
  const money = new Intl.NumberFormat('en-US', {style:'currency', currency:'USD'}).format(first.amount);
  assert((await row.locator('td.amount').textContent()).includes(money));
  await row.getByRole('button').click();
  assert(page.url().includes(encodeURIComponent(first.id)));
  await page.getByRole('button', {name:'Analyze with Jev', exact:true}).waitFor({state:'visible'});
  const analysisResponse = page.waitForResponse(r => r.url().endsWith('/api/v1/analyses') && r.request().method() === 'POST' && r.status() === 200);
  await page.getByRole('button', {name:'Analyze with Jev', exact:true}).click();
  const analysis = await (await analysisResponse).json();
  assert.equal(analysis.transaction_id, first.id);
  assert.equal(analysis.provider_mode, 'rules-only');
  assert.equal(errors.length, 0);
  const evidence = {verification: 'actual live Nessie → FastAPI → React',
    transaction_count: snapshot.transactions.length, account_count: snapshot.accounts.length,
    transaction_kinds: [...new Set(snapshot.transactions.map(t => t.kind))], live_alert_count: liveAlertCount,
    amount_date_kind_rendering: 'passed', selected_transaction_identity: 'matched',
    analysis_transaction_identity: 'matched', synthetic_rows: 0, upstream_status: 'live',
    fallback_used: false, mocked_upstream: false, external_writes: 0};
  writeFileSync(join(temp,'safe-evidence.json'),JSON.stringify(evidence,null,2),{mode:0o600});
  console.log(JSON.stringify(evidence));
} finally {
  if (browser) await browser.close();
  for (const child of children) child.kill('SIGTERM');
}
