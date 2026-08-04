import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox, font as tkfont

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_LOGO_PATH = os.path.join(_SCRIPT_DIR, "ugreen_logo.png")
_ICO_PATH = os.path.join(_SCRIPT_DIR, "ugreen_logo.ico")

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

        self.battery_var = tk.StringVar(value="Battery: -")
        ttk.Label(frame, textvariable=self.battery_var, foreground="gray", width=14, anchor="w").grid(
            row=0, column=5, padx=(15, 5)
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

    def _auto_connect(self):
        if self.client is not None or not self._selected_port():
            return
        try:
            self.client = UgreenClient(self._selected_port())
            self.connect_btn.config(text="Disconnect")
            self._set_status(f"Auto-connected to {self.port_var.get()}")
            self._refresh_status()
        except Exception as e:
            self._set_status(f"Auto-connect failed: {e}")

    def _toggle_connect(self):
        if self.client is None:
            port = self._selected_port()
            if not port:
                messagebox.showwarning("No port selected", "No Bluetooth SPP COM port detected. Pair the earbuds first, then click Refresh ports.")
                return
            try:
                self.client = UgreenClient(port)
                self.connect_btn.config(text="Disconnect")
                self._set_status(f"Connected to {self.port_var.get()}")
                self._refresh_status()
            except Exception as e:
                messagebox.showerror("Connection failed", str(e))
        else:
            self.client.close()
            self.client = None
            self.connect_btn.config(text="Connect")
            self._set_status("Not connected")

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
        try:
            frame = fn(self.client)
            self._set_status(f"{label}: sent {frame.hex().upper()}")
        except Exception as e:
            messagebox.showerror("Command failed", str(e))
            self._set_status(f"{label}: FAILED - {e}")

    def _refresh_status(self):
        if self.client is None:
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
                self.after(0, lambda: self._on_status_error(f"Status query failed: {e}"))
                return
            devices = None
            if status.get("dual_link"):
                try:
                    devices = client.query_connected_devices()
                except Exception:
                    devices = None
            self.after(0, lambda: self._apply_status(status, devices))

        threading.Thread(target=worker, daemon=True).start()

    def _on_status_error(self, message):
        self._status_refresh_busy = False
        self._set_status(message)

    def _apply_status(self, status, devices):
        self._status_refresh_busy = False
        if "error" in status:
            self._set_status(f"Status query: {status['error']} (raw={status.get('raw', '')})")
            return
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

        if not status.get("dual_link"):
            self.connected_devices_var.set("(device list unavailable while Dual Link is off)")
        elif devices:
            self.connected_devices_var.set("Connected: " + ", ".join(devices))
        elif devices is not None:
            self.connected_devices_var.set("Connected: -")
        else:
            self.connected_devices_var.set("Connected: ?")

        voice_val = status.get("broadcast_voice")
        if voice_val in self.voice_buttons:
            self._mark_active(self.voice_buttons, voice_val)

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
            self.after(1500, self._refresh_status)

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

    def _on_close(self):
        if self.client is not None:
            self.client.close()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
