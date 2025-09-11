import os
import sys
import time
import subprocess

try:
    import win32serviceutil
    import win32service
    import win32event
    import servicemanager
except Exception as e:
    # Allow import for non-Windows dev environments
    win32serviceutil = None


SERVICE_NAME = "PLCLoggerAgent"
SERVICE_DISPLAY = "PLC Logger Agent"
SERVICE_DESC = "Runs the PLC Logger Agent API and background jobs as a Windows service."


class PLCLoggerService(win32serviceutil.ServiceFramework):  # type: ignore[misc]
    _svc_name_ = SERVICE_NAME
    _svc_display_name_ = SERVICE_DISPLAY
    _svc_description_ = SERVICE_DESC

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)  # type: ignore[attr-defined]
        self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)  # type: ignore[attr-defined]
        self.proc = None

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)  # type: ignore[attr-defined]
        try:
            if self.proc and self.proc.poll() is None:
                self.proc.terminate()
                for _ in range(20):
                    if self.proc.poll() is not None:
                        break
                    time.sleep(0.2)
                if self.proc.poll() is None:
                    self.proc.kill()
        except Exception:
            pass
        win32event.SetEvent(self.hWaitStop)  # type: ignore[attr-defined]

    def SvcDoRun(self):
        servicemanager.LogInfoMsg(f"{SERVICE_DISPLAY} starting...")  # type: ignore[attr-defined]
        # Ensure loopback binding, token, and machine-scope DPAPI
        os.environ.setdefault("AGENT_HOST", "127.0.0.1")
        os.environ.setdefault("AGENT_DPAPI_MACHINE", "1")
        if not os.environ.get("AGENT_TOKEN"):
            os.environ["AGENT_TOKEN"] = __import__("secrets").token_urlsafe(24)
        # Spawn the agent process
        # If running as a PyInstaller-frozen EXE, prefer the bundled agent runner exe
        try:
            frozen = getattr(sys, 'frozen', False)
        except Exception:
            frozen = False
        base_dir = os.path.dirname(sys.executable) if frozen else os.path.dirname(__file__)
        exe_path = os.path.join(base_dir, "plclogger-agent.exe")
        if os.path.isfile(exe_path):
            cmd = [exe_path]
        else:
            # Fallback to launching via Python
            cmd = [sys.executable, "-u", os.path.join(base_dir, "run_agent.py")]
        logdir = os.path.join(os.environ.get("ProgramData", os.getcwd()), "PLCLogger", "agent", "logs")
        try:
            os.makedirs(logdir, exist_ok=True)
        except Exception:
            pass
        logfile = os.path.join(logdir, "service.out.log")
        with open(logfile, "a", encoding="utf-8") as out:
            self.proc = subprocess.Popen(cmd, stdout=out, stderr=out)
            # Wait until stop is requested
            win32event.WaitForSingleObject(self.hWaitStop, win32event.INFINITE)  # type: ignore[attr-defined]
        servicemanager.LogInfoMsg(f"{SERVICE_DISPLAY} stopped.")  # type: ignore[attr-defined]


if __name__ == '__main__':
    if win32serviceutil is None:
        print("pywin32 is required to install/run the Windows service.")
        sys.exit(1)
    win32serviceutil.HandleCommandLine(PLCLoggerService)  # type: ignore[attr-defined]
