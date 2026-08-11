# Hosting the payload (cloud)

The program does **not** bundle these APKs. It downloads them from
`config.APK_BASE_URL` every run and checks each file's SHA-256 against the value
pinned in `app/provision.py`.

## Steps
1. Upload the five files in this folder to any static host, keeping the exact
   filenames:
   ```
   01_backbutton.apk
   02_freetube.apk
   03_wifishortcut.apk
   04_yandexnavi.apk
   05_launcher.apk
   ```
2. Put the folder URL (with trailing slash) in `app/config.py`:
   ```python
   APK_BASE_URL = "https://<your-host>/carapk/"
   ```
   The program will request `APK_BASE_URL + <filename>`.
3. The host must return the raw bytes over HTTPS (object storage, a static
   bucket, a file host with direct links, etc.). No auth, or a URL that already
   includes any access token.

## Pinned hashes (must match the uploaded files)
```
309d21cc25541f6897263e9dcfe6e13c60006e8de9493b71ee6dd0cbce59302a  01_backbutton.apk
9855866cb3958b44eefba7da712d155e51c0a6d77ba3ae722eb53a60ef5330db  02_freetube.apk
5d5bd806e98cc36b5273ecbe6928a9baa77aef31c2c86968f62471c580bf4eb4  03_wifishortcut.apk
225485fdc99670cd67bb6d5c996a37b79a9e10a2827b12bfaef197be7c92586a  04_yandexnavi.apk
2af15edfb65024acbc7f09323a1c97a1d9af3035d503fd9cc83e34eda5ed1246  05_launcher.apk
```
If you ever rebuild an APK, recompute its hash (`shasum -a 256 <file>`) and update
the matching `sha256` in `app/provision.py`, then rebuild the exe.

> These are modified third-party binaries. Hosting/distributing them is your
> decision and your legal responsibility — see the note in the top-level README.
