#!/usr/bin/env python3
"""Independent experimental IC-9700 panel. Connects only to existing local QMP."""
import argparse
import json
from pathlib import Path
import queue
import socket
import stat
import tempfile
import threading
import time


class QMPError(Exception):
    """QMP returned a command error; the connection remains usable."""


class QMPClient:
    """One owner/reader only. Newline framing survives split/coalesced recv()."""

    def __init__(self, path, timeout=2.0):
        self.path = str(path)
        self.timeout = timeout
        self.sock = None
        self.buffer = b""
        self.sequence = 0

    def connect(self):
        if not stat.S_ISSOCK(Path(self.path).stat().st_mode):
            raise ValueError("Target is not an existing UNIX socket")
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            self.sock.settimeout(self.timeout)
            self.sock.connect(self.path)
            greeting = self._read(time.monotonic() + self.timeout)
            if "QMP" not in greeting:
                raise ValueError("Invalid QMP greeting")
            self.execute("qmp_capabilities")
        except Exception:
            self.close()
            raise

    def _read(self, deadline):
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("QMP timeout")
            if b"\n" in self.buffer:
                line, self.buffer = self.buffer.split(b"\n", 1)
                if not line.strip():
                    continue
                result = json.loads(line)
                if not isinstance(result, dict):
                    raise ValueError("QMP message is not an object")
                return result
            self.sock.settimeout(remaining)
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("QMP disconnected before reply")
            self.buffer += chunk
            if len(self.buffer) > 8 * 1024 * 1024:
                raise ValueError("QMP message too large")

    def execute(self, command, arguments=None):
        self.sequence += 1
        request_id = self.sequence
        message = {"execute": command, "id": request_id}
        if arguments is not None:
            message["arguments"] = arguments
        deadline = time.monotonic() + self.timeout
        self.sock.settimeout(self.timeout)
        self.sock.sendall((json.dumps(message) + "\r\n").encode())
        while True:
            reply = self._read(deadline)
            if "event" in reply:
                continue
            if reply.get("id") != request_id:
                raise ValueError("Unexpected QMP reply ID")
            if "error" in reply:
                raise QMPError(str(reply["error"]))
            if "return" not in reply:
                raise ValueError("QMP reply has no return/error")
            return reply["return"]

    def close(self):
        if self.sock is not None:
            self.sock.close()
            self.sock = None


def absolute(pixel, extent):
    """QEMU absolute input uses the inclusive range 0..32767."""
    return round(max(0, min(extent - 1, pixel)) * 32767 / (extent - 1))


def button_events(name, down):
    return {"type": "btn", "data": {"button": name, "down": down}}


