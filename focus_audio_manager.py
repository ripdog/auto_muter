#!/usr/bin/env python3
# /// script
# requires-python = ">=3.8"
# dependencies = [
#   "sdbus>=0.14.0",
#   "asyncinotify>=4.0.2"
# ]
# ///

import logging
import os
import re
import subprocess
import json
import asyncio
from asyncinotify import Inotify, Mask  # type: ignore

from sdbus import (  # type: ignore
    request_default_bus_name_async,
    dbus_method_async,
    DbusInterfaceCommonAsync,
)


def get_config_path() -> str:
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    return os.path.join(xdg_config_home, "auto_muter", "config.json")


def load_config() -> dict:
    config_path = get_config_path()
    default_config = {"configured_process_names": []}

    try:
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        else:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(default_config, f, indent=4)
            return default_config
    except Exception as e:
        logger.warning(f"Error loading config {config_path}: {e}")
        return default_config


DBUS_SERVICE_NAME_SDBUS_STR = "com.example.FocusAudioManager"
DBUS_OBJECT_PATH_SDBUS_STR = "/com/example/FocusAudioManager"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("FocusAudioManagerSDBusPactl")


class AudioManager(
    DbusInterfaceCommonAsync,
    interface_name=DBUS_SERVICE_NAME_SDBUS_STR,  # type: ignore
):
    """
    Manages audio streams for configured applications based on window focus using pactl.
    Exposed on D-Bus using python-sdbus.
    """

    def __init__(self):
        super().__init__()
        self._current_focused_pid = -1
        self.config_path = get_config_path()
        self._last_mtime = 0
        self._configured_process_names_lower = []
        self._reload_config(initial=True)
        # Start background task to watch config file
        asyncio.create_task(self._watch_config_inotify())

    def _reload_config(self, initial=False) -> bool:
        try:
            mtime = (
                os.path.getmtime(self.config_path)
                if os.path.exists(self.config_path)
                else 0
            )
            if mtime == self._last_mtime and self._last_mtime != 0:
                return False

            config = load_config()
            configured_names = config.get("configured_process_names", [])
            self._configured_process_names_lower = [
                name.lower() for name in configured_names
            ]
            self._last_mtime = mtime

            if initial:
                logger.info(f"Loaded config from {self.config_path}")
                logger.info(
                    f"Managing audio for process/app names (using pactl): {self._configured_process_names_lower}"
                )
            else:
                logger.info(f"Configuration reloaded from {self.config_path}")
                logger.info(
                    f"Updated managed apps: {self._configured_process_names_lower}"
                )

            return True
        except Exception as e:
            logger.error(f"Error reloading config: {e}")
            return False

    async def _watch_config_inotify(self):
        config_dir = os.path.dirname(self.config_path)
        # Ensure the directory exists before watching it
        os.makedirs(config_dir, exist_ok=True)

        with Inotify() as inotify:
            inotify.add_watch(
                config_dir, Mask.CLOSE_WRITE | Mask.MOVED_TO | Mask.CREATE
            )
            async for event in inotify:
                if event.name and event.name.name == os.path.basename(self.config_path):
                    # Give it a tiny delay to ensure file is fully written/closed by some editors
                    await asyncio.sleep(0.1)
                    if self._reload_config():
                        logger.info("Configuration changed, applying rules...")
                        await asyncio.get_event_loop().run_in_executor(
                            None, self._apply_audio_rules_sync
                        )

    def _run_command(self, command, timeout=5):
        try:
            logger.debug(f"Running command: {' '.join(command)}")
            result = subprocess.run(
                command, capture_output=True, text=True, check=True, timeout=timeout
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            logger.error(
                f"Command '{' '.join(command)}' failed with exit code {e.returncode}: {e.stderr.strip()}"
            )
        except subprocess.TimeoutExpired:
            logger.error(f"Command '{' '.join(command)}' timed out after {timeout}s.")
        except FileNotFoundError:
            logger.error(
                f"Command '{command[0]}' not found. Is 'pactl' installed and in PATH?"
            )
        return None

    def _get_audio_streams_info(self):
        pactl_output = self._run_command(["pactl", "list", "sink-inputs"])
        if not pactl_output:
            return []

        streams_details = []
        current_stream_info = {}
        sink_input_re = re.compile(r"Sink Input #(\d+)")
        mute_re = re.compile(r"Mute: (yes|no)")
        pid_re = re.compile(r"application\.process\.id = \"(\d+)\"")
        binary_re = re.compile(r"application\.process\.binary = \"([^\"]+)\"")
        app_name_re = re.compile(r"application\.name = \"([^\"]+)\"")

        for line in pactl_output.splitlines():
            line = line.strip()
            match_sink_input = sink_input_re.match(line)
            if match_sink_input:
                if current_stream_info and "id" in current_stream_info:
                    if (
                        "pid" in current_stream_info
                        and (
                            "binary_name" in current_stream_info
                            or "app_name" in current_stream_info
                        )
                        and "is_muted" in current_stream_info
                    ):
                        streams_details.append(current_stream_info)
                current_stream_info = {"id": match_sink_input.group(1)}
                continue

            if not current_stream_info:
                continue

            match_mute = mute_re.search(line)
            if match_mute:
                current_stream_info["is_muted"] = match_mute.group(1).lower() == "yes"

            match_pid = pid_re.search(line)
            if match_pid:
                current_stream_info["pid"] = match_pid.group(1)

            match_binary = binary_re.search(line)
            if match_binary:
                current_stream_info["binary_name"] = match_binary.group(1).lower()

            match_app_name = app_name_re.search(line)
            if match_app_name:
                current_stream_info["app_name"] = match_app_name.group(1).lower()

        if current_stream_info and "id" in current_stream_info:
            if (
                "pid" in current_stream_info
                and (
                    "binary_name" in current_stream_info
                    or "app_name" in current_stream_info
                )
                and "is_muted" in current_stream_info
            ):
                streams_details.append(current_stream_info)

        return streams_details

    def _set_stream_mute(self, stream_id: str, mute_flag: bool):
        mute_command_val = "1" if mute_flag else "0"
        logger.info(
            f"{'Muting' if mute_flag else 'Unmuting'} Sink Input ID: #{stream_id}"
        )
        self._run_command(["pactl", "set-sink-input-mute", stream_id, mute_command_val])

    @dbus_method_async(input_signature="i", result_signature="")
    async def UpdateFocus(self, pid: int) -> None:
        if self._current_focused_pid == pid:
            return
        self._current_focused_pid = pid
        await asyncio.get_event_loop().run_in_executor(
            None, self._apply_audio_rules_sync
        )

    def _apply_audio_rules_sync(self):
        streams = self._get_audio_streams_info()
        if not streams:
            return
        focused_pid_str = str(self._current_focused_pid)

        for stream in streams:
            stream_id = stream["id"]
            stream_pid = stream["pid"]
            stream_binary_name_lower = stream.get("binary_name", "")
            stream_app_name_lower = stream.get("app_name", "")
            stream_is_muted = stream["is_muted"]

            is_configured_app_by_binary = any(
                conf_name in stream_binary_name_lower
                for conf_name in self._configured_process_names_lower
                if stream_binary_name_lower
            )
            is_configured_app_by_app_name = any(
                conf_name in stream_app_name_lower
                for conf_name in self._configured_process_names_lower
                if stream_app_name_lower
            )
            is_configured_app = (
                is_configured_app_by_binary or is_configured_app_by_app_name
            )

            if is_configured_app:
                is_stream_focused = (stream_pid == focused_pid_str) and (
                    self._current_focused_pid != -1
                )
                if is_stream_focused:
                    if stream_is_muted:
                        self._set_stream_mute(stream_id, False)
                else:
                    if not stream_is_muted:
                        self._set_stream_mute(stream_id, True)

    @dbus_method_async(input_signature="", result_signature="s")
    async def Ping(self) -> str:
        return "Pong from FocusAudioManager (sdbus/pactl)"

    async def initial_mute_task(self):
        original_focused_pid = self._current_focused_pid
        self._current_focused_pid = -1
        await asyncio.get_event_loop().run_in_executor(
            None, self._apply_audio_rules_sync
        )
        self._current_focused_pid = original_focused_pid


async def main_async():
    if (
        subprocess.run(["which", "pactl"], capture_output=True, text=True).returncode
        != 0
    ):
        logger.error(
            "'pactl' command not found. Please install it (usually part of pulseaudio-utils or similar package)."
        )
        return

    audio_manager_instance = AudioManager()
    object_path_str = DBUS_OBJECT_PATH_SDBUS_STR

    audio_manager_instance.export_to_dbus(object_path_str)
    await request_default_bus_name_async(DBUS_SERVICE_NAME_SDBUS_STR)

    loop = asyncio.get_event_loop()
    loop.call_later(
        1, lambda: asyncio.create_task(audio_manager_instance.initial_mute_task())
    )

    stop_event = asyncio.Event()
    try:
        await stop_event.wait()
    except KeyboardInterrupt:
        pass
    except asyncio.CancelledError:
        pass


if __name__ == "__main__":
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        pass
