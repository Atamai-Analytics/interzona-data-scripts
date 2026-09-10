#!/usr/bin/env node
/*
 * Load the SIGAM deposit extract into LithoSurfer (group 17, one POST per row).
 *
 *   node load_deposits.cjs --package <dataPackageId> [--limit N] [--session TAG] [--dry]
 *
 * Per deposit:  POST /api/deposit/Deposit  ->  POST /api/deposit/DepositInfo
 *   ->  POST DepositStyle / DepositEndowment / DepositAge / DepositOpStatus  (each row)
 *
 * Resumable: every finished deposit is appended to load_progress_<pkg>.jsonl; a re-run
 * skips sourceIds already logged. Aborts on the first unexpected 4xx (logs the payload).
 * Creds: LITHOSURFER_USER / _PASSWORD / _HOST from ../.env  (never printed).
 */
const fs = require("fs");
const path = require("path");

const DIR = __dirname;
const ENV = path.resolve(DIR, "..", ".env");
for (const line of fs.readFileSync(ENV, "utf8").split(/\r?\n/)) {
  const m = line.match(/^([A-Z_]+)=(.*?)\r?$/);
  if (m && !process.env[m[1]]) process.env[m[1]] = m[2];
}
const HOST = (process.env.LITHOSURFER_HOST || "https://api.lithosurfer.io").replace(/\/$/, "");

// ---- args ----
const args = process.argv.slice(2);
const opt = (k, d) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : d; };
const PKG = opt("--package");
const LIMIT = parseInt(opt("--limit", "0"), 10) || 0;
const DRY = args.includes("--dry");
const SESSION = opt("--session", "sigam-" + new Date().toISOString().slice(0, 10));
if (!PKG) { console.error("--package <dataPackageId> is required"); process.exit(2); }

const PROG = path.join(DIR, `load_progress_${PKG}.jsonl`);

// ---- auth ----
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
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---- data ----
function readJsonl(name) {
  const p = path.join(DIR, name);
  if (!fs.existsSync(p)) return [];
  return fs.readFileSync(p, "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l));
}
function byBase(rows) {
  const m = new Map();
  for (const r of rows) {
    const k = r.sourceId.split("#")[0];
    if (!m.has(k)) m.set(k, []);
    m.get(k).push(r);
  }
  return m;
}

const deposits = readJsonl("deposit.jsonl");
const styles = byBase(readJsonl("deposit_style.jsonl"));
const endows = byBase(readJsonl("deposit_endowment.jsonl"));
const ages = byBase(readJsonl("deposit_age.jsonl"));
const ops = byBase(readJsonl("deposit_op_status.jsonl"));

const done = new Set();
if (fs.existsSync(PROG)) for (const l of fs.readFileSync(PROG, "utf8").split("\n").filter(Boolean)) done.add(JSON.parse(l).sourceId);

// ---- run ----
(async () => {
  console.log(`host=${HOST} package=${PKG} session=${SESSION} dry=${DRY}`);
  console.log(`deposits total=${deposits.length} already done=${done.size}` + (LIMIT ? ` limit=${LIMIT}` : ""));
  let n = 0, created = 0;
  for (const d of deposits) {
    if (done.has(d.sourceId)) continue;
    if (LIMIT && n >= LIMIT) break;
    n++;
    const depno = d.sourceId.split(":")[1];
    try {
      if (DRY) { console.log(`[dry] would create ${d.sourceId} "${d.name}" + ${(styles.get(d.sourceId) || []).length}s/${(endows.get(d.sourceId) || []).length}e/${(ages.get(d.sourceId) || []).length}a/${(ops.get(d.sourceId) || []).length}o`); continue; }

      const dep = await api("POST", "/api/deposit/Deposit", {
        name: d.name, lat: d.lat ?? null, lon: d.lon ?? null,
        latLonPrecision: d.latLonPrecision ?? null, description: d.description ?? null, sourceId: d.sourceId,
      });
      const depositId = dep.id;

      const info = await api("POST", "/api/deposit/DepositInfo", {
        dataPointDTO: { dataPackageId: Number(PKG), name: `${d.name}\\${SESSION}`, sourceId: d.sourceId, description: null },
        extendingDataPointDTO: { depositId, depositName: d.name },
      });
      const depositInfoId = info.id ?? info.extendingDataPointDTO?.id ?? info.dataPointDTO?.depositInfoId;
      if (!depositInfoId) throw Object.assign(new Error("no depositInfoId in response"), { payload: info });

      const rec = { sourceId: d.sourceId, ts: new Date().toISOString(), depno, depositId, depositInfoId,
        styles: [], endowments: [], ages: [], opstatus: [] };

      for (const s of styles.get(d.sourceId) || []) {
        const r = await api("POST", "/api/deposit/DepositStyle", {
          depositInfoId, depositTypeId: s.depositTypeId, comment: s.comment ?? null, sourceId: s.sourceId });
        rec.styles.push(r.id);
      }
      for (const e of endows.get(d.sourceId) || []) {
        const r = await api("POST", "/api/deposit/DepositEndowment", {
          depositInfoId, commodityId: e.commodityId ?? null, grade: e.grade ?? null, tonnage: e.tonnage ?? null,
          gradeRelativeOperatorId: e.gradeRelativeOperatorId ?? null, comment: e.comment ?? null, sourceId: e.sourceId });
        rec.endowments.push(r.id);
      }
      for (const a of ages.get(d.sourceId) || []) {
        const r = await api("POST", "/api/deposit/DepositAge", {
          depositInfoId, age: a.age ?? null, ageUncertainty: a.ageUncertainty ?? null,
          ageMethodId: a.ageMethodId ?? null, ageTypeId: a.ageTypeId ?? null,
          ageRelationshipId: a.ageRelationshipId ?? null, description: a.description ?? null, sourceId: a.sourceId });
        rec.ages.push(r.id);
      }
      for (const o of ops.get(d.sourceId) || []) {
        const r = await api("POST", "/api/deposit/DepositOpStatus", {
          depositInfoId, operatingStatusId: o.operatingStatusId, comment: o.comment ?? null, sourceId: o.sourceId });
        rec.opstatus.push(r.id);
      }

      fs.appendFileSync(PROG, JSON.stringify(rec) + "\n");
      created++;
      if (created % 25 === 0 || created <= 5) console.log(`  ${created} done  (last ${d.sourceId} -> deposit ${depositId}, info ${depositInfoId})`);
      await sleep(80);
    } catch (err) {
      console.error(`\nABORT at ${d.sourceId} (depno ${depno}):`, err.message);
      if (err.status) console.error("  status:", err.status);
      if (err.payload) console.error("  payload:", JSON.stringify(err.payload).slice(0, 1500));
      if (err.sent) console.error("  sent:", JSON.stringify(err.sent).slice(0, 1500));
      console.error(`\n${created} deposits loaded this run. Fix and re-run to resume.`);
      process.exit(1);
    }
  }
  console.log(`\ndone. ${created} deposits loaded this run${DRY ? " (dry)" : ""}. progress: ${PROG}`);
})();
