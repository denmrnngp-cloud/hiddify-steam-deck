#!/usr/bin/env python3
# Hiddify VPN — GTK3 Wizard Installer for SteamOS / Linux

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib, Gdk, Pango, GdkPixbuf

import os, sys, re, subprocess, threading, shutil, zipfile, json

# WORK_DIR передаётся как argv[1] (путь где лежат файлы установщика)
WORK_DIR   = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
INSTALL_SH = os.path.join(WORK_DIR, "install.sh")
DECKY_ZIP  = os.path.join(WORK_DIR, "decky-hiddify.zip")
ICON_PATH  = os.path.join(WORK_DIR, "hiddify.png")
DECKY_DIR   = "/home/deck/homebrew/plugins"
HIDDIFY_CLI = "/opt/hiddify/HiddifyCli"
APP_DIR     = "/home/deck/.local/share/app.hiddify.com"
SYSTEM_APP_DIR = "/var/lib/hiddify"


def packaged_version():
    if not os.path.exists(DECKY_ZIP):
        return "unknown"
    try:
        with zipfile.ZipFile(DECKY_ZIP) as zf:
            for candidate in ("decky-hiddify/plugin.json", "plugin.json"):
                if candidate in zf.namelist():
                    with zf.open(candidate) as f:
                        return str(json.load(f).get("version", "unknown"))
    except Exception:
        pass
    return "unknown"


APP_VERSION = packaged_version()

# ── License ────────────────────────────────────────────────────────────────────

LICENSE_TEXT = """\
Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International
(CC BY-NC-SA 4.0)

Copyright © 2023–2025 Hiddify Team
Portions copyright © 2025 Steam Deck Port Contributors

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

You are free to:
  Share   — copy and redistribute the material in any medium or format
  Adapt   — remix, transform, and build upon the material

Under the following terms:
  Attribution     — You must give appropriate credit and indicate if
                    changes were made.
  NonCommercial   — You may not use the material for commercial purposes.
  ShareAlike      — Derivatives must be distributed under the same license.

No additional restrictions — You may not apply legal terms or technological
measures that legally restrict others from doing anything the license permits.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

DISCLAIMER OF WARRANTIES AND LIMITATION OF LIABILITY

THE LICENSOR OFFERS THE LICENSED MATERIAL AS-IS AND MAKES NO WARRANTIES
OF ANY KIND. TO THE EXTENT POSSIBLE, THE LICENSOR WILL NOT BE LIABLE FOR
ANY DAMAGES ARISING FROM USE OF THE LICENSED MATERIAL.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Full license: https://creativecommons.org/licenses/by-nc-sa/4.0/legalcode
Source code:  https://github.com/hiddify/hiddify-app
Steam Deck:   https://github.com/steam-decky/hiddify-steamdeck
"""

ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')

# ── Adaptive geometry ─────────────────────────────────────────────────────────

def screen_geometry():
    display = Gdk.Display.get_default()
    monitor = display.get_monitor(0)
    geo = monitor.get_geometry()
    scale = monitor.get_scale_factor()
    return geo.width * scale, geo.height * scale

def adaptive_size():
    sw, sh = screen_geometry()
    # KDE top panel: ~28px, left dock: ~38px (measured from xwininfo on Steam Deck)
    return sw - 38, sh - 28

# ── CSS ────────────────────────────────────────────────────────────────────────

CSS = b"""
window { background-color: #111827; }

.page-box {
    background-color: #111827;
    padding: 12px 24px;
}

.nav-bar {
    background-color: #0c1120;
    padding: 8px 20px;
}

.hdr-bar {
    background-color: #0c1120;
    padding: 8px 20px;
}

.title-label {
    color: #4ade80;
    font-size: 18px;
    font-weight: bold;
}
.subtitle-label { color: #64748b; font-size: 12px; }
.section-label  { color: #4ade80; font-size: 13px; font-weight: bold; }
.desc-label     { color: #cbd5e1; font-size: 13px; }
.warning-label  { color: #fbbf24; font-size: 12px; }
.ok-label       { color: #4ade80; font-size: 13px; font-weight: bold; }
.err-label      { color: #f87171; font-size: 13px; font-weight: bold; }
.step-label     { color: #64748b; font-size: 12px; }

textview, textview text {
    background-color: #0d1117;
    color: #8b949e;
    font-family: monospace;
    font-size: 11px;
}
.log-view, .log-view text {
    background-color: #0d1117;
    color: #7ee787;
    font-family: monospace;
    font-size: 11px;
}

entry {
    background-color: #1e293b;
    color: #e2e8f0;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 7px 12px;
    font-size: 13px;
}
entry:focus { border-color: #4ade80; }

checkbutton label { color: #e2e8f0; font-size: 13px; }
checkbutton:disabled label { color: #475569; }

radiobutton label { color: #e2e8f0; font-size: 13px; }

progressbar trough {
    background-color: #1e293b;
    border-radius: 6px;
    min-height: 12px;
}
progressbar progress {
    background-color: #4ade80;
    border-radius: 6px;
}

button {
    background-color: #1e293b;
    color: #e2e8f0;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 7px 18px;
    font-size: 13px;
}
button:hover {
    background-color: #243448;
    border-color: #4ade80;
    color: #4ade80;
}
button:disabled { opacity: 0.45; }

.btn-primary {
    background-color: #166534;
    color: #dcfce7;
    border-color: #4ade80;
}
.btn-primary:hover {
    background-color: #15803d;
    color: #ffffff;
}
.btn-primary:disabled { opacity: 0.45; }

frame { border: 1px solid #1e293b; border-radius: 8px; }
frame > border { border: none; }

separator { background-color: #1e293b; min-height: 1px; }
"""

