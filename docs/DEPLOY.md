# Production deployment — Cloudflare + custom domain

The runbook for taking the web client live. Everything is driven by one file:
`deploy/production.env`.

Topology (root domain for the app, `api.` for the backend):

```
 buyer's browser
   │
   ├── https://example.com            Cloudflare Pages   static client (webapp/dist)
   │        │  POST /api/request, /api/plan …
   │        ▼
   ├── https://api.example.com        VPS + Caddy        FastAPI activation API
   │        │  streams APKs via expiring /dl links
   │        ▼
   └── file:///var/lib/carapk/payload  on the VPS itself   APKs, not web-reachable
            (streamed by /dl only after the signature checks out)
```

The browser only ever talks to the first two. It never learns the payload host:
`/dl` proxies through the API, so an approved session holds a link that expires
in 15 minutes and nothing else.

---

## 0. Prerequisites

- Cloudflare account with your domain's nameservers already delegated
- The VPS running the activation API (see `docs/ACTIVATION_VPS.md`)
- Node 20+ locally, for the build
- `npx wrangler login` once, for Pages uploads (git-connected needs none)

## 1. Fill in the one file

```bash
cp deploy/production.env.example deploy/production.env
nano deploy/production.env      # domain, both card numbers, telegram, price, VPS IP
python deploy/configure.py
```

`configure.py` writes:

| File | What it gets |
|---|---|
| `webapp/public/config.js` | API URL, both cards, telegram, price |
| `server_vps/Caddyfile` | the API hostname to get a cert for |
| `deploy/vps-env.generated` | env lines to **merge** into the VPS (chmod 600) |

Both `deploy/production.env` and `deploy/vps-env.generated` are gitignored — they
hold your card numbers and freshly minted secrets.

## 2. Cloudflare DNS

| Type | Name | Value | Proxy |
|---|---|---|---|
| A | `api` | your VPS IP | **DNS only (grey cloud)** |
| CNAME | `@` | (created by Pages in step 5) | Proxied |

> **`api` must stay grey-clouded.** Behind the orange cloud, Caddy's HTTP-01
> challenge can't complete and TLS issuance fails. If you want it proxied later,
> switch Caddy to a Cloudflare Origin Certificate first.

## 3. Payload delivery (done: served from the VPS, not R2)

The web client's payload is **served from the VPS itself**, not from R2:

```
PAYLOAD_ORIGIN=file:///var/lib/carapk/payload
DOWNLOAD_HMAC_KEY=<64-char secret, already set>
DOWNLOAD_TTL=900
```

`/dl` streams from that directory only after checking the HMAC signature minted
by `/api/plan` for one approved session. The files are not web-reachable by any
other route, so there is no bucket to make private, no custom domain, and no WAF
rule to maintain. All eight APKs are uploaded and hash-verified against the pins.

This replaced the original R2 plan because it removes the public-bucket problem
outright rather than gating it, and needs no Cloudflare credentials. R2 remains a
valid alternative: set `PAYLOAD_ORIGIN` to a private origin plus `PAYLOAD_AUTH`
and the flow is unchanged.

### Still open: the desktop app is on the old path

`app/config.py` still points `APK_BASE_URL` at the public `pub-*.r2.dev` bucket.
Two consequences:

- the **FAW payload is still downloadable by anyone** with the URL, so the
  paywall sells convenience rather than access for that car
- the **MAGE payload was never uploaded there**, so the desktop app cannot
  provision a MAGE at all (`python verify_cloud.py` fails on df01/df02/df03)

The clean fix is to move the desktop app onto the same `/api/plan` + signed `/dl`
flow the web client uses; it already holds an activation token, so the change is
in `app/download.py`, not in the protocol. Uploading the MAGE files to the public
bucket would restore desktop MAGE installs but re-opens the hole for all three.

## 4. VPS: ship the CORS fix and the payload settings

The API currently sends **no CORS headers**, so a browser client fails every call
with `Load failed`. The desktop app never hit this because it isn't a browser.

> **Check the port before copying the Caddyfile.** On this VPS `8080` is already
> held by an unrelated `node` process, so the activation service listens on
> **8081**. Copying a Caddyfile that says `8080` would silently proxy every
> activation to that other service. Confirm they agree:
>
> ```bash
> ss -lntp | grep -E '8080|8081'                      # who owns what
> systemctl cat carapk-activation | grep ExecStart    # --port must match
> grep reverse_proxy /etc/caddy/Caddyfile
> ```

