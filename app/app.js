// Backyard Homes PA: search a spot, see if an ADU is allowed, fits, and pays off.
// Built with Vite. Data comes from app/public/data/ (made by app/build_data.py).

import * as maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import "./style.css";

const PA_BBOX = [-80.52, 39.72, -74.69, 42.27];
const state = { rule: "current", metric: "jobs_after", tracts: null, towns: null, marker: null };

// ---------- Map ----------
maplibregl.setWorkerUrl(workerUrl);
const map = new maplibregl.Map({
  container: "map",
  style: "https://tiles.openfreemap.org/styles/positron",
  bounds: PA_BBOX,
  fitBoundsOptions: { padding: { left: 420, right: 40, top: 40, bottom: 40 } },
  attributionControl: { compact: true },
});
map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");
window.map = map; // handy in the browser console

// Colors for each map metric: [break, color] pairs, lowest first
const METRICS = {
  jobs_after: {
    label: "Job change, 2019 to 2024",
    steps: [[-Infinity, "#be123c"], [-5, "#fda4af"], [0, "#a7f3d0"], [5, "#059669"]],
    names: ["Lost over 5%", "Lost 0 to 5%", "Grew 0 to 5%", "Grew over 5%"],
  },
  jobs_shift: {
    label: "Job growth after 2019 minus before (pts per year)",
    steps: [[-Infinity, "#be123c"], [-1, "#fda4af"], [0, "#a7f3d0"], [1, "#059669"]],
    names: ["Slowed a lot", "Slowed a little", "Sped up a little", "Sped up a lot"],
  },
  lots_fit: {
    label: "Lots with room for an ADU (MUSA 6950)",
    steps: [[-Infinity, "#f5f3ff"], [50, "#c4b5fd"], [200, "#8b5cf6"], [500, "#5b21b6"]],
    names: ["Under 50", "50 to 200", "200 to 500", "Over 500"],
  },
};

function colorExpr(metric) {
  const m = METRICS[metric];
  const expr = ["step", ["to-number", ["get", metric], -9999], m.steps[0][1]];
  m.steps.slice(1).forEach(([brk, col]) => expr.push(brk, col));
  return ["case", ["==", ["get", metric], null], "#e7e5e4", expr];
}

function drawLegend() {
  const m = METRICS[state.metric];
  const keys = m.steps.map(([, c], i) => `<div class="key"><i style="background:${c}"></i>${m.names[i]}</div>`).join("");
  document.getElementById("legend").innerHTML =
    `<span class="label">${m.label}</span>${keys}<div class="key"><i style="background:#e7e5e4"></i>No data yet</div>`;
}

// ---------- Small helpers ----------
const fmt = (v, d = 0) => (v == null || Number.isNaN(v) ? null : Number(v).toLocaleString("en-US", { maximumFractionDigits: d }));
const pct = (v, d = 1) => (v == null || !isFinite(v) ? null : `${v > 0 ? "+" : ""}${v.toFixed(d)}%`);
const annual = (a, b, years) => (a > 0 && b > 0 ? (Math.pow(b / a, 1 / years) - 1) * 100 : null);
const val = (v) => (v == null ? `<span class="na">Not ready yet</span>` : v);
const kv = (k, v) => `<div class="kv"><span>${k}</span><span>${val(v)}</span></div>`;

function bbox(geom) {
  let [x0, y0, x1, y1] = [Infinity, Infinity, -Infinity, -Infinity];
  const polys = geom.type === "Polygon" ? [geom.coordinates] : geom.coordinates;
  polys.forEach((p) => p[0].forEach(([x, y]) => { x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y); }));
  return [x0, y0, x1, y1];
}

