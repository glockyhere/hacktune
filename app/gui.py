"""
Tkinter GUI — per-install activation flow:

  1. Buyer enters VIN + make + model, sees your card + contacts, taps Request.
  2. Program submits the request; buyer pays you and messages you the code.
  3. You approve (phone/admin page); the program receives a one-time signed token,
     verifies it (bound to this machine + VIN), and unlocks the installer once.
"""
from __future__ import annotations
import threading
import tkinter as tk

from . import config, licensing, engine, provision, activation

BG = "#0f1420"; CARD = "#1b2333"; FG = "#e8ecf5"; MUTED = "#8b95a7"
ACCENT = "#3d7bff"; OK = "#37c281"; ERR = "#ff6b6b"
FONT = ("Segoe UI", 11); FONT_B = ("Segoe UI", 11, "bold"); FONT_H = ("Segoe UI", 18, "bold")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{config.PRODUCT_NAME} {config.PRODUCT_VERSION}")
        self.configure(bg=BG); self.geometry("780x680"); self.minsize(740, 620)
        self.serial = None
        self._poll_stop = False
        self.build_request()

    # ---- ui helpers ------------------------------------------------------- #
    def _clear(self):
        self._poll_stop = True
        for w in self.winfo_children():
            w.destroy()

    def _label(self, parent, text, font=FONT, fg=FG, bg=None, **kw):
        return tk.Label(parent, text=text, font=font, fg=fg, bg=bg or BG,
                        justify=kw.pop("justify", "left"), **kw)

    def _btn(self, primary=False):
        return dict(font=FONT_B, fg="#fff", bg=ACCENT if primary else "#2a3550",
                    activebackground=ACCENT, activeforeground="#fff", relief="flat",
                    bd=0, padx=14, pady=8, cursor="hand2")

    def _copy(self, text):
        self.clipboard_clear(); self.clipboard_append(text)

    def _payment_card(self, parent):
        pay = tk.Frame(parent, bg=CARD); pay.pack(fill="x", pady=(0, 12))
        inner = tk.Frame(pay, bg=CARD); inner.pack(fill="x", padx=16, pady=14)
        self._label(inner, "Pay to card", fg=MUTED, bg=CARD).pack(anchor="w")
        self._label(inner, config.PAYMENT["card_number"], font=("Consolas", 17, "bold"),
                    bg=CARD).pack(anchor="w")
        self._label(inner, f'{config.PAYMENT["card_holder"]}   ·   {config.PAYMENT["bank_hint"]}   ·   {config.PRICE_TEXT}',
                    fg=MUTED, bg=CARD).pack(anchor="w")
        c = config.CONTACTS
        tk.Frame(inner, bg="#2a3550", height=1).pack(fill="x", pady=8)
        self._label(inner, f'Contact: {c["telegram"]}   {c["phone"]}   {c["email"]}',
                    bg=CARD).pack(anchor="w")

    # ---- screen 1: request ----------------------------------------------- #
    def build_request(self):
        self._clear(); self._poll_stop = False
        w = tk.Frame(self, bg=BG); w.pack(fill="both", expand=True, padx=24, pady=18)
        self._label(w, config.PRODUCT_NAME, font=FONT_H).pack(anchor="w")
        self._label(w, "New installation — one approval per car.", fg=MUTED).pack(anchor="w", pady=(2, 12))
        self._payment_card(w)

        form = tk.Frame(w, bg=BG); form.pack(fill="x")
        self.vin = tk.StringVar(); self.make = tk.StringVar(); self.model = tk.StringVar()
        def row(lbl, var, width=32):
            r = tk.Frame(form, bg=BG); r.pack(fill="x", pady=3)
            self._label(r, lbl, fg=MUTED, width=8).pack(side="left")
            e = tk.Entry(r, textvariable=var, font=("Consolas", 12), fg=FG, bg=CARD,
                         insertbackground=FG, relief="flat", width=width)
            e.pack(side="left"); return e
        row("VIN", self.vin); row("Make", self.make); row("Model", self.model)

        mid = licensing.machine_id()
        m = tk.Frame(w, bg=BG); m.pack(fill="x", pady=(10, 4))
        self._label(m, "Machine ID:", fg=MUTED).pack(side="left")
        self._label(m, mid, font=("Consolas", 12, "bold")).pack(side="left", padx=8)

        self.req_status = self._label(w, "", fg=ERR); self.req_status.pack(anchor="w", pady=(6, 0))
        if not activation.configured():
            self.req_status.configure(
                text="⚠ Activation server not configured (ACTIVATION_API_URL / PUBLIC_KEY).", fg=ERR)
        tk.Button(w, text="Request activation", command=self._submit,
                  **self._btn(primary=True)).pack(anchor="w", pady=(10, 0))

    def _submit(self):
        vin = self.vin.get().strip()
        if len(vin) < 11 or not vin.isalnum():
            self.req_status.configure(text="Enter a valid VIN (11–17 letters/digits).", fg=ERR); return
        if not self.make.get().strip() or not self.model.get().strip():
            self.req_status.configure(text="Enter make and model.", fg=ERR); return
        if not activation.configured():
            self.req_status.configure(text="Activation server not configured.", fg=ERR); return
        self.req_status.configure(text="Submitting…", fg=MUTED)
        def worker():
            try:
                rid, code = activation.submit_request(vin, self.make.get(), self.model.get())
                self.after(0, lambda: self.build_wait(rid, code, vin))
            except Exception as e:
                self.after(0, lambda: self.req_status.configure(
                    text=f"Could not reach the activation server: {e}", fg=ERR))
        threading.Thread(target=worker, daemon=True).start()

    # ---- screen 2: waiting for approval ----------------------------------- #
    def build_wait(self, rid, code, vin):
        self._clear(); self._poll_stop = False
        w = tk.Frame(self, bg=BG); w.pack(fill="both", expand=True, padx=24, pady=18)
        self._label(w, "Waiting for approval", font=FONT_H).pack(anchor="w")
        self._payment_card(w)

        box = tk.Frame(w, bg=CARD); box.pack(fill="x", pady=(0, 12))
        bi = tk.Frame(box, bg=CARD); bi.pack(fill="x", padx=16, pady=14)
        self._label(bi, "Your request code", fg=MUTED, bg=CARD).pack(anchor="w")
        cr = tk.Frame(bi, bg=CARD); cr.pack(anchor="w")
        self._label(cr, code, font=("Consolas", 22, "bold"), bg=CARD).pack(side="left")
        tk.Button(cr, text="Copy", command=lambda: self._copy(code), **self._btn()).pack(side="left", padx=10)
        self._label(bi, f'Pay to the card above, then send code "{code}" to {config.CONTACTS["telegram"]}.\n'
                        "This screen unlocks automatically once it is approved.",
                    fg=MUTED, bg=CARD).pack(anchor="w", pady=(6, 0))

        self.wait_status = self._label(w, "● waiting…", fg=MUTED); self.wait_status.pack(anchor="w", pady=(6, 0))
        tk.Button(w, text="Cancel", command=self.build_request, **self._btn()).pack(anchor="w", pady=(10, 0))

        threading.Thread(target=self._poll, args=(rid, vin), daemon=True).start()

    def _poll(self, rid, vin):
        import time
        dots = 0
        while not self._poll_stop:
            try:
                status, token = activation.poll_status(rid)
            except Exception:
                status, token = "pending", None
            if status == "approved" and token:
                res = activation.verify_token(token, vin)
                if res.ok:
                    self.after(0, lambda: self.build_installer(res.payload, rid, vin))
                    return
                self.after(0, lambda: self.wait_status.configure(
                    text="✗ " + res.reason, fg=ERR)); return
            if status == "rejected":
                self.after(0, lambda: self.wait_status.configure(
                    text="✗ Request was rejected. You can submit a new one.", fg=ERR)); return
            dots = (dots + 1) % 4
            self.after(0, lambda d=dots: self.wait_status.configure(
                text="● waiting for approval" + "." * d, fg=MUTED))
            for _ in range(10):
                if self._poll_stop: return
                time.sleep(0.5)

    # ---- screen 3: installer (unlocked once) ------------------------------ #
    def build_installer(self, payload, rid, vin):
        self._clear(); self._poll_stop = True
        self._rid = rid; self._done = False
        w = tk.Frame(self, bg=BG); w.pack(fill="both", expand=True, padx=24, pady=18)
        top = tk.Frame(w, bg=BG); top.pack(fill="x")
        self._label(top, "Approved", font=FONT_H, fg=OK).pack(side="left")
        self._label(top, f"VIN {payload.get('vin','')} · {payload.get('make','')} {payload.get('model','')}",
                    fg=MUTED).pack(side="right")
        self._label(w, "On the head unit enable Developer options → Wireless ADB, then press Detect.",
                    fg=MUTED, wraplength=720).pack(anchor="w", pady=(6, 10))

        dev = tk.Frame(w, bg=CARD); dev.pack(fill="x")
        di = tk.Frame(dev, bg=CARD); di.pack(fill="x", padx=16, pady=12)
        self.dev_lbl = self._label(di, "Device: not connected", bg=CARD); self.dev_lbl.pack(side="left")
        tk.Button(di, text="Detect / Reconnect", command=self._detect_async, **self._btn()).pack(side="right")

        items = tk.Frame(w, bg=CARD); items.pack(fill="x", pady=(12, 6))
        ii = tk.Frame(items, bg=CARD); ii.pack(fill="x", padx=16, pady=12)
        self._label(ii, "Installs, in order:", fg=MUTED, bg=CARD).pack(anchor="w")
        for s in provision.STEPS:
            self._label(ii, f"   • {s['name']}", bg=CARD).pack(anchor="w")

        self.go_btn = tk.Button(w, text="Install everything to the car",
                                command=self._provision_async, **self._btn(primary=True))
        self.go_btn.pack(anchor="w", pady=(8, 6))
        self._label(w, "Log", fg=MUTED).pack(anchor="w", pady=(6, 2))
        self.log_txt = tk.Text(w, height=13, font=("Consolas", 10), fg=FG, bg="#0b0f18",
                               insertbackground=FG, relief="flat", wrap="word")
        self.log_txt.pack(fill="both", expand=True); self.log_txt.configure(state="disabled")
        self._detect_async()

    def log(self, msg):
        def _():
            self.log_txt.configure(state="normal"); self.log_txt.insert("end", msg + "\n")
            self.log_txt.see("end"); self.log_txt.configure(state="disabled")
        self.after(0, _)

    def _detect_async(self):
        threading.Thread(target=self._detect, daemon=True).start()

    def _detect(self):
        self.serial = engine.ensure_device(self.log)
        if self.serial:
            info = engine.device_info(self.serial, None)
            t = f"Device: {info.get('model','?')} · Android {info.get('android','?')} (API {info.get('sdk','?')})"
            self.after(0, lambda: self.dev_lbl.configure(text=t, fg=OK))
        else:
            self.after(0, lambda: self.dev_lbl.configure(text="Device: not connected", fg=ERR))

    def _provision_async(self):
        if self._done:
            return
        if not self.serial:
            self.log("No device. Press Detect / Reconnect first."); return
        self.go_btn.configure(state="disabled", text="Installing…")
        def worker():
            ok = False
            try:
                ok = provision.provision(self.serial, self.log)
            finally:
                if ok:
                    activation.mark_consumed(self._rid)
                    self._done = True
                    self.after(0, lambda: self.go_btn.configure(text="Done ✓"))
                else:
                    self.after(0, lambda: self.go_btn.configure(
                        state="normal", text="Retry install"))
        threading.Thread(target=worker, daemon=True).start()


def run():
    App().mainloop()
