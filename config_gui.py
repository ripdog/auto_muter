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
    QComboBox,
    QDialog,
    QDialogButtonBox,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon


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


class AddFromActiveDialog(QDialog):
    def __init__(self, parent=None, active_apps=None):
        super().__init__(parent)
        self.setWindowTitle("Add Active Application")
        self.setMinimumWidth(300)

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Select a currently active audio application:"))

        self.app_combo = QComboBox()
        self.app_combo.addItems(sorted(list(active_apps or set())))
        layout.addWidget(self.app_combo)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def get_selected_app(self):
        return self.app_combo.currentText()


class AutoMuterConfigApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Auto Muter Config")
        self.resize(400, 500)
        self.config_path = get_config_path()
        self.config_data = {"configured_process_names": []}

        self.init_ui()
        self.load_config()

    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)

        layout = QVBoxLayout()

        # Title
        title_label = QLabel("Applications to Auto-Mute:")
        title_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title_label)

        # Subtitle
        desc_label = QLabel(
            "These applications will be muted when they lose window focus."
        )
        desc_label.setStyleSheet("color: gray; margin-bottom: 5px;")
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)

        # List widget
        self.list_widget = QListWidget()
        self.list_widget.setAlternatingRowColors(True)
        layout.addWidget(self.list_widget)

        # Add manual layout
        add_manual_layout = QHBoxLayout()
        self.app_input = QLineEdit()
        self.app_input.setPlaceholderText("Enter binary or window name manually...")
        self.app_input.returnPressed.connect(self.add_app_manual)

        add_manual_btn = QPushButton("Add Manual")
        add_manual_btn.clicked.connect(self.add_app_manual)

        add_manual_layout.addWidget(self.app_input)
        add_manual_layout.addWidget(add_manual_btn)

        # Add from active apps button
        add_active_btn = QPushButton("Select from currently playing audio...")
        add_active_btn.clicked.connect(self.add_app_from_active)

        layout.addWidget(add_active_btn)
        layout.addLayout(add_manual_layout)

        # Remove button
        remove_btn = QPushButton("Remove Selected")
        remove_btn.clicked.connect(self.remove_app)
        layout.addWidget(remove_btn)

        # Status label
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #444; font-style: italic;")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)

        main_widget.setLayout(layout)

    def load_config(self):
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, "r", encoding="utf-8") as f:
                    self.config_data = json.load(f)
            else:
                self.config_data = {"configured_process_names": []}

            self.refresh_list()
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

    def refresh_list(self):
        self.list_widget.clear()
        names = self.config_data.get("configured_process_names", [])
        for name in names:
            self.list_widget.addItem(name)

    def add_app_internal(self, new_app: str):
        if not new_app:
            return

        names = self.config_data.setdefault("configured_process_names", [])
        if new_app not in names:
            names.append(new_app)
            self.refresh_list()
            self.save_config()
        else:
            self.status_label.setText(f"'{new_app}' is already in the list.")

    def add_app_manual(self):
        new_app = self.app_input.text().strip()
        if new_app:
            self.add_app_internal(new_app)
            self.app_input.clear()

    def add_app_from_active(self):
        self.status_label.setText("Scanning for active audio streams...")
        QApplication.processEvents()  # Force UI update

        active_apps = get_active_audio_apps()
        if not active_apps:
            QMessageBox.information(
                self,
                "No Active Apps",
                "No relevant currently active audio applications found.",
            )
            self.status_label.setText("")
            return

        dialog = AddFromActiveDialog(self, active_apps)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected_app = dialog.get_selected_app()
            if selected_app:
                self.add_app_internal(selected_app)
        else:
            self.status_label.setText("")

    def remove_app(self):
        selected_items = self.list_widget.selectedItems()
        if not selected_items:
            return

        for item in selected_items:
            app_name = item.text()
            names = self.config_data.get("configured_process_names", [])
            if app_name in names:
                names.remove(app_name)

        self.refresh_list()
        self.save_config()


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
