import os
import json
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, font as tkfont

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_LOGO_PATH = os.path.join(_SCRIPT_DIR, "ugreen_logo.png")
_ICO_PATH = os.path.join(_SCRIPT_DIR, "ugreen_logo.ico")

_CONFIG_DIR = _SCRIPT_DIR
_CONFIG_PATH = os.path.join(_CONFIG_DIR, "settings.json")

_PERSIST_KEYS = (
    "eq_preset", "anc_raw", "spatial_audio", "game_mode", "wind_noise_reduction",
    "dual_link", "hires_audio", "prompt_volume", "broadcast_voice",
)

_STATUS_POLL_MS = 3000

try:
    import ctypes
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("UGREEN.StudioPro.Control")
except Exception:
    pass

from ugreen_client import (
    UgreenClient, list_candidate_ports,
    EQ_CLASSIC, EQ_CLASSICAL, EQ_JAZZ, EQ_ROCK, EQ_ELECTRONIC, EQ_BASS, EQ_POPULAR, EQ_TREBLE,
    ANC_LEVEL_ADAPTIVE, ANC_LEVEL_GENTLE, ANC_LEVEL_GENERAL, ANC_LEVEL_ULTRA,
    VOICE_LANG_ENGLISH, VOICE_LANG_CHINESE, VOICE_LANG_RINGTONE,
    ACTION_NO_ACTION, ACTION_NEXT_TRACK, ACTION_PREV_TRACK, ACTION_GAME_MODE,
    ACTION_ANC_CYCLE, ACTION_SPATIAL_AUDIO,
)

EQ_PRESETS = [
    ("Classic", EQ_CLASSIC), ("Classical", EQ_CLASSICAL), ("Jazz", EQ_JAZZ),
    ("Rock", EQ_ROCK), ("Electronic", EQ_ELECTRONIC), ("Bass", EQ_BASS),
    ("Popular", EQ_POPULAR), ("Treble", EQ_TREBLE),
]

ANC_LEVELS = [
    ("Adaptive", ANC_LEVEL_ADAPTIVE), ("Gentle", ANC_LEVEL_GENTLE),
    ("General", ANC_LEVEL_GENERAL), ("Ultra", ANC_LEVEL_ULTRA),
]

BUTTON_ACTIONS = [
    ("No action", ACTION_NO_ACTION),
    ("Next track", ACTION_NEXT_TRACK),
    ("Previous track", ACTION_PREV_TRACK),
    ("Game mode", ACTION_GAME_MODE),
    ("ANC cycle", ACTION_ANC_CYCLE),
    ("Spatial audio", ACTION_SPATIAL_AUDIO),
]

_MUTUALLY_EXCLUSIVE = {"Hi-Res audio", "Dual link"}

# Resending these two always drops the link to renegotiate (confirmed on real
# hardware - even resending the value already in effect disconnects). They can
# only be safely restored on the app's very first connect of a session (one
# expected disconnect/reconnect there); auto-correcting them on every later
# reconnect would recreate an endless resend-disconnect-reconnect loop.
_DISRUPTIVE_KEYS = {"hires_audio", "dual_link"}


