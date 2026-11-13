// No network requests or persistent storage. Reviewer files remain tab-local.
const $ = (id) => document.getElementById(id);
let sheet = null;
let reference = null;
let index = 0;
let changes = false;
let byPair = new Map();

function text(id, value) { $(id).textContent = value === null || value === undefined ? '' : String(value); }
function pairKey(row) { return JSON.stringify([row.case_id, row.item_id]); }
function isReviewed(row) {
  return typeof row.relevant === 'boolean' && (row.relevant === false || row.note.trim().length > 0);
}
function validHttps(value) {
  try {
    const url = new URL(value);
    return url.protocol === 'https:' ? url.href : null;
  } catch { return null; }
}
function ensure(value, message) { if (!value) throw new Error(message); }

function checkFiles(references, reviewer) {
  ensure(references?.reference_version === 1 && Array.isArray(references.records), 'Invalid study reference format.');
  ensure(reviewer?.review_sheet_version === 1 && ['reviewer_a','reviewer_b'].includes(reviewer.reviewer_slot), 'Invalid reviewer sheet.');
  ensure(Array.isArray(reviewer.judgments) && reviewer.judgments.length > 0 && reviewer.judgments.length <= 20000, 'Invalid review-sheet length.');
  ensure(references.records.length === reviewer.judgments.length, 'Review and reference pair counts differ.');
  const lookup = new Map();
  for (const record of references.records) {
    ensure(typeof record.case_id === 'string' && typeof record.item_id === 'string' && typeof record.query === 'string', 'Invalid reference row.');
    const key = pairKey(record);
    ensure(!lookup.has(key), 'Duplicate reference pair.');
    lookup.set(key, record);
  }
  const seen = new Set();
  for (const row of reviewer.judgments) {
    const key = pairKey(row);
    ensure(lookup.has(key) && !seen.has(key), 'Reviewer pair missing from reference or duplicated.');
    ensure((row.relevant === null || typeof row.relevant === 'boolean') && typeof row.note === 'string', 'Malformed reviewer decision.');
    seen.add(key);
  }
  return lookup;
}

function updateProgress() {
  const total = sheet.judgments.length;
  const reviewed = sheet.judgments.filter(isReviewed).length;
  text('progress', `${reviewed}/${total} reviewed · ${sheet.reviewer_slot}`);
}
function addAttribute(name, value) {
  const dt = document.createElement('dt');
  const dd = document.createElement('dd');
  dt.textContent = name;
  dd.textContent = value || 'Not recorded';
  $('attributes').append(dt, dd);
}
function render() {
  if (!sheet) return;
  const row = sheet.judgments[index];
  const item = byPair.get(pairKey(row));
  text('position', `${index + 1} of ${sheet.judgments.length} · ${row.case_id}`);
  text('query', item.query);
  text('title', item.title || item.item_id);
  text('description', item.description || 'No description in the frozen reference.');
  $('attributes').replaceChildren();
  addAttribute('Catalog item', item.item_id);
  addAttribute('Cuisine tags', Array.isArray(item.cuisines) ? item.cuisines.join(', ') : null);
  addAttribute('Location', item.location);
  $('source-container').replaceChildren();
  const href = validHttps(item.source_url);
  if (href) {
    const link = document.createElement('a');
    link.href = href;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.referrerPolicy = 'no-referrer';
    link.textContent = 'View recorded source (opens external site)';
    $('source-container').append(link);
  } else {
    text('source-container', 'No HTTPS source link recorded.');
  }
  $('decision').value = row.relevant === null ? '' : String(row.relevant);
  $('note').value = row.note;
  text('decision-warning', row.relevant === true && !row.note.trim()
    ? 'Positive judgments require an evidence note.' : '');
  $('previous').disabled = index === 0;
  $('next').disabled = index + 1 === sheet.judgments.length;
  $('case-selector').value = row.case_id;
  updateProgress();
}
function updateRow() {
  const row = sheet.judgments[index];
  const decision = $('decision').value;
  row.relevant = decision === '' ? null : decision === 'true';
  row.note = $('note').value.slice(0, 4000);
  changes = true;
  text('decision-warning', row.relevant === true && !row.note.trim()
    ? 'Positive judgments require an evidence note.' : '');
  updateProgress();
}
function navigate(delta) {
  index = Math.max(0, Math.min(sheet.judgments.length - 1, index + delta));
  render();
}
async function load() {
  const refFile = $('reference-file').files?.[0];
  const reviewFile = $('sheet-file').files?.[0];
  try {
    ensure(refFile && reviewFile, 'Select both files first.');
    ensure(refFile.size <= 16 * 1024 * 1024 && reviewFile.size <= 16 * 1024 * 1024, 'File exceeds 16 MB.');
    const proposedRef = JSON.parse(await refFile.text());
    const proposedSheet = JSON.parse(await reviewFile.text());
    const proposedMap = checkFiles(proposedRef, proposedSheet);
    reference = proposedRef;
    sheet = proposedSheet;
    byPair = proposedMap;
    changes = false;
    index = 0;
    const ids = [...new Set(sheet.judgments.map((row) => row.case_id))];
    $('case-selector').replaceChildren();
    for (const id of ids) {
      const option = document.createElement('option');
      option.value = id;
      option.textContent = id;
      $('case-selector').append(option);
    }
    $('workspace').hidden = false;
    text('status', `Loaded ${sheet.judgments.length} pairs for ${sheet.reviewer_slot}.`);
    render();
  } catch (error) {
    text('status', error instanceof Error ? error.message : 'Invalid review files.');
    $('workspace').hidden = true;
    sheet = null;
  }
}
function download() {
  if (!sheet) return;
  if (sheet.judgments.some((row) => row.relevant === true && !row.note.trim())) {
    text('decision-warning', 'Add evidence notes to all relevant judgments before downloading.');
    return;
  }
  const payload = JSON.stringify(sheet, null, 2) + '\n';
  const url = URL.createObjectURL(new Blob([payload], {type: 'application/json'}));
  const link = document.createElement('a');
  link.href = url;
  link.download = `${sheet.reviewer_slot}-completed.json`;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
  changes = false;
  text('status', 'File downloaded. Keep this reviewer file separate from the other reviewer.');
}
$('load').addEventListener('click', load);
$('decision').addEventListener('change', updateRow);
$('note').addEventListener('input', updateRow);
$('previous').addEventListener('click', () => navigate(-1));
$('next').addEventListener('click', () => navigate(1));
$('next-unreviewed').addEventListener('click', () => {
  if (!sheet) return;
  const start = index + 1;
  const found = sheet.judgments.findIndex((row, i) => i >= start && !isReviewed(row));
  const wrapped = found < 0 ? sheet.judgments.findIndex((row) => !isReviewed(row)) : found;
  if (wrapped >= 0) { index = wrapped; render(); }
  else text('status', 'All pairs have explicit judgments. Download your file.');
});
$('case-selector').addEventListener('change', () => {
  const found = sheet?.judgments.findIndex((row) => row.case_id === $('case-selector').value);
  if (found >= 0) { index = found; render(); }
});
$('download').addEventListener('click', download);
window.addEventListener('beforeunload', (event) => {
  if (changes) { event.preventDefault(); event.returnValue = ''; }
});
