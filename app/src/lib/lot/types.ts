// Types for one lot record, mirroring pipeline/lot_schema.json (schema_version 1.0).
// Geometry is GeoJSON in lon / lat. Areas are sq ft, lengths ft, shares 0 to 1, percents 0 to 100.
// LOT_KEYS lists every key of every block. types.test.ts compares it with the JSON Schema, and the
// `keysOf` helper makes the compiler reject a list that misses or invents a key, so the schema,
// the lists and these interfaces cannot drift apart.

export const SCHEMA_VERSION = '1.0';

export const SCENARIOS = ['today', 'local_reform', 'state_reform'] as const;
export type Scenario = (typeof SCENARIOS)[number];

/** Unit types the fit engine models. */
export const ADU_TYPES = ['detached_new', 'garage_conversion', 'over_garage', 'internal'] as const;
export type AduType = (typeof ADU_TYPES)[number];

/** Unit types a rule may allow. `attached` has no fit model yet. */
export const RULE_TYPES = [...ADU_TYPES, 'attached'] as const;
export type RuleType = (typeof RULE_TYPES)[number];

export type Confidence = 'high' | 'medium' | 'low';
export type CitationConfidence = 'verified' | 'secondary' | 'unverified';

/** Approval paths the rule files use today. Records may carry others later, so fields stay `string`. */
export const APPROVAL_PATHS = ['by_right', 'administrator_exception', 'special_exception', 'variance', 'not_allowed'] as const;
export type ApprovalPath = (typeof APPROVAL_PATHS)[number];

// ------------------------------------------------------------------ geometry
export type Position = number[];
export interface PolygonGeom {
  type: 'Polygon';
  coordinates: Position[][];
}
export interface MultiPolygonGeom {
  type: 'MultiPolygon';
  coordinates: Position[][][];
}
export type AreaGeom = PolygonGeom | MultiPolygonGeom;
export interface LineStringGeom {
  type: 'LineString';
  coordinates: Position[];
}

// ------------------------------------------------------------------ blocks
export interface Citation {
  section: string;
  url?: string | null;
  verified_on?: string | null;
  confidence: CitationConfidence;
  /** Rule file the value came from, or the build step that filled it. */
  source_file?: string;
}

export type EdgeRole = 'front' | 'rear' | 'side';
export interface Edge {
  id: number;
  role: EdgeRole;
  line: LineStringGeom;
  length_ft?: number;
}

export interface LotPart {
  /** Stable lot id: <county FIPS>-<city parcel id>. */
  id: string;
  parcel_id: string;
  address?: string | null;
  place?: string;
  county_fips?: string;
  tract?: string;
  crs_local: 2272 | 2271;
  polygon: AreaGeom;
  area_sqft: number;
  edges?: Edge[];
  front_edges: number[];
  rear_edges: number[];
  side_edges: number[];
  alley: boolean;
  corner?: boolean;
  flag_lot?: boolean;
  /** False when no street was found near any lot line. */
  street_edge?: boolean;
  shape_confidence: Confidence;
  shape_notes?: string[];
}

export type BuildingRole = 'main' | 'garage' | 'shed' | 'other';
export interface Building {
  id?: string;
  polygon: AreaGeom;
  height_ft?: number | null;
  role: BuildingRole;
  source: 'city' | 'msft' | 'unet' | 'yolo';
  area_sqft: number;
}

export interface Share {
  sqft: number;
  pct: number;
}
export interface Cover {
  building?: Share;
  tree?: Share;
  open?: Share;
  hard?: Share;
}

export interface LotObject {
  class: string;
  /** [min lon, min lat, max lon, max lat] */
  box: [number, number, number, number];
  score: number;
}

export interface ZoningFlags {
  flood?: boolean | null;
  historic?: boolean | null;
  steep_slope?: boolean | null;
  landslide?: boolean | null;
  /** True when public sewer serves the lot. */
  sewer?: boolean | null;
}
export interface Zoning {
  district: string | null;
  overlays?: string[];
  council_district?: string | null;
  flags?: ZoningFlags;
}

/** One floor or cap a state bill puts on the town, and what it means for this lot. */
export interface StateLimit {
  mode?: string;
  value?: number | null;
  for_this_lot?: number | null;
  section?: string;
  note?: string | null;
}