class Worker(threading.Thread):
    def __init__(self, path, timeout, results):
        super().__init__(daemon=True, name="ic9700-qmp")
        self.client = QMPClient(path, timeout)
        self.results = results
        self.jobs = queue.Queue(maxsize=64)
        self.stopping = threading.Event()

    def submit(self, kind, value=None):
        try:
            self.jobs.put_nowait((kind, value))
            return True
        except queue.Full:
            return False

    def pulse(self, name, axes=()):
        # Keep down/up adjacent in this serialized worker, including on QMP error.
        try:
            self.client.execute("input-send-event", {"events": [*axes, button_events(name, True)]})
            if name == "left":
                time.sleep(.12)  # let the stock consumer observe down before release
        finally:
            self.client.execute("input-send-event", {"events": [button_events(name, False)]})

    def run(self):
        try:
            self.client.connect()
            self.results.put((self, "connected", None))
            with tempfile.TemporaryDirectory(prefix="ic9700-panel-") as tmp:
                capture = Path(tmp) / "screen.ppm"
                while not self.stopping.is_set():
                    try:
                        kind, value = self.jobs.get(timeout=.1)
                    except queue.Empty:
                        continue
                    if self.stopping.is_set():
                        break
                    try:
                        if kind == "screen":
                            self.client.execute("screendump", {"filename": str(capture), "format": "ppm"})
                            if capture.stat().st_size > 16 * 1024 * 1024:
                                raise ValueError("Screenshot too large")
                            data = capture.read_bytes()
                            capture.unlink()
                            self.results.put((self, "screen", data))
                        elif kind == "touch":
                            x, y = value
                            self.pulse("left", [
                                {"type": "abs", "data": {"axis": "x", "value": absolute(x, 480)}},
                                {"type": "abs", "data": {"axis": "y", "value": absolute(y, 272)}},
                            ])
                        elif kind == "wheel":
                            self.pulse("wheel-up" if value > 0 else "wheel-down")
                        elif kind == "key":
                            keys = {"MENU": "m", "FUNCTION": "f", "M.SCOPE": "s", "QUICK": "q", "EXIT": "esc"}
                            if value not in keys:
                                raise ValueError("Key is not in the allowlist")
                            def key_event(down):
                                return {"type": "key", "data": {"down": down, "key": {"type": "qcode", "data": keys[value]}}}
                            try:
                                self.client.execute("input-send-event", {"events": [key_event(True)]})
                                time.sleep(.12)
                            finally:
                                self.client.execute("input-send-event", {"events": [key_event(False)]})
                            time.sleep(.12)  # allow release sampling before another key
                        elif kind == "power":
                            self.client.execute("qom-set", {"path": "/machine/gpio", "property": "ic9700-power-pulse", "value": True})
                    except QMPError as error:
                        self.results.put((self, "error", f"{kind}: {error}"))
                        if kind == "screen":
                            self.results.put((self, "screen-failed", None))
        except Exception as error:
            self.results.put((self, "fatal", str(error)))
        finally:
            self.client.close()  # Never quit, terminate, pause, or reset QEMU.
            self.results.put((self, "closed", None))


