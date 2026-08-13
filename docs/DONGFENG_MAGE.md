# Dongfeng Aeolus MAGE — how this unit is provisioned

Everything here was found and verified on a real MAGE on 2026-08-13. It is a
completely different lock from the FAW B70; nothing about the FAW flow applies.

> **The MAGE is always provisioned over a USB cable — never wireless.** That is
> what the installer targets, and it is how everything below was verified. (The
> FAW B70 is the opposite: always Wireless ADB.)

| | |
|---|---|
| `ro.product.model` | `DongfengAeolus` |
| `ro.product.device` | `spm8675p1_64_raite` |
| Android | 11 (API 30) |
| Build | **userdebug**, `ro.secure=0`, `ro.debuggable=1`, adbd already root |
| Display | 1440×1920 @ 160 dpi (**mdpi — 1 dp = 1 px**) |
| Launcher | `com.dftc.launcher` (`/system/app/DFLauncher_release/`) |

## 1. The install lock

Any `adb install` of a non-Dongfeng APK fails with:

```
INSTALL_FAILED_INTERNAL_ERROR: java.lang.SecurityException:
DF APK cert incorrect: DF APK cert incorrect
```

The OEM PackageManager checks every APK against Dongfeng's certificate. It is
gated by a persistent system property:

```
persist.apk.sign.verify = 1
```

Because the unit ships userdebug with root adb, we clear it rather than sign
anything:

```bash
adb root
adb shell setprop persist.apk.sign.verify 0
```

Installs then succeed with any signature. `persist.*` survives reboots, so this
is done once. **Note:** this leaves the unit's signature check off. A Dongfeng
OTA may restore the property and could remove unsigned apps.

### Getting root

`adb root` **restarts adbd**. Over the MAGE's USB cable the transport simply
re-enumerates, so this is cheap — but `profiles._df_ensure_root` still:

1. checks `id -u` first and **skips `adb root` when adbd is already root**,
   which it is on these units, so the usual path does not disturb the transport
2. waits for the device to come back via `engine.reconnect()` if it did restart
3. re-checks `id -u` and aborts *before* any install if root was not obtained

Step 3 is the one that matters: on a production (non-userdebug) unit there is no
root, `setprop` silently does nothing, and every install would otherwise fail
with `DF APK cert incorrect` one after another. Failing once, up front, with an
explanation is better.

`engine.reconnect()` also handles network transports (`adb connect ip:port`, or
re-resolving an Android 11 `adb-…._adb-tls-connect._tcp` mDNS name). That path
is not used by the MAGE (it is USB) — it exists for the wireless FAW B70 and to
keep this step robust if a MAGE is ever reached over the network.

> This is why the MAGE payload is *not* platform-signed the way the FAW payload
> is. There is no key to sign with — the check is switched off instead.

## 2. The menu lock

Installing is not enough: the apps stay invisible. `com.dftc.launcher` does not
enumerate installed packages — it renders a fixed list read from SQLite:

```
/data/user_de/0/com.dftc.launcher/databases/launcher.db      (note: user_de)
table allApp (id, appName, pkgName, iconName, position)
```

Both apps declare proper `MAIN`/`LAUNCHER` activities, so a stock launcher would
show them; this one simply never looks. Adding a row makes the tile appear:

```sql
insert into allApp (appName,pkgName,iconName,position)
values ('FreeTube','freetube.com','',8);
```

Reading the decompiled launcher confirms there is no whitelist blocking
third-party packages — `MyAppAdapter.removeListFromConfig` only drops the DAB
radio entry when the car lacks DAB, and taps go through the generic
`getLaunchIntentForPackage`.

### Reloading without breaking the unit

`AppListLoader` registers a `ContentObserver` on the global setting
`show_launcher_test_app_key`, so pulsing it reloads the table in place:

```bash
adb shell settings put global show_launcher_test_app_key 1
adb shell settings put global show_launcher_test_app_key 0
```

**Do not `am force-stop com.dftc.launcher` to reload it.** Doing so leaves
duplicate launcher tasks behind, and SystemUI's `CarStatusBar` keeps its own
flag for whether the all-apps screen is showing. It desyncs, and the hardware
app-menu button goes dead — the tap still registers
(`CarStatusBar: onClick: btn_all_app` appears in logcat) but nothing opens. The
recovery is:

```bash
adb shell pkill -f com.android.systemui      # respawns itself
```

An ignition off/on clears it too. `provision.py` uses the settings pulse and
never force-stops, specifically to avoid this.

