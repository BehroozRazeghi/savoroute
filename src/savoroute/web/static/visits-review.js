/* Private, offline review of already-generated suggestions. No fetch, network, or storage. */
const byId = id => document.getElementById(id);
const info = byId('load-status');
let suggestions = null;
let review = null;

async function selectedJson(inputId) {
  const file = byId(inputId).files?.[0];
  if (!file || file.size > 512_000) throw new Error('Select a JSON file under 512 KB.');
  return JSON.parse(await file.text());
}
function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function field(parent, text, input) {
  const label = element('label', text);
  label.append(input);
  parent.append(label);
}
function option(text, value) {
  const node = element('option', text);
  node.value = value;
  return node;
}
function refreshProgress() {
  const total = review.decisions.length;
  const count = review.decisions.filter(row =>
    ['confirm', 'reject', 'reassign'].includes(row.decision) &&
    (row.decision === 'reject' ? row.item_id === null : Boolean(row.item_id)) &&
    typeof row.reason === 'string' && row.reason.trim() && row.reviewed_on
  ).length;
  byId('progress').textContent = `${count} / ${total} reviewed`;
}
function reviewCard(cluster, decision) {
  const card = element('article', undefined, 'visit-card');
  const left = element('div');
  const title = element('h3', `Possible visit · ${cluster.started_at.slice(0, 10)}`);
  left.append(title, element('span', `${cluster.photo_count} metadata records · ${cluster.started_at} → ${cluster.ended_at}`, 'muted'));
  left.append(element('p', `Local cluster ${cluster.visit_id}`, 'muted'));
  const list = element('ul');
  if (!cluster.candidates.length) list.append(element('li', 'No nearby matched restaurant in this OSM snapshot.'));
  for (const candidate of cluster.candidates) {
    const entry = element('li', candidate.title);
    entry.append(element('span', `${candidate.distance_m} m · ${candidate.item_id}`));
    list.append(entry);
  }
  left.append(list, element('span', 'Unverified location suggestion', 'pill'));

  const right = element('div', undefined, 'fields');
  const action = element('select');
  for (const [label, value] of [['Choose a decision', ''], ['Confirm suggested restaurant', 'confirm'],
                                ['Reject this visit', 'reject'], ['Reassign to another item ID', 'reassign']]) {
    action.append(option(label, value));
  }
  action.value = decision.decision || '';
  const matched = element('select');
  matched.append(option('Choose a nearby candidate', ''));
  for (const candidate of cluster.candidates) matched.append(option(`${candidate.title} (${candidate.item_id})`, candidate.item_id));
  const other = element('input');
  other.type = 'text'; other.maxLength = 64; other.placeholder = 'Restaurant item ID';
  const reason = element('input');
  reason.type = 'text'; reason.maxLength = 300; reason.placeholder = 'Why is this decision correct?';
  const day = element('input'); day.type = 'date'; day.value = decision.reviewed_on || '';
  reason.value = decision.reason || '';
  function updateControls() {
    matched.disabled = action.value !== 'confirm';
    other.disabled = action.value !== 'reassign';
  }
  if (decision.decision === 'confirm') matched.value = decision.item_id || '';
  if (decision.decision === 'reassign') other.value = decision.item_id || '';
  function updateDecision() {
    decision.decision = action.value || null;
    decision.item_id = action.value === 'confirm' ? (matched.value || null) :
      action.value === 'reassign' ? (other.value.trim() || null) : null;
    decision.reason = reason.value || null;
    decision.reviewed_on = day.value || null;
    updateControls();
    refreshProgress();
  }
  for (const control of [action, matched, other, reason, day]) control.addEventListener('change', updateDecision);
  reason.addEventListener('input', updateDecision);
  other.addEventListener('input', updateDecision);
  field(right, 'Your decision', action);
  field(right, 'Nearby candidate (for confirm)', matched);
  field(right, 'Different restaurant ID (for reassign)', other);
  field(right, 'Rationale (required)', reason);
  field(right, 'Reviewed on (YYYY-MM-DD)', day);
  updateControls();
  card.append(left, right);
  return card;
}
byId('load-files').addEventListener('click', async () => {
  try {
    const [proposals, decisions] = await Promise.all([
      selectedJson('suggestions-file'), selectedJson('review-file')
    ]);
    if (proposals.schema_version !== 1 || proposals.status !== 'unreviewed' ||
        !Array.isArray(proposals.clusters) || !proposals.clusters.length ||
        decisions.schema_version !== 1 || !Array.isArray(decisions.decisions) ||
        proposals.clusters.length !== decisions.decisions.length ||
        proposals.clusters.some((c, i) => c.visit_id !== decisions.decisions[i].visit_id)) {
      throw new Error('Files do not contain matching visit suggestions and review rows.');
    }
    suggestions = proposals;
    review = decisions;
    const cards = byId('review-cards');
    cards.replaceChildren();
    for (let i = 0; i < suggestions.clusters.length; i++) {
      cards.append(reviewCard(suggestions.clusters[i], review.decisions[i]));
    }
    byId('queue').hidden = false;
    info.textContent = `${suggestions.clusters.length} private suggestions loaded. Review each explicitly.`;
    refreshProgress();
  } catch (_error) {
    // Do not echo rejected JSON, paths, or file contents into the page.
    info.textContent = 'Unable to read the selected review files. Check their JSON format and matching IDs.';
    byId('queue').hidden = true;
    suggestions = null;
    review = null;
  }
});
byId('export-review').addEventListener('click', () => {
  if (!review) return;
  const blob = new Blob([JSON.stringify(review, null, 2) + '\n'], {type: 'application/json'});
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = 'visit-review-decisions.json';
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
