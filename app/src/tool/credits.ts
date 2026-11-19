// Map credits for the left panel footer (the map has no attribution button). The basemap, aerial and terrain credits
// are read from the map's own sources, like MapLibre's attribution control does: a source counts while a visible layer
// draws from it. The app's own credits (CREDITS) follow.
import { create } from 'zustand';
import type { Map as MLMap } from 'maplibre-gl';

/** One piece of a credit line: plain text, or a link. */
export type CreditPart = { text: string; href?: string };

export const useCredits = create<{ parts: CreditPart[] }>(() => ({ parts: [] }));

/** Credit HTML (from a source or CREDITS) as plain text and links only. Nothing else from the HTML is kept. */
export function creditParts(html: string): CreditPart[] {
  const doc = new DOMParser().parseFromString(`<div>${html}</div>`, 'text/html');
  const out: CreditPart[] = [];
  const walk = (n: Node) => {
    if (n.nodeType === Node.TEXT_NODE) {
      if (n.textContent) out.push({ text: n.textContent });
      return;
    }
    if (n instanceof HTMLAnchorElement && /^https?:/.test(n.href)) {
      out.push({ text: n.textContent ?? n.href, href: n.href });
      return;
    }
    n.childNodes.forEach(walk);
  };
  doc.body.childNodes.forEach(walk);
  return out;
}

/** Credit strings of the sources a visible layer draws from, in style order, without repeats. */
export function sourceCredits(map: MLMap): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const l of map.getStyle().layers) {
    if (!('source' in l) || typeof l.source !== 'string' || map.getLayoutProperty(l.id, 'visibility') === 'none') continue;
    const a = (map.getSource(l.source) as { attribution?: string } | undefined)?.attribution;
    if (a && !seen.has(a)) {
      seen.add(a);
      out.push(a);
    }
  }
  const terrain = map.getTerrain()?.source;
  const t = terrain ? (map.getSource(terrain) as { attribution?: string } | undefined)?.attribution : undefined;
  if (t && !seen.has(t)) out.push(t);
  return out;
}

/** Keep the footer credits in step with the map. Returns a function that stops it. */
export function watchCredits(map: MLMap, own: string[]): () => void {
  let last = '';
  const update = () => {
    if (!map.getStyle()) return;
    const html = [...sourceCredits(map), ...own].join(' | ');
    if (html === last) return;
    last = html;
    useCredits.setState({ parts: creditParts(html) });
  };
  map.on('styledata', update);
  map.on('sourcedata', update);
  map.on('terrain', update);
  update();
  return () => {
    map.off('styledata', update);
    map.off('sourcedata', update);
    map.off('terrain', update);
  };
}