function inRing([x, y], ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i], [xj, yj] = ring[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

function inGeom(pt, geom) {
  const polys = geom.type === "Polygon" ? [geom.coordinates] : geom.coordinates;
  return polys.some((p) => inRing(pt, p[0]) && !p.slice(1).some((hole) => inRing(pt, hole)));
}

function findFeature(fc, pt) {
  return fc.features.find((f) => {
    const b = f._bbox;
    return pt[0] >= b[0] && pt[0] <= b[2] && pt[1] >= b[1] && pt[1] <= b[3] && inGeom(pt, f.geometry);
  });
}

function meters([x1, y1], [x2, y2]) {
  const k = 111320;
  return Math.hypot((x2 - x1) * k * Math.cos((y1 * Math.PI) / 180), (y2 - y1) * k);
}

// ---------- Load data ----------
async function loadData() {
  const [tracts, towns] = await Promise.all(
    ["data/tracts.geojson", "data/towns.geojson"].map((u) => fetch(u).then((r) => r.json()))
  );
  tracts.features.forEach((f) => {
    const p = f.properties;
    f._bbox = bbox(f.geometry);
    // Display numbers worked out from raw job counts
    p.jobs_after = p.jobs_2019 > 0 ? (p.jobs_2024 / p.jobs_2019 - 1) * 100 : null;
    const before = annual(p.jobs_2010, p.jobs_2019, 9);
    const after = annual(p.jobs_2019, p.jobs_2024, 5);
    p.jobs_shift = before != null && after != null ? after - before : null;
  });
  towns.features.forEach((f) => (f._bbox = bbox(f.geometry)));
  state.tracts = tracts;
  state.towns = towns;
  return { tracts, towns };
}

map.on("load", async () => {
  const { tracts, towns } = await loadData();
  map.addSource("tracts", { type: "geojson", data: tracts });
  map.addSource("towns", { type: "geojson", data: towns });
  map.addSource("pick", { type: "geojson", data: { type: "FeatureCollection", features: [] } });

  const firstLabel = map.getStyle().layers.find((l) => l.type === "symbol")?.id;
  map.addLayer({ id: "tract-fill", type: "fill", source: "tracts",
    paint: { "fill-color": colorExpr(state.metric), "fill-opacity": ["interpolate", ["linear"], ["zoom"], 7, 0.6, 14, 0.25] } }, firstLabel);
  map.addLayer({ id: "town-line", type: "line", source: "towns", minzoom: 8,
    paint: { "line-color": "#475569", "line-width": 0.6, "line-opacity": 0.5 } }, firstLabel);
  map.addLayer({ id: "pick-line", type: "line", source: "pick",
    paint: { "line-color": "#7c3aed", "line-width": 2.5 } });
  drawLegend();

  map.on("click", (e) => testSpot([e.lngLat.lng, e.lngLat.lat], "Dropped pin"));
  map.on("mouseenter", "tract-fill", () => (map.getCanvas().style.cursor = "crosshair"));
  map.on("mouseleave", "tract-fill", () => (map.getCanvas().style.cursor = ""));
});

// ---------- Controls ----------
document.querySelectorAll("#rule button").forEach((b) =>
  b.addEventListener("click", () => {
    document.querySelectorAll("#rule button").forEach((x) => x.classList.toggle("on", x === b));
    state.rule = b.dataset.v;
    if (state.last) render(state.last);
  })
);

document.getElementById("metric").addEventListener("change", (e) => {
  state.metric = e.target.value;
  map.setPaintProperty("tract-fill", "fill-color", colorExpr(state.metric));
  drawLegend();
});

document.getElementById("r-close").addEventListener("click", () => {
  document.getElementById("report").hidden = true;
  state.marker?.remove();
  state.pinLabel?.remove();
  map.getSource("pick")?.setData({ type: "FeatureCollection", features: [] });
});

// ---------- Search (Photon, free, no key) ----------
const q = document.getElementById("q");
const list = document.getElementById("suggest");
const msg = document.getElementById("search-msg");
let timer = null, results = [], active = -1;

q.addEventListener("input", () => {
  clearTimeout(timer);
  msg.hidden = true;
  if (q.value.trim().length < 3) return hideList();
  timer = setTimeout(() => searchPhoton(q.value.trim()), 350);
});

q.addEventListener("keydown", async (e) => {
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    active = Math.max(0, Math.min(results.length - 1, active + (e.key === "ArrowDown" ? 1 : -1)));
    showList();
  } else if (e.key === "Enter") {
    e.preventDefault();
    if (!results.length) await searchPhoton(q.value.trim());
    if (results.length) pick(results[Math.max(active, 0)]);
    else { msg.textContent = "No match found in Pennsylvania."; msg.hidden = false; }
  } else if (e.key === "Escape") hideList();
});

