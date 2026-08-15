# The relay — and what to hand a buyer

Only buyers with a **FAW B70** need this. The **Dongfeng MAGE** connects over a
USB cable straight from Chrome and needs nothing installed.

## Why it exists at all

A browser cannot open a raw TCP socket. The B70 is reached over Wi-Fi on ADB's
port 5555, so the page has no way to talk to it on its own — no amount of web
API will change that, it is the rule that stops any site port-scanning your home
network. The relay is a small local bridge: WebSocket in, TCP out.

Having `adb` installed does not remove the need for it. adb speaks raw TCP too,
which is exactly what the browser cannot do.

## Build it (you, once, on Windows)

```bat
agent\build_relay.bat
```

Produces `dist\AxolotlRelay.exe` — one file, no Python required on the buyer's
machine. PyInstaller cannot cross-compile, so this has to run on Windows.

## What the buyer does

1. Download `AxolotlRelay.exe`
2. Double-click it
3. Leave the window open
4. Go back to the website and press **Connect**

No arguments, no install, no configuration. On start it finds the car itself:
first by asking `adb` if that happens to be installed, otherwise by sweeping the
local network for an open ADB port. It reports what it found in plain language
and looks again each time Connect is pressed, which matters because the B70's
IP address changes between sessions.

## Two things to warn buyers about

**SmartScreen.** The exe is unsigned, so Windows shows "Windows protected your
PC" on first run. They must click *More info* → *Run anyway*. This is the single
biggest drop-off point for a nervous buyer who has just paid you. A code-signing
certificate (about $100/year from Sectigo, DigiCert and others) removes the
warning; worth it once volume justifies it.

**Same network.** The car and the computer must be on the same Wi-Fi, and
Wireless ADB must be enabled on the unit. The relay says so if it cannot find
anything, rather than failing silently.

## Security

Unchanged from the developer version, and worth keeping that way:

- binds `127.0.0.1` only, so nothing off the machine can reach it (this also
  avoids a Windows Firewall prompt)
- refuses to bridge until the backend confirms the buyer's one-time activation
  token, so a random page they visit cannot drive their car over localhost
- carries bytes only: no recipe, no payload, no signing key

Verified: a connection with no token, and one with a forged token, are both
closed with `4001 unauthorized` before any socket to the car is opened.
