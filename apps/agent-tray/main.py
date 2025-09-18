import os
import sys
import time
import subprocess
from pathlib import Path

from PySide6 import QtGui, QtWidgets, QtCore

_here = Path(__file__).resolve().parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

_mutex_handle = None

import autostart
import health
import logging_conf
import process_manager

setup_logger = logging_conf.setup_logger
get_logs_dir = logging_conf.get_logs_dir
ProcessManager = process_manager.ProcessManager
ProcessEvent = process_manager.ProcessEvent


APP_NAME = "Neuract Agent Tray"
DEFAULT_PORT = int(os.environ.get("AGENT_PORT", "5175"))

logger = setup_logger("agent-tray.ui")


def _single_instance_guard() -> bool:
    """Ensure only one tray instance per user session."""
    global _mutex_handle
    try:
        import win32event
        import win32api
        import winerror
    except Exception:
        return True
    name = "Global\\NeuractLoggerAgentTrayMutex"
    handle = win32event.CreateMutex(None, False, name)
    if handle and win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
        win32api.CloseHandle(handle)
        return False
    _mutex_handle = handle
    return True


def build_icon(color: QtGui.QColor) -> QtGui.QIcon:
    pix = QtGui.QPixmap(256, 256)
    pix.fill(QtCore.Qt.GlobalColor.transparent)
    p = QtGui.QPainter(pix)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.setBrush(QtGui.QBrush(color))
    p.setPen(QtGui.QPen(QtCore.Qt.GlobalColor.black, 4))
    p.drawEllipse(16, 16, 224, 224)
    p.end()
    return QtGui.QIcon(pix)


