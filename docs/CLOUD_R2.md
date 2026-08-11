# Hosting the payload on Cloudflare R2

R2 gives you 10 GB free, **no egress/bandwidth fees**, and stable direct HTTPS
links you control. The program downloads `APK_BASE_URL + <filename>` each run and
verifies each file's pinned SHA-256.

## 1. Create the bucket
1. Sign in at <https://dash.cloudflare.com> → **R2** (add a payment card once to
   activate R2 even on the free tier; you won't be charged within free limits).
2. **Create bucket** → name it e.g. `carapk` → Create.

## 2. Upload the five files
Drag these from `CarApkInstaller/payload/` into the bucket (Objects → Upload).
Keep the **exact** names, at the bucket **root** (no folder):

```
01_backbutton.apk
02_freetube.apk
03_wifishortcut.apk
04_yandexnavi.apk   (~101 MB — the big one)
05_launcher.apk
```

## 3. Make it publicly downloadable
Bucket → **Settings** → **Public access**:
- **Quick:** enable the **r2.dev** public URL. You get a base like
  `https://pub-abcdef0123456789.r2.dev/` — files are then at
  `https://pub-….r2.dev/01_backbutton.apk`.
- **Production:** connect a **custom domain** (e.g. `dl.yourdomain.com`) instead;
  base becomes `https://dl.yourdomain.com/`. (r2.dev is rate-limited and meant for
  testing/light use.)

Your **APK_BASE_URL** is that base, **with a trailing slash**.

## 4. Wire it up
Put the base URL in `app/config.py`:
```python
APK_BASE_URL = "https://pub-….r2.dev/"
```
Then verify hosting works (downloads every file, checks hashes):
```bash
python verify_cloud.py
```
A green run means buyers' installs will work.

## Optional: upload from the command line (rclone)
If you'd rather script uploads/re-uploads:
1. R2 → **Manage R2 API Tokens** → create a token (Object Read & Write) → note the
   Access Key ID + Secret + your account ID.
2. `rclone config` → new remote, type **S3**, provider **Cloudflare**, endpoint
   `https://<accountid>.r2.cloudflarestorage.com`, and the keys above.
3. Upload:
   ```bash
   rclone copy CarApkInstaller/payload/ r2:carapk/ --include "*.apk" -P
   ```

> These are modified third-party binaries; hosting/distributing them is your
> decision and responsibility (see the top-level README).
