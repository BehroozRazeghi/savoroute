import {ApiRequestError, browseParams, makeFilters, makePreferences, requestJson, requestImageBlob, nearbyParams, safeSourceUrl} from './api.mjs';

const $ = (selector) => document.querySelector(selector);
const nodes = {
  form: $('#discovery-form'), query: $('#search-query'), kind: $('#filter-kind'),
  cuisine: $('#filter-cuisine'), location: $('#filter-location'), diet: $('#filter-diet'),
  price: $('#filter-price'), prefCuisine: $('#prefer-cuisine'), prefDiet: $('#prefer-diet'),
  strength: $('#preference-strength'), strengthLabel: $('#strength-label'),
  preferenceFields: $('#preference-fields'), submit: $('#search-submit'),
  results: $('#results-list'), resultStatus: $('#results-status'), count: $('#result-count'),
  catalog: $('#catalog-list'), catalogStatus: $('#catalog-status'),
  catalogSummary: $('#catalog-summary'), catalogPage: $('#catalog-page-label'),
  next: $('#catalog-next'), prev: $('#catalog-prev'), datasetLabel: $('#dataset-label'),
  datasetFacts: $('#dataset-facts'), footerVersion: $('#footer-version'),
  dialog: $('#item-dialog'), dialogContent: $('#dialog-content'),
  exclusions: $('#exclusion-status'), clearExclusions: $('#clear-exclusions'),
  nearbyForm: $('#nearby-form'), nearbyAvailability: $('#nearby-availability'),
  nearbyResults: $('#nearby-results'), nearbySubmit: $('#nearby-submit'),
};
const state = {
  key: '', excluded: new Set(), catalogOffset: 0, catalogLimit: 9, catalogTotal: 0,
  catalogController: null, discoverController: null, nearbyController: null,
  lastSearch: null, detailObjectUrls: [],
};