class TrayApp(QtWidgets.QSystemTrayIcon):
    def __init__(self):
        super().__init__()
        self.pm = ProcessManager(port=DEFAULT_PORT)
        self.pm.on_event(self._on_proc_event)
        self._healthy = False
        self._last_ok_ts: float | None = None
        self._started_at: float | None = None

        # Icons
        self.icon_red = build_icon(QtGui.QColor(200, 30, 30))
        self.icon_green = build_icon(QtGui.QColor(40, 180, 40))
        self.setIcon(self.icon_red)
        self.setToolTip(f"{APP_NAME}: stopped")

        # Menu
        self.menu = QtWidgets.QMenu()
        self.act_start = self.menu.addAction("Start Agent")
        self.act_stop = self.menu.addAction("Stop Agent")
        self.act_restart = self.menu.addAction("Restart Agent")
        self.menu.addSeparator()
        self.act_open_ui = self.menu.addAction("Open UI")
        self.act_open_logs = self.menu.addAction("Open Logs Folder")
        self.menu.addSeparator()
        self.act_autostart = self.menu.addAction("Autostart on login")
        self.act_autostart.setCheckable(True)
        self.menu.addSeparator()
        self.act_exit = self.menu.addAction("Exit")
        self.setContextMenu(self.menu)

        self.act_start.triggered.connect(self._start_agent)
        self.act_stop.triggered.connect(self._stop_agent)
        self.act_restart.triggered.connect(self._restart_agent)
        self.act_open_ui.triggered.connect(self._open_ui)
        self.act_open_logs.triggered.connect(self._open_logs)
        self.act_autostart.triggered.connect(self._toggle_autostart)
        self.act_exit.triggered.connect(self._exit_app)

        self.activated.connect(self._activated)

        # Timers
        self.t_health = QtCore.QTimer(self)
        self.t_health.setInterval(2000)
        self.t_health.timeout.connect(self._poll_health)
        self.t_health.start()

        self.t_tooltip = QtCore.QTimer(self)
        self.t_tooltip.setInterval(1000)
        self.t_tooltip.timeout.connect(self._update_tooltip)
        self.t_tooltip.start()

        # Autostart initial state
        self.act_autostart.setChecked(autostart.is_enabled())

        self.show()

    def _activated(self, reason: QtWidgets.QSystemTrayIcon.ActivationReason):
        if reason == QtWidgets.QSystemTrayIcon.ActivationReason.Trigger:
            # Left click toggles popup menu
            self.contextMenu().popup(QtGui.QCursor.pos())

    def _start_agent(self):
        if self.pm.start():
            self._started_at = time.time()

    def _stop_agent(self):
        self.pm.stop()
        self._healthy = False
        self._started_at = None
        self.setIcon(self.icon_red)

    def _restart_agent(self):
        self.pm.restart()

    def _open_logs(self):
        path = get_logs_dir()
        try:
            if os.name == "nt":
                os.startfile(str(path))  # type: ignore
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as e:
            logger.warning("Open logs failed: %s", e)

    def _toggle_autostart(self):
        cur = self.act_autostart.isChecked()
        ok = autostart.enable() if cur else autostart.disable()
        if not ok:
            self.showMessage(APP_NAME, "Failed to update autostart", QtWidgets.QSystemTrayIcon.MessageIcon.Warning)
        self.act_autostart.setChecked(autostart.is_enabled())

    def _open_ui(self):
        # Try LOCALAPPDATA first, then Program Files
        candidates = []
        la = os.environ.get("LOCALAPPDATA")
        if la:
            for brand in ("Neuract Logger", "PLC Logger"):
                base = Path(la) / brand
                candidates.append(base / "plc-logger-tray.exe")
                candidates.append(base / "plc-logger-app.exe")
        for pf in (Path("C:/Program Files/NeuractLogger"), Path("C:/Program Files/PLCLogger")):
            candidates.append(pf / "ui" / "plc-logger-tray.exe")
            candidates.append(pf / "ui" / "plc-logger-app.exe")
        for p in candidates:
            try:
                if p.exists():
                    os.startfile(str(p))  # type: ignore
                    return
            except Exception:
                continue
        self.showMessage(APP_NAME, "UI not installed", QtWidgets.QSystemTrayIcon.MessageIcon.Information)

    def _poll_health(self):
        hs = health.check_health(port=DEFAULT_PORT)
        if hs.ok:
            if not self._healthy:
                self.setIcon(self.icon_green)
            self._healthy = True
            self._last_ok_ts = hs.last_ok_ts
            if self._started_at is None:
                self._started_at = hs.last_ok_ts or time.time()
        else:
            if self._healthy:
                self.setIcon(self.icon_red)
            self._healthy = False
            self._started_at = None
            self._last_ok_ts = None

    def _update_tooltip(self):
        if self._healthy:
            uptime = 0
            base_ts = self._started_at or self._last_ok_ts
            if base_ts:
                uptime = max(0, int(time.time() - base_ts))
            tip = f"{APP_NAME}: running on :{DEFAULT_PORT} (uptime {uptime}s)"
        else:
            tip = f"{APP_NAME}: stopped"
        self.setToolTip(tip)

    def _on_proc_event(self, ev: ProcessEvent):
        if ev.type == "started":
            self._started_at = time.time()
            self.showMessage(APP_NAME, "Agent starting...", QtWidgets.QSystemTrayIcon.MessageIcon.Information)
        elif ev.type == "stopped":
            self._started_at = None
            self._healthy = False
            self.setIcon(self.icon_red)
        elif ev.type == "exited":
            self._started_at = None
            self._healthy = False
            self.setIcon(self.icon_red)
            self.showMessage(APP_NAME, f"Agent exited (code {ev.code})", QtWidgets.QSystemTrayIcon.MessageIcon.Warning)
        elif ev.type == "port_busy":
            self._handle_port_busy()
        elif ev.type == "restarting":
            self.showMessage(APP_NAME, "Restarting agent...", QtWidgets.QSystemTrayIcon.MessageIcon.Information)

    def _handle_port_busy(self):
        # Show blocking dialog with Retry/Cancel
        msg = QtWidgets.QMessageBox()
        msg.setWindowTitle(APP_NAME)
        msg.setIcon(QtWidgets.QMessageBox.Icon.Warning)
        msg.setText(f"Port {DEFAULT_PORT} is in use. Retry?")
        msg.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Retry | QtWidgets.QMessageBox.StandardButton.Cancel)
        ret = msg.exec()
        if ret == QtWidgets.QMessageBox.StandardButton.Retry:
            QtCore.QTimer.singleShot(100, self._restart_agent)
        else:
            self._stop_agent()

    def _exit_app(self):
        self.hide()
        self.pm.stop()
        try:
            if _mutex_handle is not None:
                import win32api
                win32api.CloseHandle(_mutex_handle)
        except Exception:
            pass
        QtWidgets.QApplication.quit()


def main():
    if not _single_instance_guard():
        # Bring attention to existing instance
        # Simple message box; in practice we might signal existing instance via IPC
        app = QtWidgets.QApplication(sys.argv)
        QtWidgets.QMessageBox.information(None, APP_NAME, f"{APP_NAME} is already running.")
        return 0

    app = QtWidgets.QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    tray = TrayApp()
    tray.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())




