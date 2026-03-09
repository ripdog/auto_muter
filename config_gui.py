#!/usr/bin/env python3
# /// script
# requires-python = ">=3.8"
# dependencies = [
#   "PySide6"
# ]
# ///

import sys
import json
import os
import subprocess
import re
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QListWidget,
    QPushButton,
    QLineEdit,
    QLabel,
    QMessageBox,
    QMenu,
    QListWidgetItem,
    QAbstractItemView,
)
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QIcon, QAction


def get_config_path() -> str:
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    return os.path.join(xdg_config_home, "auto_muter", "config.json")


def get_active_audio_apps() -> set:
    """Fetch currently active audio applications from pactl."""
    apps = set()
    try:
        result = subprocess.run(
            ["pactl", "list", "sink-inputs"], capture_output=True, text=True, check=True
        )
        pactl_output = result.stdout

        binary_re = re.compile(r'application\.process\.binary\s*=\s*"([^"]+)"')
        app_name_re = re.compile(r'application\.name\s*=\s*"([^"]+)"')

        for line in pactl_output.splitlines():
            line = line.strip()

            match_binary = binary_re.search(line)
            if match_binary:
                apps.add(match_binary.group(1))

            match_app_name = app_name_re.search(line)
            if match_app_name:
                apps.add(match_app_name.group(1))

    except Exception as e:
        print(f"Error fetching active audio apps: {e}")

    # Filter out obvious system ones that aren't useful to mute
    ignored_apps = {
        "kded6",
        "plasma-workspace",
        "pipewire",
        "wireplumber",
        "pulseaudio",
    }
    return {app for app in apps if app.lower() not in ignored_apps and app.strip()}


class ConfiguredListWidget(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.main_app = parent

    def dragEnterEvent(self, event):
        if event.source() and event.source() != self:
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event):
        if event.source() and event.source() != self:
            items = event.source().selectedItems()
            for item in items:
                if self.main_app:
                    self.main_app.add_app_internal(item.text())  # type: ignore
            event.acceptProposedAction()
        else:
            super().dropEvent(event)


class ActiveListWidget(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)


class AutoMuterConfigApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Auto Muter Config")
        self.resize(700, 500)
        self.config_path = get_config_path()
        self.config_data = {"configured_process_names": []}

        self.init_ui()
        self.load_config()
        self.refresh_active_apps()

    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)

        main_layout = QVBoxLayout(main_widget)

        # Main lists area
        lists_layout = QHBoxLayout()

        # Left side: Active Apps
        left_layout = QVBoxLayout()
        left_header = QHBoxLayout()
        active_label = QLabel("Active Audio Applications:")
        active_label.setStyleSheet("font-weight: bold; font-size: 14px;")

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh_active_apps)

        left_header.addWidget(active_label)
        left_header.addStretch()
        left_header.addWidget(refresh_btn)

        left_layout.addLayout(left_header)

        left_desc = QLabel("Drag to the right or click 'Add >' to auto-mute.")
        left_desc.setStyleSheet("color: gray;")
        left_layout.addWidget(left_desc)

        self.active_list = ActiveListWidget(self)
        left_layout.addWidget(self.active_list)

        # Middle: Transfer buttons
        middle_layout = QVBoxLayout()
        middle_layout.addStretch()

        add_arrow_btn = QPushButton("Add >")
        add_arrow_btn.setToolTip("Add selected active app to auto-mute list")
        add_arrow_btn.clicked.connect(self.add_selected_active)
        middle_layout.addWidget(add_arrow_btn)

        remove_arrow_btn = QPushButton("< Remove")
        remove_arrow_btn.setToolTip("Remove selected app from auto-mute list")
        remove_arrow_btn.clicked.connect(self.remove_selected_configured)
        middle_layout.addWidget(remove_arrow_btn)

        middle_layout.addStretch()

        # Right side: Configured Apps
        right_layout = QVBoxLayout()
        config_label = QLabel("Auto-Muted Applications:")
        config_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        right_layout.addWidget(config_label)

        right_desc = QLabel("Right-click an item to remove it.")
        right_desc.setStyleSheet("color: gray;")
        right_layout.addWidget(right_desc)

        self.config_list = ConfiguredListWidget(self)
        self.config_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.config_list.customContextMenuRequested.connect(self.show_context_menu)
        right_layout.addWidget(self.config_list)

        lists_layout.addLayout(left_layout, 1)
        lists_layout.addLayout(middle_layout)
        lists_layout.addLayout(right_layout, 1)

        main_layout.addLayout(lists_layout)

        # Bottom: Manual Add
        manual_layout = QHBoxLayout()
        self.app_input = QLineEdit()
        self.app_input.setPlaceholderText("Or enter binary/window name manually...")
        self.app_input.returnPressed.connect(self.add_app_manual)

        add_manual_btn = QPushButton("Add Manually")
        add_manual_btn.clicked.connect(self.add_app_manual)

        manual_layout.addWidget(self.app_input)
        manual_layout.addWidget(add_manual_btn)

        main_layout.addLayout(manual_layout)

        # Status label
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #444; font-style: italic;")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(self.status_label)

    def load_config(self):
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, "r", encoding="utf-8") as f:
                    self.config_data = json.load(f)
            else:
                self.config_data = {"configured_process_names": []}

            self.refresh_config_list()
            self.status_label.setText("Config loaded.")
        except Exception as e:
            QMessageBox.critical(
                self, "Error Loading Config", f"Could not load config file:\n{e}"
            )

    def save_config(self):
        try:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.config_data, f, indent=4)
            self.status_label.setText("Configuration saved successfully.")
        except Exception as e:
            QMessageBox.critical(
                self, "Error Saving Config", f"Could not save config file:\n{e}"
            )

    def refresh_config_list(self):
        self.config_list.clear()
        names = self.config_data.get("configured_process_names", [])
        for name in names:
            self.config_list.addItem(name)

    def refresh_active_apps(self):
        self.status_label.setText("Scanning for active audio streams...")
        QApplication.processEvents()

        self.active_list.clear()
        active_apps = get_active_audio_apps()

        configured_names = set(self.config_data.get("configured_process_names", []))

        for app in sorted(list(active_apps)):
            item = QListWidgetItem(app)
            # Optionally gray out items already in the configured list
            if app in configured_names:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                item.setToolTip("Already configured")
            self.active_list.addItem(item)

        self.status_label.setText(f"Found {len(active_apps)} active audio streams.")

    def add_app_internal(self, new_app: str):
        if not new_app:
            return

        names = self.config_data.setdefault("configured_process_names", [])
        if new_app not in names:
            names.append(new_app)
            self.refresh_config_list()
            self.save_config()
            self.refresh_active_apps()  # Update left list to disable the added item
        else:
            self.status_label.setText(f"'{new_app}' is already in the list.")

    def add_app_manual(self):
        new_app = self.app_input.text().strip()
        if new_app:
            self.add_app_internal(new_app)
            self.app_input.clear()

    def add_selected_active(self):
        selected_items = self.active_list.selectedItems()
        for item in selected_items:
            self.add_app_internal(item.text())

    def remove_selected_configured(self):
        selected_items = self.config_list.selectedItems()
        if not selected_items:
            return

        for item in selected_items:
            app_name = item.text()
            names = self.config_data.get("configured_process_names", [])
            if app_name in names:
                names.remove(app_name)

        self.refresh_config_list()
        self.save_config()
        self.refresh_active_apps()  # Re-enable the item in the left list if it's currently active

    def show_context_menu(self, position: QPoint):
        item = self.config_list.itemAt(position)
        if item is not None:
            menu = QMenu()
            remove_action = QAction("Remove", self)
            remove_action.triggered.connect(self.remove_selected_configured)
            menu.addAction(remove_action)
            menu.exec(self.config_list.mapToGlobal(position))


def main():
    app = QApplication(sys.argv)

    # Try setting icon if available
    icon_path = "/usr/share/icons/hicolor/scalable/apps/auto-muter.svg"
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    window = AutoMuterConfigApp()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
