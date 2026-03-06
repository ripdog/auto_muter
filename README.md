# auto_muter

`auto_muter` is a Linux desktop utility designed to automatically mute specified applications when their windows lose focus, and unmute them when they regain focus. It leverages KDE Plasma's KWin window manager and PulseAudio/PipeWire (via `pactl`) to seamlessly manage audio streams.

This is particularly useful for games or applications that do not have a built-in "mute on background" feature, preventing them from playing audio when you Alt-Tab away to do something else.

## Components

The utility consists of two main parts that communicate via D-Bus:

1.  **KWin Script (`auto_muter_kwin/`)**: Runs inside the KDE Plasma window manager. It monitors window activation events and sends the Process ID (PID) of the currently focused window over D-Bus.
2.  **Python Background Service (`focus_audio_manager.py`)**: A daemon that listens for D-Bus messages from the KWin script. When focus changes, it uses `pactl` to check all active audio streams. If an audio stream belongs to an application in the configuration list, it mutes the stream if the application is not focused, and unmutes it if it is focused.

## Requirements

*   **Linux** with **KDE Plasma** (Wayland or X11)
*   **Python 3.8+**
*   **uv** (Python package installer and runner)
*   **PulseAudio** or **PipeWire-Pulse** (`pactl` must be available in your PATH)
*   `libsystemd-dev` (or equivalent package for your distribution, required for building `sdbus`)

## Installation

### 1. Install the KWin Script

You need to install the KWin script so Plasma can track window focus and send the PID over D-Bus.

```bash
kpackagetool6 -t KWin/Script -s auto_muter_kwin || kpackagetool6 -t KWin/Script -i auto_muter_kwin
```

After installing, enable the script in KDE System Settings -> Window Management -> KWin Scripts, and click "Apply".

### 2. Setup the Python Service

There are two ways to run the Python service: using native packages (recommended for Arch Linux) or using `uv` (recommended for development and other distributions).

**Option A: Native Packages (Arch Linux)**

The Python service requires `python`, `python-sdbus`, and `python-asyncinotify`. On Arch Linux, these can be installed from the official repositories and the AUR.

If you install via the included `PKGBUILD`, dependencies are handled automatically.

You can test the script by running it directly:
```bash
python focus_audio_manager.py
```

**Option B: Using `uv` (Other Distributions/Development)**

The Python script uses PEP 723 inline script metadata to manage its dependencies automatically. It is recommended to run it using `uv`, which creates a fast, isolated environment without messing with your system packages.

Ensure you have `uv` installed:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

You can test the script by running it directly:
```bash
uv run --script focus_audio_manager.py
```

### 3. Setup Systemd User Service (Recommended)

To run the Python service automatically in the background, set up a systemd user service. 

If you installed via the PKGBUILD, the unit file is already installed to `/usr/lib/systemd/user/focus-audio-manager.service`. Otherwise, create a file at `~/.config/systemd/user/focus-audio-manager.service`:

```ini
[Unit]
Description=Focus-based Application Audio Manager (sdbus/pactl)
After=graphical-session.target

[Service]
Type=simple
# If using Option A (Native Python / Arch PKGBUILD):
ExecStart=/usr/bin/focus_audio_manager
# If using Option B (uv):
# ExecStart=/usr/bin/env uv run --script %h/.local/bin/auto_muter/focus_audio_manager.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

*(Note: Adjust the `ExecStart` path if you cloned this repository to a different location).*

Enable and start the service:
```bash
systemctl --user daemon-reload
systemctl --user enable --now focus-audio-manager.service
```

## Configuration

The Python daemon automatically generates an empty configuration file at `~/.config/auto_muter/config.json` on its first run.

```json
{
    "configured_process_names": [
        "MyGame.exe",
        "some-other-app"
    ]
}
```

Add the binary names or application names of the programs you want to auto-mute into the `configured_process_names` list. The matching is case-insensitive and acts as a substring match against either the binary name or the application name reported by PulseAudio.

**Auto-reloading:** The daemon watches this file using `inotify`. Whenever you save changes to `config.json`, the new rules will be applied instantly without needing to restart the service.

## Troubleshooting

*   **No sound muting?** Check the Python service logs: `journalctl --user -u focus_audio_manager.service -f`
*   **"pactl command not found"**: Ensure `pulseaudio-utils` (or the equivalent package containing `pactl`) is installed on your system.
*   **KWin script not running?** Check KDE Plasma logs using `journalctl --user -f | grep kwin`
