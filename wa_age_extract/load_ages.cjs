#!/usr/bin/env node
/*
 * Load the WA age extract into LithoSurfer package 250875261
 * ("WA-DNR: USA, Washington State: Geochronology").
 *
 *   node load_ages.cjs --package 250875261 [--limit N] [--dry] [--skip-lit] [--no-precheck]
 *
 * Per sample (sample.jsonl, grouped children in age_datapoint.jsonl):
 *   POST /api/core/sample-with-locations   { sampleDTO, locationDTO }
 *     -> newSampleId, newLocationId
 *   for each child age datapoint:
 *     POST /api/age/age-datapoints
 *       { dataPointDTO{...,sampleId,locationId}, ageDataPointDTO, geoEventAtAgeExtendsStatementDTO }
 *
 * Literature (literature.jsonl) is created once and linked to the package
 * (literature-2-package). Per-datapoint literature links are NOT emitted
 * (the source is named in statementDTO.description); pass nothing to change that.
 *
 * Idempotent / resumable:
 *   - every finished sample is appended to load_progress_<pkg>.jsonl
 *   - a re-run skips sampleSourceIds already logged
 *   - for samples/datapoints NOT yet logged, --precheck (default on) first
 *     GETs by sourceId and reuses an existing row instead of duplicating
 *     (this is the SIGAM Phase-3 lesson: API delete is soft-only, every
 *      create is permanent).
 *   Aborts on the first unexpected 4xx, dumping payload + what was sent.
 *
 * Creds: LITHOSURFER_USER / _PASSWORD / _HOST from ../.env (never printed).
 */
const fs = require("fs");
const path = require("path");

const DIR = __dirname;
for (const line of fs.readFileSync(path.resolve(DIR, "..", ".env"), "utf8").split(/\r?\n/)) {
  const m = line.match(/^([A-Z_]+)=(.*?)\r?$/);
  if (m && !process.env[m[1]]) process.env[m[1]] = m[2];
}
const HOST = (process.env.LITHOSURFER_HOST || "https://api.lithosurfer.io").replace(/\/$/, "");

const args = process.argv.slice(2);
const opt = (k, d) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : d; };
const PKG = opt("--package", "250875261");
const LIMIT = parseInt(opt("--limit", "0"), 10) || 0;
const DRY = args.includes("--dry");
const SKIP_LIT = args.includes("--skip-lit");
const PRECHECK = !args.includes("--no-precheck");
const PROG = path.join(DIR, `load_progress_${PKG}.jsonl`);

