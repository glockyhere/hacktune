# webapp — thin web client

A static page that provisions the head unit from the browser. It holds **no
recipe, no payload, and no signing key** — it fetches a per-session plan from the
backend after approval and executes it over ADB. Full architecture and the
honest security boundary: [`../docs/WEBAPP.md`](../docs/WEBAPP.md).

```
config.js       public config (API URL, your card/contacts) — safe to expose
index.html      the three screens: request → wait → install
style.css       styling
app.js          flow controller + the generic op executor
transport.js    ADB over WebUSB (MAGE) or the local relay (B70), via ya-webadb
package.json    ya-webadb deps + Vite
```

## Run

```bash
npm install
npm run dev        # local dev server
npm run build      # -> dist/, deploy anywhere (ideally same-origin as the API)
```

Edit `config.js` with your `API` URL, card, and contacts before building.

## What still needs a real car

Everything up to `POST /api/plan` is plain fetch logic and works today. The ADB
transport in `transport.js` (WebUSB + relay) is written against
[ya-webadb](https://github.com/yume-chan/ya-webadb) but has not been run on a
unit — that is the seam to validate on hardware. See the "Verified / not"
section in [`../docs/WEBAPP.md`](../docs/WEBAPP.md).

- **MAGE (USB):** works from Chrome/Edge via WebUSB — no local install.
- **B70 (wireless):** also run the relay — `python ../agent/relay.py --api <url>`.