```bash
cd /opt/carapk/src && sudo git pull

sudo nano /etc/carapk/activation.env     # merge in deploy/vps-env.generated
# keep SIGNING_KEY_PKCS8 / TG_BOT_TOKEN / TG_CHAT_ID exactly as they are

sudo cp server_vps/Caddyfile /etc/caddy/Caddyfile
sudo caddy validate --config /etc/caddy/Caddyfile   # never reload a bad config
sudo systemctl reload caddy
sudo systemctl restart carapk-activation
```

Verify CORS is live (this is the check that proves the web client will work):

```bash
curl -s -i -X OPTIONS https://api.example.com/api/request \
  -H "Origin: https://example.com" \
  -H "Access-Control-Request-Method: POST" | grep -i access-control-allow-origin
```

Expect `access-control-allow-origin: https://example.com`. No header = the old
build is still running.

## 5. Build and publish the client

Pick one of the two Pages workflows. Both end at the same `dist/`.

### 5a. Git-connected (Pages builds from your repo)

Cloudflare Pages → Create → Connect to Git → pick the repo, then:

| Field | Value |
|---|---|
| Framework preset | `None` |
| Build command | `npm run build` |
| Build output directory | `dist` |
| Root directory (advanced) | `webapp` |

Root directory is the one people get wrong: the client lives in a subdirectory,
and the other two paths are relative to it.

Then set **Settings → Environment variables**. The build reads these and writes
`config.js`, so your card numbers live in Cloudflare rather than in git history:

| Variable | Example |
|---|---|
| `NODE_VERSION` | `20` |
| `CARAPK_API` | `https://api.example.com` |
| `CARAPK_CARD_1_BRAND` / `_NUMBER` / `_HOLDER` | `UZCARD` / `8600 …` / `YOUR NAME` |
| `CARAPK_CARD_2_BRAND` / `_NUMBER` / `_HOLDER` | `HUMO` / `9860 …` / `YOUR NAME` |
| `CARAPK_TELEGRAM` | `@your_handle` |
| `CARAPK_PRICE_TEXT` | `200 000 so'm` |

Without `CARAPK_API` the build keeps the committed placeholders and your live
site says `YOUR NAME`. That is the single most likely way to ship a broken
payment step, so set the variables before the first deploy.

### 5b. Direct upload (build locally, push the folder)

```bash
cd webapp
npm ci
npm run build          # bundles ya-webadb into dist/assets/transport-*.js
npm run preflight      # refuses to ship placeholder cards / http API
npx wrangler pages deploy dist --project-name carapk
```

Here `deploy/configure.py` has already written the real `config.js`, so no
environment variables are needed.

### Either way

Add `example.com` under Pages → Custom domains.

Run `npm run preflight` before trusting a build: `config.js` is public and
hand-editable, so it is exactly the file most likely to go live still saying
`YOUR NAME`.

## 6. Verify the live site

- [ ] `https://example.com` loads, cat animates, VIN accepts 17 characters
- [ ] **Request activation** returns a code (proves DNS + TLS + CORS)
- [ ] Telegram bot receives the request; approving flips the page to the install step
- [ ] **Connect** opens the Chrome WebUSB chooser (proves the ADB bundle shipped)
- [ ] `curl` on the payload host without the header returns 403
- [ ] `python verify_cloud.py` passes for all 7 APKs

---

## What is verified, and what is not

**Verified in this repo:** the production bundle builds and loads real ya-webadb
(`connectUsb` / `connectRelay` resolve at runtime); the request → await flow runs
end to end against a CORS-patched backend; the recipe guard
(`python check_recipe.py`) shows desktop and web recipes agree; preflight catches
every placeholder.

**Not verified — needs a car:** no ADB session has ever been driven from the
browser. `transport.js` was rewritten against the real ya-webadb 2.x API (the
previous version called three methods that do not exist and imported a package
that was never published), but the USB and relay paths have not touched hardware.
Budget one session with a MAGE on a USB cable before selling.

**Also outstanding:** the desktop `.exe` flow has never been replayed end to end
either (`CLAUDE.md` TODO), and `nip.io` stays in `app/config.py` until you point
the desktop app at the new API host too.
