// Public config for the web client. Nothing here is secret — it is served to
// every visitor. The recipe and payload URLs are NOT here; the server issues
// those per approved session.
//
// PLACEHOLDERS. Fill deploy/production.env and run `python deploy/configure.py`
// to generate the real values (or edit this file directly after deploy — it is
// copied verbatim into dist/, never bundled, so a hand edit survives).
// `npm run preflight` refuses to ship while these placeholders remain.
window.CARAPK = {
  API: "https://api.example.com",

  PAYMENT: {
    cards: [
      { brand: "UZCARD", number: "8600 0000 0000 0000", holder: "YOUR NAME" },
      { brand: "HUMO",   number: "9860 0000 0000 0000", holder: "YOUR NAME" },
    ],
  },
  CONTACTS: {
    telegram: "@your_telegram",
  },
  PRICE_TEXT: "200 000 so'm",

  // Local relay for WIRELESS cars (FAW B70). USB cars ignore this.
  RELAY: "ws://127.0.0.1:8765",
};
