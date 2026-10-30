// Mobile UI check (390x844) against a fixture-mode server. Asserts the main journeys render and work.
// Start the server:  cd backend && FINN_FIXTURE_MODE=1 uvicorn app.main:app --port 8000
// Run:               node scripts/e2e_mobile.cjs [http://localhost:8000]   (needs `npm i -g playwright` or local playwright)
const { chromium } = require('playwright');
const base = process.argv[2] || 'http://localhost:8000';
let failed = 0;
const ok = (cond, msg) => { console.log(`${cond ? 'PASS' : 'FAIL'}  ${msg}`); if (!cond) failed++; };

(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
  const errors = [];
  p.on('pageerror', e => errors.push(e.message));

  await p.goto(`${base}/#/today`);
  await p.waitForSelector('.brief');
  ok(/need/.test(await p.textContent('.brief')), 'Today: triage sentence renders');
  ok(await p.locator('#tier-high .row').count() > 0, 'Today: high-priority filings listed');
  ok(await p.locator('#tier-low .row').count() === 0, 'Today: routine filings folded by default');
  await p.click('.fold');
  ok(await p.locator('#tier-low .row').count() > 0, 'Today: routine filings expand');
  const before = await p.locator('.feed .row').count();
  await p.selectOption('.filters select >> nth=1', 'results');
  ok((await p.locator('.feed .row').count()) < before, 'Today: category filter narrows the list');
  await p.click('text=Clear');
  await p.click('text=7 days');
  await p.waitForTimeout(500);
  ok(await p.locator('.chip.on', { hasText: '7 days' }).count() === 1, 'Today: window selector switches');
  ok((await p.evaluate(() => document.documentElement.scrollWidth)) <= 390, 'Today: no horizontal overflow at 390px');

  await p.click('#tier-high .row:has-text("Dixon")');
  await p.waitForSelector('.num-table');
  ok(/Revenue/.test(await p.textContent('.num-table')), 'Filing: results QoQ/YoY table renders');
  ok(await p.locator('.sheet a:has-text("Open original filing")').count() === 1, 'Filing: original source link present');
  await p.keyboard.press('Escape');
  ok(await p.locator('.sheet').count() === 0, 'Filing: Escape closes the sheet');

  await p.goto(`${base}/#/alerts`);
  await p.waitForSelector('.alert-list li');
  ok(await p.locator('.alert-list li').count() > 0, 'Alerts: EOD threshold alerts render');

  await p.goto(`${base}/#/research`);
  await p.fill('#rq', 'irctc');
  await p.waitForSelector('.suggest button');
  await p.click('.suggest button');
  await p.waitForSelector('.report', { timeout: 30000 });
  ok(/IRCTC|Indian Railway/.test(await p.textContent('.report h2')), 'Research: report for non-portfolio company');
  ok(await p.locator('#r-sources .sources li').count() >= 2, 'Research: sources listed');
  await p.locator('.section-nav button', { hasText: 'Bull / bear' }).click();
  await p.waitForTimeout(400);
  ok(p.url().includes('#/research/IRCTC'), 'Research: section nav does not break routing');
  await p.locator('.cite').first().click();
  ok(await p.locator('.sheet').count() === 1, 'Research: citation opens evidence');

  await p.goto(`${base}/#/settings`);
  await p.waitForSelector('.checks');
  await p.fill('.field input >> nth=0', '3');
  await p.click('text=Save alert rules');
  await p.waitForSelector('text=Alert rules saved.');
  ok(true, 'Settings: alert rules save');

  ok(errors.length === 0, `No uncaught page errors${errors.length ? ': ' + errors.join('; ') : ''}`);
  await b.close();
  console.log(failed ? `\n${failed} check(s) failed` : '\nAll UI checks passed');
  process.exit(failed ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
