import re
import json
import subprocess
import threading
import time
import serial
from serial.tools import list_ports

SPP_UUID = "00001101-0000-1000-8000-00805F9B34FB"

_MAC_RE = re.compile(r"&([0-9A-F]{12})_C\d+$")


def _bluetooth_device_names() -> dict:
    try:
        out = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                "Get-PnpDevice | Where-Object { $_.InstanceId -match 'BTHENUM\\\\DEV_' } "
                "| Select-Object FriendlyName, InstanceId | ConvertTo-Json -Compress",
            ],
            capture_output=True, text=True, timeout=10,
        )
        data = json.loads(out.stdout)
        if isinstance(data, dict):
            data = [data]
        names = {}
        for entry in data:
            m = re.search(r"DEV_([0-9A-F]{12})", entry.get("InstanceId", "").upper())
            if m:
                names[m.group(1)] = entry.get("FriendlyName", "")
        return names
    except Exception:
        return {}


def list_candidate_ports():
    names = _bluetooth_device_names()
    candidates = []
    for p in list_ports.comports():
        hwid = (p.hwid or "").upper()
        if "BTHENUM" in hwid and SPP_UUID.upper() in hwid and "VID&" in hwid:
            mac_match = _MAC_RE.search(hwid)
            friendly = names.get(mac_match.group(1)) if mac_match else None
            candidates.append((p.device, p.description, friendly))
    return candidates


def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


def build_frame(cmd: int, param: bytes = b"") -> bytes:
    body = bytes([cmd, len(param)]) + param
    crc = crc16_modbus(body)
    return b"\xAA\xBB\xCC" + body + bytes([crc & 0xFF, (crc >> 8) & 0xFF])


ACTION_NO_ACTION = 0
ACTION_NEXT_TRACK = 4
ACTION_PREV_TRACK = 5
ACTION_GAME_MODE = 7
ACTION_ANC_CYCLE = 8
ACTION_SPATIAL_AUDIO = 11

EQ_CLASSIC = 0
EQ_JAZZ = 1
EQ_ELECTRONIC = 2
EQ_POPULAR = 3
EQ_CLASSICAL = 4
EQ_ROCK = 5
EQ_BASS = 6
EQ_TREBLE = 7

ANC_LEVEL_ADAPTIVE = 0xD1
ANC_LEVEL_GENTLE = 0xC1
ANC_LEVEL_GENERAL = 0xB1
ANC_LEVEL_ULTRA = 0xA1

VOICE_LANG_ENGLISH = 0x00
VOICE_LANG_CHINESE = 0x01
VOICE_LANG_RINGTONE = 0x02

EQ_NAMES = {
    EQ_CLASSIC: "Classic", EQ_JAZZ: "Jazz", EQ_ELECTRONIC: "Electronic",
    EQ_POPULAR: "Popular", EQ_CLASSICAL: "Classical", EQ_ROCK: "Rock",
    EQ_BASS: "Bass", EQ_TREBLE: "Treble",
}

ANC_NAMES = {
    0xA0: "Off", 0xA2: "Ambient sound",
    0xD1: "On (Adaptive)", 0xC1: "On (Gentle)", 0xB1: "On (General)", 0xA1: "On (Ultra)",
}