function element(tag, className = '', text = null) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = String(text);
  return node;
}
function clear(node) { node.replaceChildren(); }
function shortText(value, fallback = 'Not recorded') {
  return typeof value === 'string' && value.trim() ? value.trim() : fallback;
}
function lowerType(item) { return item.kind === 'recipe' ? 'Recipe' : 'Restaurant'; }
function priceLabel(item) { return item.price_tier == null ? 'Price not recorded' : `Price tier ${item.price_tier}`; }
function addSourceLink(into, item) {
  const url = safeSourceUrl(item.source_url);
  if (url) {
    const link = element('a', 'source-link', 'Original source ↗');
    link.href = url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    into.append(link);
  }
}
function tagsFor(item, target, maximum = 4) {
  const values = [...(item.cuisines || []), ...(item.dietary_tags || [])];
  const tags = element('div', 'tag-row');
  for (const value of values.slice(0, maximum)) tags.append(element('span', 'tag', value));
  if (!values.length) tags.append(element('span', 'tag empty', 'Cuisine / diet not recorded'));
  if (values.length > maximum) tags.append(element('span', 'tag', `+${values.length - maximum} more`));
  target.append(tags);
}
function recordFacts(item) {
  const facts = element('div', 'record-line');
  facts.append(element('span', '', `⌁ ${shortText(item.location, 'Location not recorded')}`));
  facts.append(element('span', '', `· ${priceLabel(item)}`));
  return facts;
}
function readFilters() {
  return makeFilters({
    kind: nodes.kind.value,
    cuisine: nodes.cuisine.value,
    location: nodes.location.value,
    maxPriceTier: nodes.price.value,
    dietaryTags: nodes.diet.value,
  });
}
function readPreferences() {
  return makePreferences({
    cuisines: nodes.prefCuisine.value,
    dietaryTags: nodes.prefDiet.value,
    strength: nodes.strength.value,
  }, [...state.excluded]);
}
function activeMode() { return $('input[name="mode"]:checked').value; }
function showError(target, error) {
  const message = error instanceof Error ? error.message : 'Something went wrong.';
  const box = element('div', 'error-note', message);
  clear(target);
  target.append(box);
  if (error instanceof ApiRequestError && error.status === 401) $('#access-control').open = true;
}
function formatEvidence(result) {
  if (result.explanation) return result.explanation;
  if (Array.isArray(result.retrieval_evidence) && result.retrieval_evidence.length) {
    return result.retrieval_evidence.map((part) => `${part.source.toUpperCase()} rank ${part.rank}`).join(' · ');
  }
  if (result.method && Array.isArray(result.matched_terms)) {
    return `Matched by ${result.method.toUpperCase()}: ${result.matched_terms.join(', ') || 'catalog text'}`;
  }
  return 'Based on recorded catalog fields.';
}
function renderCard(item, context = null, compact = false) {
  const card = element('article', compact ? 'catalog-card' : 'result-card');
  const header = element('div', 'result-card-top');
  header.append(element('span', 'item-type', lowerType(item)));
  header.append(element('span', 'source-label', shortText(item.source, 'Source not recorded')));
  card.append(header, element('h3', compact ? '' : 'result-title', item.title));
  const description = shortText(item.description, 'No description in this record.');
  const text = element('p', compact ? '' : 'result-description', description);
  card.append(text);
  tagsFor(item, card, compact ? 3 : 5);
  card.append(recordFacts(item));
  if (!compact && context) card.append(element('p', 'evidence-line', formatEvidence(context)));
  const actions = element('div', 'card-actions');
  const detail = element('button', 'link-button', 'View record →');
  detail.type = 'button';
  detail.addEventListener('click', () => openDetail(item.item_id, context));
  actions.append(detail);
  addSourceLink(actions, item);
  if (!compact && context?.item_id && activeMode() === 'recommend') {
    const hide = element('button', 'text-button card-action-right', 'Not for me');
    hide.type = 'button';
    hide.addEventListener('click', () => {
      state.excluded.add(item.item_id);
      updateExclusions();
      void performDiscovery();
    });
    actions.append(hide);
  }
  card.append(actions);
  return card;
}
function updateExclusions() {
  const count = state.excluded.size;
  nodes.exclusions.hidden = !count;
  nodes.clearExclusions.hidden = !count;
  nodes.exclusions.textContent = count ? `${count} item${count === 1 ? '' : 's'} hidden from recommendations in this page.` : '';
}
function updateMode() {
  const recommend = activeMode() === 'recommend';
  nodes.preferenceFields.hidden = !recommend;
  nodes.submit.firstChild.textContent = recommend ? 'Find my matches ' : 'Search catalog ';
}
function emptyResults(title, description, into) {
  clear(into);
  const wrap = element('div', 'empty-state');
  wrap.append(element('h4', '', title), element('p', '', description));
  into.append(wrap);
}
async function performDiscovery() {
  const query = nodes.query.value.trim();
  if (!query) { nodes.query.focus(); nodes.resultStatus.textContent = 'Enter a search query first.'; return; }
  if (query.length > 500) { nodes.resultStatus.textContent = 'Queries must be 500 characters or less.'; return; }
  let filters, preferences;
  const mode = activeMode();
  try {
    filters = readFilters();
    if (mode === 'recommend') preferences = readPreferences();
  } catch (error) { showError(nodes.results, error); return; }
  state.discoverController?.abort();
  const controller = new AbortController();
  state.discoverController = controller;
  const endpoint = mode === 'recommend' ? '/v1/recommend' : '/v1/search';
  const payload = {query, filters, limit: 12};
  if (mode === 'recommend') payload.preferences = preferences;
  nodes.results.setAttribute('aria-busy', 'true');
  nodes.submit.disabled = true;
  nodes.resultStatus.textContent = 'Searching catalog…';
  clear(nodes.results);
  nodes.results.append(element('div', 'status-line', 'Finding matching records…'));
  try {
    const data = await requestJson(endpoint, {method: 'POST', body: payload, key: state.key, signal: controller.signal});
    if (controller !== state.discoverController) return;
    state.lastSearch = {query, mode};
    nodes.count.textContent = `${data.results.length} ${data.results.length === 1 ? 'result' : 'results'}`;
    nodes.resultStatus.textContent = data.catalog_synthetic ?
      'Fictional sample catalog · not real businesses.' :
      'Retrieved from saved catalog records · availability is not verified.';
    clear(nodes.results);
    if (!data.results.length) {
      const info = data.status === 'no_eligible_items' ?
        'No records satisfy all required filters. Try removing one restriction.' :
        'No matching catalog evidence was found. Try a broader query or fewer filters.';
      emptyResults('No matches in this catalog.', info, nodes.results);
    } else {
      for (const hit of data.results) nodes.results.append(renderCard(hit.item || hit, hit));
    }
  } catch (error) {
    if (error.name !== 'AbortError' && controller === state.discoverController) {
      nodes.resultStatus.textContent = 'Search could not be completed.';
      nodes.count.textContent = 'Unavailable';
      showError(nodes.results, error);
    }
  } finally {
    if (controller === state.discoverController) {
      nodes.results.setAttribute('aria-busy', 'false');
      nodes.submit.disabled = false;
    }
  }
}
async function loadCatalog() {
  let filters, params;
  try {
    filters = readFilters();
    params = browseParams(filters, state.catalogOffset, state.catalogLimit);
  } catch (error) { showError(nodes.catalog, error); return; }
  state.catalogController?.abort();
  const controller = new AbortController();
  state.catalogController = controller;
  nodes.catalog.setAttribute('aria-busy', 'true');
  nodes.catalogStatus.textContent = 'Loading catalog…';
  try {
    const data = await requestJson(`/v1/items?${params}`, {key: state.key, signal: controller.signal});
    if (controller !== state.catalogController) return;
    state.catalogTotal = data.total;
    nodes.catalogSummary.textContent = `${data.total} ${data.total === 1 ? 'record' : 'records'} matching the selected filters`;
    const start = data.total ? data.offset + 1 : 0;
    const end = Math.min(data.offset + data.items.length, data.total);
    nodes.catalogPage.textContent = `${start}–${end} of ${data.total}`;
    nodes.prev.disabled = data.offset === 0;
    nodes.next.disabled = data.offset + data.limit >= data.total;
    nodes.catalogStatus.textContent = '';
    clear(nodes.catalog);
    if (!data.items.length) emptyResults('Nothing to show yet.', 'Try removing a filter.', nodes.catalog);
    else for (const item of data.items) nodes.catalog.append(renderCard(item, null, true));
  } catch (error) {
    if (error.name !== 'AbortError' && controller === state.catalogController) {
      nodes.catalogStatus.textContent = 'Catalog unavailable.';
      showError(nodes.catalog, error);
    }
  } finally {
    if (controller === state.catalogController) nodes.catalog.setAttribute('aria-busy', 'false');
  }
}
async function loadMeta() {
  try {
    const meta = await requestJson('/v1/meta', {key: state.key});
    nodes.datasetLabel.textContent = meta.catalog_synthetic ? 'Fictional demonstration catalog' : shortText(meta.dataset_name, 'Imported catalog');
    nodes.datasetFacts.textContent = `${meta.catalog_items} catalog records · ${meta.index_backend === 'none' ? 'Lexical retrieval' : `Index: ${meta.index_backend}`}`;
    nodes.footerVersion.textContent = `Savoroute ${meta.package_version} · HTTP API ${meta.api_version}`;
    nodes.nearbyForm.hidden = !meta.geography_enabled;
    nodes.nearbyAvailability.textContent = meta.geography_enabled ?
      `${meta.geography_restaurants} restaurants with bound OSM coordinates. Enter a point to explore.` :
      'Nearby discovery is disabled. Restart the server with a matching --osm snapshot to enable it.';
  } catch (error) {
    nodes.datasetLabel.textContent = 'Catalog metadata unavailable';
    nodes.datasetFacts.textContent = error.message;
    if (error instanceof ApiRequestError && error.status === 401) $('#access-control').open = true;
  }
}
async function loadNearby(event) {
  event.preventDefault();
  let params;
  try {
    params = nearbyParams($('#nearby-lat').value, $('#nearby-lon').value,
      $('#nearby-radius').value);
  } catch (error) {
    showError(nodes.nearbyResults, error);
    return;
  }
  state.nearbyController?.abort();
  const controller = new AbortController();
  state.nearbyController = controller;
  nodes.nearbyResults.setAttribute('aria-busy', 'true');
  nodes.nearbySubmit.disabled = true;
  nodes.nearbyAvailability.textContent = 'Finding catalog records near these coordinates…';
  try {
    const response = await requestJson(`/v1/nearby?${params}`, {key: state.key, signal: controller.signal});
    if (controller !== state.nearbyController) return;
    clear(nodes.nearbyResults);
    nodes.nearbyAvailability.textContent = `${response.results.length} matching records in the selected radius. Distances are approximate.`;
    if (!response.results.length) emptyResults('No nearby records in this snapshot.', 'Try a larger radius or different coordinates.', nodes.nearbyResults);
    for (const result of response.results) {
      const card = renderCard(result.item, null, true);
      card.append(element('p', 'distance-note', `${result.distance_m.toFixed(0)} m straight-line · ${result.geometry_basis === 'bbox_center' ? 'OSM bounding-box center' : 'OSM node'}`));
      nodes.nearbyResults.append(card);
    }
  } catch (error) {
    if (error.name !== 'AbortError' && controller === state.nearbyController) {
      nodes.nearbyAvailability.textContent = 'Nearby search could not complete.';
      showError(nodes.nearbyResults, error);
    }
  } finally {
    if (controller === state.nearbyController) {
      nodes.nearbyResults.setAttribute('aria-busy', 'false');
      nodes.nearbySubmit.disabled = false;
    }
  }
}