let TOKEN = null, TOKEN_TS = 0;
async function token() {
  if (TOKEN && Date.now() - TOKEN_TS < 9 * 3600e3) return TOKEN;
  const r = await fetch(`${HOST}/api/authenticate`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: process.env.LITHOSURFER_USER, password: process.env.LITHOSURFER_PASSWORD, rememberMe: false }),
  });
  if (!r.ok) throw new Error(`auth ${r.status}: ${await r.text()}`);
  TOKEN = (await r.json()).id_token; TOKEN_TS = Date.now();
  return TOKEN;
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function api(method, apiPath, body, tries = 4) {
  for (let attempt = 1; ; attempt++) {
    const tok = await token();
    let res;
    try {
      res = await fetch(`${HOST}${apiPath}`, {
        method,
        headers: { Accept: "application/json", Authorization: `Bearer ${tok}`, "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch (e) {
      if (attempt >= tries) throw e;
      await sleep(1000 * 2 ** attempt); continue;
    }
    if (res.status === 429 || res.status >= 500) {
      if (attempt >= tries) throw new Error(`${method} ${apiPath} -> ${res.status} after ${tries} tries`);
      await sleep(1000 * 2 ** attempt); continue;
    }
    const txt = await res.text();
    const json = txt && res.headers.get("content-type")?.includes("json") ? JSON.parse(txt) : txt;
    if (!res.ok) {
      const err = new Error(`${method} ${apiPath} -> ${res.status}`);
      err.status = res.status; err.payload = json; err.sent = body;
      throw err;
    }
    return json;
  }
}

const readJsonl = (name) =>
  fs.readFileSync(path.join(DIR, name), "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l));
const strip = (o) => JSON.parse(JSON.stringify(o, (k, v) => (k.startsWith("_") ? undefined : v)));

const samples = readJsonl("sample.jsonl");
const dpsBySample = new Map();
for (const dp of readJsonl("age_datapoint.jsonl")) {
  if (!dpsBySample.has(dp._sampleSourceId)) dpsBySample.set(dp._sampleSourceId, []);
  dpsBySample.get(dp._sampleSourceId).push(dp);
}
const literature = readJsonl("literature.jsonl");

const done = new Set();
let litDone = null;
if (fs.existsSync(PROG))
  for (const l of fs.readFileSync(PROG, "utf8").split("\n").filter(Boolean)) {
    const rec = JSON.parse(l);
    if (rec._literature) litDone = rec.ids;
    else done.add(rec.sampleSourceId);
  }

async function findBySourceId(postPath, sid) {
  if (!PRECHECK) return null;
  const rows = await api("POST", `${postPath}?page=0&size=2`, { allowedAccess: "WRITEABLE", sourceId: { equals: sid } });
  const list = Array.isArray(rows) ? rows : rows.content || [];
  return list[0] || null;
}

(async () => {
  console.log(`host=${HOST} package=${PKG} dry=${DRY} precheck=${PRECHECK}`);
  console.log(`samples=${samples.length} datapoints=${[...dpsBySample.values()].reduce((a, b) => a + b.length, 0)} already done=${done.size}` + (LIMIT ? ` limit=${LIMIT}` : ""));

  // ---- literature (once) ----
  if (!SKIP_LIT && !litDone) {
    const ids = {};
    for (const lit of literature) {
      if (DRY) { console.log(`[dry] literature "${lit.title}"`); ids[lit.sourceId] = 0; continue; }
      let row = await findBySourceId("/api/core/literature/post", lit.sourceId);
      if (!row) row = await api("POST", "/api/core/literature", strip(lit));
      const litId = row.id ?? row.literatureDTO?.id;
      ids[lit.sourceId] = litId;
      await api("POST", "/api/core/literature-2-package", { dataPackageId: Number(PKG), literatureId: litId });
      console.log(`  literature ${lit.sourceId} -> ${litId} (linked to package)`);
    }
    if (!DRY) fs.appendFileSync(PROG, JSON.stringify({ _literature: true, ts: new Date().toISOString(), ids }) + "\n");
  }

  let n = 0, sMade = 0, dMade = 0;
  for (const s of samples) {
    const ssid = s._sourceId;
    if (done.has(ssid)) continue;
    if (LIMIT && n >= LIMIT) break;
    n++;
    const kids = dpsBySample.get(ssid) || [];
    try {
      if (DRY) {
        console.log(`[dry] ${ssid} "${s.sampleDTO.name}" + ${kids.length} age datapoint(s)`);
        continue;
      }
      // sample (reuse if already there)
      let swl = await findBySourceId("/api/core/sample-with-locations/post", ssid);
      if (!swl) { swl = await api("POST", "/api/core/sample-with-locations", strip(s)); sMade++; }
      const sampleId = swl.sampleDTO?.id ?? swl.id;
      const locationId = swl.locationDTO?.id ?? swl.sampleDTO?.locationId;
      if (!sampleId || !locationId) throw Object.assign(new Error("no sampleId/locationId in response"), { payload: swl });

      const rec = { sampleSourceId: ssid, ts: new Date().toISOString(), sampleId, locationId, datapoints: [] };
      for (const dp of kids) {
        let ex = await findBySourceId("/api/age/age-datapoints/post", dp._datapointSourceId);
        let dpId;
        if (ex) {
          dpId = ex.id ?? ex.dataPointDTO?.id;
        } else {
          const body = strip(dp);
          body.dataPointDTO.sampleId = sampleId;
          body.dataPointDTO.locationId = locationId;
          const r = await api("POST", "/api/age/age-datapoints", body);
          dpId = r.id ?? r.dataPointDTO?.id;
          dMade++;
        }
        rec.datapoints.push({ sourceId: dp._datapointSourceId, id: dpId });
        await sleep(60);
      }
      fs.appendFileSync(PROG, JSON.stringify(rec) + "\n");
      if (sMade + dMade <= 8 || sMade % 50 === 0)
        console.log(`  ${done.size + n} samples seen | this run: ${sMade} samples, ${dMade} datapoints (last ${ssid})`);
      await sleep(60);
    } catch (err) {
      console.error(`\nABORT at sample ${ssid}:`, err.message);
      if (err.status) console.error("  status:", err.status);
      if (err.payload) console.error("  payload:", JSON.stringify(err.payload).slice(0, 1500));
      if (err.sent) console.error("  sent:", JSON.stringify(err.sent).slice(0, 1500));
      console.error(`\nthis run: ${sMade} samples, ${dMade} datapoints. Fix and re-run to resume.`);
      process.exit(1);
    }
  }
  console.log(`\ndone. this run: ${sMade} samples, ${dMade} datapoints${DRY ? " (dry)" : ""}. progress: ${PROG}`);
})();
