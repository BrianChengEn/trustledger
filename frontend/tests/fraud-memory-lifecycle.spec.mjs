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
 await page.goto(base);await page.getByLabel('Passcode',{exact:true}).fill(password);await page.getByRole('button',{name:'Sign in',exact:true}).click();
 await page.getByRole('button',{name:'Review this charge',exact:true}).click();
 assert(page.url().includes('txn_fixture_2'));
 await page.getByRole('radio',{name:/looks normal/}).click();
 assert.equal(await page.getByRole('checkbox').isChecked(),false);
 await page.getByRole('checkbox').check();
 const saved=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/confirmations'));
 await page.getByRole('button',{name:'Confirm normal and remember',exact:true}).click();
 const receipt=await(await saved).json();assert.equal(receipt.memory_status,'written');
 await page.getByText('You marked this normal',{exact:true}).waitFor();
 await page.getByRole('link',{name:'Activity',exact:true}).click();
 await page.locator('tr').filter({hasText:'TEST FIXTURE 1'}).getByRole('button').click();
 const context=page.getByRole('region',{name:'Relevant memory',exact:true});
 await context.getByText(/Checked with Backboard just now/).waitFor();
 assert((await context.textContent()).includes('groceries alert as normal'));
 // Prior normal history must leave the second transaction's high-amount alert intact.
 await page.getByRole('radio',{name:/looks normal/}).waitFor();
 const explained=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/explanation'));
 await page.getByRole('button',{name:'Explain this alert',exact:true}).click();
 const explanation=await(await explained).json();assert.equal(explanation.alert_type,'amount_anomaly');assert.equal(explanation.needs_human,true);
 await page.locator('nav[aria-label="Main"] a[href="#/memory"]').click();
 await page.getByRole('button',{name:'Delete memory',exact:true}).click();
 const verification=page.waitForResponse(r=>r.url().endsWith('/deletion-verification')&&r.request().method()==='GET');
 await page.getByRole('button',{name:'Yes, delete this memory',exact:true}).click();
 assert.equal((await(await verification).json()).status,'absent');
 await page.getByText('Nothing is remembered yet.',{exact:true}).waitFor();
 await page.getByRole('link',{name:'Activity',exact:true}).click();
 await page.locator('tr').filter({hasText:'TEST FIXTURE 1'}).getByRole('button').click();
 await page.getByRole('region',{name:'Relevant memory',exact:true}).getByText('No relevant memory found.',{exact:true}).waitFor();
 assert.equal(errors.length,0);
 console.log('PASS: FULL_STATEFUL_LIFECYCLE_VERIFIED_IN_ISOLATED_TEST — real rules, alert IDs, consent, mocked Backboard persistence, related context, grounded explanation, verified deletion, no reappearance.');
}finally{if(browser)await browser.close();for(const child of children)child.kill('SIGTERM');}
