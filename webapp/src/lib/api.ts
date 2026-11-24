/** Typed adapter for SavoRoute's existing read-only /v1 API. No ranking logic belongs here. */
export type Kind = 'restaurant' | 'recipe';

export type CatalogItem = {
  item_id: string;
  kind: Kind;
  title: string;
  description: string;
  cuisines: string[];
  dietary_tags: string[];
  source: string;
  source_url: string | null;
  location: string | null;
  city: string | null;
  region: string | null;
  country: string | null;
  price_tier: number | null;
};

export type CatalogMeta = {
  package_version: string;
  dataset_name: string;
  catalog_synthetic: boolean;
  catalog_items: number;
  index_backend: string;
};

export type PageOfItems = { items: CatalogItem[]; total: number; offset: number; limit: number };
export type SearchResponse = {
  query: string;
  results: { item: CatalogItem; score: number; matched_terms: string[]; method: string }[];
  catalog_synthetic: boolean;
  limitations: string;
};

export class ApiError extends Error {
  constructor(public readonly status: number) {
    super(status === 401 ? 'This catalog requires access authorization.' :
      status === 0 ? 'Unable to connect to the catalog service.' :
        'The catalog request could not be completed.');
  }
}

async function request<T>(path: string, options: RequestInit = {}, signal?: AbortSignal): Promise<T> {
  if (!/^\/v1\//.test(path)) throw new Error('Only same-origin catalog API routes are supported');
  let response: Response;
  try {
    response = await fetch(path, {
      ...options,
      signal,
      credentials: 'same-origin',
      redirect: 'error',
      headers: { Accept: 'application/json', ...options.headers },
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new ApiError(0);
  }
  if (!response.ok) throw new ApiError(response.status);
  try { return await response.json() as T; }
  catch { throw new ApiError(response.status); }
}

export function getMeta(signal?: AbortSignal): Promise<CatalogMeta> {
  return request<CatalogMeta>('/v1/meta', {}, signal);
}

export type FacetValue = { value: string; count: number };
export type FacetResponse = {
  kind: Kind;
  catalog_synthetic: boolean;
  total: number;
  cities: FacetValue[];
  cuisines: FacetValue[];
  price_tiers: number[];
  limitations: string;
};

export type DiscoveryFilters = {
  city?: string;
  cuisine?: string;
  maxPriceTier?: number | null;
};

export function getFacets(kind: Kind, signal?: AbortSignal): Promise<FacetResponse> {
  const params = new URLSearchParams({ kind });
  return request<FacetResponse>(`/v1/facets?${params}`, {}, signal);
}

export function browse(kind: Kind, offset = 0, filters: DiscoveryFilters = {}, signal?: AbortSignal): Promise<PageOfItems> {
  const params = new URLSearchParams({ kind, offset: String(offset), limit: '9' });
  if (kind === 'restaurant' && filters.city) params.set('city', filters.city);
  if (filters.cuisine) params.set('cuisine', filters.cuisine);
  if (kind === 'restaurant' && filters.maxPriceTier) params.set('max_price_tier', String(filters.maxPriceTier));
  return request<PageOfItems>(`/v1/items?${params.toString()}`, {}, signal);
}

export function search(query: string, kind: Kind, filters: DiscoveryFilters = {}, signal?: AbortSignal): Promise<SearchResponse> {
  const trimmed = query.trim();
  if (!trimmed || trimmed.length > 500) throw new Error('Search for 1–500 characters.');
  return request<SearchResponse>('/v1/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query: trimmed, method: 'bm25', limit: 100, filters: {
      kind,
      ...(kind === 'restaurant' && filters.city ? { city: filters.city } : {}),
      ...(filters.cuisine ? { cuisine: filters.cuisine } : {}),
      ...(kind === 'restaurant' && filters.maxPriceTier ? { max_price_tier: filters.maxPriceTier } : {}),
    } }),
  }, signal);
}

/** AI interpretation is optional and never returns verified restaurant/menu facts. */
export type AIStatus = {
  enabled: boolean;
  input_types: ('text' | 'image')[];
  consent_required: true;
};
export type FoodInterpretation = {
  search_query: string;
  dishes: string[];
  cuisines: string[];
  ingredients: string[];
  uncertainties: string[];
};
export type AIInterpretResponse = {
  provider: string;
  interpretation: FoodInterpretation;
  catalog_verified: false;
  limitations: string;
};

export function getAIStatus(signal?: AbortSignal): Promise<AIStatus> {
  return request<AIStatus>('/v1/ai/status', {}, signal);
}

export function interpretFood(
  prompt: string, imageBase64: string | null, consent: boolean, signal?: AbortSignal,
): Promise<AIInterpretResponse> {
  if (!consent) throw new Error('Approve external AI processing first.');
  if (!prompt.trim() && !imageBase64) throw new Error('Add a description or food photo.');
  if (prompt.length > 500) throw new Error('The prompt is too long.');
  return request<AIInterpretResponse>('/v1/ai/interpret', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      prompt: prompt.trim(), image_base64: imageBase64,
      consent_remote_processing: true,
    }),
    cache: 'no-store',
  }, signal);
}

/** Live web discoveries are external candidates, never local catalog records. */
export type WebRestaurant = {
  name: string;
  city: string;
  region: string;
  country: string;
  cuisine: string;
  source_url: string;
  source_title: string;
  source_label: 'web_search_source_not_independently_verified';
};
export type LiveStatus = { enabled: boolean; consent_required: true; limitations: string; human_review_required?: boolean };
export type LiveResult = {
  provider: string;
  requested_cuisine: string;
  requested_city: string;
  geography_scope?: 'city' | 'nearby';
  requested_cities?: string[];
  catalog_synthetic?: boolean;
  human_review_required?: boolean;
  linked_sources?: { catalog_item_id: string; source_url: string; source_title: string }[];
  catalog_results: CatalogItem[];
  web_results: WebRestaurant[];
  limitations: string;
};
export type LiveParams = {
  query: string;
  cuisine: string;
  city: string;
  region: string;
  country: string;
  geography_scope?: 'city' | 'nearby';
  nearby_cities?: string[];
};
export function getLiveStatus(signal?: AbortSignal): Promise<LiveStatus> {
  return request<LiveStatus>('/v1/live/status', {}, signal);
}
export function discoverLive(params: LiveParams, consent: boolean, signal?: AbortSignal): Promise<LiveResult> {
  if (!consent) throw new Error('External live web search requires consent.');
  if (!params.city.trim() || !params.cuisine.trim()) throw new Error('Enter cuisine and city.');
  return request<LiveResult>('/v1/live/discover', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      query: params.query.trim(), cuisine: params.cuisine.trim(), city: params.city.trim(),
      region: params.region.trim(), country: params.country.trim(),
      geography_scope: params.geography_scope ?? 'city',
      nearby_cities: params.nearby_cities ?? [], consent_remote_processing: true,
    }),
    cache: 'no-store',
  }, signal);
}
