// Capture real running React UI, never mockups or generated screenshots.
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

await access(catalog);
await access(dist).catch(() => { throw new Error('Build frontend first: cd webapp && npm run build'); });
// Do not connect to an unrelated local service or overwrite screenshots from it.
try {
  await fetch(`${base}/healthz`, { signal: AbortSignal.timeout(500) });
  throw new Error('Port 8098 is in use. Stop that process before capturing screenshots.');
} catch (error) {
  if (String(error).includes('Port 8098 is in use')) throw error;
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
    ['consumer-desktop-real.png', { width: 1440, height: 900 }, `${base}/app/?kind=restaurant&city=Boston`],
    ['consumer-mobile-real.png', { width: 390, height: 844, isMobile: true, deviceScaleFactor: 1 }, `${base}/app/?kind=restaurant&city=Boston`],
  ];
  for (const [filename, viewport, url] of examples) {
    const context = await browser.newContext({ viewport: { width: viewport.width, height: viewport.height },
      isMobile: viewport.isMobile || false, deviceScaleFactor: 1, reducedMotion: 'reduce' });
    const page = await context.newPage();
    await page.goto(url, { waitUntil: 'networkidle' });
    await page.getByRole('article').first().waitFor({ state: 'visible', timeout: 10000 });
    await page.screenshot({ path: resolve(output, filename), fullPage: true, animations: 'disabled' });
    await context.close();
    process.stdout.write(`Captured real app: docs/screenshots/${filename}\n`);
  }
  // Update the README only after BOTH real application screenshots succeeded.
  const readme = resolve(project, 'README.md');
  const original = await readFile(readme, 'utf8');
  const begin = '<!-- SCREENSHOTS_BEGIN -->';
  const end = '<!-- SCREENSHOTS_END -->';
  const start = original.indexOf(begin);
  const finish = original.indexOf(end);
  if (start < 0 || finish < start) throw new Error('README screenshot markers missing; update manually');
  const current = `${begin}\nThese screenshots were captured from the **running React consumer app**\nusing the opt-in November 2026 OSM Boston catalog. Real source-tagged records,\nnot a live verification of restaurant availability.\n\n| React desktop | React mobile |\n| --- | --- |\n| ![Current SavoRoute React desktop UI with OSM-backed Boston results](docs/screenshots/consumer-desktop-real.png) | ![Current SavoRoute React mobile UI with OSM-backed Boston results](docs/screenshots/consumer-mobile-real.png) |\n${end}`;
  await writeFile(readme, original.slice(0, start) + current + original.slice(finish + end.length));
  process.stdout.write('README now references verified consumer screenshots. Review the diff before committing.\n');
} finally {
  await browser?.close();
  proc.kill('SIGTERM');
}