async function searchPhoton(text) {
  const url = `https://photon.komoot.io/api/?q=${encodeURIComponent(text)}&bbox=${PA_BBOX.join(",")}&limit=6&lang=en`;
  try {
    const data = await fetch(url).then((r) => r.json());
    results = data.features
      .filter((f) => f.properties.state === "Pennsylvania")
      .map((f) => {
        const p = f.properties;
        const main = p.housenumber ? `${p.housenumber} ${p.street || ""}` : p.name || p.street;
        return { coords: f.geometry.coordinates, main, sub: [p.city || p.district, p.county].filter(Boolean).join(", ") };
      });
    active = results.length ? 0 : -1;
    showList();
  } catch {
    msg.textContent = "Search is not working right now. Click the map instead.";
    msg.hidden = false;
  }
}

function showList() {
  if (!results.length) return hideList();
  list.innerHTML = results.map((r, i) =>
    `<li class="${i === active ? "on" : ""}" data-i="${i}">${r.main}<span class="sub">${r.sub}</span></li>`).join("");
  list.hidden = false;
  list.querySelectorAll("li").forEach((li) => li.addEventListener("mousedown", () => pick(results[+li.dataset.i])));
}

function hideList() { list.hidden = true; results = []; active = -1; }

function pick(r) {
  q.value = r.main;
  hideList();
  testSpot(r.coords, r.main);
}

// ---------- Test a spot ----------
async function testSpot(pt, label) {
  if (!state.tracts) return;
  const tract = findFeature(state.tracts, pt);
  const town = findFeature(state.towns, pt);
  if (!tract) {
    msg.textContent = "That spot is outside Pennsylvania.";
    msg.hidden = false;
    return;
  }
  state.marker?.remove();
  state.pinLabel?.remove();
  const el = document.createElement("div");
  el.innerHTML = `<div class="pin">${label}</div>`;
  state.marker = new maplibregl.Marker({ color: "#7c3aed" }).setLngLat(pt).addTo(map);
  state.pinLabel = new maplibregl.Marker({ element: el }).setLngLat(pt).addTo(map);
  map.flyTo({ center: pt, zoom: 15.5, duration: 1400, padding: { left: 420, right: 420 } });
  map.getSource("pick").setData({ type: "FeatureCollection", features: [tract] });

  const lot = await findLot(tract.properties.GEOID, pt);
  state.last = { label, pt, tract: tract.properties, town: town?.properties || {}, lot };
  render(state.last);
}

async function findLot(geoid, pt) {
  try {
    const r = await fetch(`data/lots/${geoid}.json`);
    if (!r.ok) return null;
    const lots = await r.json();
    let best = null, bestD = 40; // within 40 m, since addresses land on the street
    lots.forEach((l) => { const d = meters(pt, [l.lon, l.lat]); if (d < bestD) { best = l; bestD = d; } });
    return best;
  } catch { return null; }
}

// ---------- Report panel ----------
const RULE_TEXT = { allowed: "Allowed", limited: "Limited", not_allowed: "Not allowed", unknown: "Unknown" };

