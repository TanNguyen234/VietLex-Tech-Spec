// Synthetic fixtures only. Set NODE_PATH to the installed Playwright package.
const {chromium} = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
(async () => {
  const out = process.argv[2] || '.tmp-redesign';
  fs.mkdirSync(out, {recursive:true});
  const browser = await chromium.launch({headless:true});
  const page = await browser.newPage();
  const routes = await (await page.request.get('http://127.0.0.1:8765/__pages')).json();
  const results=[];
  for (const width of [1440,390]) {
    await page.setViewportSize({width,height:1000});
    for (const route of routes) {
      const response = await page.goto('http://127.0.0.1:8765'+route, {waitUntil:'domcontentloaded'});
      await page.evaluate(()=>document.fonts.ready);
      const layout=await page.evaluate(()=>({overflow:document.documentElement.scrollWidth>innerWidth+1,
        heading:document.querySelector('h1,h2')?.textContent,
        overflowing:[...document.querySelectorAll('body *')].filter(e=>{const r=e.getBoundingClientRect();return r.width>0&&r.right>innerWidth+2&&getComputedStyle(e).position!=='fixed'&&!e.closest('.drawer');}).slice(0,8).map(e=>e.className)}));
      results.push({route,width,status:response.status(),...layout});
      const name=route==='/'?'home':route.slice(1).replaceAll('/','-');
      await page.screenshot({path:path.join(out,`${name}-${width}.png`),fullPage:true});
    }
  }
  for(const route of ['/','/login','/admin','/documents/sample']) {
    await page.goto('http://127.0.0.1:8765'+route,{waitUntil:'domcontentloaded'});
    await page.evaluate(()=>{document.documentElement.dataset.theme='dark'});
    await page.evaluate(()=>document.fonts.ready);
    await page.screenshot({path:path.join(out,`dark-${route.replaceAll('/','-')||'home'}.png`),fullPage:true});
  }
  fs.writeFileSync(path.join(out,'browser-results.json'),JSON.stringify(results,null,2));
  console.log(JSON.stringify(results));
  await browser.close();
  if(results.some(r=>r.status!==200||r.overflow))process.exitCode=1;
})().catch(e=>{console.error(e);process.exit(1)});
