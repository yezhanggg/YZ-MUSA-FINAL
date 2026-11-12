// Lot outlines for the places with lot records, from vector tiles next to the records (app/build_lot_tiles.py,
// layer `parcels`, z14-15). Properties: id (lot_id), tr (tract GEOID of the record), s, t, mf, mk.
export const PARCEL_LAYER = 'parcels';

export interface ParcelProps {
  id: string;
  /** Tract GEOID of the lot record. */
  tr?: string;
}