class Panel:
    def __init__(self, root, args):
        import tkinter as tk
        from tkinter import ttk
        self.tk = tk
        self.root = root
        self.args = args
        self.worker = None
        self.connected = False
        self.pending_screen = False
        self.results = queue.Queue()
        self.photo = None
        root.title("IC-9700 QEMU Emulator — LW7DFM")
        ttk.Label(root, text="EXPERIMENTAL · navigation only · no PTT/TX controls").pack(padx=10, pady=6)
        ttk.Label(root, text=f"Local QMP: {args.qmp_socket}").pack(padx=10)
        self.screen = tk.Canvas(root, width=480 * args.scale, height=272 * args.scale,
                                background="black", highlightthickness=0)
        self.screen.pack(padx=10, pady=8)
        self.screen.bind("<Button-1>", self.touch)
        self.screen.bind("<MouseWheel>", self.wheel)
        self.screen.bind("<Button-4>", lambda event: self.send("wheel", 1))
        self.screen.bind("<Button-5>", lambda event: self.send("wheel", -1))
        controls = ttk.Frame(root)
        controls.pack(pady=5)
        self.link = ttk.Button(controls, text="Connect", command=self.toggle)
        self.link.pack(side="left", padx=4)
        self.actions = []
        for title, kind, value in [("Power (pulse)", "power", None), ("Dial −", "wheel", -1), ("Dial +", "wheel", 1)]:
            button = ttk.Button(controls, text=title, command=lambda k=kind, v=value: self.send(k, v), state="disabled")
            button.pack(side="left", padx=4)
            self.actions.append(button)
        navigation = ttk.Frame(root)
        navigation.pack(pady=4)
        for title in ["MENU", "FUNCTION", "M.SCOPE", "QUICK", "EXIT"]:
            button = ttk.Button(navigation, text=title, command=lambda name=title: self.send("key", name), state="disabled")
            button.pack(side="left", padx=2)
            self.actions.append(button)
        self.status = tk.StringVar(value="Disconnected")
        ttk.Label(root, textvariable=self.status, wraplength=480 * args.scale).pack(padx=10, pady=6)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(40, self.poll)
        root.after(args.refresh_ms, self.refresh)
        self.toggle()

    def enabled(self, connected):
        self.connected = connected
        for button in self.actions:
            button.configure(state="normal" if connected else "disabled")

    def toggle(self):
        if self.worker is not None:
            self.worker.stopping.set()
            self.link.configure(state="disabled")
            self.enabled(False)
            self.status.set("Disconnecting; QEMU is still running…")
            return
        self.pending_screen = False
        self.worker = Worker(self.args.qmp_socket, self.args.timeout, self.results)
        self.link.configure(text="Disconnect")
        self.status.set("Connecting…")
        self.worker.start()

    def send(self, kind, value=None):
        if self.connected and self.worker and not self.worker.stopping.is_set():
            if self.worker.submit(kind, value):
                return True
            self.status.set("Queue full: event dropped")
        return False

    def touch(self, event):
        if self.photo is None:
            return
        width, height = self.photo.width(), self.photo.height()
        if 0 <= event.x < width and 0 <= event.y < height:
            self.send("touch", (min(479, event.x * 480 // width), min(271, event.y * 272 // height)))

    def wheel(self, event):
        # One detent per typical Windows/macOS event; no host-side dial counter.
        if event.delta:
            ticks = min(16, max(1, abs(event.delta) // 120))
            for _ in range(ticks):
                self.send("wheel", 1 if event.delta > 0 else -1)

    def refresh(self):
        if self.connected and not self.pending_screen:
            self.pending_screen = self.send("screen")
        self.root.after(self.args.refresh_ms, self.refresh)

    def poll(self):
        try:
            while True:
                worker, kind, value = self.results.get_nowait()
                if worker is not self.worker:
                    continue
                if kind == "connected":
                    if not worker.stopping.is_set():
                        self.enabled(True)
                        self.status.set("Connected · scroll on LCD or Dial ± · click = down/up")
                elif kind == "screen":
                    self.pending_screen = False
                    try:
                        raw = self.tk.PhotoImage(data=value, format="PPM")
                        if (raw.width(), raw.height()) != (480, 272):
                            raise ValueError(f"Unexpected LCD: {raw.width()}×{raw.height()} (expected 480×272)")
                        self.photo = raw.zoom(self.args.scale)
                        self.screen.delete("all")
                        self.screen.create_image(0, 0, anchor="nw", image=self.photo)
                    except Exception as error:
                        self.status.set(f"Invalid screenshot: {error}")
                elif kind == "screen-failed":
                    self.pending_screen = False
                elif kind in ("error", "fatal"):
                    self.status.set(f"Error QMP: {value}")
                    if kind == "fatal":
                        self.enabled(False)
                elif kind == "closed":
                    requested = worker.stopping.is_set()
                    self.worker = None
                    self.enabled(False)
                    self.pending_screen = False
                    self.link.configure(text="Connect", state="normal")
                    if requested:
                        self.status.set("Disconnected · QEMU was not stopped")
        except queue.Empty:
            pass
        self.root.after(40, self.poll)

    def close(self):
        if self.worker:
            self.worker.stopping.set()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qmp-socket", "--socket", required=True, type=Path,
                        help="existing local QMP UNIX socket (no URL/TCP)")
    parser.add_argument("--scale", type=int, choices=range(1, 5), default=2)
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--refresh-ms", type=int, default=500)
    args = parser.parse_args()
    if not .1 <= args.timeout <= 30:
        parser.error("--timeout must be between 0.1 and 30 seconds")
    if not 100 <= args.refresh_ms <= 60000:
        parser.error("--refresh-ms must be between 100 and 60000")
    args.qmp_socket = args.qmp_socket.expanduser().absolute()
    try:
        import tkinter as tk
        root = tk.Tk()
    except Exception as error:
        parser.exit(1, f"Tkinter/display unavailable: {error}\n")
    Panel(root, args)
    root.mainloop()


if __name__ == "__main__":
    main()
