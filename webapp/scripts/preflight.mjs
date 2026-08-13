// Refuse to ship a build that still carries placeholders.
//
// The web client's config.js is public and edited by hand after deploy, which
// makes it exactly the file most likely to go live still saying "YOUR NAME".
// `npm run preflight` reads the BUILT config (dist/config.js) and fails loudly
// on anything that would take a buyer's money to nowhere.
//
// Run it after `npm run build`, before uploading. Exit 1 = do not deploy.
import { readFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const target = join(root, "dist", "config.js");

if (!existsSync(target)) {
  console.error("preflight: dist/config.js missing — run `npm run build` first.");
  process.exit(1);
}

const src = readFileSync(target, "utf8");
const errors = [];
const warnings = [];

// Pull the config object out by evaluating it in a bare sandbox. config.js only
// assigns window.CARAPK, so a fake window is enough and nothing else runs.
let cfg;
try {
  const window = {};
  new Function("window", src)(window);
  cfg = window.CARAPK;
} catch (e) {
  console.error("preflight: config.js did not parse:", e.message);
  process.exit(1);
}
if (!cfg) { console.error("preflight: config.js set no window.CARAPK"); process.exit(1); }

// --- API endpoint ---------------------------------------------------------
const api = String(cfg.API || "");
if (!api) errors.push("API is empty");
else if (!api.startsWith("https://")) errors.push(`API must be https:// in production (got ${api})`);
if (/nip\.io/.test(api)) warnings.push(`API still uses temporary nip.io DNS (${api})`);
if (/localhost|127\.0\.0\.1/.test(api)) errors.push(`API points at localhost (${api})`);

// --- payment cards --------------------------------------------------------
const cards = Array.isArray(cfg.PAYMENT?.cards) ? cfg.PAYMENT.cards : [];
if (!cards.length) errors.push("PAYMENT.cards is empty — buyers would see no card to pay");
cards.forEach((c, i) => {
  const where = `PAYMENT.cards[${i}] (${c.brand || "?"})`;
  const digits = String(c.number || "").replace(/\D/g, "");
  if (!digits) errors.push(`${where}: number is empty`);
  else if (digits.length < 16) errors.push(`${where}: number has ${digits.length} digits, expected 16`);
  else if (/^(\d)\1+$/.test(digits.slice(4))) errors.push(`${where}: number is a placeholder (${c.number})`);
  if (!c.holder || /YOUR NAME/i.test(c.holder)) errors.push(`${where}: holder is a placeholder (${c.holder || "empty"})`);
});

// --- contacts + price -----------------------------------------------------
const tg = String(cfg.CONTACTS?.telegram || "");
if (!tg || /your_telegram/i.test(tg)) errors.push(`CONTACTS.telegram is a placeholder (${tg || "empty"})`);
if (!String(cfg.PRICE_TEXT || "").trim()) errors.push("PRICE_TEXT is empty — the cheque would show nothing");

// --- report ---------------------------------------------------------------
for (const w of warnings) console.warn(`  warn  ${w}`);
if (errors.length) {
  console.error(`\npreflight FAILED — ${errors.length} blocker(s):`);
  for (const e of errors) console.error(`  ERROR ${e}`);
  console.error("\nEdit webapp/public/config.js, rebuild, and run preflight again.");
  process.exit(1);
}
console.log(`preflight OK — API ${api}, ${cards.length} card(s), price "${cfg.PRICE_TEXT}"${warnings.length ? `, ${warnings.length} warning(s)` : ""}`);
