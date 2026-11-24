// Capture the real SavoRoute React UI in Chromium using the Boston OSM snapshot.
// Default: safe form-only captures; no AI/web requests or invented businesses.
// Explicit live mode: `npm run screenshots -- --live` performs paid API calls,
// uses the operator's configured key, and requires real source-linked matches.
import { chromium } from '@playwright/test';
import { spawn } from 'node:child_process';
import { createServer } from 'node:net';
import { access, mkdir, mkdtemp, readFile, rename, rm, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const args = process.argv.slice(2);
if (args.some(arg => arg !== '--live') || args.filter(arg => arg === '--live').length > 1) {
  throw new Error('Usage: node scripts/capture-screenshots.mjs [--live]');
}
const liveMode = args.includes('--live');
if (liveMode && !process.env.SAVOROUTE_OPENAI_API_KEY?.trim()) {
  throw new Error('Live capture requires SAVOROUTE_OPENAI_API_KEY in this terminal. Do not commit the key.');
}

const project = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const catalog = resolve(project, 'data/real/boston-osm-2026-11.json');
const dist = resolve(project, 'src/savoroute/web/consumer_dist/index.html');
const output = resolve(project, 'docs/screenshots');
const readme = resolve(project, 'README.md');
const port = 8098;
const base = `http://127.0.0.1:${port}`;
const url = `${base}/app/?kind=restaurant&city=Boston`;
const begin = '<!-- SCREENSHOTS_BEGIN -->';
const end = '<!-- SCREENSHOTS_END -->';
const width = 390;
const height = 844;

async function waitUntilReady(proc) {
  for (let attempt = 0; attempt < 80; attempt++) {
    if (proc.exitCode !== null) throw new Error(`SavoRoute server exited (${proc.exitCode})`);
    try {
      const response = await fetch(`${base}/healthz`, { signal: AbortSignal.timeout(750) });
      if (response.ok) return;
    } catch { /* starting */ }
    await new Promise(done => setTimeout(done, 150));
  }
  throw new Error('SavoRoute server did not become ready on 127.0.0.1:8098');
}

async function scrollNear(page, selector, offset = 16) {
  const target = page.locator(selector);
  await target.waitFor({ state: 'visible', timeout: 10000 });
  await target.evaluate((element, topOffset) => {
    const top = window.scrollY + element.getBoundingClientRect().top - topOffset;
    window.scrollTo({ top: Math.max(0, top), behavior: 'instant' });
  }, offset);
  await page.evaluate(() => new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done))));
}

// In default mode, show authentic React input controls without fabricating a
// provider response. A real network request is not possible in this mode.
async function showDisabledProviderForms(page) {
  await page.route('**/v1/ai/status', route => route.fulfill({
    json: { enabled: true, input_types: ['text', 'image'], consent_required: true,
      limitations: 'UI capture only; no AI call' },
  }));
  await page.route('**/v1/live/status', route => route.fulfill({
    json: { enabled: true, consent_required: true,
      limitations: 'UI capture only; no web search' },
  }));
  // Defense in depth: fail if a future UI change unexpectedly submits a call.
  await page.route('**/v1/ai/interpret', () => {
    throw new Error('Default screenshot capture must not call AI interpretation');
  });
  await page.route('**/v1/live/discover', () => {
    throw new Error('Default screenshot capture must not call live search');
  });
}

