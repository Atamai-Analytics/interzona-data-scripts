#!/usr/bin/env node
/* Delete everything a load_progress_<pkg>.jsonl created, children-first.
 *   node undo_load.cjs --package <id> [--keep-log]
 *
 * The API delete is SOFT. Children (DepositEndowment) + DepositInfo must be deleted,
 * in that order, BEFORE the Deposit, or the Deposit delete fails on
 * fk_deposit_info_deposit_id and the row is stranded (its name stays spent).
 * Runs children-first and reports failures. (See ls_deposit_extract/PHASE3_STATUS.md.)
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
const PKG = args[args.indexOf("--package") + 1];
if (!PKG) { console.error("--package required"); process.exit(2); }
const PROG = path.join(DIR, `load_progress_${PKG}.jsonl`);

let TOK, TS = 0;
async function token() {
  if (TOK && Date.now() - TS < 9e6) return TOK;
  const r = await fetch(`${HOST}/api/authenticate`, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: process.env.LITHOSURFER_USER, password: process.env.LITHOSURFER_PASSWORD, rememberMe: false }) });
  TOK = (await r.json()).id_token; TS = Date.now(); return TOK;
}
async function del(p) {
  const r = await fetch(`${HOST}${p}`, { method: "DELETE", headers: { Authorization: `Bearer ${await token()}` } });
  const txt = r.ok ? "" : await r.text();
  return { ok: r.ok || r.status === 204, status: r.status, txt };
}
(async () => {
  const rows = fs.readFileSync(PROG, "utf8").split("\n").filter(Boolean).map(JSON.parse);
  console.log(`undoing ${rows.length} deposits from package ${PKG}`);
  let d = 0; const fails = [];
  for (const r of rows) {
    for (const [kind, ids] of [["DepositStyle", r.styles], ["DepositEndowment", r.endowments],
                               ["DepositAge", r.ages], ["DepositOpStatus", r.opstatus]]) {
      for (const id of ids || []) { const x = await del(`/api/deposit/${kind}/${id}`); if (!x.ok) fails.push([kind, id, x.status]); }
    }
    const di = await del(`/api/deposit/DepositInfo/${r.depositInfoId}`);
    if (!di.ok) fails.push(["DepositInfo", r.depositInfoId, di.status, di.txt.slice(0, 120)]);
    const dp = await del(`/api/deposit/Deposit/${r.depositId}`);
    if (!dp.ok) fails.push(["Deposit", r.depositId, dp.status, dp.txt.slice(0, 120)]);
    if (++d % 25 === 0) console.log(`  ${d}`);
  }
  if (fails.length) {
    console.log(`\n${fails.length} delete(s) FAILED (rows stranded):`);
    fails.slice(0, 20).forEach((f) => console.log("  ", JSON.stringify(f)));
  }
  if (!args.includes("--keep-log")) fs.renameSync(PROG, PROG + ".undone-" + Date.now());
  console.log(`\ndone. ${d - fails.filter((f) => f[0] === "Deposit").length}/${d} deposits fully removed.`);
})().catch((e) => { console.error(e.message); process.exit(1); });
