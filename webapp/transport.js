// Transport layer — how the page reaches the head unit's ADB.
//
// Two backends, both feeding the SAME ADB protocol implementation from
// ya-webadb (https://github.com/yume-chan/ya-webadb, MIT):
//
//   connectUsb()    Dongfeng MAGE — USB cable, straight from Chrome. No app to
//                   install. Chromium only (WebUSB).
//   connectRelay()  FAW B70 — wireless. Browsers cannot open a raw TCP socket
//                   to the unit's :5555, so a tiny local agent (agent/relay.py)
//                   bridges a WebSocket to that TCP port. ya-webadb speaks the
//                   same ADB packet stream over it as it would over USB.
//
// Both expose the same small surface the executor needs: shell(), install(),
// getprop/setprop helpers, and close(). Nothing product-specific lives here —
// this file is a generic ADB pipe.
//
// This module uses bare specifiers and therefore ONLY works through the Vite
// build (`npm run build`). app.js imports it lazily so that a missing bundle
// degrades to "Connect doesn't work" instead of a blank page.
import {
  Adb,
  AdbDaemonTransport,
  AdbPacket,
  AdbPacketSerializeStream,
} from "@yume-chan/adb";
import AdbWebCredentialStore from "@yume-chan/adb-credential-web";
import { AdbDaemonWebUsbDeviceManager } from "@yume-chan/adb-daemon-webusb";
import {
  PushReadableStream,
  StructDeserializeStream,
  WritableStream,
} from "@yume-chan/stream-extra";

// The RSA keypair the unit remembers as "this computer". Persisted by the
// library in IndexedDB, so an operator authorises the same browser once.
const CRED = new AdbWebCredentialStore("CarAppInstaller");

// One ADB device, wrapped so the executor never touches ya-webadb directly.
class AdbBackend {
  constructor(adb) { this.adb = adb; }

  // Run a shell command to completion. The none-protocol shell multiplexes
  // stderr into stdout and reports no exit code, so callers verify by reading
  // the output — which is what `adb shell` users do anyway.
  async shell(command) {
    const stdout = await this.adb.subprocess.noneProtocol.spawnWaitText(command);
    return { stdout, stderr: "", exitCode: 0 };
  }

  async getprop(key) {
    return (await this.shell(`getprop ${key}`)).stdout.trim();
  }

  async setprop(key, value) {
    await this.shell(`setprop ${key} ${value}`);
    return (await this.getprop(key)) === String(value);
  }

  // Push an APK to a temp path and install it. `bytes` is an ArrayBuffer or
  // Uint8Array already verified against its pinned SHA-256 by the caller.
  async install(bytes, flags) {
    const remote = `/data/local/tmp/carapk_${Date.now()}.apk`;
    const sync = await this.adb.sync();
    try {
      await sync.write({
        filename: remote,
        file: singleChunkStream(new Uint8Array(bytes)),
        permission: 0o644,
      });
    } finally {
      await sync.dispose();
    }
    const flagStr = (flags || []).join(" ");
    const out = (await this.shell(`pm install ${flagStr} ${remote}`)).stdout;
    await this.shell(`rm -f ${remote}`);
    return { ok: /Success/.test(out), output: out.trim() };
  }

  async close() { try { await this.adb.close(); } catch { /* already gone */ } }
}

// --- USB (Dongfeng MAGE) ---------------------------------------------------
export async function connectUsb() {
  const mgr = AdbDaemonWebUsbDeviceManager.BROWSER;
  if (!mgr) throw new Error("This browser has no WebUSB. Use Chrome or Edge on desktop.");
  const device = await mgr.requestDevice();          // shows the chooser
  if (!device) throw new Error("No device selected.");
  const connection = await device.connect();
  const transport = await AdbDaemonTransport.authenticate({
    serial: device.serial, connection, credentialStore: CRED,
  });
  return new AdbBackend(new Adb(transport));
}

// --- Wireless via the local relay (FAW B70) --------------------------------
export async function connectRelay(wsUrl, sessionToken) {
  // The agent requires a per-session token so a random web page cannot drive
  // the operator's car over the localhost socket.
  const url = `${wsUrl}?token=${encodeURIComponent(sessionToken)}`;
  const connection = await webSocketConnection(url);
  const transport = await AdbDaemonTransport.authenticate({
    serial: "relay", connection, credentialStore: CRED,
  });
  return new AdbBackend(new Adb(transport));
}

// Build the duplex ya-webadb wants — ReadableWritablePair<AdbPacketData,
// Consumable<AdbPacketInit>> — on top of a binary WebSocket carrying the raw
// ADB packet stream. There is no published ya-webadb WebSocket daemon package,
// so the framing is done here with the library's own packet codecs.
async function webSocketConnection(url) {
  const ws = new WebSocket(url);
  ws.binaryType = "arraybuffer";

  await new Promise((resolve, reject) => {
    ws.addEventListener("open", resolve, { once: true });
    ws.addEventListener("error", () => reject(
      new Error("Can't reach the local relay. Is agent/relay.py running?")), { once: true });
  });

  // device -> page: raw bytes, deserialised into ADB packets
  const readable = new PushReadableStream(async (controller) => {
    await new Promise((resolve, reject) => {
      ws.addEventListener("message", (e) => {
        // enqueue() applies backpressure; a rejection means the stream is gone
        Promise.resolve(controller.enqueue(new Uint8Array(e.data))).catch(reject);
      });
      ws.addEventListener("close", () => resolve(), { once: true });
      ws.addEventListener("error", () => reject(new Error("relay socket error")), { once: true });
    });
  }).pipeThrough(new StructDeserializeStream(AdbPacket));

  // page -> device: ADB packets, serialised back to bytes
  const serializer = new AdbPacketSerializeStream();
  serializer.readable
    .pipeTo(new WritableStream({
      write(chunk) { chunk.tryConsume((value) => ws.send(value)); },
      close() { try { ws.close(); } catch { /* already closed */ } },
      abort() { try { ws.close(); } catch { /* already closed */ } },
    }))
    .catch(() => { /* socket closed under us; transport surfaces the error */ });

  return { readable, writable: serializer.writable };
}

// --- helpers ---------------------------------------------------------------
function singleChunkStream(u8) {
  return new ReadableStream({
    start(c) { c.enqueue(u8); c.close(); },
  });
}