function render({ label, tract: t, town: w, lot }) {
  document.getElementById("report").hidden = false;
  document.getElementById("r-title").textContent = label;
  document.getElementById("r-sub").textContent =
    [t.NAMELSAD, w.NAMELSAD, `${t.county} County`].filter(Boolean).join(" · ");

  // Allowed?
  const rule = state.rule === "hb2186" ? "allowed" : w.adu_rule || "unknown";
  // Fits? (MUSA 6950)
  const fits = lot ? (lot.fits ? (lot.fits_keep_trees ? "yes" : "trees") : "no") : null;
  // Pays? (MUSA 5500)
  const pays = t.pays || null;

  // Verdict
  let tone = "none", head = "No lot check for this spot", line = "Lot checks cover single-family homes in Philadelphia and Cumberland County. Tract numbers are below.";
  if (rule === "not_allowed") { tone = "bad"; head = "Not allowed here today"; line = "Switch to HB 2186 to see what the bill would change."; }
  else if (fits === "no") { tone = "bad"; head = "No room on this lot"; line = "No open spot big enough for a 600 sq ft ADU."; }
  else if (fits && pays) {
    const ok = rule === "allowed" && fits === "yes" && pays === "yes";
    tone = ok ? "good" : "warn";
    head = ok ? "Works" : "Works with changes";
    line = ok ? "Allowed, fits without cutting trees, and the rent covers the cost."
              : "Check the rule, the trees, or the rent below.";
  }

  const tiles = [
    ["Allowed", RULE_TEXT[rule], state.rule === "hb2186" ? "Under HB 2186" : "Today's rules"],
    ["Room on lot", fits ? { yes: "Fits", trees: "Fits if trees cut", no: "No room" }[fits] : (t.lots_total ? `${Math.round(100 * t.lots_fit / t.lots_total)}% of lots` : null), fits ? "MUSA 6950" : "Tract, MUSA 6950"],
    ["Pays off", pays ? { yes: "Yes", maybe: "Close", no: "No" }[pays] : null, "MUSA 5500"],
    ["Jobs since 2019", pct(t.jobs_after), "Tract, MUSA 5500"],
  ];

  const jobsYears = [2010, 2014, 2019, 2024].map((y) => [y, t[`jobs_${y}`]]).filter(([, v]) => v != null);
  const maxJobs = Math.max(...jobsYears.map(([, v]) => v), 1);
  const popBefore = annual(w.pop_2010, w.pop_2019, 9);
  const popAfter = annual(w.pop_2019, w.pop_2025, 6);
  const adus = (k) => fmt(w[`adus_${k}_${state.rule}`]);

  document.getElementById("r-body").innerHTML = `
    <div class="verdict ${tone}"><b>${head}</b>${line}</div>

    <div class="tiles">${tiles.map(([tt, v, s]) =>
      `<div class="tile"><div class="t">${tt}</div><div class="v">${val(v)}</div><div class="s">${s}</div></div>`).join("")}</div>

    <div class="card">
      <h3>Room for an ADU <span class="tag">MUSA 6950</span></h3>
      ${lot ? "" : `<div class="small muted" style="margin-bottom:6px">Lot results only in pilot counties. Tract numbers below.</div>`}
      ${lot ? kv("Lot size", `${fmt(lot.lot_m2 * 10.764)} sq ft`) : ""}
      ${lot ? kv("Open ground", `${fmt(lot.open_m2 * 10.764)} sq ft`) : ""}
      ${lot ? kv("Tree cover", `${fmt(lot.tree_m2 * 10.764)} sq ft`) : ""}
      ${kv("Lots with room in this tract", t.lots_fit != null ? `${fmt(t.lots_fit)} of ${fmt(t.lots_total)}` : null)}
      ${kv("Without cutting trees", fmt(t.lots_fit_keep_trees))}
    </div>

    <div class="card">
      <h3>Demand and payoff <span class="tag">MUSA 5500</span></h3>
      <div class="small muted">Jobs located in this tract</div>
      <div class="bars">${jobsYears.map(([, v]) => `<div style="height:${(v / maxJobs) * 100}%" title="${fmt(v)}"></div>`).join("")}</div>
      <div class="bars-x">${jobsYears.map(([y, v]) => `<span>${y}<br>${fmt(v)}</span>`).join("")}</div>
      ${kv("Town population growth, 2010-19", popBefore != null ? `${pct(popBefore, 2)} / yr` : null)}
      ${kv("Town population growth, 2019-25", popAfter != null ? `${pct(popAfter, 2)} / yr` : null)}
      ${kv("New homes permitted / yr, 2010-19", fmt(w.permits_yr_before, 1))}
      ${kv("New homes permitted / yr, 2020-25", fmt(w.permits_yr_after, 1))}
      ${kv("Median rent", t.median_rent ? `$${fmt(t.median_rent)}` : null)}
      ${kv("Trend group", t.trend_group)}
      ${kv("ADU rent vs monthly cost", t.rent_est ? `$${fmt(t.rent_est)} vs $${fmt(t.cost_month)}` : null)}
    </div>

    <div class="card">
      <h3>${w.NAMELSAD || "This town"} <span class="tag">Planner view</span></h3>
      ${kv("ADU rule today", RULE_TEXT[w.adu_rule || "unknown"])}
      ${kv(`ADUs by 2031 (${state.rule === "hb2186" ? "HB 2186" : "today's rules"})`,
           adus("mid") ? `${adus("mid")} (range ${adus("low")} to ${adus("high")})` : null)}
      ${w.source ? `<div class="small muted" style="margin-top:6px">Rule source: ${w.source}</div>` : ""}
    </div>`;
}