def apply_css():
    try:
        p = Gtk.CssProvider()
        p.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), p,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
    except Exception:
        pass

# ── Helpers ────────────────────────────────────────────────────────────────────

def lbl(text, css=None, wrap=True, xalign=0.0, markup=False):
    l = Gtk.Label()
    if markup:
        l.set_markup(text)
    else:
        l.set_text(text)
    l.set_xalign(xalign)
    if wrap:
        l.set_line_wrap(True)
        l.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
    if css:
        l.get_style_context().add_class(css)
    return l

def icon_image(size):
    if not os.path.exists(ICON_PATH):
        return None
    pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(ICON_PATH, size, size, True)
    return Gtk.Image.new_from_pixbuf(pb)

def page_box(spacing=14):
    b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)
    b.get_style_context().add_class("page-box")
    return b

# ── Wizard ─────────────────────────────────────────────────────────────────────

class HiddifyWizard(Gtk.Window):

    PAGES  = ["welcome", "license", "options", "password", "progress", "finish"]
    TITLES = ["Welcome", "License", "Components", "Password", "Installing", "Done"]

    P_WELCOME  = 0
    P_LICENSE  = 1
    P_OPTIONS  = 2
    P_PASSWORD = 3
    P_PROGRESS = 4
    P_FINISH   = 5

    def __init__(self, clean_install=False):
        super().__init__()

        w, h = adaptive_size()
        self.set_title("Hiddify VPN — Installation")
        self.set_default_size(w, h)
        self.set_resizable(True)
        self.set_size_request(1, 1)
        self.set_position(Gtk.WindowPosition.CENTER)

        if os.path.exists(ICON_PATH):
            self.set_icon_from_file(ICON_PATH)

        self.install_decky = False
        self.clean_install = clean_install or os.environ.get("HIDDIFY_CLEAN_INSTALL") == "1"
        self.sudo_password = ""
        self.install_ok    = False
        self._current      = 0
        # per-page next-button state
        self._can_next = [True, False, True, False, False, True]

        self.connect("delete-event", self._on_delete)
        self.connect("configure-event", self._on_resize)

        self._build_ui()

    def _on_resize(self, widget, event):
        pass

    # ── UI skeleton ────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(root)

        # Header bar
        hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        hdr.get_style_context().add_class("hdr-bar")

        img = icon_image(32)
        if img:
            hdr.pack_start(img, False, False, 0)

        self._hdr_title = lbl(self.TITLES[0], "title-label")
        hdr.pack_start(self._hdr_title, True, True, 0)

        self._step_lbl_hdr = lbl(f"1 / {len(self.PAGES)}", "step-label", xalign=1.0)
        hdr.pack_end(self._step_lbl_hdr, False, False, 0)

        root.pack_start(hdr, False, False, 0)
        root.pack_start(Gtk.Separator(), False, False, 0)

        # Stack (fills space)
        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self._stack.set_transition_duration(180)
        self._stack.set_vexpand(True)
        self._stack.set_hexpand(True)

        self._page_welcome()
        self._page_license()
        self._page_options()
        self._page_password()
        self._page_progress()
        self._page_finish()

        root.pack_start(self._stack, True, True, 0)
        root.pack_start(Gtk.Separator(), False, False, 0)

        # Nav bar
        nav = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        nav.get_style_context().add_class("nav-bar")

        self._btn_back = Gtk.Button(label="  ← Back  ")
        self._btn_back.connect("clicked", self._on_back)
        nav.pack_start(self._btn_back, False, False, 0)

        nav.pack_start(Gtk.Box(), True, True, 0)  # spacer

        self._btn_cancel = Gtk.Button(label="  Cancel  ")
        self._btn_cancel.connect("clicked", self._on_cancel)
        nav.pack_start(self._btn_cancel, False, False, 0)

        self._btn_next = Gtk.Button(label="  Next →  ")
        self._btn_next.get_style_context().add_class("btn-primary")
        self._btn_next.connect("clicked", self._on_next)
        nav.pack_start(self._btn_next, False, False, 0)

        root.pack_start(nav, False, False, 0)

        self._refresh_nav()

    def _refresh_nav(self):
        idx = self._current
        n   = len(self.PAGES)

        self._hdr_title.set_text(self.TITLES[idx])
        self._step_lbl_hdr.set_text(f"{idx + 1} / {n}")

        self._btn_back.set_visible(idx > 0 and idx != self.P_PROGRESS)
        self._btn_cancel.set_visible(idx < self.P_FINISH)

        if idx == self.P_FINISH:
            self._btn_next.set_label("  Close  ")
            self._btn_next.set_visible(True)
            self._btn_next.set_sensitive(True)
        elif idx == self.P_PROGRESS:
            self._btn_next.set_visible(False)
        else:
            self._btn_next.set_label("  Next →  ")
            self._btn_next.set_visible(True)
            self._btn_next.set_sensitive(self._can_next[idx])

    def _set_page_complete(self, page_idx, complete):
        self._can_next[page_idx] = complete
        if self._current == page_idx:
            self._btn_next.set_sensitive(complete)

    # ── Navigation ─────────────────────────────────────────────────────────────

    def _on_next(self, btn):
        if self._current == self.P_FINISH:
            self._cleanup()
            Gtk.main_quit()
            return
        self._current += 1
        self._stack.set_visible_child_name(self.PAGES[self._current])
        self._refresh_nav()
        if self._current == self.P_PROGRESS:
            GLib.idle_add(self._start_install)

    def _on_back(self, btn):
        self._current -= 1
        self._stack.set_visible_child_name(self.PAGES[self._current])
        self._refresh_nav()

    def _on_cancel(self, btn):
        dlg = Gtk.MessageDialog(
            transient_for=self, modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text="Cancel installation?",
        )
        dlg.format_secondary_text("Hiddify VPN will not be installed.")
        r = dlg.run()
        dlg.destroy()
        if r == Gtk.ResponseType.YES:
            self._cleanup()
            Gtk.main_quit()

    def _on_delete(self, widget, event):
        if self._current == self.P_PROGRESS:
            return True  # запрет закрытия во время установки
        self._cleanup()
        Gtk.main_quit()
        return False

    def _cleanup(self):
        if WORK_DIR.startswith("/tmp/hiddify-wizard"):
            shutil.rmtree(WORK_DIR, ignore_errors=True)

    # ── Page builders ──────────────────────────────────────────────────────────

    def _page_welcome(self):
        # Горизонтальный layout: иконка слева, текст справа
        outer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)

        # Левая колонка — иконка
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        left.set_valign(Gtk.Align.CENTER)
        left.set_halign(Gtk.Align.CENTER)
        left.set_margin_start(32)
        left.set_margin_end(24)
        img = icon_image(120)
        if img:
            left.pack_start(img, False, False, 0)
        left.pack_start(lbl(f"Steam Deck Port  ·  v{APP_VERSION}", "subtitle-label", xalign=0.5), False, False, 8)
        outer.pack_start(left, False, False, 0)

        outer.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 0)

        # Правая колонка — текст
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        right.set_border_width(24)
        right.set_valign(Gtk.Align.CENTER)

        right.pack_start(lbl("Welcome to the Hiddify VPN Installer", "title-label"), False, False, 0)
        right.pack_start(lbl(
            "Universal VPN client powered by sing-box.\n"
            "Supports VLESS, VMess, Trojan, Shadowsocks, Hysteria2, TUIC, Reality.",
            "desc-label"
        ), False, False, 0)

        right.pack_start(Gtk.Separator(), False, False, 4)
        right.pack_start(lbl("Will be installed:", "section-label"), False, False, 0)

        for item in [
            "●  Hiddify VPN GUI — Desktop Mode application",
            "●  HiddifyCli — VPN core with TUN interface support",
            "●  Systemd user service for VPN management",
            "●  Shortcut in app menu (Internet category)",
            "●  Decky plugin for Game Mode (optional)",
        ]:
            right.pack_start(lbl(item, "desc-label"), False, False, 0)

        right.pack_start(lbl(
            "⚠  Requires sudo password. Files are installed to /opt/hiddify/",
            "warning-label"
        ), False, False, 4)
        if self.clean_install and os.path.exists(HIDDIFY_CLI):
            right.pack_start(lbl(
                "Existing Hiddify client, plugin, services and saved VPN state will be removed first.",
                "warning-label"
            ), False, False, 0)

        outer.pack_start(right, True, True, 0)
        self._stack.add_named(outer, "welcome")

    def _page_license(self):
        box = page_box(10)
        box.set_border_width(14)

        box.pack_start(lbl("License Agreement", "section-label"), False, False, 0)
        box.pack_start(lbl(
            "Please read the agreement. You must accept it to continue.",
            "subtitle-label"
        ), False, False, 0)

        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.set_vexpand(True)
        sw.set_shadow_type(Gtk.ShadowType.IN)

        tv = Gtk.TextView()
        tv.set_editable(False)
        tv.set_cursor_visible(False)
        tv.set_wrap_mode(Gtk.WrapMode.WORD)
        tv.set_left_margin(12); tv.set_right_margin(12)
        tv.set_top_margin(8);   tv.set_bottom_margin(8)
        tv.get_buffer().set_text(LICENSE_TEXT)
        sw.add(tv)
        box.pack_start(sw, True, True, 0)

        lic_check = Gtk.CheckButton(
            label="I have read and accept the terms of the license agreement"
        )
        lic_check.connect("toggled", lambda c: self._set_page_complete(
            self.P_LICENSE, c.get_active()
        ))
        box.pack_start(lic_check, False, False, 0)

        self._stack.add_named(box, "license")

    def _page_options(self):
        box = page_box(16)
        box.set_border_width(14)

        box.pack_start(lbl("Installation Components", "section-label"), False, False, 0)

        def frame_with(widget):
            f = Gtk.Frame()
            f.set_shadow_type(Gtk.ShadowType.IN)
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            inner.set_border_width(14)
            inner.pack_start(widget, False, False, 0)
            f.add(inner)
            return f, inner

        base_chk = Gtk.CheckButton(label="Hiddify VPN  (required)")
        base_chk.set_active(True)
        base_chk.set_sensitive(False)
        f, inner = frame_with(base_chk)
        inner.pack_start(lbl(
            "    GUI app, CLI core, system service, menu shortcut",
            "subtitle-label"
        ), False, False, 0)
        box.pack_start(f, False, False, 0)

        has_decky = os.path.isdir(DECKY_DIR)
        has_zip   = os.path.exists(DECKY_ZIP)
        can_decky = has_decky and has_zip

        self._decky_chk = Gtk.CheckButton(
            label="Decky plugin — VPN button in Quick Access Menu (···)"
        )
        self._decky_chk.set_active(can_decky)
        self._decky_chk.set_sensitive(can_decky)
        self._decky_chk.connect("toggled", lambda c: setattr(self, "install_decky", c.get_active()))
        self.install_decky = can_decky

        f2, inner2 = frame_with(self._decky_chk)
        if not has_decky:
            note = "    ⚠  Decky Loader not found. Install Decky Loader first, then reinstall."
        elif not has_zip:
            note = "    ⚠  Plugin file not found in package."
        else:
            note = "    Control VPN from Game Mode without going to Desktop"
        inner2.pack_start(lbl(note, "subtitle-label"), False, False, 0)
        box.pack_start(f2, False, False, 0)

        box.pack_start(lbl("Install path:  /opt/hiddify/", "warning-label"), False, False, 0)

        self._stack.add_named(box, "options")

    def _page_password(self):
        box = page_box(16)
        box.set_border_width(14)

        box.pack_start(lbl("Authentication", "section-label"), False, False, 0)
        box.pack_start(lbl(
            "Installing files to /opt/ requires root privileges.\n"
            "Enter the sudo password for the deck user.",
            "desc-label"
        ), False, False, 0)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        pl = lbl("Sudo password:", "desc-label")
        pl.set_width_chars(13)
        row.pack_start(pl, False, False, 0)

        self._pw = Gtk.Entry()
        self._pw.set_visibility(False)
        self._pw.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        self._pw.set_placeholder_text("Enter password...")
        self._pw.set_hexpand(True)
        self._pw.connect("activate", lambda e: self._verify_pw())
        self._pw.connect("changed",  lambda e: (
            self._pw_status.set_text(""),
            self._set_page_complete(self.P_PASSWORD, False)
        ))
        row.pack_start(self._pw, True, True, 0)
        box.pack_start(row, False, False, 0)

        self._pw_status = lbl("", "warning-label")
        box.pack_start(self._pw_status, False, False, 0)

        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self._verify_btn = Gtk.Button(label="  Verify password  ")
        self._verify_btn.connect("clicked", lambda b: self._verify_pw())
        btn_row.pack_start(self._verify_btn, False, False, 0)
        box.pack_start(btn_row, False, False, 0)

        box.pack_start(lbl(
            "\nPassword is only used during installation and is not stored anywhere.\n"
            "On Steam Deck, set sudo password in: System Settings → User Accounts → Deck.",
            "subtitle-label"
        ), False, False, 0)

        self._stack.add_named(box, "password")

    def _verify_pw(self):
        pw = self._pw.get_text()
        if not pw:
            self._pw_status.set_markup('<span foreground="#fbbf24">⚠  Enter password</span>')
            return
        self._verify_btn.set_sensitive(False)
        self._pw_status.set_markup('<span foreground="#64748b">Verifying...</span>')

        def _check():
            try:
                r = subprocess.run(
                    ["sudo", "-S", "true"],
                    input=pw + "\n", capture_output=True, text=True, timeout=8
                )
                ok = r.returncode == 0
            except Exception:
                ok = False

            def _apply():
                self._verify_btn.set_sensitive(True)
                if ok:
                    self.sudo_password = pw
                    self._pw_status.set_markup(
                        '<span foreground="#4ade80">✓  Password accepted — click Next</span>'
                    )
                    self._set_page_complete(self.P_PASSWORD, True)
                else:
                    self._pw_status.set_markup(
                        '<span foreground="#f87171">✗  Wrong password</span>'
                    )
                    self._set_page_complete(self.P_PASSWORD, False)
            GLib.idle_add(_apply)

        threading.Thread(target=_check, daemon=True).start()

    def _page_progress(self):
        box = page_box(10)
        box.set_border_width(14)

        box.pack_start(lbl("Installing", "section-label"), False, False, 0)

        self._install_step_lbl = lbl("Preparing...", "desc-label")
        box.pack_start(self._install_step_lbl, False, False, 0)

        self._bar = Gtk.ProgressBar()
        self._bar.set_show_text(True)
        self._bar.set_text("0%")
        box.pack_start(self._bar, False, False, 0)

        box.pack_start(lbl("Installer output:", "subtitle-label"), False, False, 0)

        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.set_vexpand(True)
        sw.set_shadow_type(Gtk.ShadowType.IN)
        self._log_sw = sw

        self._log_tv = Gtk.TextView()
        self._log_tv.set_editable(False)
        self._log_tv.set_cursor_visible(False)
        self._log_tv.set_wrap_mode(Gtk.WrapMode.CHAR)
        self._log_tv.set_left_margin(10); self._log_tv.set_right_margin(10)
        self._log_tv.set_top_margin(6);   self._log_tv.set_bottom_margin(6)
        self._log_tv.get_style_context().add_class("log-view")
        self._log_buf = self._log_tv.get_buffer()
        sw.add(self._log_tv)
        box.pack_start(sw, True, True, 0)

        self._stack.add_named(box, "progress")

    def _page_finish(self):
        box = page_box(16)
        box.set_border_width(14)
        box.set_valign(Gtk.Align.CENTER)
        box.set_vexpand(True)

        img = icon_image(64)
        if img:
            img.set_halign(Gtk.Align.CENTER)
            box.pack_start(img, False, False, 0)

        self._fin_title = lbl("", xalign=0.5, markup=True)
        self._fin_title.set_justify(Gtk.Justification.CENTER)
        box.pack_start(self._fin_title, False, False, 0)

        self._fin_desc = lbl("", "desc-label", xalign=0.5)
        self._fin_desc.set_justify(Gtk.Justification.CENTER)
        box.pack_start(self._fin_desc, False, False, 0)

        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        btn_row.set_halign(Gtk.Align.CENTER)
        btn_row.set_margin_top(16)

        self._launch_btn = Gtk.Button(label="  ▶  Launch Hiddify GUI  ")
        self._launch_btn.connect("clicked", lambda b: subprocess.Popen(["/opt/hiddify/hiddify-gui"]))
        btn_row.pack_start(self._launch_btn, False, False, 0)
        box.pack_start(btn_row, False, False, 0)

        self._stack.add_named(box, "finish")

    # ── Installation logic ─────────────────────────────────────────────────────

    def _start_install(self):
        self._log_buf.set_text("")
        self._bar.set_fraction(0.0)
        self._bar.set_text("0%")
        self._install_step_lbl.set_text("Starting installer...")
        threading.Thread(target=self._run_install, daemon=True).start()
        return False

    def _run_install(self):
        total = 6 if self.install_decky else 5
        step_map = {"[1/5]": 1, "[2/5]": 2, "[3/5]": 3, "[4/5]": 4, "[5/5]": 5}

        def set_bar(frac):
            GLib.idle_add(lambda: (
                self._bar.set_fraction(min(frac, 1.0)) or
                self._bar.set_text(f"{int(min(frac, 1.0)*100)}%")
            ) and False)

        _SKIP_PREFIXES = ("job-working-directory:", "shell-init:", "bash: cannot set")

        def log(line):
            clean = ANSI_RE.sub("", line).rstrip()
            if clean and not any(clean.lstrip().startswith(p) for p in _SKIP_PREFIXES):
                GLib.idle_add(self._append_log, clean)

        def step(text):
            GLib.idle_add(self._install_step_lbl.set_text, text)

        try:
            proc = subprocess.Popen(
                ["sudo", "-S", "bash", INSTALL_SH],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True, bufsize=1,
                cwd="/tmp",
                env={
                    **os.environ,
                    "HIDDIFY_WIZARD": "1",
                    "HIDDIFY_CLEAN_INSTALL": "1" if self.clean_install else os.environ.get("HIDDIFY_CLEAN_INSTALL", ""),
                },
            )
            proc.stdin.write(self.sudo_password + "\n")
            proc.stdin.flush()
            proc.stdin.close()

            for line in proc.stdout:
                log(line)
                for marker, num in step_map.items():
                    if marker in line:
                        set_bar(num / total)
                clean = ANSI_RE.sub("", line).strip()
                if clean.startswith("✓") or clean.startswith("→"):
                    text = re.sub(r'^[✓→!\s]+', '', clean).strip()
                    if text:
                        step(text)

            proc.wait()
            success = proc.returncode == 0
        except Exception as e:
            log(f"Launch error: {e}")
            success = False

        if success and self.install_decky and os.path.exists(DECKY_ZIP):
            step("Installing Decky plugin...")
            log("\n→ Installing Decky plugin...")
            try:
                r = subprocess.run(
                    ["sudo", "-S", "unzip", "-o", DECKY_ZIP, "-d", DECKY_DIR],
                    input=self.sudo_password + "\n",
                    capture_output=True, text=True,
                )
                subprocess.run(
                    ["sudo", "-S", "chown", "-R", "deck:deck",
                     os.path.join(DECKY_DIR, "decky-hiddify")],
                    input=self.sudo_password + "\n", capture_output=True, text=True,
                )
                subprocess.run(
                    ["sudo", "-S", "systemctl", "restart", "plugin_loader"],
                    input=self.sudo_password + "\n", capture_output=True, text=True,
                )
                log("✓ Decky plugin installed" if r.returncode == 0
                    else f"✗ Decky error: {r.stderr.strip()}")
            except Exception as e:
                log(f"✗ Decky: {e}")

        set_bar(1.0)
        self.install_ok = success
        GLib.idle_add(self._finish, success)

    def _append_log(self, line):
        end = self._log_buf.get_end_iter()
        self._log_buf.insert(end, line + "\n")
        adj = self._log_sw.get_vadjustment()
        adj.set_value(adj.get_upper())

    def _finish(self, ok):
        if ok:
            self._fin_title.set_markup(
                '<span foreground="#4ade80" font_size="large" font_weight="bold">'
                '✓  Hiddify VPN installed successfully!</span>'
            )
            self._fin_desc.set_text(
                "Hiddify will appear in the app menu → Internet.\n"
                "Launch the GUI, add your VPN config and connect."
            )
            self._launch_btn.set_visible(True)
        else:
            self._fin_title.set_markup(
                '<span foreground="#f87171" font_size="large" font_weight="bold">'
                '✗  Installation failed</span>'
            )
            self._fin_desc.set_text(
                "Check the log on the previous page.\n"
                "Make sure the sudo password is correct and /opt/ is accessible."
            )
            self._launch_btn.set_visible(False)
        # переходим на страницу финиша
        self._current = self.P_FINISH
        self._stack.set_visible_child_name("finish")
        self._refresh_nav()


