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
  lastSearch: null, detailObjectUrls: [], compared: new Map(),
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
  if (item.kind === 'recipe') {
    facts.append(element('span', '', `${item.ingredients?.length || 0} recorded ingredients`));
    facts.append(element('span', '', 'Recipe source · not kitchen-tested'));
    return facts;
  }
  const city = item.city ? `${item.city}${item.region ? `, ${item.region}` : ''}` :
    shortText(item.location, 'Location not recorded');
  facts.append(element('span', '', `⌁ ${city}`));
  facts.append(element('span', '', priceLabel(item)));
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
function updateCompareButtons() {
  for (const button of document.querySelectorAll('[data-compare-id]')) {
    const selected = state.compared.has(button.dataset.compareId);
    button.setAttribute('aria-pressed', String(selected));
    button.textContent = selected ? '✓ Selected' : '+ Compare';
  }
  const bar = $('#compare-bar');
  const count = state.compared.size;
  bar.hidden = count === 0;
  $('#compare-count').textContent = `${count} of 3 selected`;
  $('#compare-open').disabled = count < 2;
}
function toggleCompare(item) {
  if (state.compared.has(item.item_id)) state.compared.delete(item.item_id);
  else if (state.compared.size < 3) state.compared.set(item.item_id, item);
  else {
    $('#results-status').textContent = 'Compare up to three records. Remove one to add another.';
    return;
  }
  updateCompareButtons();
}
function showComparison() {
  if (state.compared.size < 2) return;
  const items = [...state.compared.values()];
  const content = $('#compare-content');
  clear(content);
  const heading = element('h2', '', 'Compare your options');
  heading.id = 'compare-title';
  content.append(heading, element('p', 'compare-disclaimer',
    'These are saved catalog attributes, not live availability, verified prices, or safety guarantees.'));
  const outer = element('div', 'compare-table-wrap');
  const table = element('table', 'compare-table');
  const header = element('thead');
  const first = element('tr');
  first.append(element('th', '', 'Recorded fact'));
  for (const item of items) first.append(element('th', '', item.title));
  header.append(first); table.append(header);
  const body = element('tbody');
  const fields = [
    ['Type', (i) => lowerType(i)],
    ['City', (i) => i.kind === 'recipe' ? 'Not applicable' : shortText(i.city, 'Unknown')],
    ['Address / location', (i) => i.kind === 'recipe' ? 'Not applicable' : shortText(i.location)],
    ['Cuisine', (i) => i.cuisines?.join(', ') || 'Unknown'],
    ['Dietary tags', (i) => i.dietary_tags?.join(', ') || 'Unknown — not a safety guarantee'],
    ['Price', (i) => i.kind === 'recipe' ? 'Not applicable' : priceLabel(i)],
    ['Source', (i) => shortText(i.source)],
  ];
  for (const [label, format] of fields) {
    const row = element('tr');
    row.append(element('th', '', label));
    for (const item of items) row.append(element('td', '', format(item)));
    body.append(row);
  }
  table.append(body); outer.append(table); content.append(outer);
  $('#compare-dialog').showModal();
}
function renderCard(item, context = null, compact = false) {
  const card = element('article', compact ? 'catalog-card' : 'result-card');
  const art = element('div', `card-visual ${item.kind === 'recipe' ? 'recipe' : 'restaurant'}`);
  art.setAttribute('aria-label', 'Decorative illustration, not a photograph of this item');
  const mark = element('span', 'card-visual-mark', item.kind === 'recipe' ? '◈' : '✳');
  mark.setAttribute('aria-hidden', 'true');
  art.append(element('span', 'visual-label', lowerType(item)), mark,
    element('span', 'visual-caption', 'Illustration · not item photography'));
  card.append(art);
  const header = element('div', 'result-card-top');
  header.append(element('span', 'item-type', lowerType(item)));
  header.append(element('span', 'source-label', shortText(item.source, 'Source not recorded')));
  card.append(header, element('h3', compact ? '' : 'result-title', item.title));
  const description = shortText(item.description, 'No description in this record.');
  card.append(element('p', 'result-description', description));
  tagsFor(item, card, compact ? 2 : 4);
  card.append(recordFacts(item));
  if (!compact && context) card.append(element('p', 'evidence-line', formatEvidence(context)));
  const actions = element('div', 'card-actions');
  const detail = element('button', 'link-button', 'View details →');
  detail.type = 'button';
  detail.addEventListener('click', () => openDetail(item.item_id, context));
  actions.append(detail);
  const compare = element('button', 'compare-toggle', '+ Compare');
  compare.type = 'button';
  compare.dataset.compareId = item.item_id;
  compare.setAttribute('aria-label', `Compare ${item.title}`);
  compare.addEventListener('click', () => toggleCompare(item));
  actions.append(compare);
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
  if (state.compared.has(item.item_id)) {
    compare.setAttribute('aria-pressed', 'true');
    compare.textContent = '✓ Selected';
  } else compare.setAttribute('aria-pressed', 'false');
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
  $('.submit-text').textContent = recommend ? 'Find matches' : 'Search catalog';
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
      updateCompareButtons();
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
    updateCompareButtons();
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
    nodes.datasetFacts.textContent = `${meta.catalog_items} catalog records · ${meta.index_backend === 'none' ? 'Lexical retrieval' : `Index: ${meta.index_backend}`}${meta.source_facts_enabled ? ` · ${meta.source_facts_records} restaurants with OSM source records` : ''}${meta.recipe_notes_enabled ? ` · ${meta.recipe_notes_records} source-linked recipes` : ''}`;
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
    updateCompareButtons();
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
    if (state.activeDetail !== id || !nodes.dialog.open) return;
    clear(nodes.dialogContent);
    const title = element('h2', 'dialog-title', item.title);
    title.id = 'dialog-title';
    nodes.dialogContent.append(title);
    nodes.dialogContent.append(element('p', 'dialog-description', shortText(item.description, 'Description not recorded.')));
    tagsFor(item, nodes.dialogContent, 12);
    const definitions = element('dl', 'dialog-list');
    detailField(definitions, 'Record ID', item.item_id);
    detailField(definitions, 'Type', lowerType(item));
    if (item.kind === 'restaurant') {
      detailField(definitions, 'Location', shortText(item.location));
      detailField(definitions, 'City', shortText(item.city, 'Unknown'));
      detailField(definitions, 'City evidence', shortText(item.city_source, 'No verified city attribution'));
      detailField(definitions, 'Price tier', priceLabel(item));
    }
    detailField(definitions, 'Cuisine', item.cuisines?.join(', ') || 'Not recorded');
    detailField(definitions, 'Dietary tags', item.dietary_tags?.join(', ') || 'Not recorded; no safety inference');
    detailField(definitions, 'Source', shortText(item.source));
    if (item.kind === 'recipe') detailField(definitions, 'Ingredient count', String(item.ingredients?.length || 0));
    nodes.dialogContent.append(definitions);
    if (context) nodes.dialogContent.append(element('p', 'evidence-line', formatEvidence(context)));
    const url = safeSourceUrl(item.source_url);
    if (url) {
      const p = element('p');
      addSourceLink(p, item);
      nodes.dialogContent.append(p);
    }
    if (item.kind === 'recipe') {
      try {
        const notes = await requestJson(`/v1/items/${encodeURIComponent(id)}/recipe-notes`, {key: state.key});
        if (state.activeDetail !== id || !nodes.dialog.open) return;
        if (notes.review_status === 'source_transcribed_unverified') {
          const panel = element('section', 'reviewed-panel recipe-notes-panel');
          panel.append(element('h3', '', 'Ingredients and preparation · source-linked'));
          panel.append(element('p', 'dialog-disclaimer',
            'Adapted source text, not independently kitchen-tested or allergen-verified. Check each ingredient and follow food-safety guidance.'));
          panel.append(element('h4', '', 'Ingredients'));
          const ingredients = element('ul', 'recipe-ingredient-list');
          for (const line of notes.ingredients) ingredients.append(element('li', '', line));
          panel.append(ingredients);
          panel.append(element('h4', '', 'Preparation'));
          const steps = element('ol', 'recipe-steps');
          for (const step of notes.steps) steps.append(element('li', '', step));
          panel.append(steps);
          panel.append(element('p', 'dialog-disclaimer',
            `Adaptation: ${notes.adaptation_notice}. Source checked ${notes.source_checked_on}.`));
          panel.append(element('small', '', `${notes.source_attribution} · ${notes.source_license}`));
          for (const [href, label] of [
            [notes.source_revision_url, 'Original recipe revision ↗'],
            [notes.source_license_url, 'Reuse license ↗']
          ]) {
            const url = safeSourceUrl(href);
            if (url) {
              const link = element('a', 'source-link', label);
              link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer';
              panel.append(link);
            }
          }
          nodes.dialogContent.append(panel);
        } else nodes.dialogContent.append(element('p', 'dialog-disclaimer', 'Source-linked preparation notes not available.'));
      } catch {
        nodes.dialogContent.append(element('p', 'dialog-disclaimer', 'Recipe preparation notes unavailable.'));
      }
    }
    // The opt-in OSM fact sidecar only records raw source observations; its
    // contents are not verified venue metadata or hard-filter evidence.
    try {
      const sourceFacts = await requestJson(`/v1/items/${encodeURIComponent(id)}/source-facts`, {key: state.key});
      if (state.activeDetail !== id || !nodes.dialog.open) return;
      if (sourceFacts.facts.length) {
        const panel = element('section', 'reviewed-panel source-facts-panel');
        panel.append(element('h3', '', 'Recorded OSM observations · unverified'));
        panel.append(element('p', 'dialog-disclaimer',
          `OSM snapshot ${sourceFacts.observed_at}. May be outdated; not live venue verification.`));
        const names = { website: 'Website', menu_url: 'Menu link', opening_hours: 'Listed hours',
          cuisine_tag: 'Recorded cuisine classification', city_tag: 'Source city',
          description_tag: 'Source description (unverified)',
          outdoor_seating: 'Outdoor seating', wheelchair: 'Wheelchair accessibility',
          reservation: 'Reservations', delivery: 'Delivery', takeaway: 'Takeaway',
          diet_vegan: 'Vegan tag (not safety evidence)',
          diet_vegetarian: 'Vegetarian tag (not safety evidence)',
          diet_gluten_free: 'Gluten-free tag (not allergy evidence)' };
        for (const fact of sourceFacts.facts) {
          const entry = element('div', 'reviewed-entry');
          const label = names[fact.field] || fact.field;
          entry.append(element('strong', '', `${label} · OSM tag: ${fact.osm_tag}`));
          if (fact.field === 'website' || fact.field === 'menu_url') {
            const url = safeSourceUrl(fact.value);
            if (url) {
              const link = element('a', 'source-link', 'Open source-listed link ↗');
              link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer';
              entry.append(link);
            }
          } else entry.append(element('p', '', fact.value));
          panel.append(entry);
        }
        const osm = safeSourceUrl(sourceFacts.source_url);
        if (osm) {
          const link = element('a', 'source-link', 'Original OpenStreetMap record ↗');
          link.href = osm; link.target = '_blank'; link.rel = 'noopener noreferrer';
          panel.append(link);
        }
        panel.append(element('small', '', `${sourceFacts.attribution} · ${sourceFacts.license}`));
        nodes.dialogContent.append(panel);
      }
    } catch {
      nodes.dialogContent.append(element('p', 'dialog-disclaimer', 'OSM source observations unavailable.'));
    }
    // Reviewed evidence is a separate, optional sidecar. Its claims never
    // mutate item fields or turn dietary information into a safety guarantee.
    try {
      const evidence = await requestJson(`/v1/items/${encodeURIComponent(id)}/evidence`, {key: state.key});
      if (state.activeDetail !== id || !nodes.dialog.open) return;
      const menuStatus = evidence.menu_status === 'reviewed_reference' ?
        'Reviewed menu reference recorded; current menu contents not verified.' :
        'No reviewed menu reference recorded; this does not mean the restaurant has no menu.';
      if (item.kind === 'restaurant') nodes.dialogContent.append(element('p', 'menu-status', menuStatus));
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
      if (state.activeDetail !== id || !nodes.dialog.open) return;
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
    nodes.dialogContent.append(element('p', 'dialog-disclaimer', item.kind === 'restaurant' ? 'This is a saved catalog record, not live restaurant information. Hours, availability, current pricing and allergen safety are not verified.' : 'This source-linked recipe has not been independently kitchen-tested; ingredients, portions and allergen suitability need your own verification.'));
  } catch (error) { showError(nodes.dialogContent, error); }
}