def _push_saved_settings(client: UgreenClient, saved: dict):
    if "eq_preset" in saved:
        client.set_eq_preset(saved["eq_preset"])
        time.sleep(0.15)
    if "anc_raw" in saved:
        anc_raw = saved["anc_raw"]
        if anc_raw == 0xA0:
            client.set_anc_off()
        elif anc_raw == 0xA2:
            client.set_anc_ambient()
        else:
            client.set_anc_level(anc_raw)
        time.sleep(0.15)
    if "spatial_audio" in saved:
        client.set_spatial_audio(saved["spatial_audio"])
        time.sleep(0.15)
    if "game_mode" in saved:
        client.set_game_mode(saved["game_mode"])
        time.sleep(0.15)
    if "wind_noise_reduction" in saved:
        client.set_wind_noise_reduction(saved["wind_noise_reduction"])
        time.sleep(0.15)
    if "hires_audio" in saved:
        client.set_hires_audio(saved["hires_audio"])
        time.sleep(0.15)
    if "dual_link" in saved:
        client.set_dual_link(saved["dual_link"])
        time.sleep(0.15)
    if "prompt_volume" in saved:
        client.set_prompt_volume(saved["prompt_volume"])
        time.sleep(0.15)
    if "broadcast_voice" in saved:
        client.set_broadcast_voice_language(saved["broadcast_voice"])
        time.sleep(0.15)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("UGREEN Studio Pro Control")
        self.resizable(False, False)
        self.client: UgreenClient | None = None

        if os.path.exists(_ICO_PATH):
            try:
                self.iconbitmap(default=_ICO_PATH)
            except tk.TclError:
                pass
        if os.path.exists(_LOGO_PATH):
            try:
                self._icon_img = tk.PhotoImage(file=_LOGO_PATH).subsample(4, 4)
                self.iconphoto(True, self._icon_img)
            except tk.TclError:
                pass

        self.style = ttk.Style(self)
        default_font = tkfont.nametofont("TkDefaultFont")
        self.style.configure("Bold.TButton", font=(default_font.actual("family"), default_font.actual("size"), "bold"))

        self.eq_buttons = {}
        self.anc_mode_buttons = {}
        self.anc_level_buttons = {}
        self.toggle_buttons = {}
        self.voice_buttons = {}
        self._status_refresh_busy = False
        self._poll_after_id = None
        self._reconnect_after_id = None
        self._reconnect_attempts = 0
        self._last_port_label = None
        self._consecutive_status_failures = 0
        self._connecting = False
        self._settings_applied_this_session = False
        self._saved_settings = self._load_settings()

        self._build_connection_bar()
        self._build_eq_section()
        self._build_anc_section()
        self._build_toggles_section()
        self._build_voice_section()
        self._build_sharing_section()
        self._build_buttons_section()
        self._build_volume_buttons_section()

        self._log_lines = []
        self.log_window = None
        self.log_text = None

        self.status = tk.StringVar(value="Not connected")

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(200, self._auto_connect)

    def _build_connection_bar(self):
        frame = ttk.LabelFrame(self, text="Connection")
        frame.grid(row=0, column=0, columnspan=4, padx=10, pady=10, sticky="we")

        ttk.Label(frame, text="Device:").grid(row=0, column=0, padx=5, pady=5)
        self.port_var = tk.StringVar()
        self.port_combo = ttk.Combobox(frame, textvariable=self.port_var, width=30, state="readonly")
        self.port_combo.grid(row=0, column=1, padx=5)

        ttk.Button(frame, text="Refresh ports", command=self._refresh_ports).grid(row=0, column=2, padx=5)
        self.connect_btn = ttk.Button(frame, text="Connect", command=self._toggle_connect)
        self.connect_btn.grid(row=0, column=3, padx=5)
        ttk.Button(frame, text="Refresh status", command=self._refresh_status).grid(row=0, column=4, padx=5)
        ttk.Button(frame, text="Log", command=self._open_log_window).grid(row=0, column=5, padx=5)

        self.battery_var = tk.StringVar(value="Battery: -")
        ttk.Label(frame, textvariable=self.battery_var, foreground="gray", width=14, anchor="w").grid(
            row=0, column=6, padx=(15, 5)
        )

        self._port_by_label = {}
        self._refresh_ports()

    def _refresh_ports(self):
        candidates = list_candidate_ports()
        labels = []
        self._port_by_label = {}
        preferred = None
        for device, _description, friendly in candidates:
            label = f"{device} - {friendly}" if friendly else f"{device} - (unknown device)"
            labels.append(label)
            self._port_by_label[label] = device
            if friendly and "ugreen" in friendly.lower() and "studio" in friendly.lower():
                preferred = label

        self.port_combo["values"] = labels
        if labels:
            current = self.port_var.get()
            if current in labels:
                self.port_var.set(current)
            elif preferred:
                self.port_var.set(preferred)
            else:
                self.port_var.set(labels[-1])
        else:
            self.port_var.set("")

    def _selected_port(self):
        return self._port_by_label.get(self.port_var.get())

    def _open_client_async(self, port, on_success, on_failure, timeout_ms=6000):
        # Opening the serial port is itself a blocking OS call that can stall on a
        # flaky virtual Bluetooth SPP driver (e.g. right after a disconnect, before
        # Windows has fully released the COM port) - and unlike ser.write(), the
        # serial.Serial() constructor has no configurable timeout at all, so it can
        # hang indefinitely with no exception. Never do this on the Tk thread, and
        # never let a hung open leave the caller waiting forever: race it against a
        # hard deadline and report failure if the deadline wins.
        state = {"done": False}
        lock = threading.Lock()

        def finish(client=None, exc=None):
            with lock:
                if state["done"]:
                    if client is not None:
                        # Worker finished late, after we'd already given up on it -
                        # don't leak an open port that the next retry might need.
                        threading.Thread(target=client.close, daemon=True).start()
                    return
                state["done"] = True
            if client is not None:
                on_success(client)
            else:
                on_failure(exc)

        def worker():
            try:
                client = UgreenClient(port)
            except Exception as e:
                # Python clears the 'except ... as e' binding once this block ends, so
                # a lambda that only reads 'e' when self.after() later fires would hit
                # NameError. Bind it as a default arg to capture the value now.
                self.after(0, lambda e=e: finish(exc=e))
                return
            self.after(0, lambda: finish(client=client))

        threading.Thread(target=worker, daemon=True).start()
        self.after(timeout_ms, lambda: finish(exc=TimeoutError("port open timed out")))

    def _auto_connect(self):
        if self.client is not None or self._connecting or not self._selected_port():
            return
        port = self._selected_port()
        label = self.port_var.get()
        self._connecting = True

        def on_success(client):
            self._connecting = False
            self.client = client
            self.connect_btn.config(text="Disconnect")
            self._last_port_label = label
            self._set_status(f"Auto-connected to {label}")
            self._on_connected()

        def on_failure(e):
            self._connecting = False
            self._set_status(f"Auto-connect failed: {e}")

        self._open_client_async(port, on_success, on_failure)

    def _toggle_connect(self):
        self._cancel_reconnect()
        if self.client is None:
            if self._connecting:
                return
            port = self._selected_port()
            if not port:
                messagebox.showwarning("No port selected", "No Bluetooth SPP COM port detected. Pair the earbuds first, then click Refresh ports.")
                return
            label = self.port_var.get()
            self._connecting = True

            def on_success(client):
                self._connecting = False
                self.client = client
                self.connect_btn.config(text="Disconnect")
                self._last_port_label = label
                self._set_status(f"Connected to {label}")
                self._on_connected()

            def on_failure(e):
                self._connecting = False
                messagebox.showerror("Connection failed", str(e))

            self._open_client_async(port, on_success, on_failure)
        else:
            self._stop_status_polling()
            client = self.client
            client.remove_listener(self._on_unsolicited_frame)
            client.on_frame_log = None
            client.on_disconnect = None
            self.client = None
            self.connect_btn.config(text="Connect")
            self._set_status("Not connected")
            threading.Thread(target=client.close, daemon=True).start()

    def _load_settings(self):
        try:
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_settings(self, status):
        changed = False
        for key in _PERSIST_KEYS:
            if key in status and status[key] is not None and self._saved_settings.get(key) != status[key]:
                self._saved_settings[key] = status[key]
                changed = True
        if not changed:
            return
        try:
            os.makedirs(_CONFIG_DIR, exist_ok=True)
            with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self._saved_settings, f)
        except Exception:
            pass

    def _on_connected(self):
        self._consecutive_status_failures = 0
        client = self.client
        client.add_listener(self._on_unsolicited_frame)
        client.on_frame_log = self._on_frame_log
        # Bind the callback to this specific client instance. Two different code
        # paths (the write watchdog and a failed status poll) can each independently
        # decide "this client died" and schedule _handle_disconnect around the same
        # time; if a reconnect races ahead and replaces self.client in between, a
        # late/stale notification from the OLD client must never tear down the NEW
        # one just because self.client happened to be truthy again.
        client.on_disconnect = lambda: self.after(0, lambda: self._handle_disconnect(client))
        # The flag must be set to True on the first connect NO MATTER WHAT, even if
        # there was nothing saved yet to push - otherwise, on a fresh install with no
        # settings.json, the first connect populates _saved_settings from the status
        # it just read, and the *second* connect (the very next reconnect) would then
        # wrongly qualify as "first".
        first_connect_of_session = not self._settings_applied_this_session
        self._settings_applied_this_session = True
        self._sync_settings_after_connect(client, first_connect_of_session)
        self._start_status_polling()

    def _handle_disconnect(self, client=None):
        if client is not None and client is not self.client:
            return
        if self.client is None:
            return
        self._stop_status_polling()
        client = self.client
        try:
            client.remove_listener(self._on_unsolicited_frame)
            client.on_frame_log = None
            client.on_disconnect = None
        except Exception:
            pass
        self.client = None
        threading.Thread(target=client.close, daemon=True).start()
        self.connect_btn.config(text="Connect")
        self._set_status("Device disconnected - reconnecting...")
        self._reconnect_attempts = 0
        # Give the device/OS a real head start on its own reconnection before we
        # touch the port ourselves.
        self._schedule_reconnect(5000)

    def _cancel_reconnect(self):
        if self._reconnect_after_id is not None:
            self.after_cancel(self._reconnect_after_id)
            self._reconnect_after_id = None

    def _schedule_reconnect(self, delay_ms):
        self._cancel_reconnect()
        self._reconnect_after_id = self.after(delay_ms, self._attempt_reconnect)

    def _attempt_reconnect(self):
        self._reconnect_after_id = None
        if self.client is not None or self._connecting:
            return
        self._refresh_ports()
        if self._last_port_label and self._last_port_label in self._port_by_label:
            self.port_var.set(self._last_port_label)
            port = self._port_by_label[self._last_port_label]
        else:
            port = self._selected_port()

        if not port:
            self._reconnect_give_up_or_retry()
            return

        label = self.port_var.get()
        self._connecting = True

        def on_success(client):
            self._connecting = False
            if self.client is not None:
                # a manual connect already won the race while this attempt was in flight
                threading.Thread(target=client.close, daemon=True).start()
                return
            self.client = client
            self.connect_btn.config(text="Disconnect")
            self._last_port_label = label
            self._set_status(f"Reconnected to {label}")
            self._on_connected()

        def on_failure(e):
            self._connecting = False
            self._reconnect_give_up_or_retry()

        self._open_client_async(port, on_success, on_failure)

    def _reconnect_give_up_or_retry(self):
        self._reconnect_attempts += 1
        # Keep retrying forever - the earbuds may stay off/out of range for a long
        # time (e.g. overnight), and the whole point of this feature is that the app
        # picks them back up without the user having to click Connect. Back off to a
        # slower cadence after the initial burst so an extended absence doesn't mean
        # hammering the port every 5s indefinitely.
        if self._reconnect_attempts <= 15:
            self._set_status("Device disconnected - reconnecting...")
            self._schedule_reconnect(5000)
        else:
            self._set_status("Device disconnected - waiting for it to come back...")
            self._schedule_reconnect(30000)

    def _on_unsolicited_frame(self, cmd, payload):
        # Runs on the client's background reader thread. Any frame that wasn't
        # claimed by one of our own pending requests means the earbuds pushed it
        # on their own (setting changed from the phone, a device joined/left, etc).
        if cmd in (0x04, 0x0D):
            self.after(0, lambda: self._refresh_status(warn_if_disconnected=False))

    def _sync_settings_after_connect(self, client, allow_disruptive):
        # The earbuds reset some settings (ANC in particular) back to their own
        # default on every fresh connection, independent of anything the app does.
        # Read what the device actually has right now and correct any drift from
        # what we last saved - except hires_audio/dual_link, which always disconnect
        # the link when (re)sent (even to their current value), so those are only
        # restored on the very first connect of this app session (one expected
        # disconnect/reconnect there is fine); auto-correcting them on every later
        # reconnect would recreate an endless resend-disconnect-reconnect loop.
        if not self._saved_settings:
            self._refresh_status(warn_if_disconnected=False)
            return

        self._set_status("Syncing settings...")

        def worker():
            try:
                status = client.query_status()
            except Exception as e:
                self.after(0, lambda e=e: self._on_status_error(f"Status query failed: {e}", client))
                return
            if "error" in status:
                self.after(0, lambda: self._apply_status(status, None, client))
                return

            to_push = {}
            for key, value in self._saved_settings.items():
                if key not in _PERSIST_KEYS:
                    continue
                if key in _DISRUPTIVE_KEYS:
                    if not allow_disruptive:
                        continue
                if status.get(key) != value:
                    to_push[key] = value

            if to_push:
                try:
                    _push_saved_settings(client, to_push)
                except Exception as e:
                    self.after(0, lambda e=e: self._set_status(f"Failed to sync settings: {e}"))
                    return

            self.after(0, lambda: self._refresh_status(warn_if_disconnected=False))

        threading.Thread(target=worker, daemon=True).start()

    def _start_status_polling(self):
        self._poll_status()

    def _stop_status_polling(self):
        if self._poll_after_id is not None:
            self.after_cancel(self._poll_after_id)
            self._poll_after_id = None

    def _poll_status(self):
        if self.client is not None:
            self._refresh_status(warn_if_disconnected=False)
        self._poll_after_id = self.after(_STATUS_POLL_MS, self._poll_status)

    def _set_status(self, text: str):
        self.status.set(text)

    def _mark_active(self, group: dict, key):
        for k, btn in group.items():
            btn.configure(style="Bold.TButton" if k == key else "TButton")

    def _fixed_button(self, parent, text, command, width=108, height=26):
        holder = tk.Frame(parent, width=width, height=height)
        holder.grid_propagate(False)
        holder.pack_propagate(False)
        btn = ttk.Button(holder, text=text, command=command)
        btn.pack(fill="both", expand=True)
        return holder, btn

    def _run(self, label: str, fn):
        if self.client is None:
            messagebox.showwarning("Not connected", "Connect to a device first.")
            return
        client = self.client
        self._set_status(f"{label}: sending...")

        def worker():
            try:
                frame = fn(client)
            except Exception as e:
                self.after(0, lambda e=e: self._set_status(f"{label}: FAILED - {e}"))
                self.after(0, lambda e=e: messagebox.showerror("Command failed", str(e)))
                return
            self.after(0, lambda: self._set_status(f"{label}: sent {frame.hex().upper()}"))

        threading.Thread(target=worker, daemon=True).start()

    def _refresh_status(self, warn_if_disconnected=True):
        if self.client is None:
            if warn_if_disconnected:
                messagebox.showwarning("Not connected", "Connect to a device first.")
            return
        if self._status_refresh_busy:
            return
        self._status_refresh_busy = True
        client = self.client
        self._set_status("Refreshing status...")

        def worker():
            try:
                status = client.query_status()
            except Exception as e:
                self.after(0, lambda e=e: self._on_status_error(f"Status query failed: {e}", client))
                return
            try:
                devices = client.query_connected_devices()
            except Exception:
                devices = None
            self.after(0, lambda: self._apply_status(status, devices, client))

        threading.Thread(target=worker, daemon=True).start()

    def _on_status_error(self, message, client):
        self._status_refresh_busy = False
        self._set_status(message)
        self._handle_disconnect(client)

    def _apply_status(self, status, devices, client):
        self._status_refresh_busy = False
        if "error" in status:
            self._set_status(f"Status query: {status['error']} (raw={status.get('raw', '')})")
            if client is self.client:
                self._consecutive_status_failures += 1
                if self._consecutive_status_failures >= 2:
                    self._handle_disconnect(client)
            return
        self._consecutive_status_failures = 0
        summary = (
            f"ANC={status.get('anc', '?')}  EQ={status.get('eq', '?')}  "
            f"Game={'On' if status.get('game_mode') else 'Off'}  "
            f"Spatial={'On' if status.get('spatial_audio') else 'Off'}  "
            f"Wind={'On' if status.get('wind_noise_reduction') else 'Off'}"
        )
        self._set_status(summary)

        battery = status.get("battery")
        self.battery_var.set(f"Battery: {battery}%" if battery is not None else "Battery: N/A")

        eq_val = status.get("eq_preset")
        if eq_val in self.eq_buttons:
            self._mark_active(self.eq_buttons, eq_val)

        anc_raw = status.get("anc_raw")
        if anc_raw is not None:
            mode = {0xA0: "off", 0xA2: "ambient"}.get(anc_raw, "on")
            if mode in self.anc_mode_buttons:
                self._mark_active(self.anc_mode_buttons, mode)
            if anc_raw in self.anc_level_buttons:
                self._mark_active(self.anc_level_buttons, anc_raw)

        for name, key in (
            ("Spatial audio", "spatial_audio"),
            ("Game mode", "game_mode"),
            ("Wind noise reduction", "wind_noise_reduction"),
            ("Dual link", "dual_link"),
            ("Hi-Res audio", "hires_audio"),
        ):
            if key in status and name in self.toggle_buttons:
                self._mark_active(self.toggle_buttons[name], "on" if status[key] else "off")

        if devices:
            self.connected_devices_var.set("Connected: " + ", ".join(devices))
        elif devices is not None:
            self.connected_devices_var.set("Connected: -")
        else:
            self.connected_devices_var.set("Connected: ?")

        voice_val = status.get("broadcast_voice")
        if voice_val in self.voice_buttons:
            self._mark_active(self.voice_buttons, voice_val)

        prompt_volume = status.get("prompt_volume")
        if prompt_volume is not None:
            self.vol_var.set(prompt_volume)

        self._save_settings(status)

    def _build_eq_section(self):
        frame = ttk.LabelFrame(self, text="EQ preset")
        frame.grid(row=1, column=0, columnspan=4, padx=10, pady=5, sticky="we")
        for col in range(4):
            frame.columnconfigure(col, weight=1, uniform="eqcol")
        for i, (name, value) in enumerate(EQ_PRESETS):
            holder, btn = self._fixed_button(
                frame, name, lambda v=value, n=name: self._click_eq(v, n)
            )
            holder.grid(row=i // 4, column=i % 4, padx=3, pady=3)
            self.eq_buttons[value] = btn

    def _click_eq(self, value, name):
        self._run(f"EQ {name}", lambda c: c.set_eq_preset(value))
        self._mark_active(self.eq_buttons, value)

    def _build_anc_section(self):
        frame = ttk.LabelFrame(self, text="ANC")
        frame.grid(row=2, column=0, columnspan=4, padx=10, pady=5, sticky="we")

        modes = ttk.Frame(frame)
        modes.grid(row=0, column=0, sticky="w", padx=5, pady=5)
        holder, btn = self._fixed_button(modes, "Off", lambda: self._click_anc_mode("off"))
        holder.grid(row=0, column=0, padx=3)
        self.anc_mode_buttons["off"] = btn
        holder, btn = self._fixed_button(modes, "On", lambda: self._click_anc_mode("on"))
        holder.grid(row=0, column=1, padx=3)
        self.anc_mode_buttons["on"] = btn
        holder, btn = self._fixed_button(modes, "Ambient", lambda: self._click_anc_mode("ambient"))
        holder.grid(row=0, column=2, padx=3)
        self.anc_mode_buttons["ambient"] = btn

        levels = ttk.Frame(frame)
        levels.grid(row=1, column=0, sticky="w", padx=5, pady=5)
        ttk.Label(levels, text="Mode:").grid(row=0, column=0, columnspan=4, sticky="w")
        for i, (name, value) in enumerate(ANC_LEVELS):
            holder, btn = self._fixed_button(
                levels, name, lambda v=value, n=name: self._click_anc_level(v, n)
            )
            holder.grid(row=1, column=i, padx=3, pady=3)
            self.anc_level_buttons[value] = btn

    def _click_anc_mode(self, mode):
        fns = {
            "off": lambda c: c.set_anc_off(),
            "on": lambda c: c.set_anc_on(),
            "ambient": lambda c: c.set_anc_ambient(),
        }
        self._run(f"ANC {mode}", fns[mode])
        self._mark_active(self.anc_mode_buttons, mode)
        if mode == "on":
            self._mark_active(self.anc_level_buttons, ANC_LEVEL_ULTRA)
        else:
            self._mark_active(self.anc_level_buttons, None)

    def _click_anc_level(self, value, name):
        self._run(f"ANC level {name}", lambda c: c.set_anc_level(value))
        self._mark_active(self.anc_level_buttons, value)
        self._mark_active(self.anc_mode_buttons, "on")

    def _build_toggles_section(self):
        frame = ttk.LabelFrame(self, text="Toggles")
        frame.grid(row=3, column=0, columnspan=4, padx=10, pady=5, sticky="we")

        toggles = [
            ("Spatial audio", lambda c, on: c.set_spatial_audio(on)),
            ("Game mode", lambda c, on: c.set_game_mode(on)),
            ("Wind noise reduction", lambda c, on: c.set_wind_noise_reduction(on)),
            ("Dual link", lambda c, on: c.set_dual_link(on)),
            ("Hi-Res audio", lambda c, on: c.set_hires_audio(on)),
        ]
        self.connected_devices_var = tk.StringVar(value="")
        for i, (name, fn) in enumerate(toggles):
            ttk.Label(frame, text=name, width=20).grid(row=i, column=0, sticky="w", padx=5, pady=3)
            holder, on_btn = self._fixed_button(frame, "On", lambda f=fn, n=name: self._click_toggle(f, n, True), width=60)
            holder.grid(row=i, column=1, padx=3)
            holder, off_btn = self._fixed_button(frame, "Off", lambda f=fn, n=name: self._click_toggle(f, n, False), width=60)
            holder.grid(row=i, column=2, padx=3)
            self.toggle_buttons[name] = {"on": on_btn, "off": off_btn}
            if name == "Dual link":
                ttk.Label(frame, textvariable=self.connected_devices_var, foreground="gray").grid(
                    row=i, column=3, sticky="w", padx=(10, 5)
                )

        ttk.Label(frame, text="Prompt volume (0-15):").grid(row=len(toggles), column=0, sticky="w", padx=5, pady=(8, 3))
        self.vol_var = tk.IntVar(value=10)
        vol_spin = ttk.Spinbox(frame, from_=0, to=15, textvariable=self.vol_var, width=5,
                                command=self._apply_prompt_volume)
        vol_spin.grid(row=len(toggles), column=1, sticky="w", padx=3, pady=(8, 3))
        vol_spin.bind("<Return>", lambda e: self._apply_prompt_volume())
        vol_spin.bind("<FocusOut>", lambda e: self._apply_prompt_volume())

    def _apply_prompt_volume(self):
        try:
            level = self.vol_var.get()
        except tk.TclError:
            return
        self._run("Prompt volume", lambda c: c.set_prompt_volume(level))

    def _click_toggle(self, fn, name, on):
        self._run(f"{name} {'on' if on else 'off'}", lambda c: fn(c, on))
        self._mark_active(self.toggle_buttons[name], "on" if on else "off")
        if name in _MUTUALLY_EXCLUSIVE:
            # Hi-Res audio in particular disconnects the device to renegotiate its
            # codec, so this follow-up refresh commonly lands in the window where
            # self.client is briefly None again - must not pop the "not connected"
            # warning dialog for what is just the toggle's own expected side effect.
            self.after(1500, lambda: self._refresh_status(warn_if_disconnected=False))

    def _build_voice_section(self):
        frame = ttk.LabelFrame(self, text="Broadcast voice language")
        frame.grid(row=4, column=0, columnspan=4, padx=10, pady=5, sticky="we")
        for i, (name, value) in enumerate((("English", VOICE_LANG_ENGLISH), ("Chinese", VOICE_LANG_CHINESE), ("Ringtone", VOICE_LANG_RINGTONE))):
            holder, btn = self._fixed_button(frame, name, lambda v=value, n=name: self._click_voice(v, n))
            holder.grid(row=0, column=i, padx=5, pady=5)
            self.voice_buttons[value] = btn

    def _click_voice(self, value, name):
        self._run(f"Voice {name}", lambda c: c.set_broadcast_voice_language(value))
        self._mark_active(self.voice_buttons, value)

    def _build_sharing_section(self):
        frame = ttk.LabelFrame(self, text="Audio sharing")
        frame.grid(row=5, column=0, columnspan=4, padx=10, pady=5, sticky="we")
        ttk.Button(frame, text="Start",
                   command=lambda: self._run("Audio sharing start", lambda c: c.start_audio_sharing())
                   ).grid(row=0, column=0, padx=5, pady=5)
        ttk.Button(frame, text="Stop",
                   command=lambda: self._run("Audio sharing stop", lambda c: c.stop_audio_sharing())
                   ).grid(row=0, column=1, padx=5, pady=5)

    def _build_buttons_section(self):
        frame = ttk.LabelFrame(self, text="ANC button customization")
        frame.grid(row=6, column=0, columnspan=2, padx=10, pady=5, sticky="nswe")

        action_names = [name for name, _ in BUTTON_ACTIONS]

        ttk.Label(frame, text="ANC single-click:").grid(row=0, column=0, sticky="w", padx=5, pady=3)
        self.anc_single = ttk.Combobox(frame, values=action_names, width=15, state="readonly")
        self.anc_single.current(4)
        self.anc_single.grid(row=0, column=1, padx=5)
        self.anc_single.bind("<<ComboboxSelected>>", lambda e: self._apply_anc_buttons())

        ttk.Label(frame, text="ANC double-click:").grid(row=1, column=0, sticky="w", padx=5, pady=3)
        self.anc_double = ttk.Combobox(frame, values=action_names, width=15, state="readonly")
        self.anc_double.current(5)
        self.anc_double.grid(row=1, column=1, padx=5)
        self.anc_double.bind("<<ComboboxSelected>>", lambda e: self._apply_anc_buttons())

        ttk.Label(frame, text="ANC press-hold:").grid(row=2, column=0, sticky="w", padx=5, pady=3)
        self.anc_hold = ttk.Combobox(frame, values=action_names, width=15, state="readonly")
        self.anc_hold.current(3)
        self.anc_hold.grid(row=2, column=1, padx=5)
        self.anc_hold.bind("<<ComboboxSelected>>", lambda e: self._apply_anc_buttons())

    def _build_volume_buttons_section(self):
        frame = ttk.LabelFrame(self, text="Volume +/- buttons")
        frame.grid(row=6, column=2, columnspan=2, padx=10, pady=5, sticky="nswe")

        action_names = [name for name, _ in BUTTON_ACTIONS]

        ttk.Label(frame, text="Volume+ press-hold:").grid(row=0, column=0, sticky="w", padx=5, pady=3)
        self.vol_up = ttk.Combobox(frame, values=action_names, width=15, state="readonly")
        self.vol_up.current(2)
        self.vol_up.grid(row=0, column=1, padx=5, pady=3)
        self.vol_up.bind("<<ComboboxSelected>>", lambda e: self._run(
            "Volume+ hold action",
            lambda c: c.set_volume_up_hold_action(BUTTON_ACTIONS[self.vol_up.current()][1])
        ))

        ttk.Label(frame, text="Volume- press-hold:").grid(row=1, column=0, sticky="w", padx=5, pady=3)
        self.vol_down = ttk.Combobox(frame, values=action_names, width=15, state="readonly")
        self.vol_down.current(1)
        self.vol_down.grid(row=1, column=1, padx=5, pady=3)
        self.vol_down.bind("<<ComboboxSelected>>", lambda e: self._run(
            "Volume- hold action",
            lambda c: c.set_volume_down_hold_action(BUTTON_ACTIONS[self.vol_down.current()][1])
        ))

    def _apply_anc_buttons(self):
        single = BUTTON_ACTIONS[self.anc_single.current()][1]
        double = BUTTON_ACTIONS[self.anc_double.current()][1]
        hold = BUTTON_ACTIONS[self.anc_hold.current()][1]
        self._run(
            "ANC button actions",
            lambda c: c.set_anc_button_actions(single, double, hold)
        )

    def _open_log_window(self):
        if self.log_window is not None and self.log_window.winfo_exists():
            self.log_window.lift()
            self.log_window.focus_force()
            return

        win = tk.Toplevel(self)
        win.title("Bluetooth log")
        win.geometry("700x400")
        win.protocol("WM_DELETE_WINDOW", self._close_log_window)
        self.log_window = win

        text_frame = ttk.Frame(win)
        text_frame.pack(fill="both", expand=True, padx=5, pady=5)
        text_frame.columnconfigure(0, weight=1)
        text_frame.rowconfigure(0, weight=1)

        self.log_text = tk.Text(text_frame, state="disabled", font=("Consolas", 9), wrap="none")
        self.log_text.grid(row=0, column=0, sticky="nswe")
        scroll = ttk.Scrollbar(text_frame, orient="vertical", command=self.log_text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scroll.set)

        ttk.Button(win, text="Clear log", command=self._clear_log).pack(anchor="w", padx=5, pady=(0, 5))

        self.log_text.configure(state="normal")
        self.log_text.insert("end", "".join(self._log_lines))
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _close_log_window(self):
        if self.log_window is not None:
            self.log_window.destroy()
        self.log_window = None
        self.log_text = None

    def _on_frame_log(self, direction, data):
        self.after(0, lambda: self._log_frame(direction, data))

    def _log_frame(self, direction, data: bytes):
        ts = time.strftime("%H:%M:%S")
        line = f"{ts} {direction:<2} {data.hex(' ').upper()}\n"
        self._log_lines.append(line)
        if len(self._log_lines) > 500:
            self._log_lines = self._log_lines[-500:]

        if self.log_text is not None:
            self.log_text.configure(state="normal")
            self.log_text.insert("end", line)
            line_count = int(self.log_text.index("end-1c").split(".")[0])
            if line_count > 500:
                self.log_text.delete("1.0", f"{line_count - 500}.0")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")

    def _clear_log(self):
        self._log_lines = []
        if self.log_text is not None:
            self.log_text.configure(state="normal")
            self.log_text.delete("1.0", "end")
            self.log_text.configure(state="disabled")

    def _on_close(self):
        self._stop_status_polling()
        self._cancel_reconnect()
        if self.client is not None:
            self.client.close()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