# ── Already-installed window ───────────────────────────────────────────────────

class AlreadyInstalledWindow(Gtk.Window):
    """Shown when Hiddify is already installed. Choose: reinstall or uninstall."""

    def __init__(self):
        super().__init__(title="Hiddify VPN")
        w, h = adaptive_size()
        self.set_default_size(min(w, 560), min(h, 380))
        self.set_resizable(True)
        self.set_size_request(1, 1)
        self.set_position(Gtk.WindowPosition.CENTER)
        if os.path.exists(ICON_PATH):
            self.set_icon_from_file(ICON_PATH)
        self.connect("delete-event", lambda *_: Gtk.main_quit())
        self.connect("configure-event", lambda w, e: None)

        self._action  = "reinstall"
        self._sudo_pw = ""

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        root.get_style_context().add_class("page-box")
        self.add(root)

        # Header
        hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        hdr.set_border_width(14)
        img = icon_image(48)
        if img:
            hdr.pack_start(img, False, False, 0)
        tb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        tb.set_valign(Gtk.Align.CENTER)
        tb.pack_start(lbl("Hiddify VPN", "title-label"), False, False, 0)
        tb.pack_start(lbl("is already installed on this device", "subtitle-label"), False, False, 0)
        hdr.pack_start(tb, True, True, 0)
        root.pack_start(hdr, False, False, 0)

        root.pack_start(Gtk.Separator(), False, False, 0)

        # Content
        cnt = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        cnt.set_border_width(16)
        cnt.set_vexpand(True)

        cnt.pack_start(lbl(
            "Installation found in /opt/hiddify/\nChoose an action:",
            "desc-label"
        ), False, False, 0)

        self._r_reinstall = Gtk.RadioButton.new_with_label(None, "Reinstall / Update")
        self._r_reinstall.connect("toggled", self._on_radio)

        self._r_uninstall = Gtk.RadioButton.new_with_label_from_widget(
            self._r_reinstall, "Uninstall Hiddify completely"
        )
        self._r_uninstall.connect("toggled", self._on_radio)

        radio_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        radio_box.set_border_width(4)

        for r, sublabel in [
            (self._r_reinstall, "Runs a clean reinstall: removes old client, plugin and saved state, then installs again"),
            (self._r_uninstall, "Removes /opt/hiddify/, plugin, services, shortcuts and saved state"),
        ]:
            rb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            rb.pack_start(r, False, False, 0)
            sub = lbl("    " + sublabel, "subtitle-label")
            sub.set_margin_start(28)
            rb.pack_start(sub, False, False, 0)
            radio_box.pack_start(rb, False, False, 0)

        cnt.pack_start(radio_box, False, False, 0)

        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        btn_row.set_halign(Gtk.Align.END)
        btn_row.set_margin_top(8)

        btn_cancel = Gtk.Button(label="  Cancel  ")
        btn_cancel.connect("clicked", lambda b: Gtk.main_quit())

        self._btn_next = Gtk.Button(label="  Next →  ")
        self._btn_next.get_style_context().add_class("btn-primary")
        self._btn_next.connect("clicked", self._on_next)

        btn_row.pack_start(btn_cancel, False, False, 0)
        btn_row.pack_start(self._btn_next, False, False, 0)
        cnt.pack_start(btn_row, False, False, 0)

        root.pack_start(cnt, True, True, 0)

    def _on_radio(self, btn):
        self._action = "reinstall" if self._r_reinstall.get_active() else "uninstall"

    def _on_next(self, btn):
        if self._action == "reinstall":
            self.hide()
            win = HiddifyWizard(clean_install=True)
            win.show_all()
        else:
            self._do_uninstall_flow()

    # ── Uninstall flow ────────────────────────────────────────────────────────

    def _do_uninstall_flow(self):
        self.hide()

        pw_win = Gtk.Window(title="Uninstall — Hiddify VPN")
        pw_win.set_default_size(420, 240)
        pw_win.set_resizable(True)
        pw_win.set_size_request(1, 1)
        pw_win.set_position(Gtk.WindowPosition.CENTER)
        if os.path.exists(ICON_PATH):
            pw_win.set_icon_from_file(ICON_PATH)
        pw_win.connect("delete-event", lambda *_: Gtk.main_quit())

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        vbox.get_style_context().add_class("page-box")
        vbox.set_border_width(16)
        pw_win.add(vbox)

        vbox.pack_start(lbl("Enter sudo password to uninstall:", "section-label"), False, False, 0)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        pl = lbl("Password:", "desc-label")
        pl.set_width_chars(9)
        row.pack_start(pl, False, False, 0)
        pw_entry = Gtk.Entry()
        pw_entry.set_visibility(False)
        pw_entry.set_hexpand(True)
        pw_entry.set_placeholder_text("sudo password...")
        row.pack_start(pw_entry, True, True, 0)
        vbox.pack_start(row, False, False, 0)

        status_lbl = lbl("", "warning-label")
        vbox.pack_start(status_lbl, False, False, 0)

        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        btn_row.set_halign(Gtk.Align.END)
        btn_back = Gtk.Button(label="  ← Back  ")
        btn_del  = Gtk.Button(label="  Uninstall  ")
        btn_del.get_style_context().add_class("btn-primary")

        def go_back(_):
            pw_win.destroy()
            self.show_all()

        def do_delete(_):
            pw = pw_entry.get_text()
            if not pw:
                status_lbl.set_markup('<span foreground="#fbbf24">⚠  Enter password</span>')
                return
            btn_del.set_sensitive(False)
            btn_back.set_sensitive(False)
            status_lbl.set_markup('<span foreground="#64748b">Verifying password...</span>')
            while Gtk.events_pending():
                Gtk.main_iteration()

            r = subprocess.run(["sudo", "-S", "true"],
                               input=pw + "\n", capture_output=True, text=True, timeout=8)
            if r.returncode != 0:
                status_lbl.set_markup('<span foreground="#f87171">✗  Wrong password</span>')
                btn_del.set_sensitive(True)
                btn_back.set_sensitive(True)
                return

            status_lbl.set_markup('<span foreground="#64748b">Removing...</span>')
            while Gtk.events_pending():
                Gtk.main_iteration()

            result = [None]

            def _uninstall_thread():
                cmds = [
                    ["sudo", "-S", "bash", "-c",
                     "su -l deck -c 'XDG_RUNTIME_DIR=/run/user/1000 "
                     "systemctl --user stop hiddify 2>/dev/null; "
                     "systemctl --user disable hiddify 2>/dev/null' 2>/dev/null || true"],
                    ["sudo", "-S", "rm", "-f",
                     "/home/deck/.config/systemd/user/hiddify.service"],
                    ["sudo", "-S", "rm", "-rf", "/opt/hiddify"],
                    ["sudo", "-S", "rm", "-rf", APP_DIR, SYSTEM_APP_DIR],
                    ["sudo", "-S", "rm", "-f",
                     "/home/deck/.local/share/applications/hiddify.desktop",
                     "/home/deck/.local/share/icons/hicolor/256x256/apps/hiddify.png",
                     "/home/deck/Desktop/hiddify.desktop"],
                    ["sudo", "-S", "rm", "-rf",
                     "/home/deck/homebrew/plugins/decky-hiddify"],
                    ["sudo", "-S", "bash", "-c",
                     "su -l deck -c "
                     "'gtk-update-icon-cache ~/.local/share/icons/hicolor/ 2>/dev/null' "
                     "2>/dev/null || true"],
                ]
                ok = True
                for cmd in cmds:
                    r2 = subprocess.run(cmd, input=pw + "\n",
                                        capture_output=True, text=True)
                    if r2.returncode not in (0, 1):
                        ok = False
                result[0] = ok
                GLib.idle_add(_done, ok)

            def _done(ok):
                pw_win.destroy()
                res_win = Gtk.Window(title="Hiddify VPN")
                res_win.set_default_size(380, 200)
                res_win.set_resizable(True)
                res_win.set_size_request(1, 1)
                res_win.set_position(Gtk.WindowPosition.CENTER)
                if os.path.exists(ICON_PATH):
                    res_win.set_icon_from_file(ICON_PATH)
                res_win.connect("delete-event", lambda *_: Gtk.main_quit())

                rb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
                rb.get_style_context().add_class("page-box")
                rb.set_border_width(32)
                rb.set_valign(Gtk.Align.CENTER)
                res_win.add(rb)

                if ok:
                    rb.pack_start(lbl("✓  Hiddify VPN removed", "ok-label", xalign=0.5), False, False, 0)
                    rb.pack_start(lbl(
                        "All files, service and shortcuts have been removed.",
                        "subtitle-label", xalign=0.5
                    ), False, False, 0)
                else:
                    rb.pack_start(lbl("✗  Removal failed", "err-label", xalign=0.5), False, False, 0)

                close_btn = Gtk.Button(label="  Close  ")
                close_btn.set_halign(Gtk.Align.CENTER)
                close_btn.connect("clicked", lambda b: Gtk.main_quit())
                rb.pack_start(close_btn, False, False, 0)
                res_win.show_all()

            threading.Thread(target=_uninstall_thread, daemon=True).start()

        btn_back.connect("clicked", go_back)
        btn_del.connect("clicked", do_delete)
        pw_entry.connect("activate", do_delete)

        btn_row.pack_start(btn_back, False, False, 0)
        btn_row.pack_start(btn_del, False, False, 0)
        vbox.pack_start(btn_row, False, False, 0)

        pw_win.show_all()


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        print("No display found. Run in Desktop Mode or:")
        print(f"  sudo bash {INSTALL_SH}")
        sys.exit(1)

    if os.getuid() == 0:
        print("Do not run the wizard as root.")
        sys.exit(1)

    apply_css()

    w, h = adaptive_size()
    if os.path.exists(HIDDIFY_CLI) and os.environ.get("HIDDIFY_CLEAN_INSTALL") != "1":
        win = AlreadyInstalledWindow()
        win.show_all()
        win.resize(min(w, 560), min(h, 380))
    else:
        win = HiddifyWizard()
        win.show_all()
        win.resize(w, h)

    Gtk.main()


if __name__ == "__main__":
    main()
