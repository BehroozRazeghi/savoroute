import assert from 'node:assert/strict';
import {afterEach, test} from 'node:test';
import {
  ApiRequestError, browseParams, makeFilters, makePreferences,
  parseTags, requestJson, safeSourceUrl,
} from '../../src/savoroute/web/static/api.mjs';

const originalFetch = globalThis.fetch;
afterEach(() => {globalThis.fetch = originalFetch;});

test('tags are canonicalized for duplicates but original spelling survives', () => {
  assert.deepEqual(parseTags(' Vegan,vegan, Vegetarian, ,Vegan '), ['Vegan', 'Vegetarian']);
  assert.throws(() => parseTags('a,b,c', 2), /at most 2/);
  assert.throws(() => parseTags('x'.repeat(121)), /120 characters/);
});

test('untrusted source URLs cannot become script links', () => {
  assert.equal(safeSourceUrl('javascript:alert(1)'), null);
  assert.equal(safeSourceUrl('data:text/html,evil'), null);
  assert.equal(safeSourceUrl('//malicious.example/bad'), null);
  assert.equal(safeSourceUrl('https://www.openstreetmap.org/node/1'),
    'https://www.openstreetmap.org/node/1');
});

test('hard filters and soft preferences maintain separate contracts', () => {
  assert.deepEqual(makeFilters({
    kind: 'restaurant', cuisine: '  Mexican  ', location: '', maxPriceTier: '2',
    dietaryTags: 'vegan,VEGAN',
  }), {
    kind: 'restaurant', cuisine: 'Mexican', location: null,
    max_price_tier: 2, dietary_tags: ['vegan'],
  });
  assert.deepEqual(makePreferences({
    cuisines: ' Japanese ', dietaryTags: '', strength: '0.5',
  }, ['r001']), {
    cuisines: ['Japanese'], dietary_tags: [],
    excluded_item_ids: ['r001'], preference_strength: 0.5,
  });
  assert.throws(() => makePreferences({strength: '1.1'}), /between 0 and 1/);
  assert.throws(() => makeFilters({kind: 'invalid'}), /Invalid kind/);
});

test('catalog query params are encoded safely, including repeated tags', () => {
  const params = browseParams({
    kind: 'restaurant', cuisine: 'Thai & Lao', location: null,
    max_price_tier: null, dietary_tags: ['vegan', 'gluten-free'],
  }, 9, 9);
  assert.equal(params.get('cuisine'), 'Thai & Lao');
  assert.deepEqual(params.getAll('dietary_tags'), ['vegan', 'gluten-free']);
  assert.equal(params.get('offset'), '9');
  assert.throws(() => browseParams({dietary_tags: []}, -1, 9), /pagination/);
});

test('client only calls same-origin v1 and keeps access key in a header', async () => {
  let observed;
  globalThis.fetch = async (path, options) => {
    observed = {path, options};
    return {ok: true, status: 200, json: async () => ({results: []})};
  };
  const response = await requestJson('/v1/search', {
    method: 'POST', key: 'test-secret', body: {query: 'noodles'},
  });
  assert.deepEqual(response, {results: []});
  assert.equal(observed.path, '/v1/search');
  assert.equal(observed.options.credentials, 'same-origin');
  assert.equal(observed.options.headers['X-API-Key'], 'test-secret');
  assert.equal(observed.options.body, JSON.stringify({query: 'noodles'}));
  await assert.rejects(requestJson('https://example.com/'), /Only same-origin/);
  await assert.rejects(requestJson('/v2/items'), /Only same-origin/);
});

test('401 and 422 do not echo untrusted error details', async () => {
  globalThis.fetch = async () => ({
    ok: false, status: 401,
    json: async () => ({error: {message: 'SECRET_STOLEN_IN_DETAILS'}}),
  });
  await assert.rejects(requestJson('/v1/meta'),
    (error) => error instanceof ApiRequestError && error.status === 401 &&
      !error.message.includes('SECRET_STOLEN_IN_DETAILS'));
});
