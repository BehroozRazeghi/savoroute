/** Canonical, shareable consumer search state. No catalog facts are inferred. */
import type { Kind } from './api';

export type DiscoveryState = {
  kind: Kind;
  q: string;
  city: string;
  cuisine: string;
  maxPriceTier: number | null;
  page: number;
};

export const PAGE_SIZE = 9;
export const SEARCH_LIMIT = 100; // Hard limit of the existing /v1/search contract.
export const DEFAULT_DISCOVERY: DiscoveryState = {
  kind: 'restaurant', q: '', city: '', cuisine: '', maxPriceTier: null, page: 1,
};

function safeText(value: string | null, max: number): string {
  const trimmed = (value || '').trim();
  return trimmed.length <= max ? trimmed : '';
}

export function parseDiscovery(search: string): DiscoveryState {
  const params = new URLSearchParams(search);
  const kind = params.get('kind') === 'recipe' ? 'recipe' : 'restaurant';
  const price = Number(params.get('price'));
  const pageString = params.get('page') || '';
  const page = /^[1-9][0-9]{0,5}$/.test(pageString) ? Number(pageString) : 1;
  return {
    kind,
    q: safeText(params.get('q'), 500),
    city: kind === 'restaurant' ? safeText(params.get('city'), 120) : '',
    cuisine: safeText(params.get('cuisine'), 120),
    maxPriceTier: kind === 'restaurant' && [1, 2, 3, 4].includes(price) ? price : null,
    page: Math.min(page, 111112), // /v1/items offset maximum: 1,000,000.
  };
}

export function discoveryQuery(state: DiscoveryState): string {
  const params = new URLSearchParams();
  if (state.kind !== 'restaurant') params.set('kind', state.kind);
  if (state.q) params.set('q', state.q);
  if (state.kind === 'restaurant' && state.city) params.set('city', state.city);
  if (state.cuisine) params.set('cuisine', state.cuisine);
  if (state.kind === 'restaurant' && state.maxPriceTier) params.set('price', String(state.maxPriceTier));
  if (state.page > 1) params.set('page', String(state.page));
  const query = params.toString();
  return query ? `?${query}` : '';
}

export function replaceDiscovery(state: DiscoveryState): void {
  window.history.replaceState(null, '', `${window.location.pathname}${discoveryQuery(state)}${window.location.hash}`);
}

export function pushDiscovery(state: DiscoveryState): void {
  const url = `${window.location.pathname}${discoveryQuery(state)}${window.location.hash}`;
  if (url !== `${window.location.pathname}${window.location.search}${window.location.hash}`) {
    window.history.pushState(null, '', url);
  }
}
