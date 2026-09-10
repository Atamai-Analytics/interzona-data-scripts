#!/usr/bin/env node
// Verify loaded WA deposits against the API.  node verify_loaded.cjs [n]
const fs = require("fs"), path = require("path");
for (const line of fs.readFileSync(path.resolve(__dirname, "..", ".env"), "utf8").split(/\r?\n/)) {
  const m = line.match(/^([A-Z_]+)=(.*?)\r?$/);
  if (m && !process.env[m[1]]) process.env[m[1]] = m[2];
}
const HOST = (process.env.LITHOSURFER_HOST || "https://api.lithosurfer.io").replace(/\/$/, "");
const PKG = process.argv[2] || "250875260";
const N = parseInt(process.argv[3] || "3", 10);

(async () => {
  const a = await fetch(`${HOST}/api/authenticate`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: process.env.LITHOSURFER_USER, password: process.env.LITHOSURFER_PASSWORD, rememberMe: false }),
  });
  const tok = (await a.json()).id_token;
  const H = { Authorization: `Bearer ${tok}`, Accept: "application/json" };
  const get = async (p) => { const r = await fetch(`${HOST}${p}`, { headers: H }); return { s: r.status, b: r.ok ? await r.json() : await r.text() }; };

  const prog = fs.readFileSync(path.join(__dirname, `load_progress_${PKG}.jsonl`), "utf8").split("\n").filter(Boolean).map(JSON.parse);
  console.log(`progress log: ${prog.length} deposits`);
  for (const rec of prog.slice(0, N)) {
    const d = await get(`/api/deposit/Deposit/${rec.depositId}`);
    const di = await get(`/api/deposit/DepositInfo/${rec.depositInfoId}`);
    console.log(`\n=== ${rec.sourceId}  "${rec.name}" ===`);
    console.log(`Deposit ${rec.depositId}: status=${d.s}`, JSON.stringify({
      name: d.b.name, lat: d.b.lat, lon: d.b.lon, latLonPrecision: d.b.latLonPrecision,
      description: d.b.description, sourceId: d.b.sourceId,
    }));
    console.log(`DepositInfo ${rec.depositInfoId}: status=${di.s}`, JSON.stringify({
      dataPackageId: di.b?.dataPointDTO?.dataPackageId, name: di.b?.dataPointDTO?.name,
      depositId: di.b?.extendingDataPointDTO?.depositId,
    }));
    for (const eid of rec.endowments) {
      const e = await get(`/api/deposit/DepositEndowment/${eid}`);
      console.log(`  Endowment ${eid}: status=${e.s}`, JSON.stringify({
        depositInfoId: e.b.depositInfoId, commodityId: e.b.commodityId, comment: e.b.comment, sourceId: e.b.sourceId,
      }));
    }
  }
  // package deposit count
  for (const ep of [`/api/deposit/DepositInfo?dataPackageId=${PKG}&size=1`, `/api/management/data-packages/${PKG}`]) {
    const r = await get(ep);
    console.log(`\n${ep} -> ${r.s}`, typeof r.b === "object" ? JSON.stringify(r.b).slice(0, 300) : r.b.slice(0, 200));
  }
})().catch((e) => { console.error(e.message); process.exit(1); });
