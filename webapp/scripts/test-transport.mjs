// Regression test for the transport bug that froze a real install at 7%.
//
// A write onto a closed WebSocket used to look like a SUCCESSFUL write, because
// the promise from `chunk.tryConsume(...)` was dropped. The packet vanished and
// every later ADB call waited forever for a reply the car never received. The
// browser's only symptom was the phase counter stopping.
//
// Requires the fake relay and Node's WebSocket:
//     python webapp/scripts/fake-relay.py 8799 &
//     node --experimental-websocket webapp/scripts/test-transport.mjs
import { webSocketConnection } from "../transport.js";
import { Consumable } from "@yume-chan/stream-extra";

const BASE = "ws://127.0.0.1:8799";
const DEADLINE = 5000;                   // a hang is the bug; never wait it out
let failures = 0;

function check(name, ok, detail) {
  console.log(`${ok ? "  ok  " : "FAIL  "}${name}${detail ? " — " + detail : ""}`);
  if (!ok) failures++;
}

// The whole point: an operation must SETTLE. Never resolve on timeout.
function within(ms, promise) {
  return Promise.race([
    promise,
    new Promise((_, reject) =>
      setTimeout(() => reject(new Error("HUNG: never settled")), ms)),
  ]);
}

// The serializer's writable takes Consumable-wrapped chunks, same as the
// real AdbPacketDispatcher does via Consumable.WritableStream.write.
const send = (writer, value) => Consumable.WritableStream.write(writer, value);

const packet = (payload) => ({
  command: 0x45545257, arg0: 1, arg1: 1,
  payload: new Uint8Array(payload), checksum: 0, magic: 0x45545257 ^ 0xffffffff,
});

async function writesRejectAfterDrop() {
  const { connection, link } = await webSocketConnection(`${BASE}/drop-after/1`);
  const w = connection.writable.getWriter();
  await send(w, packet(64));                       // this one lands, then drop
  await new Promise((r) => setTimeout(r, 400));    // let the close land

  let settled = "hung";
  try { await within(DEADLINE, send(w, packet(64))); settled = "resolved"; }
  catch (e) { settled = e.message.startsWith("HUNG") ? "hung" : "rejected"; }

  check("write after a dropped socket rejects", settled === "rejected",
    settled === "hung" ? "froze — this is the 7% bug" : `write ${settled}`);
  check("link is marked dead", link.dead === true);
  check("death reason is actionable", /press Connect again/i.test(link.reason),
    JSON.stringify(link.reason));
}

async function readsRejectAfterDrop() {
  const { connection, link } = await webSocketConnection(`${BASE}/drop-after/1`);
  const r = connection.readable.getReader();
  const w = connection.writable.getWriter();
  // The drop can land between the packet header and its payload, so this
  // write may itself fail. That is the case under test, not an error here.
  await send(w, packet(64)).catch(() => {});

  let settled = "hung";
  try {
    const { done } = await within(DEADLINE, r.read());
    settled = done ? "ended" : "got-data";
  } catch (e) {
    settled = e.message.startsWith("HUNG") ? "hung" : "rejected";
  }
  // ya-webadb's BufferedTransformStream.abort() closes its buffer instead of
  // erroring it, so an upstream error is FLATTENED into a clean end and the
  // reason is destroyed. That is the whole story behind the field report of a
  // bare "ExactReadable ended". We cannot fix it from this side, so the link's
  // own death reason — not the stream — is what must carry the explanation.
  check("read settles rather than hanging", settled !== "hung", `read ${settled}`);
  check("the reason survives on the link, since the stream drops it",
    /press Connect again/i.test(link.reason || ""), JSON.stringify(link.reason));
}

async function relayCodesAreTranslated() {
  for (const [code, expect] of [[4004, /could not find the car/i],
                                [4005, /address may have changed/i],
                                [4001, /did not accept this activation/i]]) {
    const { link } = await webSocketConnection(`${BASE}/close/${code}`);
    await new Promise((r) => setTimeout(r, 500));
    check(`close ${code} explains itself`, expect.test(link.reason || ""),
      JSON.stringify(link.reason));
  }
}

async function healthyLinkStaysAlive() {
  const { connection, link } = await webSocketConnection(`${BASE}/echo`);
  const w = connection.writable.getWriter();
  for (let i = 0; i < 5; i++) await within(DEADLINE, send(w, packet(1024)));
  check("a healthy link is not killed", link.dead === false, link.reason);
}

for (const t of [writesRejectAfterDrop, readsRejectAfterDrop,
                 relayCodesAreTranslated, healthyLinkStaysAlive]) {
  console.log(`\n${t.name}`);
  try { await t(); }
  catch (e) { check(t.name, false, `threw ${e.message}`); }
}

console.log(failures ? `\n${failures} failing` : "\nall passing");
process.exit(failures ? 1 : 0);