nodes.form.addEventListener('submit', (event) => {event.preventDefault(); void performDiscovery();});
for (const button of document.querySelectorAll('[data-kind]')) {
  button.addEventListener('click', () => {
    nodes.kind.value = button.dataset.kind;
    for (const candidate of document.querySelectorAll('[data-kind]')) {
      const active = candidate === button;
      candidate.classList.toggle('active', active);
      candidate.setAttribute('aria-pressed', String(active));
    }
    if (nodes.query.value.trim()) void performDiscovery();
  });
}
for (const button of document.querySelectorAll('[data-example]')) {
  button.addEventListener('click', () => {
    nodes.query.value = button.dataset.example;
    void performDiscovery();
  });
}
$('#clear-search').addEventListener('click', () => {
  state.discoverController?.abort();
  state.discoverController = null;
  nodes.query.value = '';
  nodes.count.textContent = 'Browse to begin';
  nodes.resultStatus.textContent = 'Search cleared. Browse the catalog below or enter another craving.';
  emptyResults('What sounds good today?', 'Enter a dish, cuisine or flavor to find matching catalog records.', nodes.results);
  nodes.results.setAttribute('aria-busy', 'false');
  nodes.submit.disabled = false;
  nodes.query.focus();
});
$('#compare-clear').addEventListener('click', () => { state.compared.clear(); updateCompareButtons(); });
$('#compare-open').addEventListener('click', showComparison);
$('#compare-close').addEventListener('click', () => $('#compare-dialog').close());
$('#compare-dialog').addEventListener('click', (event) => {
  if (event.target === $('#compare-dialog')) $('#compare-dialog').close();
});
for (const input of document.querySelectorAll('input[name="mode"]')) input.addEventListener('change', updateMode);
nodes.strength.addEventListener('input', () => {nodes.strengthLabel.textContent = Number(nodes.strength.value).toFixed(2);});
$('#reset-filters').addEventListener('click', () => {
  nodes.form.reset();
  state.excluded.clear();
  nodes.strengthLabel.textContent = '0.25';
  updateMode(); updateExclusions();
  state.catalogOffset = 0;
  nodes.kind.value = '';
  for (const button of document.querySelectorAll('[data-kind]')) {
    const active = button.dataset.kind === '';
    button.classList.toggle('active', active);
    button.setAttribute('aria-pressed', String(active));
  }
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