function revokeDetailImages() {
  for (const url of state.detailObjectUrls) URL.revokeObjectURL(url);
  state.detailObjectUrls = [];
}

function detailField(list, label, value) {
  list.append(element('dt', '', label), element('dd', '', String(value)));
}
async function openDetail(id, context) {
  state.activeDetail = id;
  revokeDetailImages();
  clear(nodes.dialogContent);
  nodes.dialogContent.append(element('p', 'status-line', 'Loading record…'));
  if (!nodes.dialog.open) nodes.dialog.showModal();
  try {
    const item = await requestJson(`/v1/items/${encodeURIComponent(id)}`, {key: state.key});
    clear(nodes.dialogContent);
    nodes.dialogContent.append(element('h2', 'dialog-title', item.title));
    nodes.dialogContent.append(element('p', 'dialog-description', shortText(item.description, 'Description not recorded.')));
    tagsFor(item, nodes.dialogContent, 12);
    const definitions = element('dl', 'dialog-list');
    detailField(definitions, 'Record ID', item.item_id);
    detailField(definitions, 'Type', lowerType(item));
    detailField(definitions, 'Location', shortText(item.location));
    detailField(definitions, 'Price tier', priceLabel(item));
    detailField(definitions, 'Cuisine', item.cuisines?.join(', ') || 'Not recorded');
    detailField(definitions, 'Dietary tags', item.dietary_tags?.join(', ') || 'Not recorded');
    detailField(definitions, 'Source', shortText(item.source));
    if (item.kind === 'recipe') detailField(definitions, 'Ingredients', item.ingredients?.join(', ') || 'Not recorded');
    nodes.dialogContent.append(definitions);
    if (context) nodes.dialogContent.append(element('p', 'evidence-line', formatEvidence(context)));
    const url = safeSourceUrl(item.source_url);
    if (url) {
      const p = element('p');
      addSourceLink(p, item);
      nodes.dialogContent.append(p);
    }
    // Reviewed evidence is a separate, optional sidecar. Its claims never
    // mutate item fields or turn dietary information into a safety guarantee.
    try {
      const evidence = await requestJson(`/v1/items/${encodeURIComponent(id)}/evidence`, {key: state.key});
      const menuStatus = evidence.menu_status === 'reviewed_reference' ?
        'Reviewed menu reference recorded; current menu contents not verified.' :
        'No reviewed menu reference recorded; this does not mean the restaurant has no menu.';
      nodes.dialogContent.append(element('p', 'menu-status', menuStatus));
      if (evidence.reviewed_claims.length) {
        const panel = element('section', 'reviewed-panel');
        panel.append(element('h3', '', 'Reviewed source references'));
        for (const claim of evidence.reviewed_claims) {
          const entry = element('div', 'reviewed-entry');
          const labels = {menu_url: 'Menu reference', image_url: 'Licensed image reference',
            cuisine: 'Cuisine evidence', descriptive_note: 'Source note'};
          entry.append(element('strong', '', labels[claim.kind] || 'Source reference'));
          if (claim.kind === 'menu_url' || claim.kind === 'image_url') {
            const url = safeSourceUrl(claim.value);
            if (url) {
              const link = element('a', 'source-link', claim.kind === 'menu_url' ? 'View menu source ↗' : 'View image at source ↗');
              link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer';
              entry.append(link);
            }
          } else entry.append(element('p', '', claim.value));
          entry.append(element('small', '', `Recorded ${claim.observed_on} · Reviewed reference, not live verification`));
          const source = safeSourceUrl(claim.source_url);
          if (source) {
            const citation = element('a', 'source-link', 'Evidence source ↗');
            citation.href = source; citation.target = '_blank'; citation.rel = 'noopener noreferrer';
            entry.append(citation);
          }
          if (claim.license) entry.append(element('small', '', `Image credit: ${claim.attribution} · ${claim.license}`));
          panel.append(entry);
        }
        nodes.dialogContent.append(panel);
      }
    } catch {
      nodes.dialogContent.append(element('p', 'dialog-disclaimer', 'Reviewed source references are unavailable.'));
    }
    try {
      const media = await requestJson(`/v1/items/${encodeURIComponent(id)}/media`, {key: state.key});
      if (media.images.length) {
        const gallery = element('section', 'reviewed-gallery');
        gallery.append(element('h3', '', 'Locally packaged reviewed images'));
        // Only images served by this Savoroute instance are embedded; third-party
        // image URLs remain external references and are never hotlinked.
        for (const asset of media.images.slice(0, 3)) {
          const frame = element('figure');
          try {
            const blob = await requestImageBlob(`/v1/media/${encodeURIComponent(asset.asset_id)}`, {key: state.key});
            // A subsequent dialog may have superseded this request.
            if (!nodes.dialog.open || state.activeDetail !== id) break;
            const url = URL.createObjectURL(blob);
            state.detailObjectUrls.push(url);
            const image = element('img');
            image.src = url;
            image.alt = `Recorded image for ${item.title}; image content not independently verified`;
            image.loading = 'lazy';
            frame.append(image);
          } catch {
            frame.append(element('p', 'status-line', 'Local image could not be displayed.'));
          }
          frame.append(element('figcaption', '', `${asset.attribution} · ${asset.license} · Reviewed ${asset.reviewed_on} · ${asset.modifications}`));
          const src = safeSourceUrl(asset.source_url);
          if (src) {
            const a = element('a', 'source-link', 'Image credit/source ↗');
            a.href = src; a.target = '_blank'; a.rel = 'noopener noreferrer';
            frame.append(a);
          }
          gallery.append(frame);
        }
        if (state.activeDetail === id) nodes.dialogContent.append(gallery);
      }
    } catch {
      nodes.dialogContent.append(element('p', 'dialog-disclaimer', 'Local media references are unavailable.'));
    }
    nodes.dialogContent.append(element('p', 'dialog-disclaimer', 'This is a saved catalog record, not live restaurant information. Hours, availability, current pricing and allergen safety are not verified.'));
  } catch (error) { showError(nodes.dialogContent, error); }
}