export interface Rules {
  allowed: boolean;
  approval_path: string | null;
  reasons: string[];
  types_allowed: RuleType[] | null;
  max_adus: number | null;
  max_size_sqft: number | null;
  min_size_sqft: number | null;
  max_share_of_house: number | null;
  min_lot_sqft: number | null;
  max_height_ft: number | null;
  setback_front_ft: number | null;
  setback_side_ft: number | null;
  setback_rear_ft: number | null;
  setback_rear_alley_ft: number | null;
  separation_ft: number | null;
  max_building_coverage: number | null;
  max_impervious: number | null;
  owner_occupancy: boolean | null;
  parking_spaces: number | null;
  /** Rule key -> where its value comes from. */
  citations: Record<string, Citation>;
  /** Rule keys filled from building code defaults or planning assumptions. */
  assumed: string[];
  // The keys below were added on Nov 11, 2026. Records built before that do not have them.
  /** Approval path per unit type. A value the app does not know reads as unknown. */
  approval_by_type?: Partial<Record<RuleType, string>>;
  max_height_by_type?: Partial<Record<RuleType, number | null>>;
  /** Rear setback that applies to this lot (alley or not). */
  setback_rear_effective_ft?: number | null;
  /** alley, no_alley, or how an unknown alley was handled. */
  rear_setback_rule?: string;
  /** Under state reform: each floor or cap of the state bill and its value for this lot. */
  state_limits?: Record<string, StateLimit>;
  /** Building code distances in ft, such as rated_wall_below_ft. */
  fire_separation?: Record<string, number | null>;
  /** True when the historic path opened the unit. */
  historic_path?: boolean;
}

export interface Buildable {
  /** Where a new building may go, keeping sheds and trees. */
  keep: AreaGeom | null;
  keep_sqft: number;
  /** Same, if sheds and trees go. */
  clear?: AreaGeom | null;
  clear_sqft?: number;
  /** Buildable ground in front of the house, left out of keep and clear because the unit fits behind. */
  front_sqft?: number;
}

export interface Check {
  pass: boolean;
  value?: number | null;
  limit?: number | null;
  note?: string;
}

export const CHECK_NAMES = [
  'allowed', 'type_allowed', 'min_lot_size', 'room', 'size_cap', 'min_size', 'share_of_house', 'height',
  'building_coverage', 'impervious',
] as const;
export type CheckName = (typeof CHECK_NAMES)[number];
/** Named checks, plus any extra check a later engine adds. */
export type FitChecks = Partial<Record<CheckName, Check>> & Record<string, Check | undefined>;

export interface FitResult {
  adu_type: AduType;
  fits: boolean;
  largest_sqft: number;
  largest_if_cleared_sqft?: number | null;
  spot: AreaGeom | null;
  width_ft: number | null;
  depth_ft: number | null;
  angle_deg: number | null;
  /** Code of the one constraint that decides the answer. */
  limiting: string;
  note?: string;
  checks: FitChecks;
  warnings?: string[];
  assumed?: string[];
  /** Approval path for this unit type (records from Nov 11, 2026 on). */
  approval_path?: string | null;
  /** Height limit used for this unit type (records from Nov 11, 2026 on). */
  max_height_ft?: number | null;
  second?: FitResult | null;
}

export interface Facts {
  year_built?: number | null;
  living_sqft?: number | null;
  stories?: number | null;
  assessed_value?: number | null;
  last_sale_date?: string | null;
  last_sale_price?: number | null;
  zip?: string | null;
}

export interface RentByBedroom {
  b0?: number | null;
  b1?: number | null;
  b2?: number | null;
  b3?: number | null;
}
export interface Money {
  rent_by_bedroom?: RentByBedroom;
  /** Local build cost relative to the state, 1.0 = average. */
  cost_index?: number | null;
}

export interface Quality {
  imagery_date?: string | null;
  data_dates?: Record<string, string | null>;
  confidence: Confidence;
  assumptions: string[];
}

export type PerScenario<T> = Partial<Record<Scenario, T>>;

