#!/usr/bin/env node
// Find the Washington data package id by name.  node find_package.cjs "<name substring>"
const fs = require("fs"), path = require("path");
for (const line of fs.readFileSync(path.resolve(__dirname, "..", ".env"), "utf8").split(/\r?\n/)) {
  const m = line.match(/^([A-Z_]+)=(.*?)\r?$/);
  if (m && !process.env[m[1]]) process.env[m[1]] = m[2];
}
const HOST = (process.env.LITHOSURFER_HOST || "https://api.lithosurfer.io").replace(/\/$/, "");
const q = (process.argv[2] || "washington").toLowerCase();

(async () => {
  const a = await fetch(`${HOST}/api/authenticate`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: process.env.LITHOSURFER_USER, password: process.env.LITHOSURFER_PASSWORD, rememberMe: false }),
  });
  if (!a.ok) throw new Error(`auth ${a.status}`);
  const tok = (await a.json()).id_token;
  const H = { Authorization: `Bearer ${tok}`, Accept: "application/json" };

  for (const ep of ["/api/management/data-packages?size=2000", "/api/data-packages?size=2000", "/api/management/data-packages/mine?size=2000"]) {
    const r = await fetch(`${HOST}${ep}`, { headers: H });
    if (!r.ok) { console.log(`${ep} -> ${r.status}`); continue; }
    const rows = await r.json();
    const list = Array.isArray(rows) ? rows : rows.content || [];
    const hits = list.filter((p) => JSON.stringify(p).toLowerCase().includes(q));
    console.log(`\n${ep}  (${list.length} packages, ${hits.length} match "${q}")`);
    for (const p of hits) console.log(`  id=${p.id}  "${p.name}"  writable=${p.writable ?? p.canWrite ?? "?"}  deleted=${p.deletedTimestamp ?? null}`);
    if (hits.length) return;
  }
})().catch((e) => { console.error(e.message); process.exit(1); });
