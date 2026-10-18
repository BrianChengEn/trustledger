import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {existsSync, mkdtempSync, readFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {chromium} from 'playwright';

// Fraud Intelligence Lab: every chapter, real numbers recomputed from the saved artifacts, honest comparison wording, and no backend or provider calls.
const root = fileURLToPath(new URL('../..', import.meta.url));
const temp = mkdtempSync(join(tmpdir(), 'trustledger-fraudlab-'));
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
const BASE = 'http://127.0.0.1:5177';
let browser;
const errors = [];
try {
  const frontendLogs = start(process.execPath, ['frontend/node_modules/vite/bin/vite.js', 'frontend', '--host', '127.0.0.1', '--port', '5177'],
    {API_PROXY_TARGET: 'http://127.0.0.1:8126'});
  const backendLogs = start(resolve(root, 'backend/.venv/bin/python'), ['-c',
    'import runpy,sys; sys.argv=["x"]; ns=runpy.run_path("backend/tests/admin_console_server.py", run_name="loaded"); '
    + 'import uvicorn; uvicorn.run(ns["app"], host="127.0.0.1", port=8126, log_level="warning")'],
  {PYTHONPATH: 'backend', APP_ENV: 'test', TRANSACTION_PROVIDER: 'synthetic', DATABASE_PATH: join(temp, 'test.db'), FRONTEND_ORIGIN: BASE});
  await Promise.all([ready(BASE, frontendLogs), ready('http://127.0.0.1:8126/api/v1/health', backendLogs)]);
  const chrome = process.env.PLAYWRIGHT_CHROME_PATH;
  browser = await chromium.launch({headless: true, ...(chrome ? {executablePath: chrome} :
    existsSync('/Applications/Google Chrome.app') ? {channel: 'chrome'} : {})});

  const data = name => JSON.parse(readFileSync(join(root, 'frontend/src/fraudlab/data', name + '.json'), 'utf8'));
  const models = data('models'), evidence = data('evidence');
  const headline = models.find(m => m.model === 'v2_merchant_step_causal');
  const tpAt = (m, k) => m.fraud_ranks.filter(r => r <= k).length;
  const ctx = await browser.newContext({viewport: {width: 1440, height: 900}, reducedMotion: 'reduce'});
  const page = await ctx.newPage();
  page.setDefaultTimeout(8000);
  page.on('pageerror', error => errors.push(error.message));
  const apiCalls = [];
  page.on('request', r => { const u = r.url(); if (u.includes('/api/v1/')) apiCalls.push(r.method() + ' ' + u.split('/api/v1')[1]); });
  assert.equal((await page.request.post(`${BASE}/api/v1/auth/login`, {data: {role: 'user', passcode: 'browser-user-pass'}})).status(), 200);
  const text = () => page.locator('.fl-stage').innerText();
  const noScroll = async label => {
    for (const [dx, dy] of [[0, 900], [900, 0]]) { await page.mouse.move(700, 60); await page.mouse.wheel(dx, dy); }
    await page.waitForTimeout(120);
    assert.equal(await page.evaluate(() => scrollX + scrollY + document.querySelector('main').scrollTop), 0, `${label} must not scroll the page`);
  };
  const chapters = ['challenge', 'features', 'architecture', 'evaluation', 'explorer', 'arena'];

  // --- every chapter is reachable by deep link, rail and Next ---
  await page.goto(`${BASE}/#/fraud-lab`);
  await page.getByRole('heading', {name: 'Overview', exact: true}).first().waitFor();
  assert((await page.locator('.fl-head').innerText()).includes('System B'), 'System B chip on every chapter');
  for (const c of chapters) {
    await page.goto(`${BASE}/#/fraud-lab/${c}`);
    await page.locator('.fl-stage section').waitFor();
    assert((await page.locator('.fl-head').innerText()).includes('System B'));
    await noScroll(c);
  }
  await page.goto(`${BASE}/#/fraud-lab`);
  await page.getByRole('button', {name: 'Next chapter'}).click();
  await page.waitForFunction(() => location.hash === '#/fraud-lab/challenge');
  await page.locator('.fl-rail').getByRole('button', {name: /Benchmark arena/}).click();
  await page.waitForFunction(() => location.hash === '#/fraud-lab/arena');

  // --- overview: the verified headline, three systems, nothing invented ---
  await page.goto(`${BASE}/#/fraud-lab`);
  await page.getByText('97.5%').first().waitFor();
  assert((await text()).includes('896 were ground-truth fraud'));
  await page.getByRole('button', {name: 'Average precision'}).click();
  assert((await text()).includes('0.9576'));
  await page.getByRole('button', {name: 'False alarms in the 919'}).click();
  await page.locator('.fl-bignum strong', {hasText: '23'}).waitFor();
  assert((await text()).includes('System B · you are here'));
  for (const label of ['System A', 'System C', 'The product’s fraud rules', 'BankSim data browsing']) assert((await text()).includes(label), label);
  await page.locator('.fl-dots').focus(); await page.keyboard.press('ArrowRight');
  assert((await page.locator('.fl-dotinfo').innerText()).includes('Rank 2'));
  await page.getByRole('button', {name: /See how TrustLedger detects/}).click();
  await page.waitForFunction(() => location.hash.startsWith('#/case/'));

  // --- challenge: accuracy trap uses the real test counts ---
  await page.goto(`${BASE}/#/fraud-lab/challenge`);
  await page.getByRole('checkbox', {name: /Predict “legitimate”/}).check();
  assert((await text()).includes('98.92%') && (await text()).includes('1,200'));
  assert((await text()).includes('9.9'), 'expected random hits at 919');

  // --- features: slider, accordion, leakage wording ---
  await page.goto(`${BASE}/#/fraud-lab/features`);
  await page.getByRole('button', {name: 'Customer history'}).click();
  assert((await text()).toLowerCase().includes('known at prediction time?'));
  await page.locator('#fl-t').fill('50');
  assert((await text()).includes('this row’s own label, and labels from later steps'));
  assert((await text()).includes('Test features were never affected'));
  assert((await text()).includes('Evidence pending') || (await text()).toLowerCase().includes('evidence pending'));

  // --- architecture: every layer opens with real artifacts ---
  await page.goto(`${BASE}/#/fraud-lab/architecture`);
  const layerButtons = page.locator('.fl-stack button');
  assert.equal(await layerButtons.count(), 9);
  for (let i = 0; i < 9; i++) { await layerButtons.nth(i).click(); await page.locator('.fl-detail .fl-example').waitFor(); assert((await page.locator('.fl-detail').innerText()).toLowerCase().includes('effect on the next stage')); }
  await layerButtons.nth(5).click();
  const modelText = await page.locator('.fl-detail').innerText();
  assert(modelText.includes('max_iter') && modelText.includes('80') && modelText.includes('Conceptual illustration, not the trained model'));
  await layerButtons.nth(7).click();
  assert((await page.locator('.fl-detail').innerText()).includes(String(tpAt(headline, 919))), 'confusion matrix at 919 from real data');

  // --- evaluation: exact numbers, accessible chart, slider ---
  await page.goto(`${BASE}/#/fraud-lab/evaluation`);
  await page.locator('.fl-chart svg[role="img"]').waitFor();
  assert((await page.locator('.fl-chart svg title').first().textContent()).includes('Precision-recall'));
  assert((await text()).includes('not</b> a blind holdout'.replace('</b>', '')) || (await text()).includes('not a blind holdout'));
  await page.locator('#fl-k2').fill('500');
  const tp500 = tpAt(headline, 500);
  await page.locator('.fl-confusion .tp strong').waitFor();
  assert.equal((await page.locator('.fl-confusion .tp strong').innerText()).replace(/,/g, ''), String(tp500));

  // --- explorer: three separate things, exact budget, filters, trace ---
  await page.goto(`${BASE}/#/fraud-lab/explorer`);
  assert.equal((await page.locator('.fl-confusion .tp strong').innerText()).replace(/,/g, ''), '896');
  assert.equal((await page.locator('.fl-confusion .fp strong').innerText()), '23');
  assert.equal((await page.locator('.fl-confusion .fn strong').innerText()), '304');
  assert.equal((await page.locator('.fl-confusion .tn strong').innerText()), '110,083');
  for (const label of ['Ground truth', 'Model score', 'Evaluation outcome']) assert((await page.locator('.fl-legend').innerText()).includes(label));
  await page.getByRole('button', {name: '500'}).click();
  assert.equal((await page.locator('.fl-confusion .tp strong').innerText()).replace(/,/g, ''), String(tp500));
  assert.equal(Number((await page.locator('.fl-confusion .fp strong').innerText()).replace(/,/g, '')), 500 - tp500);
  await page.getByRole('tab', {name: 'Missed fraud'}).click();
  await page.getByRole('button', {name: /Inspect rank/}).first().click();
  const trace = await page.locator('.fl-trace').innerText();
  assert(trace.includes('Evidence pending') && trace.includes('False negative') && trace.includes('Ground truth: fraud'));
  await page.getByRole('button', {name: '919'}).click();
  await page.getByRole('tab', {name: 'False alarms'}).click();
  await page.getByRole('button', {name: /Inspect rank/}).first().click();
  assert((await page.locator('.fl-trace').innerText()).includes('False positive'));

  // --- arena: ties stated as ties, comparable and non-comparable kept apart ---
  await page.goto(`${BASE}/#/fraud-lab/arena`);
  const arena = await text();
  assert(arena.includes('a tie, not a win'));
  assert(arena.includes('Published reference results (not directly comparable)') && arena.includes('N/A'));
  assert(arena.includes('adapted') && arena.includes('Limits you should know'));
  for (const banned of ['Kaggle #1', 'state-of-the-art', 'beats', 'outperforms', 'best in class']) assert(!arena.toLowerCase().includes(banned.toLowerCase()), `banned claim: ${banned}`);
  await page.getByRole('button', {name: 'False positives at 919'}).click();
  const firstVals = await page.locator('.fl-bars .val').allInnerTexts();
  const nums = firstVals.map(Number).filter(Number.isFinite);
  assert(nums.every((v, i) => i === 0 || v >= nums[i - 1]), 'lower is better: sorted ascending');
  await page.getByRole('button', {name: 'Matched features'}).click();
  assert((await page.locator('.fl-bars').innerText()).includes('TrustLedger, no merchant fraud rate'));
  assert(!(await page.locator('.fl-bars').innerText()).includes('merchant-aware'), 'merchant-aware models are not "matched features"');
  const bootCust = evidence.bootstrap.headline_vs_public_lgbm_customer_blocks.ap_difference;
  await page.getByRole('button', {name: 'Full pipelines'}).click();
  assert((await text()).includes(bootCust.ci95_low.toFixed(4)), 'bootstrap interval shown from data');
  await noScroll('arena');

  // --- the lab never calls the backend for anything but the shared workspace reads ---
  const forbidden = apiCalls.filter(c => /analyses|explanation|confirmations|memories|admin|data-sources|relevant/.test(c) && !/^GET/.test(c));
  assert.deepEqual(forbidden, [], `unexpected calls: ${forbidden}`);
  assert(!apiCalls.some(c => /^(POST|PUT|PATCH|DELETE) \/(analyses|alerts|memories)/.test(c)), 'no writes or provider calls');

  // --- dark theme and a phone ---
  await page.emulateMedia({colorScheme: 'dark'});
  await page.goto(`${BASE}/#/fraud-lab/architecture`);
  await page.locator('.fl-detail').waitFor();
  const phone = await browser.newPage({viewport: {width: 390, height: 844}, hasTouch: true, isMobile: true, reducedMotion: 'reduce'});
  phone.on('pageerror', error => errors.push(error.message));
  assert.equal((await phone.request.post(`${BASE}/api/v1/auth/login`, {data: {role: 'user', passcode: 'browser-user-pass'}})).status(), 200);
  for (const c of ['', ...chapters.map(x => '/' + x)]) {
    await phone.goto(`${BASE}/#/fraud-lab${c}`);
    await phone.locator('.fl-stage section').waitFor();
    assert(await phone.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `fraud-lab${c} fits a phone width`);
  }
  assert.deepEqual(errors, []);
  console.log('Fraud Intelligence Lab checks passed.');
} finally {
  await browser?.close();
  for (const child of children) child.kill();
}
