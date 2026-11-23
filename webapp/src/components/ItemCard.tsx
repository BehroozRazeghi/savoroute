import type { CatalogItem } from '../lib/api';
import { Icon } from './Icon';

export function ItemCard({ item, index, onView }: { item: CatalogItem; index: number; onView: (item: CatalogItem) => void }) {
  const isRecipe = item.kind === 'recipe';
  const location = [item.city, item.region].filter(Boolean).join(', ') || item.location || 'Area not recorded';
  return <article className="item-card">
    <div className={`item-art art-${index % 6}`} aria-hidden="true">
      <div className="dish-outline"><div className="dish-inner"><Icon name={isRecipe ? 'book' : 'utensils'} size={33} /></div></div>
      <span className="art-corner">{String(index + 1).padStart(2, '0')}</span>
      <span className="art-caption">Catalog illustration · No photo</span>
    </div>
    <div className="item-body">
      <div className="item-topline"><span>{isRecipe ? 'RECIPE' : 'RESTAURANT'}</span><span>{item.cuisines.slice(0, 2).join(' · ') || 'Cuisine not recorded'}</span></div>
      <h3>{item.title}</h3>
      <p className="item-description">{item.description || 'A description has not been recorded for this entry.'}</p>
      <div className="item-footer"><span className="item-location">{isRecipe ? 'Cooking reference' : location}</span><button type="button" className="text-action" onClick={() => onView(item)} aria-label={`View recorded details for ${item.title}`}>Details <Icon name="arrow-up-right" size={16}/></button></div>
    </div>
  </article>;
}