class UgreenClient:
    def __init__(self, port: str, timeout: float = 3.0):
        self.ser = serial.Serial(port=port, baudrate=115200, timeout=timeout)
        self.lock = threading.RLock()

    def close(self):
        self.ser.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _send(self, cmd: int, param: bytes = b""):
        frame = build_frame(cmd, param)
        with self.lock:
            self.ser.write(frame)
        return frame

    def query_status(self) -> dict:
        with self.lock:
            self.ser.reset_input_buffer()
            self._send(0x04, bytes([0]))
            time.sleep(0.5)
            resp = self.ser.read(512)
        if not resp.startswith(b"\xDD\xEE\xFF\x04"):
            return {"raw": resp.hex(), "error": "no/unexpected response"}

        length = resp[5]
        param = resp[6:6 + length]
        result = {"raw": param.hex()}
        if len(param) > 0:
            result["battery"] = param[0] if param[0] != 0xFF else None
        if len(param) > 1:
            result["case_battery"] = param[1] if param[1] != 0xFF else None
        if len(param) > 2:
            result["right_battery"] = param[2] if param[2] != 0xFF else None
        if len(param) > 3:
            result["anc_raw"] = param[3]
            result["anc"] = ANC_NAMES.get(param[3], f"unknown (0x{param[3]:02X})")
        if len(param) > 4:
            result["eq_preset"] = param[4]
            result["eq"] = EQ_NAMES.get(param[4], f"unknown ({param[4]})")
        if len(param) > 5:
            result["dual_link"] = bool(param[5])
        if len(param) > 6:
            result["game_mode"] = bool(param[6])
        if len(param) > 7:
            result["hires_audio"] = bool(param[7])
        if len(param) > 8:
            result["anc_button_single_click"] = param[8]
        if len(param) > 9:
            result["anc_button_double_click"] = param[9]
        if len(param) > 11:
            result["anc_button_press_hold"] = param[11]
        if len(param) > 16:
            result["broadcast_voice"] = param[16]
            result["broadcast_voice_name"] = {0: "English", 1: "Chinese", 2: "Ringtone"}.get(
                param[16], f"unknown ({param[16]})"
            )
        if len(param) > 19:
            result["prompt_volume"] = param[19]
        if len(param) > 20:
            result["spatial_audio"] = bool(param[20])
        if len(param) > 25:
            result["wind_noise_reduction"] = bool(param[25])
        return result

    def query_connected_devices(self) -> list:
        with self.lock:
            self.ser.reset_input_buffer()
            self._send(0x0D, bytes([0]))
            time.sleep(0.3)
            old_timeout = self.ser.timeout
            self.ser.timeout = 0.5
            try:
                resp = self.ser.read(1024)
            finally:
                self.ser.timeout = old_timeout

        devices = []
        i = 0
        while i + 6 <= len(resp):
            if resp[i:i + 3] != b"\xDD\xEE\xFF" or resp[i + 3] != 0x0D:
                i += 1
                continue
            length = resp[i + 5]
            payload = resp[i + 6:i + 6 + length]
            if len(payload) == length and length > 8:
                index = payload[1]
                name = payload[2:length - 6].decode("ascii", errors="replace")
                devices.append((index, name))
            i += 6 + length + 2
        devices.sort(key=lambda d: d[0])
        return [name for _, name in devices]

    def set_eq_preset(self, preset: int):
        return self._send(0x05, bytes([preset]))

    def set_anc_off(self):
        return self._send(0x09, bytes([0xA0]))

    def set_anc_on(self):
        return self._send(0x09, bytes([0xA1]))

    def set_anc_ambient(self):
        return self._send(0x09, bytes([0xA2]))

    def set_anc_level(self, level: int, ensure_on_first: bool = False):
        if ensure_on_first:
            self.set_anc_on()
            time.sleep(0.3)
        return self._send(0x09, bytes([level]))

    def set_spatial_audio(self, on: bool):
        return self._send(0x12, bytes([1 if on else 0]))

    def set_prompt_volume(self, level: int):
        return self._send(0x11, bytes([level]))

    def set_broadcast_voice_language(self, lang: int):
        return self._send(0x0C, bytes([lang]))

    def set_game_mode(self, on: bool):
        return self._send(0x08, bytes([1 if on else 0]))

    def set_wind_noise_reduction(self, on: bool):
        return self._send(0x17, bytes([1 if on else 0]))

    def set_dual_link(self, on: bool):
        return self._send(0x06, bytes([1 if on else 0]))

    def set_hires_audio(self, on: bool):
        return self._send(0x0B, bytes([1 if on else 0]))

    def start_audio_sharing(self):
        return self._send(0x16, bytes([0x01]) + b"\xFF" * 7)

    def stop_audio_sharing(self):
        return self._send(0x16, bytes([0x00]))

    def set_anc_button_actions(self, single_click: int, double_click: int, press_hold: int):
        param = bytes([single_click, double_click, 0, press_hold, 0, 0, 0, 0])
        return self._send(0x0A, param)

    def set_volume_up_hold_action(self, action: int):
        return self._send(0x14, bytes([action]))

    def set_volume_down_hold_action(self, action: int):
        return self._send(0x15, bytes([action]))
