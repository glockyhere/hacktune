# Activation backend on your VPS (API + Telegram bot)

Runs the activation API and the Telegram approval bot on your VPS. APKs stay on
Cloudflare R2. Same signed-token model as before, so the desktop app is unchanged
— only `ACTIVATION_API_URL` points at your VPS.

Assumes Ubuntu/Debian. Replace `api.yourdomain.com` with a subdomain you control.

## 1. DNS
Point an A record `api.yourdomain.com` → your VPS IP.

## 2. Packages
```bash
sudo apt update
sudo apt install -y python3-venv git
# Caddy (auto-HTTPS):
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy
```

## 3. App user + files
```bash
sudo useradd -r -s /usr/sbin/nologin carapk
sudo mkdir -p /opt/carapk /var/lib/carapk /etc/carapk
sudo git clone https://github.com/glockyhere/hacktune /opt/carapk/src
sudo python3 -m venv /opt/carapk/venv
sudo /opt/carapk/venv/bin/pip install -r /opt/carapk/src/server_vps/requirements.txt
sudo ln -s /opt/carapk/src/server_vps /opt/carapk/server_vps
sudo chown -R carapk:carapk /var/lib/carapk
```

## 4. Signing key + secrets
```bash
# on your workstation (from the repo):
python keygen/generate_activation_keys.py
#  -> ACTIVATION_PUBLIC_KEY  goes into app/config.py
#  -> ACTIVATION_PRIVATE_PKCS8 goes into the env file below
```
```bash
sudo cp /opt/carapk/src/server_vps/activation.env.example /etc/carapk/activation.env
sudo nano /etc/carapk/activation.env      # fill SIGNING_KEY_PKCS8, ADMIN_TOKEN, TG_*
sudo chown carapk:carapk /etc/carapk/activation.env
sudo chmod 600 /etc/carapk/activation.env
```

### Telegram bot
1. @BotFather → `/newbot` → copy the token → `TG_BOT_TOKEN`.
2. Message @userinfobot → copy your numeric id → `TG_CHAT_ID` (only you can approve).
No webhook needed — the service long-polls Telegram.

## 5. Service + HTTPS
```bash
sudo cp /opt/carapk/src/server_vps/carapk-activation.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now carapk-activation
# Caddy:
sudo cp /opt/carapk/src/server_vps/Caddyfile /etc/caddy/Caddyfile
sudo nano /etc/caddy/Caddyfile          # set api.yourdomain.com
sudo systemctl reload caddy
```
Run **one** uvicorn worker (the unit does) — a single process owns the bot poller
and the SQLite db.

## 6. Wire the app
`app/config.py`:
```python
ACTIVATION_API_URL    = "https://api.yourdomain.com"
ACTIVATION_PUBLIC_KEY = "<public key from step 4>"
```

## 7. Test
```bash
curl https://api.yourdomain.com/healthz            # {"ok":true}
```
Then in the program: enter a VIN + make/model → Request → you get a Telegram
message → tap ✅ Approve → the program unlocks and installs. Single-use is enforced
server-side; a second install needs a new approved request.

## Ops notes
- Secrets live only in `/etc/carapk/activation.env` (chmod 600). If the box is
  breached, rotate: regenerate the keypair, update the app's public key, redeploy.
- Back up `/var/lib/carapk/activations.db` if you want request history.
- Update: `cd /opt/carapk/src && sudo git pull && sudo systemctl restart carapk-activation`.
- Logs: `journalctl -u carapk-activation -f`.