async function capture(browser, staged, shot) {
  const context = await browser.newContext({
    viewport: { width: shot.width, height: shot.height },
    isMobile: Boolean(shot.mobile), deviceScaleFactor: 1, reducedMotion: 'reduce',
    serviceWorkers: 'block',
  });
  try {
    const page = await context.newPage();
    if (!liveMode) await showDisabledProviderForms(page);
    await page.goto(url, { waitUntil: 'networkidle' });
    await page.getByRole('article').first().waitFor({ state: 'visible', timeout: 10000 });
    await page.evaluate(async () => { await document.fonts.ready; });

    if (shot.position === 'filters') await scrollNear(page, '.discovery-filters');
    if (shot.position === 'results') await scrollNear(page, '.results-status');
    if (shot.position === 'top') await page.evaluate(() => window.scrollTo(0, 0));
    if (shot.position === 'ai') {
      await page.getByLabel('Describe your craving (optional with a photo)')
        .fill('spicy noodles with vegetables');
      if (liveMode) {
        await page.getByLabel(/I agree to send this description/).check();
        const waiting = page.waitForResponse(response =>
          response.url().includes('/v1/ai/interpret') && response.request().method() === 'POST',
        { timeout: 65000 });
        await page.getByRole('button', { name: 'Interpret food' }).click();
        const response = await waiting;
        if (!response.ok()) throw new Error(`Real AI screenshot request failed: HTTP ${response.status()}`);
        await page.locator('.ai-result').waitFor({ state: 'visible', timeout: 10000 });
        await scrollNear(page, '.ai-result', 285);
      } else {
        await scrollNear(page, '.ai-discovery', 70);
      }
    }
    if (shot.position === 'live') {
      await page.getByLabel('Required cuisine', { exact: true }).fill('Persian');
      await page.getByLabel('Required city', { exact: true }).fill('Boston');
      await page.getByLabel('State / region (optional)').fill('MA');
      await page.getByLabel('Country (optional)').fill('United States');
      await page.getByLabel('Additional request (optional)').fill('Traditional Persian food');
      if (liveMode) {
        await page.getByLabel(/I agree to send my search terms/).check();
        const waiting = page.waitForResponse(response =>
          response.url().includes('/v1/live/discover') && response.request().method() === 'POST',
        { timeout: 65000 });
        await page.getByRole('button', { name: 'Discover online' }).click();
        const response = await waiting;
        if (!response.ok()) throw new Error(`Real web search failed: HTTP ${response.status()}`);
        const result = await response.json();
        if (!Array.isArray(result?.web_results) || result.web_results.length === 0 ||
            result.web_results.some(entry => !/^https:\/\//.test(entry.source_url || ''))) {
          throw new Error('No source-linked web restaurants found for Persian in Boston. No screenshot was published.');
        }
        await page.locator('.live-results').waitFor({ state: 'visible', timeout: 10000 });
        await scrollNear(page, '.live-results', 280);
      } else {
        await scrollNear(page, '.live-discovery', 70);
      }
    }
    await page.screenshot({
      path: resolve(staged, shot.filename),
      fullPage: Boolean(shot.fullPage), animations: 'disabled',
    });
    process.stdout.write(`Captured React UI: docs/screenshots/${shot.filename}\n`);
  } finally {
    await context.close();
  }
}

await access(catalog);
await access(dist).catch(() => { throw new Error('Build frontend first: cd webapp && npm run build'); });
const original = await readFile(readme, 'utf8');
const start = original.indexOf(begin);
const finish = original.indexOf(end);
if (start < 0 || finish < start || original.lastIndexOf(begin) !== start || original.lastIndexOf(end) !== finish) {
  throw new Error('README must contain exactly one ordered pair of screenshot markers');
}
await new Promise((done, fail) => {
  const probe = createServer();
  probe.once('error', fail);
  probe.listen({ host: '127.0.0.1', port, exclusive: true }, () => probe.close(done));
}).catch(error => { throw new Error(`Screenshot port ${port} is unavailable: ${error.message}`); });

// The default screenshot run cannot make paid calls even if the user has a key.
// Live mode is explicit and uses the operator's local environment only.
const serverEnv = liveMode ? {
  ...process.env, SAVOROUTE_AI_ENABLED: '1', SAVOROUTE_LIVE_ENABLED: '1',
} : {
  ...process.env, SAVOROUTE_AI_ENABLED: '0', SAVOROUTE_LIVE_ENABLED: '0',
  SAVOROUTE_OPENAI_API_KEY: '',
};
const proc = spawn(process.env.SAVOROUTE_COMMAND || 'savoroute', [
  'web', 'serve', '--catalog', catalog, '--host', '127.0.0.1', '--port', String(port),
], { cwd: project, stdio: 'inherit', env: serverEnv });
let browser;
let staged;
try {
  await waitUntilReady(proc);
  await mkdir(output, { recursive: true });
  staged = await mkdtemp(resolve(output, '.savoroute-capture-'));
  browser = await chromium.launch({ headless: true });
  const shots = [
    { filename: 'consumer-desktop-real.png', width: 1440, height: 900, fullPage: true },
    { filename: 'consumer-mobile-real.png', width, height, mobile: true, fullPage: true },
    { filename: 'consumer-mobile-search.png', width, height, mobile: true, position: 'top' },
    { filename: 'consumer-mobile-filters.png', width, height, mobile: true, position: 'filters' },
    { filename: 'consumer-mobile-results.png', width, height, mobile: true, position: 'results' },
    { filename: 'consumer-mobile-ai-discovery.png', width, height, mobile: true, position: 'ai' },
    { filename: 'consumer-mobile-live-discovery.png', width, height, mobile: true, position: 'live' },
  ];
  for (const shot of shots) await capture(browser, staged, shot);

  const gallery = [
    begin,
    'These screenshots show the current SavoRoute React interface with the Boston OSM',
    'catalog. The catalog reflects a dated source snapshot; check current details',
    'before visiting.',
    liveMode ? 'The AI and online-discovery panels show actual API responses captured during this session.' :
      'The AI and online-discovery panels show the input forms only. No external model or web search was used.',
    liveMode ? 'Web-discovered candidates link to sources; restaurant status and menus have not been independently checked.' :
      'To capture actual source-linked AI/web results, use `npm run screenshots -- --live` with a local server-side API key.',
    '',
    '#### Desktop application',
    '',
    '![SavoRoute desktop React consumer app](docs/screenshots/consumer-desktop-real.png)',
    '',
    '#### Mobile search and browsing',
    '',
    '| Search | Filters | Catalog results |',
    '| :---: | :---: | :---: |',
    '| ![SavoRoute mobile search](docs/screenshots/consumer-mobile-search.png) | ![SavoRoute mobile filters](docs/screenshots/consumer-mobile-filters.png) | ![SavoRoute mobile catalog results](docs/screenshots/consumer-mobile-results.png) |',
    '',
    liveMode ? '#### AI-assisted and live discovery — actual provider responses' :
      '#### AI-assisted and live discovery — request forms',
    '',
    liveMode ? '| Food interpretation | Online restaurant discovery |' :
      '| Food prompt input | Online restaurant search input |',
    '| :---: | :---: |',
    '| ![SavoRoute AI food interpretation panel](docs/screenshots/consumer-mobile-ai-discovery.png) | ![SavoRoute live restaurant discovery panel](docs/screenshots/consumer-mobile-live-discovery.png) |',
    '',
    '[View the complete mobile page](docs/screenshots/consumer-mobile-real.png).',
    end,
  ].join('\n');

  // Stage all seven images; nothing is published if an API call or screenshot fails.
  for (const shot of shots) await rename(resolve(staged, shot.filename), resolve(output, shot.filename));
  await writeFile(readme, original.slice(0, start) + gallery + original.slice(finish + end.length), 'utf8');
  process.stdout.write(`README updated: ${liveMode ? 'real AI and web search responses' : 'safe request forms, no fake results'}.\n`);
} finally {
  await browser?.close();
  if (staged) await rm(staged, { recursive: true, force: true });
  proc.kill('SIGTERM');
}
