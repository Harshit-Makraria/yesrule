const puppeteer = require('puppeteer-core');
const BASE = process.env.BASE || 'http://localhost:8790';
const shots = process.argv[2];
let fails = 0;
const log = (ok, msg) => { if (!ok) fails++; console.log(`${ok ? 'PASS' : 'FAIL'}  ${msg}`); };
const wait = ms => new Promise(r => setTimeout(r, ms));

(async () => {
  const b = await puppeteer.launch({ executablePath: process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless: true });
  const p = await b.newPage();
  await p.setViewport({ width: 1280, height: 900 });
  const errors = [];
  p.on('pageerror', e => errors.push(e.message));
  p.on('console', m => m.type() === 'error' && errors.push(m.text()));
  p.on('dialog', async d => { console.log('      dialog: ' + d.message().replace(/\n/g, ' | ')); await d.accept(); });
  const text = () => p.$eval('#view', e => e.innerText);
  const click = async sel => { const el = await p.$(sel); if (!el) throw new Error('missing ' + sel); await el.click(); await wait(700); };

  await p.goto(BASE + '/#inbox'); await wait(1000);
  let t = await text();
  log(t.includes('invoice-bot') && t.includes('git push --force'), 'Inbox shows both pending requests');
  log(await p.$eval('header', e => /audit chain OK|Chain OK|verified/i.test(e.innerText)), 'Header shows audit chain OK');
  await p.screenshot({ path: shots + '/1-inbox.png' });

  for (let i = 0; i < 2; i++) {
    const cards = await p.$$('[data-req]');
    if (!cards.length) break;
    const s = await cards[0].evaluate(e => e.innerText);
    const btn = await cards[0].$(s.includes('git push') ? '[data-deny]' : '[data-approve]');
    await btn.click(); await wait(800);
  }
  t = await text();
  log(/Nothing waiting|All clear/i.test(t), 'Approve + Deny buttons clear the inbox');
  const st = await (await fetch(BASE + '/v1/requests?limit=2')).json();
  log(st.map(r => r.status).sort().join() === 'approved,denied', 'Database shows approved + denied: ' + st.map(r => r.status).join(','));

  await p.goto(BASE + '/#history'); await wait(800);
  t = await text(); log(/denied/i.test(t) && /approved/i.test(t), 'History lists the decisions');

  await p.goto(BASE + '/#rules'); await wait(700);
  await click('[data-mine]'); await wait(800);
  t = await text(); log(t.includes('R-1') && /proposed/i.test(t), 'Find rules now -> proposed rules with evidence');
  await p.screenshot({ path: shots + '/2-rules.png', fullPage: true });
  await click('[data-backtest="R-1"]');
  await click('[data-accept="R-1"]');
  const r1 = (await (await fetch(BASE + '/v1/rules')).json()).find(r => r.id === 'R-1');
  log(r1.status === 'active', 'Accept turns R-1 active');

  const rr = await (await fetch(BASE + '/v1/requests', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ agent: 'invoice-bot', platform: 'n8n', action: 'send_email', target: { type: 'invoice' }, amount: { value: 1200 }, recipient: { id: 'billing@acme-dental.com', known: true }, reversible: false, environment: 'production', client: 'acme-dental' }) })).json();
  log(rr.status === 'auto_approved' && rr.receipt?.rule === 'R-1', `Next invoice auto-approved with receipt (${rr.status}, rule ${rr.receipt?.rule}, ${rr.receipt?.evidence?.approvals} approvals)`);

  await p.goto(BASE + '/#history'); await wait(800);
  await p.screenshot({ path: shots + '/3-history.png' });
  const wrong = await p.$('[data-flag]');
  log(!!wrong, '"Wrong" button shown on the auto-approval');
  if (wrong) { await wrong.click(); await wait(800); }
  const r1b = (await (await fetch(BASE + '/v1/rules')).json()).find(r => r.id === 'R-1');
  log(r1b.status === 'paused', 'Clicking Wrong pauses R-1 (drift watch)');

  await p.goto(BASE + '/#lines'); await wait(600);
  await p.type('#lf', 'amount.value'); await p.select('#lo', 'gte'); await p.type('#lv', '100000'); await p.type('#ld', 'Big money always asks');
  await click('[data-addline]');
  log((await text()).includes('Big money always asks'), 'Hard line added from UI');

  await p.goto(BASE + '/#insights'); await wait(800);
  t = await text(); log(/Requests/i.test(t) && t.includes('invoice-bot'), 'Insights renders stats');
  await p.screenshot({ path: shots + '/4-insights.png' });
  await p.goto(BASE + '/#audit'); await wait(800);
  t = await text(); log(/verified/i.test(t), 'Audit tab: chain verified');
  await p.screenshot({ path: shots + '/5-audit.png' });

  await p.setViewport({ width: 390, height: 844 });
  await p.goto(BASE + '/#rules'); await wait(800);
  const overflow = await p.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  log(!overflow, 'Phone width (390px): no horizontal scroll');
  await p.screenshot({ path: shots + '/6-mobile.png' });

  log(errors.length === 0, 'No JavaScript errors in the page' + (errors.length ? ': ' + errors.join(' ; ') : ''));
  await b.close();
  console.log(fails ? `\n${fails} FAILED` : '\nALL PASSED');
  process.exit(fails ? 1 : 0);
})().catch(e => { console.log('FAIL  crashed: ' + e.message); process.exit(1); });
