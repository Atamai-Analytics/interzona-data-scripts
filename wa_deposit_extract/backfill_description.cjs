#!/usr/bin/env node
/*
 * Backfill DepositInfo.dataPointDTO.description with the full narrative text
 * (deposit_description_full.csv) — the loader had left it null, only the
 * compact 255-char Deposit.description was pushed.
 *
 *   node backfill_description.cjs --package <id> [--limit N]
 *
 * Resumable via backfill_progress_<pkg>.jsonl (sourceIds already done are skipped).
 */
const fs = require("fs"), path = require("path");
const DIR = __dirname;
for (const line of fs.readFileSync(path.resolve(DIR, "..", ".env"), "utf8").split(/\r?\n/)) {
  const m = line.match(/^([A-Z_]+)=(.*?)\r?$/);
  if (m && !process.env[m[1]]) process.env[m[1]] = m[2];
}
const HOST = (process.env.LITHOSURFER_HOST || "https://api.lithosurfer.io").replace(/\/$/, "");
const args = process.argv.slice(2);
const opt = (k, d) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : d; };
const PKG = opt("--package");
const LIMIT = parseInt(opt("--limit", "0"), 10) || 0;
if (!PKG) { console.error("--package <id> required"); process.exit(2); }
const PROG = path.join(DIR, `backfill_progress_${PKG}.jsonl`);

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
        method, headers: { Accept: "application/json", Authorization: `Bearer ${tok}`, "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch (e) { if (attempt >= tries) throw e; await sleep(1000 * 2 ** attempt); continue; }
    if (res.status === 429 || res.status >= 500) {
      if (attempt >= tries) throw new Error(`${method} ${apiPath} -> ${res.status} after ${tries} tries`);
      await sleep(1000 * 2 ** attempt); continue;
    }
    const txt = await res.text();
    const json = txt && res.headers.get("content-type")?.includes("json") ? JSON.parse(txt) : txt;
    if (!res.ok) { const err = new Error(`${method} ${apiPath} -> ${res.status}`); err.status = res.status; err.payload = json; throw err; }
    return json;
  }
}

// load progress -> depositInfoId per sourceId
const loadProg = fs.readFileSync(path.join(DIR, `load_progress_${PKG}.jsonl`), "utf8")
  .split("\n").filter(Boolean).map(JSON.parse);
const infoIdOf = new Map(loadProg.map((r) => [r.sourceId, r.depositInfoId]));

// full descriptions
function parseCsvLine(line) {
  // simple RFC4180 parser (fields may contain commas/quotes, no embedded newlines here)
  const out = []; let cur = "", inQ = false;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (inQ) {
      if (c === '"') { if (line[i + 1] === '"') { cur += '"'; i++; } else inQ = false; }
      else cur += c;
    } else if (c === '"') inQ = true;
    else if (c === ",") { out.push(cur); cur = ""; }
    else cur += c;
  }
  out.push(cur);
  return out;
}
const descLines = fs.readFileSync(path.join(DIR, "deposit_description_full.csv"), "utf8").split(/\r?\n/).filter(Boolean);
descLines.shift(); // header
const descOf = new Map();
for (const l of descLines) {
  const [cid, ...rest] = parseCsvLine(l);
  descOf.set(`WA:${cid}`, rest.join(","));
}

const done = new Set();
if (fs.existsSync(PROG)) for (const l of fs.readFileSync(PROG, "utf8").split("\n").filter(Boolean)) done.add(JSON.parse(l).sourceId);

(async () => {
  const sourceIds = [...infoIdOf.keys()];
  console.log(`host=${HOST} package=${PKG} deposits=${sourceIds.length} already done=${done.size}` + (LIMIT ? ` limit=${LIMIT}` : ""));
  let n = 0, updated = 0, skippedNoDesc = 0;
  for (const sid of sourceIds) {
    if (done.has(sid)) continue;
    if (LIMIT && n >= LIMIT) break;
    n++;
    const infoId = infoIdOf.get(sid);
    const desc = descOf.get(sid);
    if (!desc) { skippedNoDesc++; fs.appendFileSync(PROG, JSON.stringify({ sourceId: sid, skipped: "no-desc" }) + "\n"); continue; }
    try {
      const di = await api("GET", `/api/deposit/DepositInfo/${infoId}`);
      di.dataPointDTO.description = desc;
      await api("PUT", "/api/deposit/DepositInfo", di);
      fs.appendFileSync(PROG, JSON.stringify({ sourceId: sid, depositInfoId: infoId, ts: new Date().toISOString() }) + "\n");
      updated++;
      if (updated % 100 === 0 || updated <= 5) console.log(`  ${updated} done (last ${sid})`);
      await sleep(60);
    } catch (err) {
      console.error(`\nABORT at ${sid} (infoId ${infoId}):`, err.message);
      if (err.status) console.error("  status:", err.status);
      if (err.payload) console.error("  payload:", JSON.stringify(err.payload).slice(0, 800));
      console.error(`\n${updated} updated this run. Fix and re-run to resume.`);
      process.exit(1);
    }
  }
  console.log(`\ndone. ${updated} updated, ${skippedNoDesc} skipped (no description) this run. progress: ${PROG}`);
})();
