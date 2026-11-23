import type { FacetResponse, Kind } from '../lib/api';
import type { DiscoveryState } from '../lib/searchState';
import { Icon } from './Icon';

type Props = {
  state: DiscoveryState;
  facets: FacetResponse | null;
  facetsError: boolean;
  onChange: (patch: Partial<DiscoveryState>) => void;
  onClear: () => void;
};

/** Present only recorded values; missing data is never presented as a match. */
export function DiscoveryFilters({ state, facets, facetsError, onChange, onClear }: Props) {
  const selectValue = (next: string, key: 'city' | 'cuisine') => onChange({ [key]: next, page: 1 });
  const options = (key: 'cities' | 'cuisines', current: string) => {
    const listed = facets?.[key] || [];
    return current && !listed.some(row => row.value === current)
      ? [{ value: current, count: 0 }, ...listed] : listed;
  };
  return <div className="discovery-filters" role="group" aria-label="Refine recorded catalog entries">
    <div className="filter-heading"><span><Icon name="search" size={17}/> Refine your results</span>
      <button className="filter-clear" type="button" onClick={onClear}>Clear filters</button></div>
    <div className="filter-grid">
      <div className="filter-field"><label htmlFor="filter-kind">Type</label>
        <select id="filter-kind" value={state.kind} onChange={event => onChange({ kind: event.target.value as Kind, city: '', maxPriceTier: null, cuisine: '', page: 1 })}>
          <option value="restaurant">Restaurants</option>
          <option value="recipe">Recipes</option>
        </select>
      </div>
      {state.kind === 'restaurant' && <div className="filter-field"><label htmlFor="filter-city">City</label>
        <select id="filter-city" value={state.city} onChange={event => selectValue(event.target.value, 'city')}>
          <option value="">Any recorded city</option>
          {options('cities', state.city).map(row => <option key={row.value} value={row.value}>{row.value}{row.count ? ` (${row.count})` : ' (not in current catalog)'}</option>)}
        </select>
      </div>}
      <div className="filter-field"><label htmlFor="filter-cuisine">Cuisine</label>
        <select id="filter-cuisine" value={state.cuisine} onChange={event => selectValue(event.target.value, 'cuisine')}>
          <option value="">All recorded cuisines</option>
          {options('cuisines', state.cuisine).map(row => <option key={row.value} value={row.value}>{row.value} ({row.count})</option>)}
        </select>
      </div>
      {state.kind === 'restaurant' && <div className="filter-field"><label htmlFor="filter-price">Maximum recorded price tier</label>
        <select id="filter-price" value={state.maxPriceTier ?? ''} onChange={event => onChange({ maxPriceTier: event.target.value ? Number(event.target.value) : null, page: 1 })}>
          <option value="">Any recorded tier</option>
          {[1, 2, 3, 4].map(tier => <option key={tier} value={tier}>Tier {tier}</option>)}
        </select>
      </div>}
    </div>
    {facetsError && <p className="filter-warning" role="status">Recorded filter options are temporarily unavailable. Existing search and URL filters still work.</p>}
    <p className="filter-disclaimer">Only explicitly recorded attributes satisfy filters. Unknown city, cuisine, or price information is excluded from corresponding matches. Tiers are not current prices.</p>
  </div>;
}
