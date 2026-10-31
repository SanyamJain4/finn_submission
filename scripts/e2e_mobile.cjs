// Mobile UI check (390x844) against a fixture-mode server. Asserts the main journeys render and work.
// Start the server:  cd backend && FINN_FIXTURE_MODE=1 uvicorn app.main:app --port 8000
// Run:               node scripts/e2e_mobile.cjs [http://localhost:8000]   (needs playwright)
const { chromium } = require('playwright');
const base = process.argv[2] || 'http://localhost:8000';
let failed = 0;
const ok = (cond, msg) => { console.log(`${cond ? 'PASS' : 'FAIL'}  ${msg}`); if (!cond) failed++; };
const noOverflow = async (p, where) => ok((await p.evaluate(() => document.documentElement.scrollWidth)) <= 390, `${where}: no horizontal overflow at 390px`);

(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
  const errors = [];
  p.on('pageerror', e => errors.push(e.message));

  // Portfolio first so Today can show the snapshot
  await p.goto(`${base}/#/portfolio`);
  await p.waitForSelector('text=Load an example portfolio');
  await p.click('text=Load an example portfolio');
  await p.waitForSelector('.pf-totals');
  ok(/₹/.test(await p.textContent('.pf-hero dd')), 'Portfolio: total value renders');
  ok(await p.locator('.holdings-table tbody tr').count() >= 5, 'Portfolio: example holdings listed');
  ok(await p.locator('.sharebar').count() === 2, 'Portfolio: sector and market-cap allocation');
  await p.click('text=Add holding');
  await p.fill('.hold-form input >> nth=0', 'ITC');
  await p.fill('.hold-form input >> nth=1', '100');
  await p.fill('.hold-form input >> nth=2', '250');
  await p.click('.hold-form button[type=submit]');
  await p.waitForTimeout(800);
  ok(await p.locator('.holdings-table th:has-text("ITC")').count() === 1, 'Portfolio: add holding');
  await p.click('.holdings-table th:has-text("ITC")');
  await p.click('.sheet button.danger');
  await p.waitForTimeout(800);
  ok(await p.locator('.holdings-table th:has-text("ITC")').count() === 0, 'Portfolio: remove holding');
  await noOverflow(p, 'Portfolio');

  await p.goto(`${base}/#/today`);
  await p.waitForSelector('.index-card .index-level');
  ok(await p.locator('.index-card').count() === 4, 'Today: four Indian indices');
  ok(/close|delayed/i.test(await p.textContent('.data-stamp')), 'Today: index timestamp/source shown');
  await p.waitForSelector('.snap-value');
  ok(true, 'Today: portfolio snapshot renders');
  await p.waitForSelector('.brief-card .brief-head');
  ok(await p.locator('.brief-lines li').count() > 0, 'Today: daily briefing with lines');
  await p.waitForSelector('.filings .brief');
  ok(/need/.test(await p.textContent('.filings .brief')), 'Today: filings triage renders');
  await p.selectOption('.filters select >> nth=1', 'results');
  ok(await p.locator('.filings .feed .row').count() >= 1, 'Today: category filter');
  await p.click('#tier-high .row:has-text("Dixon")');
  await p.waitForSelector('.num-table');
  ok(/Revenue/.test(await p.textContent('.num-table')), 'Filing: results QoQ/YoY table');
  await p.keyboard.press('Escape');
  await noOverflow(p, 'Today');

  await p.goto(`${base}/#/alerts`);
  await p.waitForSelector('.alert-item');
  const before = await p.locator('.alert-item.unread').count();
  await p.click('text=Mark all read');
  ok(before > 0 && await p.locator('.alert-item.unread').count() === 0, 'Alerts: mark all read');
  const open = await p.locator('.alert-list:not(.acked) > .alert-item').count();
  await p.locator('.alert-item button:has-text("Acknowledge")').first().click();
  ok(await p.locator('.alert-list:not(.acked) > .alert-item').count() === open - 1, 'Alerts: acknowledge moves alert out');
  await p.click('.chip:has-text("Price & volume")');
  ok(await p.locator('.alert-item.k-market').count() === await p.locator('.alert-list:not(.acked) > .alert-item').count(), 'Alerts: type filter');
  await noOverflow(p, 'Alerts');

  await p.goto(`${base}/#/copilot`);
  await p.waitForSelector('.starter');
  await p.fill('#cq', 'How did Dixon do?');
  await p.click('.ask-row button[type=submit]');
  await p.waitForSelector('.answer', { timeout: 30000 });
  ok(await p.locator('.answer').count() === 1, 'Copilot: answers (or explains no model) with sources');
  await noOverflow(p, 'Copilot');

  await p.goto(`${base}/#/research`);
  await p.fill('#rq', 'irctc');
  await p.waitForSelector('.suggest button');
  await p.click('.suggest button');
  await p.waitForSelector('.report', { timeout: 30000 });
  ok(/IRCTC|Indian Railway/.test(await p.textContent('.report h2')), 'Research: report for non-portfolio company');
  ok(await p.locator('.report .chart').count() >= 2, 'Research: charts render');
  await p.locator('.section-nav button', { hasText: 'Bull / bear' }).click();
  await p.waitForTimeout(400);
  ok(p.url().includes('#/research/IRCTC'), 'Research: section nav keeps the route');
  await noOverflow(p, 'Research');

  await p.goto(`${base}/#/account`);
  await p.waitForSelector('.checks');
  await p.fill('.field input >> nth=0', '3');
  await p.click('text=Save alert rules');
  await p.waitForSelector('text=Alert rules saved.');
  ok(true, 'Account: alert rules save');
  ok(await p.locator('text=Watchlist').count() >= 1 && await p.locator('#system').count() === 1, 'Account: watchlist + system status sections');
  await noOverflow(p, 'Account');

  ok(errors.length === 0, `No uncaught page errors${errors.length ? ': ' + errors.join('; ') : ''}`);
  await b.close();
  console.log(failed ? `\n${failed} check(s) failed` : '\nAll UI checks passed');
  process.exit(failed ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
