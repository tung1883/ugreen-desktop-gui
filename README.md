# UGREEN Studio Pro PC Control

A reverse-engineered desktop GUI for controlling UGREEN Studio Pro headphones.

Mostly for Windows. If you want a version for other platforms, read the protocol below and build it yourself!

*Note: Remember to pair the headphone with Windows first*

## Building the binary
```
pip install pyinstaller
python -m PyInstaller --onefile --windowed --name "UgreenStudioProControl" --icon ugreen_logo.ico --add-data "ugreen_logo.png;." --add-data "ugreen_logo.ico;." ugreen_gui.py
```

## Protocol
### Transport
- Classic Bluetooth SPP (RFCOMM), not BLE.
- SPP UUID: `00001101-0000-1000-8000-00805F9B34FB`.
- Windows exposes a paired SPP device as an outgoing COM port (Settings → Bluetooth & devices → Devices → More Bluetooth settings → COM Ports tab)

### Command frame

```
AA BB CC | CMD(1) | LEN(1) | PARAM(LEN) | CRC16(2, little-endian)
```

CRC-16/MODBUS (poly `0x8005`, init `0xFFFF`, reflected in/out), computed over `CMD + LEN + PARAM` (prefix excluded)

### Response frame

```
DD EE FF | CMD(1) | subtype(1) | LEN(1) | PARAM(LEN) | CRC16(2, little-endian)
```

Set-commands get an ack response echoing `CMD`/`PARAM`

### Commands

| CMD | Feature | Param |
|---|---|---|
| `0x05` | EQ preset | 1 byte: `0`=Classic, `1`=Jazz, `2`=Electronic, `3`=Popular, `4`=Classical, `5`=Rock, `6`=Bass, `7`=Treble |
| `0x09` | ANC | 1 byte: `0xA0`=off, `0xA1`=on/Ultra, `0xA2`=Ambient, `0xD1`=Adaptive, `0xC1`=Gentle, `0xB1`=General (levels only apply once ANC is on) |
| `0x11` | Prompt/announcement volume | 1 byte, literal level |
| `0x12` | Spatial audio | 1 byte: `1`=on, `0`=off |
| `0x0C` | Broadcast voice / sound-type | 1 byte: `0`=English, `1`=Chinese, `2`=Ringtone |
| `0x08` | Game mode | 1 byte: `1`=on, `0`=off |
| `0x17` | Wind noise reduction | 1 byte: `1`=on, `0`=off |
| `0x06` | Dual link | 1 byte: `1`=on, `0`=off (audio-routing preference; does not force-disconnect the other host) |
| `0x0B` | Hi-Res audio | 1 byte: `1`=on, `0`=off (forces an A2DP reconnect) |
| `0x16` | Audio sharing | Start: `01 FF FF FF FF FF FF FF` (8 bytes). Stop: `00` (1 byte) |
| `0x0A` | ANC button gestures (bulk write) | 8 bytes: `[single_click, double_click, 0, press_hold, 0, 0, 0, 0]` — always pass current values for gestures not being changed |
| `0x14` | Volume+ button, press-hold action | 1 byte, action code |
| `0x15` | Volume− button, press-hold action | 1 byte, action code |
| `0x04` | Status query | Param `00`. See below for response format |
| `0x0D` | Connected-devices query | Param `00`. Only responds while Dual Link is on. See below |
| `0x01` | Device info query | Param ignored. Response `PARAM` is a fixed 6 bytes: `00 02 05 00 00 00` |

Action codes (`0x0A`/`0x14`/`0x15`): `0`=No action, `4`=Next track, `5`=Previous track, `7`=Game mode, `8`=ANC cycle, `11`=Spatial audio.

### Status query (`CMD 0x04`)

Response `PARAM` byte offsets:

| Offset | Field |
|---|---|
| `0` | Battery % (main unit) |
| `1` | Battery % (case), `0xFF`=none |
| `2` | Battery % (right earbud), `0xFF`=none |
| `3` | ANC raw value (same as `0x09` param) |
| `4` | EQ preset (same as `0x05` param) |
| `5` | Dual link |
| `6` | Game mode |
| `7` | Hi-Res audio |
| `8` | ANC button single-click action (same as `0x0A` param[0]) |
| `9` | ANC button double-click action (same as `0x0A` param[1]) |
| `11` | ANC button press-hold action (same as `0x0A` param[3]) |
| `16` | Broadcast voice (same as `0x0C` param) |
| `19` | Prompt volume |
| `20` | Spatial audio |
| `25` | Wind noise reduction |

### Connected-devices query (`CMD 0x0D`)

Returns nothing (zero-byte response) while Dual Link is off. While on, response may contain multiple concatenated `DD EE FF 0D ...` frames, each `PARAM`:

```
0x02 | device_index(1) | name (ASCII) | 6 trailing bytes (unconfirmed)
```

### Skippies
- Factory reset
- Offsets 10, 12–15, 17–18, 21–24, 26+ in the status payload
