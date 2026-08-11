# Activation backend (per-install, pay → you approve)

One paid, **manually approved** request = one install. The decision and the
single-use rule live on a Cloudflare Worker you control; the program can only
*verify* a signed token, never mint or self-approve.

```
buyer enters VIN+make+model ─▶ POST /api/request ─▶ Worker stores "pending"
                                                      └─▶ pings you (Telegram / admin page)
you review payment, tap Approve ─▶ Worker signs a ONE-TIME token (Ed25519)
program polls /api/status ─▶ gets token ONCE ─▶ verifies (machine+VIN) ─▶ installs
```

## One-time deploy

Needs Node.js. All commands run in `server/`.

```bash
cd server
npm i -g wrangler            # or use: npx wrangler ...

# 1) create the KV store, paste the printed id into wrangler.toml (ACTIVATIONS id)
npx wrangler kv namespace create ACTIVATIONS

# 2) make the signing keypair (from repo root)
python ../keygen/generate_activation_keys.py
#    -> paste ACTIVATION_PUBLIC_KEY into app/config.py
#    -> keep ACTIVATION_PRIVATE_PKCS8 for the next step

# 3) set secrets
npx wrangler secret put SIGNING_KEY_PKCS8     # paste ACTIVATION_PRIVATE_PKCS8
npx wrangler secret put ADMIN_TOKEN           # a long random password (admin page)

# 4) deploy
npx wrangler deploy
#    -> prints https://carapk-activation.<you>.workers.dev
```

Then in `app/config.py`:
```python
ACTIVATION_API_URL    = "https://carapk-activation.<you>.workers.dev"
ACTIVATION_PUBLIC_KEY = "<the public key from step 2>"
```

## Approving requests

**Admin page (always available):** open `…workers.dev/admin`, paste your
`ADMIN_TOKEN`. Pending requests (code, VIN, make/model, machine id) list live with
**Approve / Reject** buttons.

**Telegram (optional, approve from your phone):**
```bash
# create a bot with @BotFather, get its token; get your numeric chat id (@userinfobot)
npx wrangler secret put TG_BOT_TOKEN          # the bot token
# set TG_CHAT_ID in wrangler.toml [vars], then redeploy:
npx wrangler deploy
# point Telegram at the worker:
#   https://api.telegram.org/bot<TG_BOT_TOKEN>/setWebhook?url=https://<worker>/tg
```
Each new request now arrives as a message with **✅ Approve / ❌ Reject** buttons.

## Security properties
- **No self-service:** approval is a server decision, gated by your `ADMIN_TOKEN`
  (or your Telegram chat id). Buyers cannot approve themselves.
- **Single-use:** the token is delivered exactly once and bound to that request;
  installing again needs a new paid, approved request.
- **Bound to car + machine:** the token carries the VIN + Machine ID and is
  Ed25519-signed; the app rejects it on any other machine or a different VIN.
- **Unforgeable:** the private key exists only as a Worker secret; the app ships
  only the public key.
- A determined person could still patch the *program* to skip the call — but the
  server never issues a real token, so nothing legitimate is unlocked. This is far
  stronger than the offline model.

## Data note
Requests store VIN + make/model + a machine fingerprint in your KV for 14 days
(auto-expire). VIN is a vehicle identifier — handle it as customer data.
