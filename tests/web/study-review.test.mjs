import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const html = fs.readFileSync('src/savoroute/web/static/study-review.html', 'utf8');
const script = fs.readFileSync('src/savoroute/web/static/study-review.js', 'utf8');
test('study review is selected-file-only and never sends labels to a server', () => {
  assert.match(html, /type="file"/);
  assert.match(script, /\.text\(\)/);
  assert.doesNotMatch(script, /\bfetch\s*\(|XMLHttpRequest|sendBeacon|localStorage|sessionStorage/);
  assert.doesNotMatch(html, /<script>(.|\n)*?<\/script>/);
});
test('study reviewer provides explicit decisions and downloads a separate sheet', () => {
  assert.match(script, /row\.relevant = decision === '' \? null/);
  assert.match(script, /row\.note/);
  assert.match(script, /URL\.createObjectURL/);
  assert.match(script, /link\.download/);
  assert.match(script, /noopener noreferrer/);
  assert.match(script, /textContent/);
  assert.doesNotMatch(script, /innerHTML/);
});
