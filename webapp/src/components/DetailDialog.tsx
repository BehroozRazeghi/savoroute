import { useEffect, useRef } from 'react';
import type { CatalogItem } from '../lib/api';
import { Icon } from './Icon';

function safeLink(value: string | null): string | undefined {
  if (!value) return undefined;
  try { const u = new URL(value); return ['http:', 'https:'].includes(u.protocol) ? u.href : undefined; }
  catch { return undefined; }
}

export function DetailDialog({ item, onClose }: { item: CatalogItem | null; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { if (item) ref.current?.showModal(); else ref.current?.close(); }, [item]);
  return <dialog ref={ref} className="detail-dialog" onClose={onClose} aria-label="Catalog entry details">
    {item && <div className="detail-content">
      <div className="detail-heading"><span className="eyebrow">RECORDED CATALOG ENTRY</span><button type="button" className="icon-button" onClick={onClose} aria-label="Close details"><Icon name="close"/></button></div>
      <h2>{item.title}</h2>
      <p>{item.description || 'No description recorded.'}</p>
      <dl className="facts">
        <div><dt>Type</dt><dd>{item.kind}</dd></div>
        <div><dt>Cuisine</dt><dd>{item.cuisines.join(', ') || 'Not recorded'}</dd></div>
        {item.kind === 'restaurant' && <div><dt>Area</dt><dd>{item.city || item.location || 'Not recorded'}</dd></div>}
        <div><dt>Price tier</dt><dd>{item.price_tier ? `${item.price_tier} (catalog tier, not a current price)` : 'Not recorded'}</dd></div>
        <div><dt>Source</dt><dd>{item.source}</dd></div>
      </dl>
      {safeLink(item.source_url) && <a className="source-link" href={safeLink(item.source_url)} target="_blank" rel="noopener noreferrer">Original source <Icon name="arrow-up-right" size={16}/></a>}
      <p className="detail-disclaimer"><Icon name="info" size={17}/> Recorded metadata is not live verification of opening hours, prices, ingredients, dietary safety, or availability.</p>
    </div>}
  </dialog>;
}
