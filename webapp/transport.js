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

// A link that has gone silent this long is treated as gone. ADB is strictly
// request/response — a healthy push never stops moving bytes for anywhere near
// this long — so silence means the car left the network, not that it is busy.
const IDLE_LIMIT_MS = 30_000;

// Liveness for one connection. Without this a dropped Wi-Fi link leaves every
// subsequent ADB call awaiting a reply that can never arrive: the UI freezes
// mid-install with no error, which is strictly worse than failing.
function makeLink() {
  const waiters = new Set();
  return {
    dead: false,
    reason: "",
    kill(reason) {
      if (this.dead) return;
      this.dead = true;
      this.reason = reason;
      for (const w of waiters) w(new Error(reason));
      waiters.clear();
    },
    // Register a rejector for the duration of one operation.
    watch(reject) {
      if (this.dead) { reject(new Error(this.reason)); return () => {}; }
      waiters.add(reject);
      return () => waiters.delete(reject);
    },
  };
}

// One ADB device, wrapped so the executor never touches ya-webadb directly.
class AdbBackend {
  // `link` is null for USB, where the browser itself surfaces a yanked cable.
  constructor(adb, link) { this.adb = adb; this.link = link || null; }

  get dead() { return !!this.link?.dead; }

  // Every call races the operation against the link dying, so a vanished car
  // produces a message the buyer can act on instead of an endless spinner.
  async run(fn) {
    if (this.link?.dead) throw new Error(this.link.reason);
    if (!this.link) return fn();
    let release;
    const died = new Promise((_, reject) => { release = this.link.watch(reject); });
    try { return await Promise.race([fn(), died]); }
    finally { release(); }
  }

  // Run a shell command to completion. The none-protocol shell multiplexes
  // stderr into stdout and reports no exit code, so callers verify by reading
  // the output — which is what `adb shell` users do anyway.
  async shell(command) {
    const stdout = await this.run(() =>
      this.adb.subprocess.noneProtocol.spawnWaitText(command));
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
    await this.run(async () => {
      const sync = await this.adb.sync();
      try {
        await sync.write({
          filename: remote,
          file: singleChunkStream(new Uint8Array(bytes)),
          permission: 0o644,
        });
      } finally {
        try { await sync.dispose(); } catch { /* link already gone */ }
      }
    });
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
  const { connection, link } = await webSocketConnection(url);
  const transport = await AdbDaemonTransport.authenticate({
    serial: "relay", connection, credentialStore: CRED,
  });
  return new AdbBackend(new Adb(transport), link);
}

// The relay closes with its own codes when it knows exactly what went wrong.
// Translating them here is the difference between "ExactReadable ended" and a
// sentence the buyer can act on.
function describeClose(code, reason) {
  switch (code) {
    case 1000: case 1005:
      return "The helper closed the connection. Restart it and press Connect.";
    case 4001:
      return "The helper did not accept this activation. Close it, reopen it, "
        + "and press Connect again.";
    case 4004:
      return "The helper could not find the car. Check that Wireless ADB is on "
        + "and that the car and this computer are on the same Wi-Fi.";
    case 4005:
      return "The helper lost the car — its Wi-Fi address may have changed. "
        + "Press Connect again.";
    case 1006:
      return "The connection to the car dropped. Check the car is awake and "
        + "still on Wi-Fi, then press Connect again.";
    default:
      return `The connection to the car closed unexpectedly (code ${code}`
        + `${reason ? ": " + reason : ""}). Press Connect again.`;
  }
}

// Build the duplex ya-webadb wants — ReadableWritablePair<AdbPacketData,
// Consumable<AdbPacketInit>> — on top of a binary WebSocket carrying the raw
// ADB packet stream. There is no published ya-webadb WebSocket daemon package,
// so the framing is done here with the library's own packet codecs.
export async function webSocketConnection(url) {
  const ws = new WebSocket(url);
  ws.binaryType = "arraybuffer";
  const link = makeLink();

  await new Promise((resolve, reject) => {
    ws.addEventListener("open", resolve, { once: true });
    ws.addEventListener("error", () => reject(
      new Error("Can't reach the helper. Open it and leave its window running, "
        + "then press Connect.")), { once: true });
  });

  // Silence, not just a close event, ends a link: a car that walks out of Wi-Fi
  // range leaves the socket open on this side for minutes.
  let idle;
  const beat = () => {
    clearTimeout(idle);
    if (link.dead) return;
    idle = setTimeout(() => die(
      "The car stopped responding. Check it is awake and on Wi-Fi, "
      + "then press Connect again."), IDLE_LIMIT_MS);
  };

  const gone = () => link.reason
    || "The connection to the car closed. Press Connect again.";

  // One teardown for the whole link. Failing writes one at a time leaves the
  // pipe alive and produces a second, unowned rejection per packet still in
  // flight; aborting the pump errors the serializer once, and every later write
  // then rejects through the normal streams path.
  const pump = new AbortController();
  const die = (why) => {
    clearTimeout(idle);
    link.kill(why);
    pump.abort(new Error(why));
  };

  let closingOurselves = false;
  const shut = () => {
    closingOurselves = true;
    clearTimeout(idle);
    try { ws.close(); } catch { /* already closed */ }
  };

  // device -> page: raw bytes, deserialised into ADB packets
  const readable = new PushReadableStream((controller) => new Promise((resolve, reject) => {
    ws.addEventListener("message", (e) => {
      beat();
      // enqueue() is serialised internally, so ordering holds without awaiting;
      // a rejection means the stream is gone
      Promise.resolve(controller.enqueue(new Uint8Array(e.data))).catch(reject);
    });
    ws.addEventListener("close", (e) => {
      clearTimeout(idle);
      if (closingOurselves) { resolve(); return; }
      // Ending the stream cleanly here is what produced the opaque
      // "ExactReadable ended": every pending ADB read simply saw end-of-stream.
      // An unexpected close is an error, and it carries a reason.
      const why = describeClose(e.code, e.reason);
      die(why);
      reject(new Error(why));
    }, { once: true });
    ws.addEventListener("error", () => {
      const why = "The connection to the car failed. Press Connect again.";
      die(why);
      reject(new Error(why));
    }, { once: true });
  })).pipeThrough(new StructDeserializeStream(AdbPacket));

  // page -> device: ADB packets, serialised back to bytes
  const serializer = new AdbPacketSerializeStream();
  serializer.readable
    .pipeTo(new WritableStream({
      write(chunk) {
        // Reporting the failure is load-bearing. Silently dropping it made a
        // send onto a closed socket look like a SUCCESSFUL write, so the packet
        // vanished and every later ADB call waited forever for a reply to
        // something the car never received: an install frozen mid-progress.
        //
        // `chunk.error()` is the channel the ADB writer awaits, so calling
        // `consume()` on a failure would report success and hang the caller
        // exactly as the old code did.
        if (ws.readyState !== WebSocket.OPEN) {
          chunk.error(new Error(gone()));
          return;
        }
        chunk.tryConsume((value) => {
          try { ws.send(value); beat(); }
          catch { chunk.error(new Error(gone())); }
        });
      },
      close: shut,
      abort: shut,
    }), { signal: pump.signal })
    .catch((e) => die(e?.message
      || "The connection to the car closed. Press Connect again."));

  beat();
  return { connection: { readable, writable: serializer.writable }, link };
}

// --- helpers ---------------------------------------------------------------
function singleChunkStream(u8) {
  return new ReadableStream({
    start(c) { c.enqueue(u8); c.close(); },
  });
}
