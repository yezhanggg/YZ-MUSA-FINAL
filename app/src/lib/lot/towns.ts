// The municipalities that have lot records. A city place (pittsburgh) is one town. A county place (chester_county)
// holds several towns, and each of its lots follows its own town's rule file: the town of a lot is that rule file.
// Names, GEOIDs and code links are shared/rules/towns_index.json's (towns.test.ts checks them against it).
import { PLACE_BY_COUNTY } from './load.js';
import type { LotRecord } from './types.js';

export interface LotTown {
  /** Rule file (shared/rules/<file>.json), the key a lot's citations name. */
  file: string;
  /** 10 digit Census GEOID of the municipality. */
  geoid: string;
  /** Census name, "West Chester borough". */
  name: string;
  /** Place folder of its lot records. */
  place: string;
  /** The zoning code the rule file cites. */
  code_url: string;
}

const ALL_TOWNS: readonly LotTown[] = [
  { file: 'pittsburgh', geoid: '4200361000', name: 'Pittsburgh city', place: 'pittsburgh', code_url: 'https://ecode360.com/45474194' },
  { file: 'philadelphia', geoid: '4210160000', name: 'Philadelphia city', place: 'philadelphia', code_url: 'https://codelibrary.amlegal.com/codes/philadelphia/latest/philadelphia_pa/0-0-0-292755' },
  { file: 'pa_lehigh_allentown', geoid: '4207702000', name: 'Allentown city', place: 'allentown', code_url: 'https://ecode360.com/49783893' },
  { file: 'pa_chester_west_chester', geoid: '4202982704', name: 'West Chester borough', place: 'chester_county', code_url: 'https://ecode360.com/6471979' },
  { file: 'pa_chester_phoenixville', geoid: '4202960120', name: 'Phoenixville borough', place: 'chester_county', code_url: 'https://ecode360.com/47638080' },
  { file: 'pa_chester_west_vincent', geoid: '4202984160', name: 'West Vincent township', place: 'chester_county', code_url: 'https://ecode360.com/32399799' },
  { file: 'pa_chester_malvern', geoid: '4202946792', name: 'Malvern borough', place: 'chester_county', code_url: 'https://ecode360.com/11230593' },
  { file: 'pa_chester_east_brandywine', geoid: '4202920864', name: 'East Brandywine township', place: 'chester_county', code_url: 'https://ecode360.com/11881518' },
  { file: 'pa_centre_college', geoid: '4202715136', name: 'College township', place: 'centre_county', code_url: 'https://ecode360.com/10705471' },
  { file: 'pa_centre_state_college', geoid: '4202773808', name: 'State College borough', place: 'centre_county', code_url: 'https://ecode360.com/32909719' },
  { file: 'pa_montgomery_lower_merion', geoid: '4209144976', name: 'Lower Merion township', place: 'montgomery_county', code_url: 'https://ecode360.com/35907405' },
  { file: 'pa_montgomery_narberth', geoid: '4209152664', name: 'Narberth borough', place: 'montgomery_county', code_url: 'https://ecode360.com/34400015' },
  { file: 'pa_montgomery_upper_dublin', geoid: '4209179008', name: 'Upper Dublin township', place: 'montgomery_county', code_url: 'https://codelibrary.amlegal.com/codes/upperdublin/latest/upperdublintwp_pa/0-0-0-24735' },
  { file: 'pa_dauphin_harrisburg', geoid: '4204332800', name: 'Harrisburg city', place: 'dauphin_county', code_url: 'https://ecode360.com/26959105' },
  { file: 'pa_dauphin_lower_paxton', geoid: '4204345056', name: 'Lower Paxton township', place: 'dauphin_county', code_url: 'https://ecode360.com/34198634' },
  { file: 'pa_dauphin_swatara', geoid: '4204375672', name: 'Swatara township', place: 'dauphin_county', code_url: 'https://ecode360.com/11636509' },
  { file: 'pa_erie_erie', geoid: '4204924000', name: 'Erie city', place: 'erie_county', code_url: 'https://ecode360.com/33839105' },
  { file: 'pa_cumberland_camp_hill', geoid: '4204111000', name: 'Camp Hill borough', place: 'cumberland_county', code_url: 'https://ecode360.com/12763634' },
  { file: 'pa_cumberland_lower_allen', geoid: '4204144832', name: 'Lower Allen township', place: 'cumberland_county', code_url: 'https://ecode360.com/11213000' },
  { file: 'pa_cumberland_upper_allen', geoid: '4204178736', name: 'Upper Allen township', place: 'cumberland_county', code_url: 'https://ecode360.com/8577949' },
  { file: 'pa_northampton_bethlehem', geoid: '4209506088', name: 'Bethlehem city', place: 'northampton_county', code_url: 'https://k12.bethlehem-pa.gov/getattachment/Community-Economic-Development/Planning-Zoning/Zoning-Office/Zoning-Ordinance-August-2023.pdf.aspx?lang=en-US' },
  { file: 'pa_northampton_bethlehem_township', geoid: '4209506096', name: 'Bethlehem township', place: 'northampton_county', code_url: 'https://ecode360.com/13370636' },
  { file: 'pa_northampton_easton', geoid: '4209521648', name: 'Easton city', place: 'northampton_county', code_url: 'https://ecode360.com/9647638' },
  { file: 'pa_northampton_lower_saucon', geoid: '4209545104', name: 'Lower Saucon township', place: 'northampton_county', code_url: 'https://ecode360.com/6775923' },
  { file: 'pa_northampton_wilson', geoid: '4209585592', name: 'Wilson borough', place: 'northampton_county', code_url: 'https://ecode360.com/11718930' },
  { file: 'pa_bucks_bristol', geoid: '4201708768', name: 'Bristol township', place: 'bucks_county', code_url: 'https://ecode360.com/9499446' },
  { file: 'pa_bucks_doylestown', geoid: '4201719792', name: 'Doylestown township', place: 'bucks_county', code_url: 'https://ecode360.com/10729898' },
  { file: 'pa_bucks_doylestown_borough', geoid: '4201719784', name: 'Doylestown borough', place: 'bucks_county', code_url: 'https://ecode360.com/11768539' },
  { file: 'pa_bucks_lower_southampton', geoid: '4201745112', name: 'Lower Southampton township', place: 'bucks_county', code_url: 'https://ecode360.com/29169162' },
  { file: 'pa_bucks_new_britain', geoid: '4201753304', name: 'New Britain township', place: 'bucks_county', code_url: 'https://ecode360.com/30859978' },
  { file: 'pa_bucks_plumstead', geoid: '4201761616', name: 'Plumstead township', place: 'bucks_county', code_url: 'https://ecode360.com/11770606' },
  { file: 'pa_bucks_warminster', geoid: '4201780952', name: 'Warminster township', place: 'bucks_county', code_url: 'https://ecode360.com/14238962' },
  { file: 'pa_bucks_warwick', geoid: '4201781144', name: 'Warwick township', place: 'bucks_county', code_url: 'https://ecode360.com/11665361' },
  { file: 'pa_york_east_manchester', geoid: '4213321464', name: 'East Manchester township', place: 'york_county', code_url: 'https://ecode360.com/13287498' },
  { file: 'pa_york_hanover', geoid: '4213332448', name: 'Hanover borough', place: 'york_county', code_url: 'https://ecode360.com/15699677' },
  { file: 'pa_york_lower_windsor', geoid: '4213345152', name: 'Lower Windsor township', place: 'york_county', code_url: 'https://ecode360.com/36205355' },
  { file: 'pa_york_newberry', geoid: '4213353224', name: 'Newberry township', place: 'york_county', code_url: 'https://ecode360.com/36783754' },
  { file: 'pa_york_springettsbury', geoid: '4213372992', name: 'Springettsbury township', place: 'york_county', code_url: 'https://ecode360.com/5176819' },
  { file: 'pa_york_york', geoid: '4213387048', name: 'York city', place: 'york_county', code_url: 'https://www.yorkcity.org/wp-content/uploads/2026/06/Part-13-Planning-Zoning-Updated-6-23-26.pdf' },
  { file: 'pa_york_york_township', geoid: '4213387056', name: 'York township', place: 'york_county', code_url: 'https://yorktownshippa.gov/wp-content/uploads/Zoning-Ordinance-last-amendment-3-14-23.pdf' },
  { file: 'pa_delaware_aston', geoid: '4204503336', name: 'Aston township', place: 'delaware_county', code_url: 'https://codelibrary.amlegal.com/codes/astontwppa/latest/astontownship_pa/0-0-0-6217' },
  { file: 'pa_delaware_bethel', geoid: '4204506024', name: 'Bethel township', place: 'delaware_county', code_url: 'https://ecode360.com/11463872' },
  { file: 'pa_delaware_chester', geoid: '4204513208', name: 'Chester city', place: 'delaware_county', code_url: 'https://ecode360.com/45941765' },
  { file: 'pa_delaware_clifton_heights', geoid: '4204514264', name: 'Clifton Heights borough', place: 'delaware_county', code_url: 'https://ecode360.com/16213818' },
  { file: 'pa_delaware_collingdale', geoid: '4204515232', name: 'Collingdale borough', place: 'delaware_county', code_url: 'https://ecode360.com/29755627' },
  { file: 'pa_delaware_concord', geoid: '4204515488', name: 'Concord township', place: 'delaware_county', code_url: 'https://ecode360.com/10946616' },
  { file: 'pa_delaware_darby_township', geoid: '4204518160', name: 'Darby township', place: 'delaware_county', code_url: 'https://ecode360.com/27167274' },
  { file: 'pa_delaware_glenolden', geoid: '4204529720', name: 'Glenolden borough', place: 'delaware_county', code_url: 'https://ecode360.com/10762245' },
  { file: 'pa_delaware_haverford', geoid: '4204533144', name: 'Haverford township', place: 'delaware_county', code_url: 'https://ecode360.com/12186661' },
  { file: 'pa_delaware_media', geoid: '4204548480', name: 'Media borough', place: 'delaware_county', code_url: 'https://ecode360.com/6866878' },
  { file: 'pa_delaware_nether_providence', geoid: '4204553104', name: 'Nether Providence township', place: 'delaware_county', code_url: 'https://ecode360.com/11544796' },
  { file: 'pa_delaware_radnor', geoid: '4204563264', name: 'Radnor township', place: 'delaware_county', code_url: 'https://ecode360.com/11078356' },
  { file: 'pa_delaware_ridley', geoid: '4204564800', name: 'Ridley township', place: 'delaware_county', code_url: 'https://ecode360.com/8799872' },
  { file: 'pa_delaware_springfield', geoid: '4204573032', name: 'Springfield township', place: 'delaware_county', code_url: 'https://ecode360.com/30536824' },
  { file: 'pa_delaware_swarthmore', geoid: '4204575648', name: 'Swarthmore borough', place: 'delaware_county', code_url: 'https://codelibrary.amlegal.com/codes/swarthmore/latest/swarthm_pa/0-0-0-23482' },
  { file: 'pa_delaware_thornbury', geoid: '4204576576', name: 'Thornbury township', place: 'delaware_county', code_url: 'https://ecode360.com/30828967' },
  { file: 'pa_delaware_upper_chichester', geoid: '4204578776', name: 'Upper Chichester township', place: 'delaware_county', code_url: 'https://ecode360.com/15685575' },
  { file: 'pa_delaware_upper_darby', geoid: '4204579000', name: 'Upper Darby township', place: 'delaware_county', code_url: 'https://ecode360.com/33161971' },
  { file: 'pa_delaware_yeadon', geoid: '4204586968', name: 'Yeadon borough', place: 'delaware_county', code_url: 'https://ecode360.com/11892117' },
  { file: 'pa_chester_east_coventry', geoid: '4202921008', name: 'East Coventry township', place: 'chester_county', code_url: 'https://ecode360.com/30868304' },
  { file: 'pa_chester_east_goshen', geoid: '4202921192', name: 'East Goshen township', place: 'chester_county', code_url: 'https://ecode360.com/7252554' },
  { file: 'pa_chester_east_nottingham', geoid: '4202921624', name: 'East Nottingham township', place: 'chester_county', code_url: 'https://ecode360.com/30831666' },
  { file: 'pa_chester_honey_brook', geoid: '4202935536', name: 'Honey Brook township', place: 'chester_county', code_url: 'https://ecode360.com/30832599' },
  { file: 'pa_chester_north_coventry', geoid: '4202954936', name: 'North Coventry township', place: 'chester_county', code_url: 'https://ecode360.com/11562582' },
  { file: 'pa_chester_schuylkill', geoid: '4202968288', name: 'Schuylkill township', place: 'chester_county', code_url: 'https://ecode360.com/13604405' },
  { file: 'pa_chester_west_caln', geoid: '4202982664', name: 'West Caln township', place: 'chester_county', code_url: 'https://ecode360.com/38019890' },
  { file: 'pa_chester_west_goshen', geoid: '4202983080', name: 'West Goshen township', place: 'chester_county', code_url: 'https://ecode360.com/10796167' },
  { file: 'pa_chester_westtown', geoid: '4202984104', name: 'Westtown township', place: 'chester_county', code_url: 'https://ecode360.com/12396615' },
  { file: 'pa_montgomery_ambler', geoid: '4209102264', name: 'Ambler borough', place: 'montgomery_county', code_url: 'https://boroughofambler.com/download/137/code-of-ordinances-by-chapter/6843/27-chapter-zoning.pdf' },
  { file: 'pa_montgomery_cheltenham', geoid: '4209112968', name: 'Cheltenham township', place: 'montgomery_county', code_url: 'https://ecode360.com/6448532' },
  { file: 'pa_montgomery_conshohocken', geoid: '4209115848', name: 'Conshohocken borough', place: 'montgomery_county', code_url: 'https://ecode360.com/14317188' },
  { file: 'pa_montgomery_douglass', geoid: '4209119672', name: 'Douglass township', place: 'montgomery_county', code_url: 'https://ecode360.com/39409917' },
  { file: 'pa_montgomery_franconia', geoid: '4209127280', name: 'Franconia township', place: 'montgomery_county', code_url: 'https://ecode360.com/8789917' },
  { file: 'pa_montgomery_hatfield', geoid: '4209133120', name: 'Hatfield township', place: 'montgomery_county', code_url: 'https://ecode360.com/10506475' },
  { file: 'pa_montgomery_horsham', geoid: '4209135808', name: 'Horsham township', place: 'montgomery_county', code_url: 'https://ecode360.com/44681314' },
  { file: 'pa_montgomery_lansdale', geoid: '4209141432', name: 'Lansdale borough', place: 'montgomery_county', code_url: 'https://ecode360.com/11763313' },
  { file: 'pa_montgomery_limerick', geoid: '4209143312', name: 'Limerick township', place: 'montgomery_county', code_url: 'https://ecode360.com/11206587' },
  { file: 'pa_montgomery_lower_pottsgrove', geoid: '4209145072', name: 'Lower Pottsgrove township', place: 'montgomery_county', code_url: 'https://ecode360.com/13282057' },
  { file: 'pa_montgomery_montgomery', geoid: '4209150640', name: 'Montgomery township', place: 'montgomery_county', code_url: 'https://ecode360.com/11516266' },
  { file: 'pa_montgomery_norristown', geoid: '4209154656', name: 'Norristown borough', place: 'montgomery_county', code_url: 'https://ecode360.com/11552876' },
  { file: 'pa_montgomery_plymouth', geoid: '4209161664', name: 'Plymouth township', place: 'montgomery_county', code_url: 'https://ecode360.com/26906730' },
  { file: 'pa_montgomery_skippack', geoid: '4209171016', name: 'Skippack township', place: 'montgomery_county', code_url: 'https://ecode360.com/9228557' },
  { file: 'pa_montgomery_springfield', geoid: '4209173088', name: 'Springfield township', place: 'montgomery_county', code_url: 'https://ecode360.com/11823514' },
  { file: 'pa_montgomery_upper_gwynedd', geoid: '4209179056', name: 'Upper Gwynedd township', place: 'montgomery_county', code_url: 'https://ecode360.com/10790758' },
  { file: 'pa_montgomery_upper_merion', geoid: '4209179136', name: 'Upper Merion township', place: 'montgomery_county', code_url: 'https://ecode360.com/11658450' },
  { file: 'pa_montgomery_upper_providence', geoid: '4209179256', name: 'Upper Providence township', place: 'montgomery_county', code_url: 'https://ecode360.com/42975244' },
  { file: 'pa_montgomery_west_norriton', geoid: '4209183696', name: 'West Norriton township', place: 'montgomery_county', code_url: 'https://ecode360.com/15475025' },
  { file: 'pa_montgomery_whitemarsh', geoid: '4209184624', name: 'Whitemarsh township', place: 'montgomery_county', code_url: 'https://ecode360.com/11708888' },
  { file: 'pa_montgomery_whitpain', geoid: '4209184888', name: 'Whitpain township', place: 'montgomery_county', code_url: 'https://ecode360.com/10515979' },
  { file: 'pa_lancaster_east_lampeter', geoid: '4207121344', name: 'East Lampeter township', place: 'lancaster_county', code_url: 'https://ecode360.com/48621783' },
  { file: 'pa_lancaster_elizabethtown', geoid: '4207123016', name: 'Elizabethtown borough', place: 'lancaster_county', code_url: 'https://ecode360.com/27498291' },
  { file: 'pa_lancaster_lancaster', geoid: '4207141216', name: 'Lancaster city', place: 'lancaster_county', code_url: 'https://ecode360.com/8122408' },
  { file: 'pa_lancaster_lancaster_township', geoid: '4207141224', name: 'Lancaster township', place: 'lancaster_county', code_url: 'https://ecode360.com/13005392' },
  { file: 'pa_lancaster_manheim', geoid: '4207146896', name: 'Manheim township', place: 'lancaster_county', code_url: 'https://manheimtownship.org/DocumentCenter/View/8076/2-Ordinance-Updates' },
  { file: 'pa_lancaster_mount_joy', geoid: '4207151664', name: 'Mount Joy township', place: 'lancaster_county', code_url: 'https://ecode360.com/11526470' },
  { file: 'pa_lancaster_penn', geoid: '4207158840', name: 'Penn township', place: 'lancaster_county', code_url: 'https://ecode360.com/30832287' },
  { file: 'pa_lancaster_warwick', geoid: '4207181168', name: 'Warwick township', place: 'lancaster_county', code_url: 'https://ecode360.com/11671452' },
  { file: 'pa_lancaster_west_earl', geoid: '4207182824', name: 'West Earl township', place: 'lancaster_county', code_url: 'https://ecode360.com/12452988' },
  { file: 'pa_lancaster_west_hempfield', geoid: '4207183152', name: 'West Hempfield township', place: 'lancaster_county', code_url: 'https://ecode360.com/13152773' },
  { file: 'pa_lancaster_west_lampeter', geoid: '4207183256', name: 'West Lampeter township', place: 'lancaster_county', code_url: 'https://ecode360.com/11694778' },
];

