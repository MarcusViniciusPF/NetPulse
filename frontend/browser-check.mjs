import { chromium } from 'playwright-core';
import assert from 'node:assert/strict';
import { existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const output = fileURLToPath(new URL('../artifacts/browser/', import.meta.url));
mkdirSync(output, {recursive:true});

const executablePath = process.env.CHROME_PATH || [
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  '/usr/bin/chromium', '/usr/bin/chromium-browser', '/usr/bin/google-chrome',
].find(existsSync);
assert(executablePath, 'Defina CHROME_PATH com o caminho para Chrome/Chromium instalado.');
const browser = await chromium.launch({ executablePath, headless: true });
const errors = [];
const report = [];
try {
  for (const base of ['http://127.0.0.1:5173', 'http://127.0.0.1:8000']) {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    page.on('pageerror', e => errors.push(`${base}: ${e.message}`));
    page.on('console', m => { if(m.type()==='error') errors.push(`${base}: ${m.text()}`); });
    const responses = [];
    page.on('response', r => { if(r.url().includes('/api/')) responses.push({url:r.url(),status:r.status()}); });
    await page.goto(base);
    await page.getByRole('heading', {name:'Visão geral da rede'}).waitFor();
    await page.waitForFunction(() => document.querySelectorAll('.target-row').length > 0);
    await page.waitForSelector('.chart .recharts-surface');
    assert.equal(await page.locator('.alert').count(), 0);
    assert(await page.locator('.metric-value').first().innerText() !== '—');
    assert(await page.locator('.chart .recharts-area').count() > 0);
    assert(await page.locator('.chart .recharts-area-dots circle').count() > 0, 'Amostras isoladas devem estar visíveis');
    assert.equal(await page.locator('.chart .recharts-area-dots circle').first().getAttribute('fill'),'#5aa6ff');
    await Promise.all([
      page.waitForResponse(r=>r.url().includes('/api/dashboard?hours=1')&&r.status()===200),
      page.getByRole('button', {name:'1h', exact:true}).click(),
    ]);
    await page.getByRole('button', {name:'Configurar monitoramento',exact:true}).click();
    await page.getByRole('dialog').waitFor();
    await Promise.all([
      page.waitForResponse(r=>r.url().includes('/api/config')&&r.request().method()==='PUT'&&r.status()===200),
      page.getByRole('button',{name:'Salvar configuração',exact:true}).click(),
    ]);
    await page.getByRole('dialog').waitFor({state:'hidden'});
    assert.equal(await page.evaluate(async()=> (await fetch('http://127.0.0.1:8000/api/health')).status),200);
    await page.getByRole('button',{name:/Histórico de eventos/}).click();
    await page.getByRole('heading',{name:'Quedas e recuperações'}).waitFor();
    await page.getByRole('button',{name:'Visão geral',exact:true}).click();
    await page.screenshot({path:`${output}/dashboard-${new URL(base).port}-desktop.png`,fullPage:true});
    await page.setViewportSize({width:390,height:844});
    await page.waitForTimeout(300);
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth), 'Overflow horizontal no celular');
    await page.screenshot({path:`${output}/dashboard-${new URL(base).port}-mobile.png`,fullPage:true});
    assert(responses.some(r=>r.url.includes('/api/dashboard')&&r.status===200));
    assert(responses.every(r=>r.status===200),JSON.stringify(responses));
    report.push({base,apiResponses:responses.length,desktop:true,mobile:true,charts:true,settingsDialog:true,events:true});
    await page.close();
  }
  assert.deepEqual(errors,[]);
  writeFileSync(`${output}/browser.json`,JSON.stringify({report,errors},null,2));
  console.log(JSON.stringify({report,errors},null,2));
} finally { await browser.close(); }
