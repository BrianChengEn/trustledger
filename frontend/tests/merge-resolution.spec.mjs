// Reconciliation browser regression: isolated local app plus explicitly labeled UI-only fixtures.
// Complete stateful workflow on explicit canonical TEST FIXTURES and provider test doubles.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createServer} from 'node:net';
import {existsSync, mkdtempSync} from 'node:fs';
import {randomBytes} from 'node:crypto';
import {tmpdir} from 'node:os';
import {join, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {chromium} from 'playwright';
const root=fileURLToPath(new URL('../..',import.meta.url));
const temp=mkdtempSync(join(tmpdir(),'trustledger-lifecycle-'));
const children=[];
async function port(){const server=createServer();await new Promise(r=>server.listen(0,'127.0.0.1',r));const p=server.address().port;await new Promise(r=>server.close(r));return p;}
const apiPort=await port(),uiPort=await port();
const base=`http://127.0.0.1:${uiPort}`,password=randomBytes(24).toString('hex');
function start(command,args,env){const child=spawn(command,args,{cwd:root,env:{...process.env,...env},stdio:'pipe'});child.stdout.resume();child.stderr.resume();children.push(child);}
async function ready(url){for(let i=0;i<100;i++){if(children.some(c=>c.exitCode!==null))throw new Error('Isolated fixture service failed');try{if((await fetch(url)).ok)return;}catch{}await new Promise(r=>setTimeout(r,100));}throw new Error('Local startup timeout');}
let browser;
try{
 start(resolve(root,'backend/.venv/bin/python'),['backend/tests/fraud_memory_server.py'],{PYTHONPATH:'backend',APP_ENV:'test',TRANSACTION_PROVIDER:'synthetic',LIFECYCLE_PASSCODE:password,LIFECYCLE_PORT:String(apiPort),DATABASE_PATH:join(temp,'test.db'),SOURCE_DATABASE_DIR:join(temp,'sources'),FRONTEND_ORIGIN:base});
 start(process.execPath,['frontend/node_modules/vite/bin/vite.js','frontend','--host','127.0.0.1','--port',String(uiPort),'--strictPort'],{API_PROXY_TARGET:`http://127.0.0.1:${apiPort}`});
 await Promise.all([ready(base),ready(`http://127.0.0.1:${apiPort}/api/v1/auth/me`)]);
 browser=await chromium.launch({headless:true,...(existsSync('/Applications/Google Chrome.app')?{channel:'chrome'}:{})});
 const page=await browser.newPage({viewport:{width:1440,height:1000}});page.setDefaultTimeout(15000);
 const errors=[];page.on('pageerror',()=>errors.push('browser error'));

 const calls = new Map();
 page.on('request', request => {
   if (request.method() === 'GET' && request.url().endsWith('/relevant-memories')) {
     const path = new URL(request.url()).pathname;
     calls.set(path, (calls.get(path) ?? 0) + 1);
   }
 });
 const gotoCase = async id => { await page.evaluate(id => { location.hash = '#/case/' + id + '/activity'; }, id); };
 const card = page.getByRole('region',{name:'Relevant memory',exact:true});
 const none = {memories:[],retrieval_mode:'local_fallback',checked_at:null,failure:null};
 const summary = 'The demo user explicitly confirmed a groceries alert as normal. Recheck future evidence.';
 const memory = {memory_id:'mem_ui',summary,source:'backboard',created_at:'2026-10-18T12:00:00Z',verification:'unverified'};
 const firstPath='/api/v1/transactions/txn_fixture_1/relevant-memories';
 const secondPath='/api/v1/transactions/txn_fixture_2/relevant-memories';
 await page.goto(base + '/#/case/missing');
 await page.getByLabel('Passcode',{exact:true}).fill(password);
 await page.getByRole('button',{name:'Sign in',exact:true}).click();
 await page.getByText('That transaction was not found.',{exact:true}).waitFor();
 assert.equal(calls.size,0,'missing transaction must not trigger memory reads');
 await gotoCase('txn_fixture_1');
 await card.getByText('No relevant memory found.',{exact:true}).waitFor();
 assert.equal(await page.locator('.relevant').count(),1,'only the main card is rendered');
 assert.equal(await page.locator('.steps .memnote').count(),0,'old component is not rendered');
 assert.equal(calls.get(firstPath),1,'StrictMode must not duplicate a memory request');
 assert.equal(await page.getByRole('link',{name:'See how memory works',exact:true}).getAttribute('href'),'#/memory/lab');
 assert.equal(await page.getByRole('link',{name:'See how privacy works',exact:true}).getAttribute('href'),'#/privacy/lab');
 let phase='error';
 await page.route('**' + secondPath, async route => {
   if(phase==='error') return route.fulfill({status:503,json:{error:{code:'fixture_unavailable'}}});
   return route.fulfill({json:{...none,memories:[memory],retrieval_mode:phase==='unavailable'?'unavailable':'local_fallback',failure:'missing_key'}});
 });
 await gotoCase('txn_fixture_2');
 await card.getByText('Memory could not be loaded.',{exact:true}).waitFor();
 assert(!(await card.textContent()).includes(summary));
 assert.equal(await page.locator('.facts .memnote').count(),0,'failed memory read hides the shared facts note');
 phase='unverified';
 await card.getByRole('button',{name:'Try again',exact:true}).click();
 await card.getByText('Relevant memory found',{exact:true}).waitFor();
 assert((await card.textContent()).includes('Could not be verified with Backboard just now.'));
 assert((await card.textContent()).includes('Provider verification is incomplete.'));
 assert.equal(calls.get(secondPath),2,'retry issues exactly one fresh read');
 assert.equal(await page.locator('.facts .memnote').count(),1,'facts note shares the successful read');
 assert((await page.locator('.facts .memnote').textContent()).includes('Could not be verified with Backboard just now.'));
 phase='unavailable';
 await gotoCase('missing');
 await page.getByText('That transaction was not found.',{exact:true}).waitFor();
 await gotoCase('txn_fixture_2');
 await card.getByText('Memory could not be checked right now.',{exact:true}).waitFor();
 assert(!(await card.textContent()).includes(summary),'unavailable payload must not show a stale sentence');
 assert.equal(await page.locator('.facts .memnote').count(),0,'unavailable memory hides the shared facts note');
 let held;
 await page.route('**' + firstPath, route => { held=route; });
 await gotoCase('txn_fixture_1');
 await page.waitForFunction(()=>document.querySelector('.relevant')?.textContent.includes('Checking your saved memories'));
 for(let i=0;!held&&i<100;i++)await new Promise(r=>setTimeout(r,10));
 assert(held);
 phase='unverified';
 await gotoCase('txn_fixture_2');
 await card.getByText('Relevant memory found',{exact:true}).waitFor();
 const unrelated='The demo user explicitly confirmed a streaming alert as normal. Recheck future evidence.';
 await held.fulfill({json:{...none,memories:[{...memory,summary:unrelated}]}});
 await page.waitForTimeout(100);
 assert(!(await card.textContent()).includes(unrelated),'late response from another case must be ignored');
 // UI-only fixture responses exercise main pagination; rules are separately exercised by the lifecycle suite.
 let evidenceMissing=false;
 await page.route('**/api/v1/workspace/refresh',async route=>{
   if(route.request().method()!=='POST')return route.continue();
   const upstream=await route.fetch();const snapshot=await upstream.json();
   const template=snapshot.transactions[0];
   snapshot.transactions=Array.from({length:7},(_,i)=>({...template,id:'txn_ui_'+i,merchant_display:'UI FIXTURE '+i,
     amount:300+i,source:'synthetic',merchant_category:evidenceMissing?'other':'groceries',
     direction:evidenceMissing?'unknown':'debit',settlement_status:'completed'}));
   await route.fulfill({json:snapshot});
 });
 await page.route('**/api/v1/alerts',route=>route.fulfill({json:evidenceMissing?[]:Array.from({length:7},(_,i)=>({
   alert_id:'alert_txn_ui_'+i,transaction_id:'txn_ui_'+i,alert_type:'amount_anomaly',severity:'high',
   needs_human:true,confidence:1,evidence:['Explicit pagination UI fixture.'],provider_mode:'rules-only',
   model_version:null,request_id:'ui-test',status:'open'}))}));
 await page.goto(base+'/#/today');
 await page.reload();
 const queue=page.locator('.queuepanel');
 await queue.locator('li').first().waitFor();
 assert.equal(await queue.locator('li').count(),3);
 await queue.getByRole('button',{name:'Next page',exact:true}).click();
 assert.equal(await queue.locator('li').count(),3);
 await queue.getByRole('button',{name:'Next page',exact:true}).click();
 assert.equal(await queue.locator('li').count(),1);
 assert(await queue.getByRole('button',{name:'Next page',exact:true}).isDisabled());
 await queue.getByRole('button',{name:'Previous page',exact:true}).click();
 assert.equal(await queue.locator('li').count(),3);
 evidenceMissing=true;
 await page.reload();
 await page.getByRole('heading',{name:'Some transactions need more evidence.',exact:true}).waitFor();
 assert.equal(await page.getByText(/7 transactions checked by the rules/).count(),0);
 assert((await page.locator('.today').textContent()).includes('An absent alert is not a safe verdict.'));
 await page.route('**/api/v1/transactions/txn_ui_0/relevant-memories',route=>route.fulfill({json:{...none,memories:[memory]}}));
 await page.getByRole('link',{name:'Activity',exact:true}).click();
 await page.locator('tr').filter({hasText:'UI FIXTURE 0'}).getByRole('button').click();
 await page.getByRole('heading',{name:'What was checked',exact:true}).waitFor();
 assert((await page.locator('.case').textContent()).includes('Insufficient evidence'));
 assert.equal(await page.locator('.relevant').count(),1);
 await card.getByText('No relevance claim: this transaction has no specific category evidence.',{exact:true}).waitFor();
 assert(!(await card.textContent()).includes(summary),'generic other must not claim a match even if a payload supplies a row');
 assert.equal(await page.locator('.facts .memnote').count(),0);
 assert.deepEqual(errors,[]);
 console.log('PASS: merge resolution — three-item pagination, dynamic headings, insufficient evidence, one card/read, hook missing/found transitions, retry/status states, and stale-response isolation.');
}finally{if(browser)await browser.close();for(const child of children)child.kill('SIGTERM');}