That same key doubles as a debug mode — `AppTestUtils` defines
`0 = curated list`, `1 = DV test apps`, `2 = all installed apps`. Mode 2 dumps
every system service into the grid; it is not what we want, which is why the
pulse ends at 0.

## 3. Icons

The launcher does not mask icons, and it renders them in a 200×200 px slot. An
app shipping a legacy square `ic_launcher.png` therefore towers over the OEM
tiles. The rounding on OEM icons is baked into the artwork, not applied by code.

Spec measured from the launcher's own mipmaps (mdpi, 1:1 with the display):

```
canvas 200x200 · tile 120x120 centred (40px inset) · corner radius 25 · soft shadow
```

`AppInfoEntity.getAppIcon()` decides where the icon comes from:

- `iconName` empty → `PackageManager.getApplicationIcon()` (the app's own icon)
- `iconName` set   → that **mipmap inside the launcher's own package**

So there are two ways to get a native-looking tile:

**a) Restyle the app's own icon** — `tools/restyle_icon.py` composites the real
artwork into the tile spec, lifting the shadow from a genuine OEM asset so it
matches exactly. The APK must then be re-signed. Used for FreeTube.

```bash
python tools/restyle_icon.py --apk ft.apk --out ft_styled.apk \
    --icon-path 'res/mipmap-{d}-v4/ic_launcher.png' \
    --launcher DFLauncher_release.apk
zipalign -f -p 4 ft_styled.apk ft_aligned.apk
apksigner sign --ks your.jks --out df01_freetube.apk ft_aligned.apk
```

Find the real icon path with `aapt2 dump badging <apk> | grep "^application:"`
— it is **not** always `ic_launcher`. Yandex's is `res/drawable-{d}-v4/icon.png`,
and its `mipmap/ic_launcher.png` is a leftover green Android robot.

**b) Point `iconName` at an existing OEM mipmap.** The launcher ships 27
`icon_allapp_*` tiles and several are unused. Zero risk, no APK touched, and
native by construction.

### Yandex Navi cannot be restyled

Re-signing `ru.yandex.yandexnavi` makes it crash on launch, in a loop:

```
java.lang.IllegalStateException: Internal error, application signature mismatch
    at com.yandex.passport.internal.ag.b(SourceFile:8115)
```

Its Passport module verifies its own signature. The MAGE payload therefore ships
the **pristine** Yandex APK and uses route (b) — `icon_allapp_navi`, an unused
navigation tile already in the launcher. Verified to survive a launcher and
SystemUI restart.

> The FAW payload's `04_yandexnavi.apk` *is* re-signed and patched to defeat this
> check. Reusing it on the MAGE would allow route (a) and get the real yellow
> arrow at native size — **untested on a MAGE**; the car went offline before it
> could be tried. If you test it, install `04_yandexnavi.apk`, launch it, and
> check `adb logcat -b crash` for `signature mismatch` before switching
> `DF_MENU_ROWS`.

### A caching trap

The launcher holds a cached icon per package. After reinstalling an app with a
different icon, the grid can keep showing the **old** one — or keep showing a
*new* one after you have reverted the APK. Always confirm an icon change with a
launcher restart (plus the SystemUI restart above) before believing it.

## 4. What the installer does, end to end

`app/profiles.py` → `dongfeng_mage`:

1. `prepare` — `adb root`, clear `persist.apk.sign.verify`, verify it read back 0
2. install `df01_freetube.apk` (restyled icon, re-signed)
3. install `df02_yandexnavi.apk` (pristine, original signature) + grant perms
4. `finish` — delete any old rows for those packages, append fresh rows to
   `allApp` at `max(position)+1`, pulse `show_launcher_test_app_key`

Step 4 is idempotent: re-running the installer will not create duplicate tiles.

## Verified on the unit

- both APKs install once the property is cleared
- both tiles appear in the menu and launch
  (`ru.yandex.yandexnavi/.core.NavigatorActivity`, FreeTube's `MainActivity`)
- both tiles measure **120 px**, identical to the OEM reference, and survive a
  launcher + SystemUI restart
- Yandex runs with zero crashes on its original signature

The verification above was over USB — which is exactly the field setup for this
car, so there is no separate transport to re-check. Not yet verified: the whole
flow driven **through the built exe** (only by hand so far).

## Gotchas

- Yandex showed `No Network Location Provider is installed` and drew a blank map
  with no network. It needs Wi-Fi; confirm a GNSS fix outdoors.
- The unit pops a seat-position dialog ("Сохранить текущий расход?") on some
  launcher restarts. It is a vehicle setting — dismiss with Back, do not answer
  it programmatically.
