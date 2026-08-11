"""Tkinter GUI: paywall gate, then the installer."""
from __future__ import annotations
import threading
import tkinter as tk
from tkinter import filedialog, ttk

from . import config, licensing, engine, provision

BG = "#0f1420"
CARD = "#1b2333"
FG = "#e8ecf5"
MUTED = "#8b95a7"
ACCENT = "#3d7bff"
OK = "#37c281"
ERR = "#ff6b6b"
FONT = ("Segoe UI", 11)
FONT_B = ("Segoe UI", 11, "bold")
FONT_H = ("Segoe UI", 18, "bold")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{config.PRODUCT_NAME} {config.PRODUCT_VERSION}")
        self.configure(bg=BG)
        self.geometry("760x620")
        self.minsize(720, 580)
        self.serial: str | None = None

        st = licensing.current_status()
        if st.ok:
            self.build_main(st)
        else:
            self.build_paywall()

    # ---- helpers ---------------------------------------------------------- #
    def _clear(self):
        for w in self.winfo_children():
            w.destroy()

    def _label(self, parent, text, font=FONT, fg=FG, **kw):
        return tk.Label(parent, text=text, font=font, fg=fg, bg=kw.pop("bg", BG),
                        justify=kw.pop("justify", "left"), **kw)

    # ---- paywall ---------------------------------------------------------- #
    def build_paywall(self):
        self._clear()
        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True, padx=24, pady=18)

        self._label(wrap, config.PRODUCT_NAME, font=FONT_H).pack(anchor="w")
        self._label(wrap, f"License required — {config.PRICE_TEXT}", fg=MUTED).pack(anchor="w", pady=(2, 14))

        pay = tk.Frame(wrap, bg=CARD)
        pay.pack(fill="x", pady=(0, 12))
        inner = tk.Frame(pay, bg=CARD); inner.pack(fill="x", padx=16, pady=14)
        self._label(inner, "Pay to card", fg=MUTED, bg=CARD).pack(anchor="w")
        self._label(inner, config.PAYMENT["card_number"], font=("Consolas", 18, "bold"),
                    bg=CARD).pack(anchor="w", pady=(0, 2))
        self._label(inner, f'{config.PAYMENT["card_holder"]}   ·   {config.PAYMENT["bank_hint"]}',
                    fg=MUTED, bg=CARD).pack(anchor="w")
        tk.Frame(inner, bg="#2a3550", height=1).pack(fill="x", pady=10)
        c = config.CONTACTS
        self._label(inner, "Contacts", fg=MUTED, bg=CARD).pack(anchor="w")
        self._label(inner, f'Telegram: {c["telegram"]}    Phone: {c["phone"]}    Email: {c["email"]}',
                    bg=CARD).pack(anchor="w")
        self._label(inner, config.PAYMENT_INSTRUCTIONS, fg=MUTED, bg=CARD).pack(anchor="w", pady=(10, 0))

        mid = licensing.machine_id()
        midf = tk.Frame(wrap, bg=BG); midf.pack(fill="x", pady=(2, 8))
        self._label(midf, "Your Machine ID:", fg=MUTED).pack(side="left")
        e = tk.Entry(midf, font=("Consolas", 12, "bold"), fg=FG, bg=CARD,
                     insertbackground=FG, relief="flat", width=24)
        e.insert(0, mid); e.configure(state="readonly")
        e.pack(side="left", padx=8)
        tk.Button(midf, text="Copy", command=lambda: self._copy(mid), **self._btn()).pack(side="left")

        self._label(wrap, "Paste your license key:", fg=MUTED).pack(anchor="w", pady=(10, 2))
        self.key_txt = tk.Text(wrap, height=3, font=("Consolas", 10), fg=FG, bg=CARD,
                               insertbackground=FG, relief="flat", wrap="char")
        self.key_txt.pack(fill="x")

        self.pw_status = self._label(wrap, "", fg=ERR); self.pw_status.pack(anchor="w", pady=(8, 0))
        tk.Button(wrap, text="Activate", command=self._activate,
                  **self._btn(primary=True)).pack(anchor="w", pady=(8, 0))

    def _activate(self):
        key = self.key_txt.get("1.0", "end").strip()
        res = licensing.verify_license(key)
        if res.ok:
            licensing.save_license(key)
            self.build_main(res)
        else:
            self.pw_status.configure(text="✗ " + res.reason, fg=ERR)

    # ---- main installer --------------------------------------------------- #
    def build_main(self, status: licensing.LicenseResult):
        self._clear()
        wrap = tk.Frame(self, bg=BG); wrap.pack(fill="both", expand=True, padx=24, pady=18)

        top = tk.Frame(wrap, bg=BG); top.pack(fill="x")
        self._label(top, config.PRODUCT_NAME, font=FONT_H).pack(side="left")
        ref = status.payload.get("ref") or status.payload.get("mid", "")
        self._label(top, f"Licensed · {ref}", fg=OK).pack(side="right")

        self._label(wrap, "Step 1 — On the head unit, enable Developer options → "
                    "Wireless ADB. Everything else is automatic.", fg=MUTED,
                    wraplength=700).pack(anchor="w", pady=(6, 12))

        dev = tk.Frame(wrap, bg=CARD); dev.pack(fill="x")
        di = tk.Frame(dev, bg=CARD); di.pack(fill="x", padx=16, pady=12)
        self.dev_lbl = self._label(di, "Device: not connected", bg=CARD)
        self.dev_lbl.pack(side="left")
        tk.Button(di, text="Detect / Reconnect", command=self._detect_async,
                  **self._btn()).pack(side="right")

        items = tk.Frame(wrap, bg=CARD); items.pack(fill="x", pady=(12, 6))
        ii = tk.Frame(items, bg=CARD); ii.pack(fill="x", padx=16, pady=12)
        self._label(ii, "This will install, in order:", fg=MUTED, bg=CARD).pack(anchor="w")
        for s in provision.STEPS:
            self._label(ii, f"   • {s['name']}", bg=CARD).pack(anchor="w")

        act = tk.Frame(wrap, bg=BG); act.pack(fill="x", pady=(10, 6))
        self.go_btn = tk.Button(act, text="Install everything to the car",
                                command=self._provision_async, **self._btn(primary=True))
        self.go_btn.pack(side="left")

        self._label(wrap, "Log", fg=MUTED).pack(anchor="w", pady=(8, 2))
        self.log_txt = tk.Text(wrap, height=16, font=("Consolas", 10), fg=FG, bg="#0b0f18",
                               insertbackground=FG, relief="flat", wrap="word")
        self.log_txt.pack(fill="both", expand=True)
        self.log_txt.configure(state="disabled")

        self._detect_async()

    # ---- actions ---------------------------------------------------------- #
    def log(self, msg: str):
        def _():
            self.log_txt.configure(state="normal")
            self.log_txt.insert("end", msg + "\n")
            self.log_txt.see("end")
            self.log_txt.configure(state="disabled")
        self.after(0, _)

    def _detect_async(self):
        threading.Thread(target=self._detect, daemon=True).start()

    def _detect(self):
        self.serial = engine.ensure_device(self.log)
        if self.serial:
            info = engine.device_info(self.serial, None)
            txt = f"Device: {info.get('model','?')} · Android {info.get('android','?')} " \
                  f"(API {info.get('sdk','?')}) · {self.serial}"
            self.after(0, lambda: self.dev_lbl.configure(text=txt, fg=OK))
        else:
            self.after(0, lambda: self.dev_lbl.configure(text="Device: not connected", fg=ERR))

    def _guard(self) -> bool:
        if not licensing.current_status().ok:
            self.build_paywall(); return False
        if not self.serial:
            self.log("No device connected. Press Detect / Reconnect first."); return False
        return True

    def _provision_async(self):
        if not self._guard():
            return
        self.go_btn.configure(state="disabled", text="Installing…")
        def worker():
            try:
                provision.provision(self.serial, self.log)
            finally:
                self.after(0, lambda: self.go_btn.configure(
                    state="normal", text="Install everything to the car"))
        threading.Thread(target=worker, daemon=True).start()

    # ---- small ui utils --------------------------------------------------- #
    def _copy(self, text: str):
        self.clipboard_clear(); self.clipboard_append(text)

    def _btn(self, primary: bool = False):
        return dict(font=FONT_B, fg="#ffffff", bg=ACCENT if primary else "#2a3550",
                    activebackground=ACCENT, activeforeground="#fff", relief="flat",
                    bd=0, padx=14, pady=8, cursor="hand2")


def run():
    App().mainloop()
