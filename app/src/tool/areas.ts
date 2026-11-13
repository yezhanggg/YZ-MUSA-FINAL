// Tracts, towns and counties (app/public/data/*.geojson, about 10 MB) load only when they are needed: Explore,
// or a lot test whose tract is not known from a parcel tile or a link. Test Project starts without them.
import { bboxOf, findFeature, loadData, type FC, type LngLat, type TownProps, type TractProps } from './geo';
import { useTool } from './store';

/** One tract of public/data/city_tracts.json: the tract's own fields and its town. */
type CityTract = Pick<TractProps, 'GEOID' | 'NAMELSAD' | 'county' | 'rent_b0' | 'rent_b1' | 'rent_b2' | 'rent_b3'> & { town?: string | null; town_geoid?: string | null };

let cityTracts: Promise<FC<CityTract> | null> | null = null;

/**
 * The tract and town at a point in Pittsburgh or Philadelphia, from the small city tract index (about 80 KB
 * gzipped) instead of the 10 MB area files. null outside the two cities or when the index does not load.
 */
export async function cityTractAt(pt: LngLat): Promise<{ tract: TractProps; town: TownProps } | null> {
  if (!cityTracts)
    cityTracts = fetch('data/city_tracts.json')
      .then((r) => (r.ok ? (r.json() as Promise<FC<CityTract>>) : null))
      .then((fc) => {
        if (fc) for (const f of fc.features) f._bbox = bboxOf(f.geometry);
        return fc;
      })
      .catch(() => {
        cityTracts = null;
        return null;
      });
  const fc = await cityTracts;
  const hit = fc ? findFeature(fc, pt) : undefined;
  if (!hit) return null;
  const { town, town_geoid, ...tract } = hit.properties;
  return { tract, town: { GEOID: town_geoid ?? undefined, NAMELSAD: town ?? undefined } };
}

let pending: Promise<boolean> | null = null;

/** Load the area files once. Resolves true when they are in the store. */
export function loadAreas(): Promise<boolean> {
  if (useTool.getState().areas === 'ready') return Promise.resolve(true);
  if (!pending) {
    useTool.getState().set({ areas: 'loading' });
    pending = loadData()
      .then(({ tracts, towns, counties }) => {
        useTool.getState().set({ tracts, towns, counties, areas: 'ready' });
        return true;
      })
      .catch(() => {
        pending = null;
        useTool.getState().set({ areas: 'error' });
        return false;
      });
  }
  return pending;
}
