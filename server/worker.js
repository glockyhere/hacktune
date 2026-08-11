/**
 * Activation backend — Cloudflare Worker.
 *
 * Endpoints
 *   POST /api/request      {mid,vin,make,model}      -> {rid, code, status:"pending"}
 *   GET  /api/status?rid=                              -> {status} (+ {token} once, when approved)
 *   GET  /api/pending      (admin)                     -> [ pending requests ]
 *   POST /api/approve      (admin) {rid}               -> approves + mints one-time token
 *   POST /api/reject       (admin) {rid}               -> rejects
 *   GET  /admin                                        -> admin page (asks for admin token)
 *   POST /tg               (Telegram webhook)          -> inline Approve/Reject buttons
 *
 * Secrets / vars (wrangler):
 *   SIGNING_KEY_PKCS8  (secret)  base64 PKCS8 Ed25519 private key (from generate_activation_keys.py)
 *   ADMIN_TOKEN        (secret)  password for the admin page / admin API
 *   TG_BOT_TOKEN       (secret, optional)  Telegram bot token
 *   TG_CHAT_ID         (var,   optional)  your Telegram chat/user id to notify
 * KV binding: ACTIVATIONS
 */

const enc = new TextEncoder();
const b64url = (buf) =>
  btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const b64ToBytes = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
const json = (obj, status = 200) =>
  new Response(JSON.stringify(obj), { status, headers: { "content-type": "application/json" } });

function code6() {
  const A = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"; // no I,L,O,0,1
  const r = crypto.getRandomValues(new Uint8Array(6));
  return [...r].map((x) => A[x % A.length]).join("");
}

async function signToken(env, payloadObj) {
  const key = await crypto.subtle.importKey(
    "pkcs8", b64ToBytes(env.SIGNING_KEY_PKCS8), { name: "Ed25519" }, false, ["sign"]
  );
  const payloadBytes = enc.encode(JSON.stringify(payloadObj));
  const sig = await crypto.subtle.sign({ name: "Ed25519" }, key, payloadBytes);
  return b64url(payloadBytes) + "." + b64url(sig);
}

function isAdmin(req, env) {
  const h = req.headers.get("Authorization") || "";
  return env.ADMIN_TOKEN && h === "Bearer " + env.ADMIN_TOKEN;
}

async function notifyTelegram(env, rec) {
  if (!env.TG_BOT_TOKEN || !env.TG_CHAT_ID) return;
  const text =
    `🆕 Activation request\ncode: *${rec.code}*\nVIN: \`${rec.vin}\`\n` +
    `car: ${rec.make} ${rec.model}\nmachine: \`${rec.mid}\``;
  const reply_markup = {
    inline_keyboard: [[
      { text: "✅ Approve", callback_data: "approve:" + rec.rid },
      { text: "❌ Reject", callback_data: "reject:" + rec.rid },
    ]],
  };
  await fetch(`https://api.telegram.org/bot${env.TG_BOT_TOKEN}/sendMessage`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ chat_id: env.TG_CHAT_ID, text, parse_mode: "Markdown", reply_markup }),
  });
}

async function approve(env, rid) {
  const raw = await env.ACTIVATIONS.get("req:" + rid);
  if (!raw) return { ok: false, reason: "not found" };
  const rec = JSON.parse(raw);
  if (rec.status === "approved") return { ok: true, rec };
  const payload = {
    rid: rec.rid, mid: rec.mid, vin: rec.vin, make: rec.make, model: rec.model,
    iat: Math.floor(Date.now() / 1000), nonce: b64url(crypto.getRandomValues(new Uint8Array(12))),
    tag: "activation",
  };
  rec.token = await signToken(env, payload);
  rec.status = "approved";
  rec.delivered = false;
  rec.approved_at = Date.now();
  await env.ACTIVATIONS.put("req:" + rid, JSON.stringify(rec));
  return { ok: true, rec };
}