nodes.form.addEventListener('submit', (event) => {event.preventDefault(); void performDiscovery();});
for (const input of document.querySelectorAll('input[name="mode"]')) input.addEventListener('change', updateMode);
nodes.strength.addEventListener('input', () => {nodes.strengthLabel.textContent = Number(nodes.strength.value).toFixed(2);});
$('#reset-filters').addEventListener('click', () => {
  nodes.form.reset();
  state.excluded.clear();
  nodes.strengthLabel.textContent = '0.25';
  updateMode(); updateExclusions();
  state.catalogOffset = 0;
  void loadCatalog();
});
nodes.clearExclusions.addEventListener('click', () => {
  state.excluded.clear(); updateExclusions();
  if (state.lastSearch?.mode === 'recommend') void performDiscovery();
});
$('#apply-catalog-filters').addEventListener('click', () => {state.catalogOffset = 0; void loadCatalog();});
nodes.prev.addEventListener('click', () => {state.catalogOffset = Math.max(0, state.catalogOffset - state.catalogLimit); void loadCatalog();});
nodes.next.addEventListener('click', () => {state.catalogOffset += state.catalogLimit; void loadCatalog();});
$('#close-dialog').addEventListener('click', () => nodes.dialog.close());
nodes.dialog.addEventListener('click', (event) => {if (event.target === nodes.dialog) nodes.dialog.close();});
nodes.dialog.addEventListener('close', () => {state.activeDetail = null; revokeDetailImages();});
nodes.nearbyForm.addEventListener('submit', (event) => {void loadNearby(event);});
$('#access-form').addEventListener('submit', (event) => {
  event.preventDefault();
  state.key = $('#access-key').value;
  $('#access-key').value = '';
  $('#access-control').open = false;
  state.catalogOffset = 0;
  void loadMeta(); void loadCatalog();
});
$('#clear-access-key').addEventListener('click', () => {
  state.key = '';
  $('#access-key').value = '';
  $('#access-control').open = false;
  state.catalogOffset = 0;
  void loadMeta(); void loadCatalog();
});
updateMode();
void loadMeta();
void loadCatalog();
