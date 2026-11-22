"""No QEMU/display required: local fake QMP exercises framing and panel events."""
import json
from pathlib import Path
import queue
import socket
import tempfile
import threading
import time
import unittest
from control_panel import QMPClient, QMPError, Worker, absolute


class FakeQMP:
    def __init__(self, behavior):
        self.behavior = behavior
        self.commands = []
        self.errors = []

    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="panel-test-")
        self.path = Path(self.tmp.name) / "qmp.sock"
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(str(self.path))
        self.server.listen(1)
        self.server.settimeout(2)
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()
        return self

    def run(self):
        try:
            with self.server.accept()[0] as conn:
                conn.settimeout(2)
                # Partial greeting + coalesced blank line/event: retain buffered bytes.
                conn.sendall(b'{"Q')
                time.sleep(.005)
                conn.sendall(b'MP":{"version":{}}}\r\n\r\n{"event":"RESET"}\n')
                with conn.makefile("rb") as stream:
                    while line := stream.readline():
                        request = json.loads(line)
                        self.commands.append(request)
                        if not self.behavior(conn, request):
                            break
        except Exception as error:
            self.errors.append(error)

    def __exit__(self, *args):
        self.thread.join(3)
        self.server.close()
        self.tmp.cleanup()
        if self.thread.is_alive():
            raise AssertionError("Fake QMP did not exit")
        if self.errors:
            raise self.errors[0]


def reply(conn, request, content=None):
    message = {"id": request["id"], "return": {} if content is None else content}
    wire = (json.dumps(message) + "\r\n").encode()
    conn.sendall(b'{"event":"STOP"}\n' + wire[:4])
    time.sleep(.002)
    conn.sendall(wire[4:])
    return True


class QMPTests(unittest.TestCase):
    def test_fragmented_coalesced_events_and_ids(self):
        with FakeQMP(reply) as fake:
            client = QMPClient(fake.path)
            try:
                client.connect()
                self.assertEqual(client.execute("query-status"), {})
                self.assertEqual([x["id"] for x in fake.commands], [1, 2])
            finally:
                client.close()

    def test_command_error_keeps_connection_usable(self):
        def behavior(conn, req):
            if req["execute"] == "bad":
                conn.sendall((json.dumps({"id": req["id"], "error": {"class": "CommandNotFound"}}) + "\n").encode())
                return True
            return reply(conn, req)
        with FakeQMP(behavior) as fake:
            client = QMPClient(fake.path)
            try:
                client.connect()
                with self.assertRaises(QMPError):
                    client.execute("bad")
                self.assertEqual(client.execute("query-status"), {})
            finally:
                client.close()

    def test_eof(self):
        def behavior(conn, req):
            return reply(conn, req) if req["execute"] == "qmp_capabilities" else False
        with FakeQMP(behavior) as fake:
            client = QMPClient(fake.path)
            try:
                client.connect()
                with self.assertRaises(ConnectionError):
                    client.execute("query-status")
            finally:
                client.close()

    def test_timeout_not_extended_by_events(self):
        def behavior(conn, req):
            if req["execute"] == "qmp_capabilities":
                return reply(conn, req)
            for _ in range(8):
                try:
                    conn.sendall(b'{"event":"STOP"}\n')
                except (BrokenPipeError, ConnectionResetError):
                    return False
                time.sleep(.02)
            return False
        with FakeQMP(behavior) as fake:
            client = QMPClient(fake.path, timeout=.08)
            try:
                client.connect()
                start = time.monotonic()
                with self.assertRaises(TimeoutError):
                    client.execute("query-status")
                self.assertLess(time.monotonic() - start, .3)
            finally:
                client.close()

    def test_worker_controls_capture_and_disconnect_without_quit(self):
        def behavior(conn, req):
            if req["execute"] == "screendump":
                Path(req["arguments"]["filename"]).write_bytes(b"P6\n1 1\n255\n\x00\x00\x00")
            return reply(conn, req)
        with FakeQMP(behavior) as fake:
            results = queue.Queue()
            worker = Worker(fake.path, 1, results)
            worker.start()
            self.assertEqual(results.get(timeout=2)[1], "connected")
            for kind, value in [("touch", (479, 271)), ("wheel", 1), ("wheel", -1), ("power", None), ("screen", None)]:
                self.assertTrue(worker.submit(kind, value))
            result = results.get(timeout=2)
            self.assertEqual(result[1], "screen")
            self.assertTrue(result[2].startswith(b"P6"))
            worker.stopping.set()
            worker.join(2)
            self.assertFalse(worker.is_alive())
            commands = fake.commands
            self.assertEqual([c["execute"] for c in commands], ["qmp_capabilities"] + ["input-send-event"] * 6 + ["qom-set", "screendump"])
            events = [c["arguments"]["events"] for c in commands if c["execute"] == "input-send-event"]
            self.assertEqual(events[0][:2], [
                {"type": "abs", "data": {"axis": "x", "value": 32767}},
                {"type": "abs", "data": {"axis": "y", "value": 32767}},
            ])
            for down, up, name in [(events[0], events[1], "left"), (events[2], events[3], "wheel-up"), (events[4], events[5], "wheel-down")]:
                self.assertEqual(down[-1]["data"], {"button": name, "down": True})
                self.assertEqual(up[-1]["data"], {"button": name, "down": False})
            self.assertEqual(commands[-2]["arguments"], {"path": "/machine/gpio", "property": "ic9700-power-pulse", "value": True})
            self.assertFalse(Path(commands[-1]["arguments"]["filename"]).exists())

    def test_navigation_whitelist_down_up(self):
        with FakeQMP(lambda conn, req: reply(conn, req)) as fake:
            results = queue.Queue(); worker = Worker(fake.path, 1, results); worker.start()
            self.assertEqual(results.get(timeout=2)[1], "connected")
            self.assertTrue(worker.submit("key", "MENU"))
            self.assertTrue(worker.submit("power"))
            deadline = time.monotonic() + 3
            while len(fake.commands) < 4 and time.monotonic() < deadline:
                time.sleep(.01)
            worker.stopping.set(); worker.join(2)
            events = [c["arguments"]["events"][0] for c in fake.commands if c["execute"] == "input-send-event"]
            self.assertEqual(events, [{"type":"key","data":{"down":down,"key":{"type":"qcode","data":"m"}}} for down in (True, False)])

    def test_unknown_key_cannot_emit_ptt(self):
        with FakeQMP(lambda conn, req: reply(conn, req)) as fake:
            results = queue.Queue(); worker = Worker(fake.path, 1, results); worker.start()
            self.assertEqual(results.get(timeout=2)[1], "connected")
            worker.submit("key", "TRANSMIT")
            self.assertEqual(results.get(timeout=2)[1], "fatal")
            worker.join(2)
            self.assertEqual([c["execute"] for c in fake.commands], ["qmp_capabilities"])

    def test_absolute_bounds(self):
        self.assertEqual(absolute(0, 480), 0)
        self.assertEqual(absolute(479, 480), 32767)
        self.assertEqual(absolute(-30, 272), 0)
        self.assertEqual(absolute(999, 272), 32767)


if __name__ == "__main__":
    unittest.main()
