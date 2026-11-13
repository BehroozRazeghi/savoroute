import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const script = fs.readFileSync('src/savoroute/web/static/visits-review.js', 'utf8');
const html = fs.readFileSync('src/savoroute/web/static/visits-review.html', 'utf8');
test('private visit review reads explicitly selected files only', () => {
  assert.match(script, /file\.text\(\)/);
  assert.doesNotMatch(script, /\bfetch\s*\(/);
  assert.doesNotMatch(script, /XMLHttpRequest|localStorage|sessionStorage/);
  assert.match(html, /type="file"/);
  assert.doesNotMatch(html, /<script>(.|\n)*?<\/script>/);
});
test('review output is a local download not a server mutation', () => {
  assert.match(script, /URL\.createObjectURL/);
  assert.match(script, /link\.download/);
  assert.doesNotMatch(script, /POST|PUT|DELETE|sendBeacon/);
});