export interface LotRecord {
  schema_version: typeof SCHEMA_VERSION;
  lot: LotPart;
  buildings: Building[];
  cover?: Cover;
  objects?: LotObject[];
  zoning: Zoning;
  rules: PerScenario<Rules>;
  buildable: PerScenario<Buildable>;
  fit: PerScenario<Partial<Record<AduType, FitResult>>>;
  facts?: Facts;
  money?: Money;
  quality: Quality;
}

// ------------------------------------------------------------------ key lists
type Missing<T, K extends readonly PropertyKey[]> = Exclude<keyof T, K[number]>;

/** Returns the list unchanged. The compiler rejects a list that misses a key of T. */
const keysOf =
  <T>() =>
  <const K extends readonly (keyof T)[]>(keys: K & ([Missing<T, K>] extends [never] ? unknown : { missing: Missing<T, K> })): K =>
    keys;

export const LOT_KEYS = {
  record: keysOf<LotRecord>()(['schema_version', 'lot', 'buildings', 'cover', 'objects', 'zoning', 'rules', 'buildable', 'fit', 'facts', 'money', 'quality']),
  citation: keysOf<Citation>()(['section', 'url', 'verified_on', 'confidence', 'source_file']),
  edge: keysOf<Edge>()(['id', 'role', 'line', 'length_ft']),
  lot: keysOf<LotPart>()([
    'id', 'parcel_id', 'address', 'place', 'county_fips', 'tract', 'crs_local', 'polygon', 'area_sqft', 'edges',
    'front_edges', 'rear_edges', 'side_edges', 'alley', 'corner', 'flag_lot', 'street_edge', 'shape_confidence', 'shape_notes',
  ]),
  building: keysOf<Building>()(['id', 'polygon', 'height_ft', 'role', 'source', 'area_sqft']),
  share: keysOf<Share>()(['sqft', 'pct']),
  cover: keysOf<Cover>()(['building', 'tree', 'open', 'hard']),
  object: keysOf<LotObject>()(['class', 'box', 'score']),
  zoning: keysOf<Zoning>()(['district', 'overlays', 'council_district', 'flags']),
  zoning_flags: keysOf<ZoningFlags>()(['flood', 'historic', 'steep_slope', 'landslide', 'sewer']),
  rules: keysOf<Rules>()([
    'allowed', 'approval_path', 'reasons', 'types_allowed', 'max_adus', 'max_size_sqft', 'min_size_sqft',
    'max_share_of_house', 'min_lot_sqft', 'max_height_ft', 'setback_front_ft', 'setback_side_ft', 'setback_rear_ft',
    'setback_rear_alley_ft', 'separation_ft', 'max_building_coverage', 'max_impervious', 'owner_occupancy',
    'parking_spaces', 'citations', 'assumed', 'approval_by_type', 'max_height_by_type', 'setback_rear_effective_ft',
    'rear_setback_rule', 'state_limits', 'fire_separation', 'historic_path',
  ]),
  buildable: keysOf<Buildable>()(['keep', 'keep_sqft', 'clear', 'clear_sqft', 'front_sqft']),
  check: keysOf<Check>()(['pass', 'value', 'limit', 'note']),
  fit_result: keysOf<FitResult>()([
    'adu_type', 'fits', 'largest_sqft', 'largest_if_cleared_sqft', 'spot', 'width_ft', 'depth_ft', 'angle_deg',
    'limiting', 'note', 'checks', 'warnings', 'assumed', 'approval_path', 'max_height_ft', 'second',
  ]),
  fit_checks: CHECK_NAMES,
  facts: keysOf<Facts>()(['year_built', 'living_sqft', 'stories', 'assessed_value', 'last_sale_date', 'last_sale_price', 'zip']),
  money: keysOf<Money>()(['rent_by_bedroom', 'cost_index']),
  rent_by_bedroom: keysOf<RentByBedroom>()(['b0', 'b1', 'b2', 'b3']),
  quality: keysOf<Quality>()(['imagery_date', 'data_dates', 'confidence', 'assumptions']),
} as const;

export type LotBlock = keyof typeof LOT_KEYS;

export const isScenario = (s: unknown): s is Scenario => typeof s === 'string' && (SCENARIOS as readonly string[]).includes(s);
export const isAduType = (t: unknown): t is AduType => typeof t === 'string' && (ADU_TYPES as readonly string[]).includes(t);
