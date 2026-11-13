/** Small, same-origin client for Savoroute HTTP v1; no business-logic duplication. */
export class ApiRequestError extends Error {
  constructor(message, status) {
    super(message);
    this.name = 'ApiRequestError';
    this.status = status;
  }
}

export function parseTags(value, maximum = 20) {
  const tags = String(value ?? '').split(',').map((part) => part.trim()).filter(Boolean);
  const result = [];
  const seen = new Set();
  for (const tag of tags) {
    if (tag.length > 120) throw new Error('Each tag must be 120 characters or less.');
    const key = tag.toLocaleLowerCase();
    if (!seen.has(key)) { seen.add(key); result.push(tag); }
  }
  if (result.length > maximum) throw new Error(`Use at most ${maximum} distinct tags.`);
  return result;
}

export function safeSourceUrl(raw) {
  if (typeof raw !== 'string' || !raw) return null;
  try {
    const url = new URL(raw);
    return ['https:', 'http:'].includes(url.protocol) ? url.href : null;
  } catch { return null; }
}

export function makeFilters(form) {
  const kind = form.kind || null;
  if (kind !== null && !['restaurant', 'recipe'].includes(kind)) throw new Error('Invalid kind.');
  const price = form.maxPriceTier === '' || form.maxPriceTier == null
    ? null : Number(form.maxPriceTier);
  if (price !== null && ![1, 2, 3, 4].includes(price)) throw new Error('Invalid price tier.');
  return {
    kind,
    cuisine: String(form.cuisine || '').trim() || null,
    location: String(form.location || '').trim() || null,
    max_price_tier: price,
    dietary_tags: parseTags(form.dietaryTags),
  };
}

export function makePreferences(form, excludedIds = []) {
  const strength = Number(form.strength);
  if (!Number.isFinite(strength) || strength < 0 || strength > 1) {
    throw new Error('Preference emphasis must be between 0 and 1.');
  }
  if (excludedIds.length > 1000 || new Set(excludedIds).size !== excludedIds.length) {
    throw new Error('Invalid excluded item list.');
  }
  return {
    cuisines: parseTags(form.cuisines),
    dietary_tags: parseTags(form.dietaryTags),
    excluded_item_ids: excludedIds,
    preference_strength: strength,
  };
}

export function browseParams(filters, offset, limit) {
  if (!Number.isInteger(offset) || offset < 0 || !Number.isInteger(limit) || limit < 1 || limit > 100) {
    throw new Error('Invalid pagination.');
  }
  const params = new URLSearchParams({offset: String(offset), limit: String(limit)});
  for (const key of ['kind', 'cuisine', 'location', 'max_price_tier']) {
    if (filters[key] != null && filters[key] !== '') params.set(key, String(filters[key]));
  }
  for (const tag of filters.dietary_tags) params.append('dietary_tags', tag);
  return params;
}

export async function requestJson(path, {method = 'GET', body, key = '', signal} = {}) {
  if (!/^\/v1(?:\/|$)/.test(path)) throw new Error('Only same-origin HTTP v1 requests are permitted.');
  const headers = {Accept: 'application/json'};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (key) headers['X-API-Key'] = key;
  let response;
  try {
    response = await fetch(path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
      credentials: 'same-origin',
      redirect: 'error',
    });
  } catch (error) {
    if (error.name === 'AbortError') throw error;
    throw new ApiRequestError('Could not reach the Savoroute API. Check that the local server is running.', 0);
  }
  let data;
  try { data = await response.json(); } catch { data = null; }
  if (!response.ok) {
    const prefix = response.status === 401 ? 'API access denied. Set the key under Access.' :
      response.status === 422 ? 'Some fields are invalid. Please review your filters.' :
      response.status >= 500 ? 'The catalog service encountered an error.' : 'Request could not be completed.';
    // Avoid rendering echoed raw input or untrusted server error messages.
    throw new ApiRequestError(prefix, response.status);
  }
  return data;
}


export function nearbyParams(latitude, longitude, radius) {
  if (latitude === '' || longitude === '') throw new Error('Enter both coordinates.');
  const lat = Number(latitude), lon = Number(longitude), r = Number(radius);
  if (!Number.isFinite(lat) || !Number.isFinite(lon) ||
      lat < -90 || lat > 90 || lon < -180 || lon > 180) {
    throw new Error('Latitude must be −90..90 and longitude −180..180.');
  }
  if (!Number.isInteger(r) || r < 25 || r > 20000) throw new Error('Radius must be 25..20000 m.');
  return new URLSearchParams({latitude: String(lat), longitude: String(lon), radius_m: String(r)});
}

export async function requestImageBlob(path, {key = '', signal} = {}) {
  if (!/^\/v1\/media\/img_[0-9a-f]{24}$/.test(path)) {
    throw new Error('Invalid local media path.');
  }
  const headers = {Accept: 'image/png'};
  if (key) headers['X-API-Key'] = key;
  let result;
  try {
    result = await fetch(path, {method: 'GET', headers, credentials: 'same-origin',
      redirect: 'error', signal});
  } catch (error) {
    if (error.name === 'AbortError') throw error;
    throw new ApiRequestError('Could not load the local image.', 0);
  }
  if (!result.ok || !(result.headers?.get('Content-Type') || '').startsWith('image/png')) {
    throw new ApiRequestError('Local image response is invalid.', result.status);
  }
  const blob = await result.blob();
  if (blob.size > 16 * 1024 * 1024) throw new ApiRequestError('Local image is too large.', 413);
  return blob;
}
