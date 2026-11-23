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

export function browse(kind: Kind, offset = 0, signal?: AbortSignal): Promise<PageOfItems> {
  const params = new URLSearchParams({ kind, offset: String(offset), limit: '9' });
  return request<PageOfItems>(`/v1/items?${params.toString()}`, {}, signal);
}

export function search(query: string, kind: Kind, signal?: AbortSignal): Promise<SearchResponse> {
  const trimmed = query.trim();
  if (!trimmed || trimmed.length > 500) throw new Error('Search for 1–500 characters.');
  return request<SearchResponse>('/v1/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query: trimmed, method: 'bm25', limit: 9, filters: { kind } }),
  }, signal);
}
