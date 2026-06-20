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
import shutil
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
logger = logging.getLogger("FocusAudioManagerSDBusPipeWire")


class AudioManager(
    DbusInterfaceCommonAsync,
    interface_name=DBUS_SERVICE_NAME_SDBUS_STR,  # type: ignore
):
    """
    Manages audio streams for configured applications based on window focus using PipeWire.
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
                    f"Managing audio for process/app names (using PipeWire): {self._configured_process_names_lower}"
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
                f"Command '{command[0]}' not found. Is it installed and in PATH?"
            )
        return None

    def _get_wpctl_mute_state(self, stream_id: str):
        wpctl_output = self._run_command(["wpctl", "get-volume", stream_id])
        if wpctl_output is None:
            return None

        return "[MUTED]" in wpctl_output

    def _get_audio_streams_info(self):
        pw_dump_output = self._run_command(["pw-dump"])
        if not pw_dump_output:
            return []

        try:
            pipewire_objects = json.loads(pw_dump_output)
        except json.JSONDecodeError as e:
            logger.error(f"Unable to parse pw-dump output as JSON: {e}")
            return []

        clients_by_id = {}
        for pipewire_object in pipewire_objects:
            if pipewire_object.get("type") != "PipeWire:Interface:Client":
                continue

            client_id = str(pipewire_object.get("id", ""))
            props = pipewire_object.get("info", {}).get("props", {})
            if client_id and isinstance(props, dict):
                clients_by_id[client_id] = props

        streams_details = []
        for pipewire_object in pipewire_objects:
            if pipewire_object.get("type") != "PipeWire:Interface:Node":
                continue

            props = pipewire_object.get("info", {}).get("props", {})
            if not isinstance(props, dict):
                continue

            media_class = props.get("media.class", "")
            if "stream" not in str(media_class).lower():
                continue

            stream_id = str(pipewire_object.get("id", ""))
            if not stream_id:
                continue

            client_props = clients_by_id.get(str(props.get("client.id", "")), {})
            pid = props.get("application.process.id") or client_props.get(
                "application.process.id"
            ) or client_props.get("pipewire.sec.pid")
            binary_name = props.get("application.process.binary") or client_props.get(
                "application.process.binary"
            )
            app_name = props.get("application.name") or client_props.get(
                "application.name"
            )

            stream_info = {
                "id": stream_id,
                "is_muted": self._get_wpctl_mute_state(stream_id),
                "media_class": str(media_class),
                "media_name": str(
                    props.get("media.name") or props.get("node.name") or ""
                ),
            }
            if pid:
                stream_info["pid"] = str(pid)
            if binary_name:
                stream_info["binary_name"] = str(binary_name).lower()
            if app_name:
                stream_info["app_name"] = str(app_name).lower()

            if (
                stream_info["is_muted"] is not None
                and ("binary_name" in stream_info or "app_name" in stream_info)
            ):
                streams_details.append(stream_info)

        return streams_details

    def _set_stream_mute(self, stream_id: str, mute_flag: bool):
        mute_command_val = "1" if mute_flag else "0"
        logger.info(
            f"{'Muting' if mute_flag else 'Unmuting'} PipeWire Node ID: {stream_id}"
        )
        self._run_command(["wpctl", "set-mute", stream_id, mute_command_val])

    def _get_process_info(self, pid: str):
        try:
            with open(f"/proc/{pid}/status", "r", encoding="utf-8") as f:
                status_lines = f.readlines()
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                cmdline = f.read().replace(b"\0", b" ").decode(
                    "utf-8", errors="replace"
                )
        except Exception:
            return None

        process_info = {"pid": pid, "ppid": "", "name": "", "cmdline": cmdline}
        for line in status_lines:
            key, _, value = line.partition(":")
            value = value.strip()
            if key == "Name":
                process_info["name"] = value
            elif key == "PPid":
                process_info["ppid"] = value

        return process_info

    def _get_process_ancestors(self, pid: str):
        ancestors = []
        seen_pids = set()
        current_pid = pid

        for _ in range(128):
            if not current_pid or current_pid in seen_pids:
                break

            seen_pids.add(current_pid)
            process_info = self._get_process_info(current_pid)
            if not process_info:
                break

            ancestors.append(process_info)
            parent_pid = process_info.get("ppid", "")
            if not parent_pid or parent_pid == "0":
                break

            current_pid = parent_pid

        return ancestors

    def _is_broad_common_ancestor(self, process_info: dict) -> bool:
        process_name = process_info.get("name", "").lower()
        cmdline = process_info.get("cmdline", "").lower()

        if process_info.get("pid") in {"1"}:
            return True

        broad_process_names = {
            "bash",
            "bwrap",
            "fish",
            "kwin_wayland",
            "kwin_x11",
            "plasmashell",
            "sh",
            "steam",
            "steamwebhelper",
            "systemd",
            "zsh",
        }
        if process_name in broad_process_names:
            return True

        return "/steam/steam.sh" in cmdline or "app-steam@autostart.service" in cmdline

    def _are_processes_related_by_specific_ancestor(
        self, stream_pid: str, focused_pid: str
    ) -> bool:
        stream_ancestors = self._get_process_ancestors(stream_pid)
        focused_ancestors = self._get_process_ancestors(focused_pid)
        if not stream_ancestors or not focused_ancestors:
            return False

        stream_ancestor_by_pid = {
            process_info["pid"]: process_info for process_info in stream_ancestors
        }

        for focused_ancestor in focused_ancestors:
            common_ancestor = stream_ancestor_by_pid.get(focused_ancestor["pid"])
            if not common_ancestor:
                continue

            if self._is_broad_common_ancestor(common_ancestor):
                return False

            logger.debug(
                "Matched stream PID %s to focused PID %s via common ancestor %s (%s)",
                stream_pid,
                focused_pid,
                common_ancestor.get("pid"),
                common_ancestor.get("name"),
            )
            return True

        return False

    @dbus_method_async(input_signature="i", result_signature="")
    async def UpdateFocus(self, pid: int) -> None:
        logger.info(f"UpdateFocus called with pid: {pid}")
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
            stream_pid = stream.get("pid", "")
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
                is_stream_focused = False
                if stream_pid and self._current_focused_pid != -1:
                    if stream_pid == focused_pid_str:
                        is_stream_focused = True
                    else:
                        if self._are_processes_related_by_specific_ancestor(
                            stream_pid, focused_pid_str
                        ):
                            is_stream_focused = True

                if not stream_pid:
                    logger.debug(
                        "Skipping configured stream %s because PipeWire did not expose a process PID",
                        stream_app_name_lower or stream_binary_name_lower or stream_id,
                    )
                    continue

                if is_stream_focused:
                    if stream_is_muted:
                        self._set_stream_mute(stream_id, False)
                else:
                    if not stream_is_muted:
                        self._set_stream_mute(stream_id, True)

    @dbus_method_async(input_signature="", result_signature="s")
    async def Ping(self) -> str:
        return "Pong from FocusAudioManager (sdbus/PipeWire)"

    async def initial_mute_task(self):
        original_focused_pid = self._current_focused_pid
        self._current_focused_pid = -1
        await asyncio.get_event_loop().run_in_executor(
            None, self._apply_audio_rules_sync
        )
        self._current_focused_pid = original_focused_pid


async def main_async():
    missing_commands = [
        command for command in ("pw-dump", "wpctl") if shutil.which(command) is None
    ]
    if missing_commands:
        logger.error(
            "Required PipeWire command(s) not found in PATH: %s",
            ", ".join(missing_commands),
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
