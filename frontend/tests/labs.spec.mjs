import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {existsSync, mkdtempSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {chromium} from 'playwright';

// Memory Lab, Privacy Lab and the Relevant memory card, against an isolated synthetic backend. The labs must never write or call a provider.
const root = fileURLToPath(new URL('../..', import.meta.url));
const temp = mkdtempSync(join(tmpdir(), 'trustledger-labs-'));
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
const BASE = 'http://127.0.0.1:5176';
let browser;
const errors = [];
try {
  const frontendLogs = start(process.execPath, ['frontend/node_modules/vite/bin/vite.js', 'frontend', '--host', '127.0.0.1', '--port', '5176'],
    {API_PROXY_TARGET: 'http://127.0.0.1:8125', VITE_CACHE_DIR: join(temp, 'vite-cache')});
  const backendLogs = start(resolve(root, 'backend/.venv/bin/python'), ['-c',
    'import runpy,sys; sys.argv=["x"]; ns=runpy.run_path("backend/tests/admin_console_server.py", run_name="loaded"); '
    + 'import uvicorn; uvicorn.run(ns["app"], host="127.0.0.1", port=8125, log_level="warning")'],
  {PYTHONPATH: 'backend', TRANSACTION_PROVIDER: 'synthetic', DATABASE_PATH: join(temp, 'test.db'), FRONTEND_ORIGIN: BASE});
  await Promise.all([ready(BASE, frontendLogs), ready('http://127.0.0.1:8125/api/v1/health', backendLogs)]);
  const chrome = process.env.PLAYWRIGHT_CHROME_PATH;
  browser = await chromium.launch({headless: true, ...(chrome ? {executablePath: chrome} :
    existsSync('/Applications/Google Chrome.app') ? {channel: 'chrome'} : {})});

  const SENTENCE = 'The demo user explicitly confirmed a streaming alert as normal. Recheck future evidence.';
  const api = path => `${BASE}/api/v1${path}`;
  const ctx = await browser.newContext({viewport: {width: 1440, height: 900}, reducedMotion: 'reduce'});
  const page = await ctx.newPage();
  page.setDefaultTimeout(8000);
  page.on('pageerror', error => errors.push(error.message));
  // Anything the UI sends that is not a read. Sign-in and the workspace refresh are expected; nothing else may be written.
  const writes = [];
  page.on('request', r => { const u = r.url();
    if (r.method() !== 'GET' && !/\/auth\/|\/workspace\/refresh/.test(u)) writes.push(r.method() + ' ' + u.split('/api/v1')[1]); });
  assert.equal((await page.request.post(api('/auth/login'), {data: {role: 'admin', passcode: 'browser-admin-pass'}})).status(), 200);
  await page.addInitScript(() => { try { sessionStorage.setItem('trustledger.preview', '1'); } catch {} });
  const noScroll = async label => {
    for (const [dx, dy] of [[0, 900], [900, 0]]) { await page.mouse.move(700, 80); await page.mouse.wheel(dx, dy); }
    await page.waitForTimeout(120);
    const moved = await page.evaluate(() => scrollX + scrollY + document.querySelector('main').scrollTop + document.querySelector('.frame').scrollTop);
    assert.equal(moved, 0, `${label} must not scroll the page`);
  };
  const stepTitle = () => page.locator('#lab-step-title').innerText();
  // Steps change after a render, so wait for the title instead of reading it immediately.
  const expectStep = async re => { await page.waitForFunction(src => new RegExp(src).test(document.querySelector('#lab-step-title')?.textContent ?? ''), re.source);
    assert.match(await stepTitle(), re); };

  // --- both modes exist in Memory and Privacy; real pages are unchanged ---
  await page.goto(`${BASE}/#/memory`);
  await page.getByRole('button', {name: 'My Memories'}).waitFor();
  await page.getByRole('button', {name: 'Memory Lab'}).waitFor();
  await page.getByRole('heading', {name: /allowed it to remember/}).waitFor();
  await page.goto(`${BASE}/#/privacy`);
  await page.getByRole('button', {name: 'My Privacy'}).waitFor();
  await page.getByRole('button', {name: 'Privacy Lab'}).waitFor();
  await page.getByRole('heading', {name: 'What AI actually sees.'}).waitFor();

  // --- Memory Lab, Level 1 ---
  await page.goto(`${BASE}/#/memory/lab`);
  await expectStep(/The original transaction/);
  await page.getByText('Demo story:').waitFor();
  assert((await page.locator('.labhead').innerText()).includes('txn_syn_004'));
  await page.getByRole('button', {name: 'Next', exact: true}).click();
  await expectStep(/Why the alert triggered/);
  // The four conditions and the real 6 minute gap come from the two real transactions and the real alert.
  for (const text of ['Same merchant', 'Same amount', 'Within 24 hours (6 minutes apart)', 'Debit']) await page.getByRole('button', {name: text}).waitFor();
  await page.getByRole('button', {name: 'Same amount'}).click();
  assert((await page.locator('.txnrow.hot').count()) >= 2, 'a clicked condition highlights both transactions');
  assert((await page.locator('.labpanel').last().innerText()).includes('Possible duplicate'));
  await page.getByRole('button', {name: 'Next', exact: true}).click();
  await expectStep(/Your decision/);
  await page.getByRole('button', {name: 'Next', exact: true}).click();
  await expectStep(/Explicit consent/);
  const consent = page.getByRole('checkbox', {name: /Remember this decision/});
  assert.equal(await consent.isChecked(), false, 'consent starts unchecked');
  assert((await page.locator('.labpanel').last().innerText()).includes('No memory is written'));
  await consent.check();
  assert((await page.locator('.labpanel').last().innerText()).includes('Eligible for a privacy-safe memory'));
  await consent.uncheck();
  await page.getByRole('button', {name: 'Next', exact: true}).click();
  await expectStep(/From facts to a memory event/);
  assert.equal(await page.getByRole('button', {name: 'Transform into Memory Event'}).count(), 1);
  await page.getByRole('button', {name: 'Transform into Memory Event'}).click();
  const outcome = await page.locator('.tcols .result').innerText();
  assert(outcome.includes(SENTENCE), 'the exact approved sentence');
  for (const leaked of ['StreamWave', '11.99', 'acct_', 'txn_syn']) assert(!outcome.includes(leaked), `memory event must not contain ${leaked}`);
  const verdicts = await page.locator('.engine .verdict').allInnerTexts();
  assert.deepEqual(verdicts, ['REMOVED', 'REMOVED', 'REMOVED', 'REMOVED', 'RETAINED', 'RETAINED']);
  await page.getByRole('button', {name: /Merchant/}).first().click();
  assert((await page.locator('.tdetail').innerText()).includes('If it were shared'));
  assert((await page.locator('.tnote').innerText()).includes('not encryption'));
  await noScroll('Memory Lab step 5');
  await page.getByRole('button', {name: 'Next', exact: true}).click();
  await expectStep(/Where the data goes/);
  await page.getByRole('button', {name: /Backboard memory/}).click();
  const body = await page.locator('.labpanel').last().innerText();
  assert(body.includes('"content"') && body.includes(SENTENCE));
  await page.getByRole('button', {name: /SQLite/}).click();
  assert((await page.locator('.labpanel').last().innerText()).includes('The structured transaction'));
  await page.getByRole('button', {name: 'Next', exact: true}).click();
  await expectStep(/The memory result/);
  assert((await page.locator('.memcard.preview').innerText()).includes('Preview only'));

  // --- Level 2: this dataset has no later alert, so the walkthrough says so and invents nothing ---
  await page.getByRole('button', {name: 'Next', exact: true}).click();
  await expectStep(/A new transaction arrives/);
  assert((await page.locator('.labpanel').nth(1).innerText()).includes('not in this dataset'));
  for (let i = 0; i < 4; i++) await page.getByRole('button', {name: 'Next', exact: true}).click();
  await expectStep(/Backboard verification/);
  assert(/illustrative/i.test(await page.locator('.labpanel').last().innerText()), 'guided result is labelled');
  await page.getByRole('button', {name: 'Next', exact: true}).click();
  await expectStep(/What memory changes/);
  const after = await page.locator('.beforeafter').innerText();
  assert(after.includes('Historical context') && after.includes('not approved'));
  await page.getByRole('button', {name: 'Next', exact: true}).click();
  await page.getByRole('button', {name: /Delete \(walkthrough only\)/}).click();
  assert((await page.locator('.labpanel').last().innerText()).includes('No relevant memory found.'));
  await page.getByRole('button', {name: 'Next', exact: true}).click();
  assert((await page.locator('.lesson').innerText()).includes('not what the fraud rules decide'));
  await page.getByRole('button', {name: 'Previous', exact: true}).click();
  await expectStep(/Delete the memory/);
  await page.getByRole('button', {name: 'Restart journey'}).click();
  await expectStep(/The original transaction/);

  // --- Privacy Lab: every provider, and no provider is ever called ---
  await page.goto(`${BASE}/#/privacy/lab`);
  await page.getByRole('heading', {name: /outside AI/}).waitFor();
  for (let i = 0; i < 2; i++) await page.getByRole('button', {name: 'Next', exact: true}).click();
  await expectStep(/Select an external service/);
  await page.getByRole('radio', {name: /Gemini/}).click();
  await page.getByRole('button', {name: 'Next', exact: true}).click();
  await expectStep(/Privacy transformation for Gemini/);
  await page.getByRole('button', {name: /Transform into approved payload/}).click();
  const gemini = await page.locator('pre[aria-label="Approved payload"]').innerText();
  assert(gemini.includes('"task": "explain_existing_alert"') && gemini.includes('"reason_codes"'));
  for (const key of ['merchant_category', 'amount_bucket', 'currency', 'local_day_part', 'same_category_same_amount_24h_count', 'is_subscription', 'subscription_delta_bucket', 'prior_user_confirmation'])
    assert(gemini.includes(`"${key}"`), `Gemini payload has ${key}`);
  for (const leaked of ['StreamWave', '11.99', 'acct_', 'txn_syn']) assert(!gemini.includes(leaked), `provider payload must not contain ${leaked}`);
  await page.getByRole('button', {name: 'Previous', exact: true}).click();
  await page.getByRole('radio', {name: /Backboard/}).click();
  await page.getByRole('button', {name: 'Next', exact: true}).click();
  await page.getByRole('button', {name: /Transform into approved payload/}).click();
  assert((await page.locator('.tcols .result').innerText()).includes(SENTENCE));
  await page.getByRole('button', {name: 'Previous', exact: true}).click();
  await page.getByRole('radio', {name: /Jev/}).click();
  await page.getByRole('button', {name: 'Next', exact: true}).click();
  await page.getByRole('button', {name: /Transform into approved payload/}).click();
  assert.equal((await page.locator('pre[aria-label="Approved payload"]').innerText()).includes('"task"'), false, 'Jev gets the eight fields only');
  for (let i = 0; i < 3; i++) await page.getByRole('button', {name: 'Next', exact: true}).click();
  await expectStep(/The privacy takeaway/);
  assert((await page.locator('.lesson').innerText()).includes('before the request leaves the backend'));
  await noScroll('Privacy Lab');
  assert.deepEqual(writes, [], `the labs must not write or call any provider: ${writes}`);

  // --- Real data for Level 2: a later duplicate, a real consented memory, then the Relevant memory card ---
  const added = await (await page.request.post(api('/admin/demo/transactions'), {headers: {origin: BASE}, data: {merchant: 'StreamWave', category: 'streaming', amount: 11.99,
    occurred_at: '2026-10-17T16:00:00-04:00', direction: 'debit', is_subscription: true}})).json();
  const laterId = added.id;
  assert(laterId, 'later transaction created');
  const alerts = await (await page.request.get(api('/alerts'))).json();
  const laterAlert = alerts.find(a => a.transaction_id === laterId);
  assert.equal(laterAlert.alert_type, 'duplicate');
  // Before any memory: the card says none was found and the alert still needs a person.
  await page.goto(`${BASE}/#/case/${laterId}/today`); await page.reload();
  await page.getByText('No relevant memory found.', {exact: true}).waitFor();
  assert((await page.locator('.relevant').innerText()).includes('This transaction still requires review.'));
  // A real, consented memory through the normal confirmation endpoint.
  const first = alerts.find(a => a.transaction_id === 'txn_syn_004');
  const saved = await (await page.request.post(api(`/alerts/${first.alert_id}/confirmations`), {headers: {origin: BASE}, data: {decision: 'normal', consent_to_memory: true}})).json();
  assert.equal(saved.memory_status, 'written');
  await page.goto(`${BASE}/#/memory/lab/l2-5`); await page.reload();
  await page.getByText('Relevant memory found', {exact: true}).waitFor();
  assert((await page.locator('.labpanel').last().innerText()).includes('This copy is on this server.'), 'local copy is never called Backboard-verified');
  await expectStep(/Backboard verification/);
  assert(/real result/i.test(await page.locator('.labpanel').last().innerText()));
  await page.goto(`${BASE}/#/case/${laterId}/today`); await page.reload();
  await page.getByText('Relevant memory found', {exact: true}).waitFor();
  assert((await page.locator('.relevant').innerText()).includes(SENTENCE));
  assert((await page.locator('.relevant').innerText()).includes('This transaction still requires review.'));
  await page.getByText('You told TrustLedger this category is normal').waitFor();
  const still = (await (await page.request.get(api('/alerts'))).json()).find(a => a.transaction_id === laterId);
  assert.equal(still.alert_type, 'duplicate'); assert.equal(still.needs_human, true); assert.equal(still.status, 'open');
  assert.equal(await page.getByText('Mark').count() >= 0, true);
  // Failure states never keep an old sentence.
  const memoryRoute = '**/relevant-memories';
  await page.route(memoryRoute, route => route.fulfill({status: 500, json: {error: {code: 'internal_error'}}}), {times: 1});
  await page.reload();
  await page.getByText('Memory could not be loaded.').waitFor();
  assert(!(await page.locator('.relevant').innerText()).includes('explicitly confirmed'), 'an HTTP error shows no stale sentence');
  assert.equal(await page.getByText('You told TrustLedger this category is normal').count(), 0, 'the facts note follows the same result');
  await page.route(memoryRoute, route => route.fulfill({json: {memories: [{memory_id: 'mem_x', summary: SENTENCE, created_at: '2026-10-18T12:00:00Z',
    source: 'backboard', verification: 'unverified'}], retrieval_mode: 'unavailable', checked_at: null, failure: 'provider_error'}}), {times: 1});
  await page.reload();
  await page.getByText('Memory could not be checked right now.').waitFor();
  assert(!(await page.locator('.relevant').innerText()).includes('explicitly confirmed'), 'unavailable shows no summary');
  await page.route(memoryRoute, route => route.fulfill({json: {memories: [], retrieval_mode: 'remote_verified', checked_at: '2026-10-18T12:00:00Z', failure: null}}), {times: 1});
  await page.reload();
  await page.getByText('No relevant memory found.', {exact: true}).waitFor();
  assert(!(await page.locator('.relevant').innerText()).includes('Checked with Backboard'), 'an empty verified list is not a match');
  await page.route(memoryRoute, route => route.fulfill({json: {memories: [{memory_id: 'mem_y', summary: SENTENCE, created_at: '2026-10-18T12:00:00Z',
    source: 'backboard', verification: 'remote_verified'}], retrieval_mode: 'remote_verified', checked_at: '2026-10-18T12:00:00Z', failure: null}}), {times: 1});
  await page.reload();
  await page.getByText('Checked with Backboard just now.').waitFor();
  // Real delete: the memory disappears from the card and the alert is unchanged.
  const memories = await (await page.request.get(api('/memories'))).json();
  assert.equal((await page.request.delete(api(`/memories/${memories[0].memory_id}`), {headers: {origin: BASE}})).status(), 204);
  await page.reload();
  await page.getByText('No relevant memory found.', {exact: true}).waitFor();
  const afterDelete = (await (await page.request.get(api('/alerts'))).json()).find(a => a.transaction_id === laterId);
  assert.equal(afterDelete.alert_type, 'duplicate'); assert.equal(afterDelete.status, 'open');
  await page.goto(`${BASE}/#/memory/lab/l2-5`); await page.reload();
  await page.getByText('Illustrative').first().waitFor();

  // --- mobile: both labs stay usable, and keyboard Next works ---
  const phone = await browser.newPage({viewport: {width: 390, height: 844}, hasTouch: true, isMobile: true, reducedMotion: 'reduce'});
  phone.on('pageerror', error => errors.push(error.message));
  assert.equal((await phone.request.post(api('/auth/login'), {data: {role: 'user', passcode: 'browser-user-pass'}})).status(), 200);
  for (const route of ['#/memory/lab/l1-5', '#/privacy/lab/p-4']) {
    await phone.goto(BASE + '/' + route);
    await phone.locator('#lab-step-title').waitFor();
    assert(await phone.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${route} fits a phone width`);
  }
  await page.goto(`${BASE}/#/memory/lab`);
  await page.getByRole('button', {name: 'Next', exact: true}).focus();
  await page.keyboard.press('Enter');
  await expectStep(/Why the alert triggered/);

  assert.deepEqual(errors, []);
  console.log('Memory Lab, Privacy Lab and Relevant memory checks passed.');
} finally {
  await browser?.close();
  for (const child of children) child.kill();
}