async function reject(env, rid) {
  const raw = await env.ACTIVATIONS.get("req:" + rid);
  if (!raw) return { ok: false };
  const rec = JSON.parse(raw);
  rec.status = "rejected";
  await env.ACTIVATIONS.put("req:" + rid, JSON.stringify(rec));
  return { ok: true };
}

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    const p = url.pathname;

    // ---- buyer: create a request ----
    if (p === "/api/request" && req.method === "POST") {
      const b = await req.json().catch(() => ({}));
      for (const f of ["mid", "vin", "make", "model"]) {
        if (!b[f] || String(b[f]).length > 128) return json({ error: "invalid " + f }, 400);
      }
      const rid = crypto.randomUUID();
      const rec = {
        rid, code: code6(), mid: b.mid, vin: b.vin.toUpperCase(),
        make: b.make, model: b.model, status: "pending", created: Date.now(),
      };
      await env.ACTIVATIONS.put("req:" + rid, JSON.stringify(rec), { expirationTtl: 60 * 60 * 24 * 14 });
      await notifyTelegram(env, rec);
      return json({ rid, code: rec.code, status: "pending" });
    }

    // ---- buyer: poll status; deliver token exactly once ----
    if (p === "/api/status" && req.method === "GET") {
      const rid = url.searchParams.get("rid") || "";
      const raw = await env.ACTIVATIONS.get("req:" + rid);
      if (!raw) return json({ status: "unknown" });
      const rec = JSON.parse(raw);
      if (rec.status === "approved" && !rec.delivered) {
        rec.delivered = true;
        await env.ACTIVATIONS.put("req:" + rid, JSON.stringify(rec));
        return json({ status: "approved", token: rec.token });
      }
      return json({ status: rec.status, delivered: !!rec.delivered });
    }

    // ---- admin: list pending ----
    if (p === "/api/pending" && req.method === "GET") {
      if (!isAdmin(req, env)) return json({ error: "unauthorized" }, 401);
      const list = await env.ACTIVATIONS.list({ prefix: "req:" });
      const out = [];
      for (const k of list.keys) {
        const rec = JSON.parse(await env.ACTIVATIONS.get(k.name));
        if (rec.status === "pending") out.push(rec);
      }
      out.sort((a, b) => a.created - b.created);
      return json(out);
    }

    // ---- admin: approve / reject ----
    if (p === "/api/approve" && req.method === "POST") {
      if (!isAdmin(req, env)) return json({ error: "unauthorized" }, 401);
      const { rid } = await req.json().catch(() => ({}));
      const r = await approve(env, rid);
      return json(r.ok ? { ok: true } : { error: r.reason || "failed" }, r.ok ? 200 : 400);
    }
    if (p === "/api/reject" && req.method === "POST") {
      if (!isAdmin(req, env)) return json({ error: "unauthorized" }, 401);
      const { rid } = await req.json().catch(() => ({}));
      const r = await reject(env, rid);
      return json({ ok: r.ok });
    }

    // ---- Telegram webhook (optional) ----
    if (p === "/tg" && req.method === "POST") {
      const u = await req.json().catch(() => ({}));
      const cq = u.callback_query;
      if (cq && String(cq.message?.chat?.id) === String(env.TG_CHAT_ID)) {
        const [action, rid] = String(cq.data || "").split(":");
        if (action === "approve") await approve(env, rid);
        else if (action === "reject") await reject(env, rid);
        // acknowledge
        await fetch(`https://api.telegram.org/bot${env.TG_BOT_TOKEN}/answerCallbackQuery`, {
          method: "POST", headers: { "content-type": "application/json" },
          body: JSON.stringify({ callback_query_id: cq.id, text: action + "d" }),
        });
      }
      return json({ ok: true });
    }

    // ---- admin page ----
    if (p === "/admin" || p === "/") {
      return new Response(ADMIN_HTML, { headers: { "content-type": "text/html; charset=utf-8" } });
    }

    return new Response("Not found", { status: 404 });
  },
};

const ADMIN_HTML = `<!doctype html><meta charset=utf-8><title>Activation admin</title>
<style>body{font-family:system-ui;background:#0f1420;color:#e8ecf5;margin:0;padding:20px}
h1{font-size:18px}input,button{font:inherit;padding:8px;border-radius:8px;border:0}
input{background:#1b2333;color:#e8ecf5;width:320px}
button{background:#3d7bff;color:#fff;cursor:pointer;margin-left:6px}
button.r{background:#ff6b6b}.card{background:#1b2333;padding:14px;border-radius:12px;margin:10px 0}
code{color:#8b95a7}.muted{color:#8b95a7}</style>
<h1>Activation requests</h1>
<div><input id=tok type=password placeholder="admin token"><button onclick=save()>Save & refresh</button>
<span class=muted id=msg></span></div>
<div id=list></div>
<script>
let T=localStorage.getItem('adm')||'';document.getElementById('tok').value=T;
function save(){T=document.getElementById('tok').value;localStorage.setItem('adm',T);load();}
async function api(path,opt={}){opt.headers=Object.assign({'Authorization':'Bearer '+T},opt.headers||{});return fetch(path,opt);}
async function act(rid,how){await api('/api/'+how,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({rid})});load();}
async function load(){
 const m=document.getElementById('msg');m.textContent='…';
 const r=await api('/api/pending');
 if(!r.ok){m.textContent=' (bad token?)';return;}
 m.textContent='';const rows=await r.json();const el=document.getElementById('list');
 el.innerHTML=rows.length?'':'<p class=muted>No pending requests.</p>';
 for(const x of rows){const d=document.createElement('div');d.className='card';
  d.innerHTML='<b>'+x.code+'</b> &nbsp; '+x.make+' '+x.model+'<br>VIN <code>'+x.vin+'</code><br>machine <code>'+x.mid+'</code>';
  const a=document.createElement('button');a.textContent='Approve';a.onclick=()=>act(x.rid,'approve');
  const rj=document.createElement('button');rj.textContent='Reject';rj.className='r';rj.onclick=()=>act(x.rid,'reject');
  d.appendChild(document.createElement('br'));d.appendChild(a);d.appendChild(rj);el.appendChild(d);}
}
if(T)load();setInterval(()=>{if(T)load();},8000);
</script>`;
