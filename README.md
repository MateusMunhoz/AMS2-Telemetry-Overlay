# AMS2 Telemetry Overlay

A real-time telemetry overlay for [Automobilista 2](https://www.game-automobilista2.com/) that displays throttle, brake, steering inputs, gear, speed, RPM, and lap times as click-through widgets on top of the game.

## Features

- **Throttle / Brake Graph** -- scrolling time-series graph showing the last 8 seconds of pedal inputs
- **Rotating Steering Wheel** -- visual indicator that follows your steering wheel position
- **Gear Indicator** -- large gear number (R/N/1-7) with color coding
- **Speed & RPM** -- digital speedometer (km/h) and RPM bar with shift light that flashes near the limiter
- **Lap Timing** -- live lap time, delta to best lap (green/red), and last completed lap time
- **Click-through** -- all windows pass mouse clicks to the game so you can keep playing normally
- **Always on top** -- widgets stay visible over the game in borderless windowed mode
- **Configurable layout** -- press **F6** to enter config mode and drag widgets wherever you want. Positions are saved to `overlay_config.json` and persist across sessions
- **Reset layout** -- press **F5** during config mode to reset all widget positions to defaults

## Screenshots

*To be added*

## How It Works

The overlay reads AMS2's **shared memory** (`$pcars2$`), the same data source used by tools like Crew Chief, SimHub, and SecondMonitor. AMS2 exports telemetry in the Project Cars 2 shared memory format (Madness Engine).

The project is a single Python script (`ams2_overlay.py`) compiled into a standalone Windows executable via PyInstaller.

## Tech Stack

- **Python 3** + **PyQt5** for the overlay windows
- **ctypes** for reading Windows shared memory
- **PyInstaller** for single-file executable packaging

## Installation

### Option 1: Download Pre-built EXE (Recommended)

1. Go to [Releases](https://github.com/MateusMunhoz/AMS2-Telemetry-Overlay/releases)
2. Download `AMS2_Telemetry.exe`
3. Run it -- no installation required

### Option 2: Run from Source

```bash
pip install PyQt5
python ams2_overlay.py
```

## Requirements

**In AMS2, you must enable Shared Memory:**

`Options > System > Shared Memory = Project Cars 2`

Without this, the overlay cannot read telemetry data.

**Use borderless windowed mode** in AMS2 for best results. Exclusive fullscreen may hide the overlay.

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| **F6** | Toggle config mode -- drag widgets to reposition them |
| **F5** | Reset all widget positions to defaults (only works in config mode) |
| **F8** | Close all overlays and exit |

## Usage

1. Run `AMS2_Telemetry.exe`
2. Start AMS2 and enter a session
3. Three overlay widgets appear:
   - **Top-left**: lap time, delta to best lap, last lap
   - **Bottom-right**: gear, speed, RPM bar
   - **Bottom-center**: throttle/brake graph + steering wheel
4. Press **F6** to enter config mode -- a legend appears at the top-center and widgets become draggable
5. Drag each widget to your preferred position
6. Press **F6** again to save positions and return to normal mode
7. Press **F8** at any time to close the overlay
8. Right-click the system tray icon and select **Quit** to exit

Widget positions are saved to `overlay_config.json` next to the executable and restored on the next launch.

## Limitations

- **No exclusive fullscreen support** -- the overlay requires borderless/windowed mode
- **Track map removed** -- the position-based track map feature was unstable and has been removed. Use the in-game radar instead.
- **Single monitor only** -- widgets are positioned for the primary monitor
- **Windows only** -- uses Windows shared memory API (`OpenFileMappingW`, `MapViewOfFile`)

## Building from Source

```bash
pip install pyinstaller PyQt5
pyinstaller --onefile --windowed --name "AMS2_Telemetry" --distpath "." ams2_overlay.py
```

## Credits

Built by reverse-engineering the AMS2 shared memory layout with reference to [SecondMonitor](https://gitlab.com/winzarten/SecondMonitor).

## License

MIT
