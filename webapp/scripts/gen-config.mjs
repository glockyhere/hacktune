// Generate public/config.js from environment variables, when they are present.
//
// Why: with Cloudflare Pages connected to git, the build runs from the repo, so
// whatever config.js is committed is what buyers see. Committing real card
// numbers to git is a poor trade (permanent history, and the repo may be
// public), so instead the values live in the Pages dashboard under
// Settings -> Environment variables, and this runs as `prebuild`.
//
// If CARAPK_API is not set, this does NOTHING and leaves config.js untouched.
// That keeps the other two workflows working unchanged:
//   - local dev, where the committed placeholders are fine
//   - direct upload, where deploy/configure.py already stamped the real values
//
// Variables (set these in the Pages dashboard):
//   CARAPK_API            https://api.yourdomain.com      (required to trigger)
//   CARAPK_CARD_1_BRAND   UZCARD
//   (no holder: the name is not shown in the UI, so it is never published)
//   CARAPK_CARD_1_NUMBER  8600 ...
//   CARAPK_CARD_2_*       same shape, optional
//   CARAPK_TELEGRAM       @handle
//   CARAPK_PRICE_TEXT     200 000 so'm
//   CARAPK_RELAY          optional, defaults to ws://127.0.0.1:8765
//   CARAPK_RELAY_DOWNLOAD optional, defaults to /AxolotlRelay.exe
import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const env = process.env;
const api = (env.CARAPK_API || "").trim();

if (!api) {
  console.log("gen-config: CARAPK_API unset — keeping the existing public/config.js");
  process.exit(0);
}

const q = (s) =>
  '"' + String(s ?? "").replace(/\\/g, "\\\\").replace(/"/g, '\\"').replace(/\n/g, " ") + '"';

const cards = [1, 2]
  .map((n) => ({
    brand: (env[`CARAPK_CARD_${n}_BRAND`] || "").trim(),
    number: (env[`CARAPK_CARD_${n}_NUMBER`] || "").trim(),
  }))
  .filter((c) => c.number);

if (!cards.length) {
  console.error("gen-config: CARAPK_API is set but no CARAPK_CARD_1_NUMBER — refusing to\n" +
                "build a payment step with no card. Set the card variables in Pages.");
  process.exit(1);
}

const out = `// Public config for the web client. Served to every visitor by design.
// GENERATED AT BUILD TIME from CARAPK_* environment variables — do not edit by
// hand in a git-connected deploy; change the variables in the Pages dashboard
// and redeploy. The recipe and payload URLs are NOT here: the server issues
// those per approved session.
window.CARAPK = {
  API: ${q(api.replace(/\/$/, ""))},

  PAYMENT: {
    cards: [
${cards.map((c) => `      { brand: ${q(c.brand)}, number: ${q(c.number)} }`).join(",\n")},
    ],
  },
  CONTACTS: {
    telegram: ${q(env.CARAPK_TELEGRAM || "")},
  },
  PRICE_TEXT: ${q(env.CARAPK_PRICE_TEXT || "")},

  // Local relay for WIRELESS cars (FAW B70). USB cars ignore this.
  RELAY: ${q(env.CARAPK_RELAY || "ws://127.0.0.1:8765")},
  RELAY_DOWNLOAD: ${q(env.CARAPK_RELAY_DOWNLOAD || "/AxolotlRelay.exe")},
};
`;

const target = join(dirname(fileURLToPath(import.meta.url)), "..", "public", "config.js");
writeFileSync(target, out);
console.log(`gen-config: wrote public/config.js — API ${api}, ${cards.length} card(s)`);