const REGISTERED = new Set(Object.values(PLACE_BY_COUNTY));

/** Towns with lot records today (their place is in the loader's registry), in registry order. */
export const LOT_TOWNS: readonly LotTown[] = ALL_TOWNS.filter((t) => REGISTERED.has(t.place)).sort(
  (a, b) => Object.values(PLACE_BY_COUNTY).indexOf(a.place) - Object.values(PLACE_BY_COUNTY).indexOf(b.place),
);

const BY_FILE = new Map(LOT_TOWNS.map((t) => [t.file, t]));
const BY_GEOID = new Map(LOT_TOWNS.map((t) => [t.geoid, t]));
const BY_NAME = new Map(LOT_TOWNS.map((t) => [t.name.toLowerCase(), t]));

export const lotTownByGeoid = (geoid: string | null | undefined): LotTown | null => (geoid ? (BY_GEOID.get(geoid) ?? null) : null);
export const lotTownByFile = (file: string | null | undefined): LotTown | null => (file ? (BY_FILE.get(file.split('#')[0]) ?? null) : null);

/** The lot towns of one place folder. */
export const townsOfPlace = (place: string): LotTown[] => LOT_TOWNS.filter((t) => t.place === place);

/** "West Chester borough" -> "West Chester", "College township" -> "College Township", "Pittsburgh city" -> "Pittsburgh". */
export const townShortName = (t: LotTown): string => t.name.replace(/ (city|borough)$/, '').replace(/ township$/, ' Township');

const SCENARIOS = ['today', 'local_reform', 'state_reform'] as const;

/**
 * The town of a lot record. The record's own `lot.rule_file` or `lot.municipality` when the build writes them, else
 * the town rule file its citations name, else the only town of its place. null when none of these names a lot town.
 */
export function lotTownOf(rec: LotRecord | null | undefined): LotTown | null {
  if (!rec) return null;
  const own = rec.lot as { rule_file?: unknown; municipality?: unknown };
  if (typeof own.rule_file === 'string' && BY_FILE.has(own.rule_file)) return BY_FILE.get(own.rule_file)!;
  if (typeof own.municipality === 'string' && BY_NAME.has(own.municipality.toLowerCase())) return BY_NAME.get(own.municipality.toLowerCase())!;
  for (const s of SCENARIOS) {
    const r = rec.rules?.[s];
    for (const c of [...Object.values(r?.citations ?? {}), ...Object.values(r?.citations_by_type ?? {})]) {
      const t = lotTownByFile(c?.source_file);
      if (t) return t;
    }
  }
  const place = rec.lot.place ?? PLACE_BY_COUNTY[rec.lot.id.slice(0, 5)];
  const only = place ? townsOfPlace(place) : [];
  return only.length === 1 ? only[0] : null;
}
