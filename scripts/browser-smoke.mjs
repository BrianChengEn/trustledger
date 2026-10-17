// Run in CI against its own localhost services; no external/vendor access is allowed.
import {createRequire} from 'node:module';
import fs from 'node:fs';
import assert from 'node:assert/strict';
const require=createRequire(new URL('../frontend/package.json',import.meta.url));
const {chromium}=require('playwright');
fs.mkdirSync('artifacts',{recursive:true});
const browser=await chromium.launch({headless:true});
try {
  const context=await browser.newContext({viewport:{width:1440,height:1000}});
  const errors=[];const page=await context.newPage();
  page.on('pageerror',e=>errors.push(String(e)));
  await page.route('**/*',route=>{
    const url=new URL(route.request().url());
    return ['127.0.0.1','localhost'].includes(url.hostname)?route.continue():route.abort();
  });
  await page.goto('http://127.0.0.1:8765/index.html');
  const links=page.locator('a.navitem[data-file]');
  const files=await links.evaluateAll(es=>es.map(e=>e.dataset.file));
  for(const file of files){
    await page.locator(`a.navitem[data-file="${file}"]`).click();
    await page.locator('main article h1').waitFor();
    assert((await page.locator('main article').innerText()).length>80, file+' is empty');
  }
  await page.goto('http://127.0.0.1:8765/index.html#diagrams');
  for(let i=0;i<6;i++){
    await page.locator(`[data-diagram="${i}"]`).click();
    const size=await page.locator('.stage svg').boundingBox();
    assert(size&&size.width>600&&size.height>300,'Missing or tiny diagram '+i);
    assert(!(await page.locator('.stage').innerText()).includes('Syntax error'));
  }
  await page.locator('[data-diagram="0"]').click();
  await page.locator('[data-expand]').click();
  await page.screenshot({path:'artifacts/architecture-desktop.png'});
  await page.keyboard.press('Escape');
  await page.locator('[data-diagram="1"]').click();
  await page.locator('[data-expand]').click();
  await page.screenshot({path:'artifacts/data-flow-desktop.png'});
  await page.keyboard.press('Escape');
  await page.setViewportSize({width:390,height:844});
  await page.goto('http://127.0.0.1:8765/index.html');
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+2));
  await page.screenshot({path:'artifacts/docs-mobile.png',fullPage:true});
  await page.goto('http://127.0.0.1:8765/pages/START-HERE-md.html');
  await page.locator('main article h1').waitFor();
  await page.setViewportSize({width:1440,height:1000});
  await page.goto('http://127.0.0.1:5173');
  await page.getByRole('button',{name:/Possible duplicate/}).click();
  await page.getByRole('heading',{name:'Privacy Inspector'}).waitFor();
  await page.locator('pre').filter({hasText:'same_category_same_amount_24h_count'}).waitFor();
  await page.screenshot({path:'artifacts/app-privacy-desktop.png',fullPage:true});
  await page.getByRole('checkbox').check();
  await page.getByRole('button',{name:'This is normal'}).click();
  await page.getByRole('status').filter({hasText:'Confirmed normal'}).waitFor();
  await page.getByRole('button',{name:/Confirmed memory/}).click();
  await page.getByRole('button',{name:'Delete memory'}).click();
  await page.getByText('No stored facts.',{exact:false}).waitFor();
  await page.setViewportSize({width:390,height:844});
  await page.getByRole('button',{name:'Overview & transactions'}).click();
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+2));
  await page.screenshot({path:'artifacts/app-mobile.png',fullPage:true});
  assert.deepEqual(errors,[],'Browser runtime errors');
  console.log(`PASS: ${files.length} reading pages, six diagrams, zoom/fullscreen, mobile layout, confirmation/memory/delete.`);
}finally{await browser.close()}
