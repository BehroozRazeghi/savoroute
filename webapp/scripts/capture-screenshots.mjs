// Capture the real SavoRoute React application, never renderings or mockups.
// Usage: cd webapp && npm ci && npm run build && npm run screenshots
// Requires an installed SavoRoute CLI and Playwright Chromium.
import { chromium } from '@playwright/test';
import { spawn } from 'node:child_process';
import { access, mkdir, readFile, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const project = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const catalog = resolve(project, 'data/real/boston-osm-2026-11.json');
const dist = resolve(project, 'src/savoroute/web/consumer_dist/index.html');
const output = resolve(project, 'docs/screenshots');
const port = 8098;
const base = `http://127.0.0.1:${port}`;
const url = `${base}/app/?kind=restaurant&city=Boston`;

async function waitUntilReady(proc) {
  for (let attempt = 0; attempt < 80; attempt++) {
    if (proc.exitCode !== null) throw new Error(`SavoRoute server exited (${proc.exitCode})`);
    try {
      const response = await fetch(`${base}/healthz`, { signal: AbortSignal.timeout(750) });
      if (response.ok) return;
    } catch { /* server is starting */ }
    await new Promise(done => setTimeout(done, 150));
  }
  throw new Error('SavoRoute server did not become ready on 127.0.0.1:8098');
}

async function setScrollPosition(page, position) {
  if (position === 'top') {
    await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' }));
    return;
  }
  const selector = position === 'filters' ? '.discovery-filters' : '.results-status';
  const target = page.locator(selector);
  await target.waitFor({ state: 'visible', timeout: 10000 });
  // Use genuine browser viewport screenshots at consistent dimensions, not
  // slices of a long full-page screenshot. Align the selected UI area at top.
  await target.evaluate(element => {
    const top = window.scrollY + element.getBoundingClientRect().top - 16;
    window.scrollTo({ top: Math.max(0, top), behavior: 'instant' });
  });
}

await access(catalog);
await access(dist).catch(() => { throw new Error('Build frontend first: cd webapp && npm run build'); });
// Do not connect to an unrelated local service or overwrite screenshots from it.
try {
  await fetch(`${base}/healthz`, { signal: AbortSignal.timeout(500) });
  throw new Error('Port 8098 is in use. Stop that process before capturing screenshots.');
} catch (error) {
  if (String(error).includes('Port 8098 is in use')) throw error;
}

// Verify the README markers before starting, so failures do not unexpectedly
// replace the top-of-repository documentation.
const readme = resolve(project, 'README.md');
const original = await readFile(readme, 'utf8');
const begin = '<!-- SCREENSHOTS_BEGIN -->';
const end = '<!-- SCREENSHOTS_END -->';
const start = original.indexOf(begin);
const finish = original.indexOf(end);
if (start < 0 || finish < start || original.lastIndexOf(begin) !== start || original.lastIndexOf(end) !== finish) {
  throw new Error('README must contain exactly one ordered pair of screenshot markers');
}

const proc = spawn(process.env.SAVOROUTE_COMMAND || 'savoroute', [
  'web', 'serve', '--catalog', catalog, '--host', '127.0.0.1', '--port', String(port),
], { cwd: project, stdio: 'inherit' });
let browser;
try {
  await waitUntilReady(proc);
  await mkdir(output, { recursive: true });
  browser = await chromium.launch({ headless: true });
  const examples = [
    { filename: 'consumer-desktop-real.png', width: 1440, height: 900, fullPage: true },
    { filename: 'consumer-mobile-real.png', width: 390, height: 844, mobile: true, fullPage: true },
    { filename: 'consumer-mobile-search.png', width: 390, height: 844, mobile: true, position: 'top' },
    { filename: 'consumer-mobile-filters.png', width: 390, height: 844, mobile: true, position: 'filters' },
    { filename: 'consumer-mobile-results.png', width: 390, height: 844, mobile: true, position: 'results' },
  ];
  for (const shot of examples) {
    const context = await browser.newContext({
      viewport: { width: shot.width, height: shot.height },
      isMobile: Boolean(shot.mobile), deviceScaleFactor: 1, reducedMotion: 'reduce',
    });
    try {
      const page = await context.newPage();
      await page.goto(url, { waitUntil: 'networkidle' });
      await page.getByRole('article').first().waitFor({ state: 'visible', timeout: 10000 });
      await page.evaluate(async () => { await document.fonts.ready; });
      if (shot.position) await setScrollPosition(page, shot.position);
      await page.screenshot({
        path: resolve(output, shot.filename),
        fullPage: Boolean(shot.fullPage),
        animations: 'disabled',
      });
      process.stdout.write(`Captured real app: docs/screenshots/${shot.filename}\n`);
    } finally {
      await context.close();
    }
  }

  // Update the README only after ALL five real browser screenshots succeeded.
  // Full-page desktop has its own row; mobile thumbnails share equal heights.
  const gallery = [
    begin,
    'These screenshots were captured from the **running React consumer app** using',
    'the opt-in November 2026 Boston OSM snapshot. Records are source-tagged,',
    'but this does **not** verify current restaurant availability.',
    '',
    '#### Desktop application',
    '',
    '![SavoRoute desktop food discovery with Boston OSM records](docs/screenshots/consumer-desktop-real.png)',
    '',
    '#### Mobile application',
    '',
    '| Search | Filters | Restaurant results |',
    '| :---: | :---: | :---: |',
    '| ![SavoRoute mobile search screen](docs/screenshots/consumer-mobile-search.png) | ![SavoRoute mobile filter controls](docs/screenshots/consumer-mobile-filters.png) | ![SavoRoute mobile restaurant results](docs/screenshots/consumer-mobile-results.png) |',
    '',
    '[View the complete mobile screenshot](docs/screenshots/consumer-mobile-real.png).',
    end,
  ].join('\n');
  await writeFile(readme, original.slice(0, start) + gallery + original.slice(finish + end.length), 'utf8');
  process.stdout.write('README now uses the desktop-first gallery and three equal-size mobile viewports.\n');
} finally {
  await browser?.close();
  proc.kill('SIGTERM');
}
