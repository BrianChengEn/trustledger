import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {existsSync, mkdtempSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {chromium} from 'playwright';

// Login, role separation, admin demo-data editing, and "the page never scrolls", against an isolated synthetic backend.
const root = fileURLToPath(new URL('../..', import.meta.url));
const temp = mkdtempSync(join(tmpdir(), 'trustledger-auth-'));
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
const BASE = 'http://127.0.0.1:5175';
let browser;
const errors = [];
try {
  const frontendLogs = start(process.execPath, ['frontend/node_modules/vite/bin/vite.js', 'frontend', '--host', '127.0.0.1', '--port', '5175'],
    {API_PROXY_TARGET: 'http://127.0.0.1:8124'});
  const backendLogs = start(resolve(root, 'backend/.venv/bin/python'), ['-c',
    'import runpy,sys; sys.argv=["x"]; ns=runpy.run_path("backend/tests/admin_console_server.py", run_name="loaded"); '
    + 'import uvicorn; uvicorn.run(ns["app"], host="127.0.0.1", port=8124, log_level="warning")'],
  {PYTHONPATH: 'backend', APP_ENV: 'test', TRANSACTION_PROVIDER: 'synthetic', DATABASE_PATH: join(temp, 'test.db'), FRONTEND_ORIGIN: BASE});
  await Promise.all([ready(BASE, frontendLogs), ready('http://127.0.0.1:8124/api/v1/health', backendLogs)]);
  const chrome = process.env.PLAYWRIGHT_CHROME_PATH;
  browser = await chromium.launch({headless: true, ...(chrome ? {executablePath: chrome} :
    existsSync('/Applications/Google Chrome.app') ? {channel: 'chrome'} : {})});

  async function fresh() {
    const page = await browser.newPage({viewport: {width: 1440, height: 900}, reducedMotion: 'reduce'});
    page.setDefaultTimeout(8000);
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(BASE);
    return page;
  }
  async function signIn(page, role, passcode) {
    await page.getByRole('button', {name: role === 'admin' ? 'Admin' : 'User', exact: true}).click();
    // Picking a role must never submit the form on its own.
    assert.equal(await page.getByRole('alert').count(), 0, 'choosing a role must not trigger a sign-in attempt');
    await page.getByLabel('Passcode').fill(passcode);
    await page.getByRole('button', {name: /^Sign in/}).click();
  }
  async function assertNoScroll(page, label) {
    for (const [dx, dy] of [[0, 900], [900, 0], [0, -900], [-900, 0]]) { await page.mouse.move(700, 450); await page.mouse.wheel(dx, dy); }
    for (const key of ['PageDown', 'End', 'Space', 'ArrowDown']) await page.keyboard.press(key);
    await page.waitForTimeout(150);
    const moved = await page.evaluate(() => [...document.querySelectorAll('*')]
      .filter(e => (e.scrollTop || e.scrollLeft) && !e.hasAttribute('data-paged')).length + scrollX + scrollY);
    assert.equal(moved, 0, `${label} must not scroll`);
  }

  // Before sign-in nothing is reachable.
  const guest = await fresh();
  await guest.getByRole('heading', {name: 'Sign in'}).waitFor();
  assert.equal((await guest.request.get(`${BASE}/api/v1/transactions`)).status(), 401);
  await assertNoScroll(guest, 'login page');
  await signIn(guest, 'user', 'wrong');
  await guest.getByRole('alert').waitFor();
  assert.equal(await guest.getByRole('link', {name: /^Today/}).count(), 0);

  // A user sees their own screens and none of the admin ones.
  await guest.getByLabel('Passcode').fill('browser-user-pass');
  await guest.getByRole('button', {name: /^Sign in/}).click();
  await guest.getByRole('link', {name: /^Today/}).waitFor();
  assert.equal(await guest.getByRole('link', {name: /Demo data/}).count(), 0);
  assert.equal(await guest.locator('#NAV-ADMIN').count(), 0);
  assert.equal((await guest.request.get(`${BASE}/api/v1/admin/demo/status`)).status(), 403);
  await guest.evaluate(() => { location.hash = '#/admin'; });
  await guest.getByRole('link', {name: /^Today/}).waitFor();
  await assertNoScroll(guest, 'user home');
  await guest.getByRole('button', {name: 'Sign out'}).click();
  await guest.getByRole('heading', {name: 'Sign in'}).waitFor();
  assert.equal((await guest.request.get(`${BASE}/api/v1/transactions`)).status(), 401);

  // An admin edits the demo, previews the user's view, and resets.
  await signIn(guest, 'admin', 'browser-admin-pass');
  await guest.getByRole('heading', {name: /Edit the demo/}).waitFor();
  await assertNoScroll(guest, 'admin demo data');
  const rows = () => guest.locator('.txtable tbody tr').count();
  assert.equal(await rows(), 18);
  await guest.getByLabel('Merchant').fill('E2E Bistro');
  await guest.getByLabel('Amount (USD)').fill('12.50');
  await guest.getByRole('button', {name: 'Add charge'}).click();
  await guest.getByText(/Added E2E Bistro/).first().waitFor();
  assert.equal(await rows(), 19);
  await guest.getByRole('button', {name: 'Delete E2E Bistro'}).click();
  await guest.getByRole('button', {name: 'Delete', exact: true}).click();
  await guest.getByText('Deleted E2E Bistro.').waitFor();
  assert.equal(await rows(), 18);
  await guest.getByRole('button', {name: 'Inject a duplicate charge Two identical charges minutes apart.'}).click();
  await guest.getByText(/Added 2 charges/).waitFor();
  assert.equal(await rows(), 20);
  await guest.getByRole('button', {name: 'Preview as user'}).click();
  await guest.getByRole('link', {name: /^Today/}).waitFor();
  await assertNoScroll(guest, 'admin previewing the user');
  await guest.getByRole('button', {name: 'Back to admin'}).click();
  await guest.getByRole('heading', {name: /Edit the demo/}).waitFor();
  await guest.getByRole('button', {name: 'Reset demo'}).click();
  await guest.getByRole('button', {name: 'Yes, reset'}).click();
  await guest.getByText(/Demo reset/).first().waitFor();
  assert.equal(await rows(), 18);
  await guest.getByRole('button', {name: 'Changes', exact: false}).click();
  await guest.locator('.changes li').first().waitFor();
  await assertNoScroll(guest, 'change log');
  await guest.getByRole('link', {name: /Data sources/}).click();
  await assertNoScroll(guest, 'data sources');

  assert.deepEqual(errors, []);
  console.log('Auth and demo-data checks passed.');
} finally {
  await browser?.close();
  for (const child of children) child.kill();
}
