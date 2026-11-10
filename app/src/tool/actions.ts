import { Marker, type GeoJSONSource } from 'maplibre-gl';
import { findFeature, findLot, type LngLat } from './geo';
import { mapRef, useTool } from './store';

let marker: Marker | null = null;
let counter = 0;

const isPhone = () => window.matchMedia('(max-width: 639px)').matches;
const reduced = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;

/** Room the floating panels take, so the map centres the spot in the open part. */
export function mapPadding(report: boolean) {
  if (isPhone()) return { left: 20, right: 20, top: 150, bottom: report ? Math.round(window.innerHeight * 0.5) : 40 };
  const wide = window.innerWidth >= 1100;
  return { left: wide ? 400 : 370, right: report ? (wide ? 470 : 420) : 40, top: 80, bottom: 40 };
}

function pinElement(label: string) {
  const el = document.createElement('div');
  el.className = 'bh-pin';
  el.innerHTML = `<div class="bh-pin-ring"></div><div class="bh-pin-dot"></div><div class="bh-pin-label"></div>`;
  (el.querySelector('.bh-pin-label') as HTMLElement).textContent = label;
  return el;
}

/** Test one spot: find its tract and town, the nearest lot, and open the report. */
export async function testSpot(pt: LngLat, label: string) {
  const { tracts, towns, set } = useTool.getState();
  const map = mapRef.current;
  if (!tracts || !towns || !map) return;
  const tract = findFeature(tracts, pt);
  const town = findFeature(towns, pt);
  if (!tract) {
    set({ msg: 'That spot is outside Pennsylvania.' });
    return;
  }
  const n = ++counter;
  set({ msg: null, busy: true });

  marker?.remove();
  marker = new Marker({ element: pinElement(label) }).setLngLat(pt).addTo(map);
  map.flyTo({ center: pt, zoom: Math.max(map.getZoom(), 15.5), duration: reduced() ? 0 : 1400, padding: mapPadding(true), essential: true });
  (map.getSource('pick') as GeoJSONSource | undefined)?.setData({ type: 'FeatureCollection', features: [tract as unknown as GeoJSON.Feature] });

  const lot = await findLot(tract.properties.GEOID, pt);
  if (n !== counter) return; // a newer spot won
  set({ busy: false, spot: { n, label, pt, tract: tract.properties, town: town?.properties ?? {}, lot } });
}

export function clearSpot() {
  marker?.remove();
  marker = null;
  (mapRef.current?.getSource('pick') as GeoJSONSource | undefined)?.setData({ type: 'FeatureCollection', features: [] });
  useTool.getState().set({ spot: null });
}
