from __future__ import annotations

import json
import queue
import socket
import threading
import time
import uuid
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent
LIVE_FRONTEND_DIR = ROOT / "live_frontend"
DISTRES_HOST = "127.0.0.1"
DISTRES_PORT = 54000


def send_line(sock: socket.socket, line: str) -> None:
    """Send one newline-terminated DistRes protocol command."""
    sock.sendall((line + "\n").encode("utf-8"))


def recv_line(sock: socket.socket) -> str:
    """Read one newline-terminated response from the C++ DistRes server."""
    data = bytearray()
    while True:
        chunk = sock.recv(1)
        if not chunk:
            raise ConnectionError("DistRes server closed the socket")
        if chunk == b"\n":
            return data.decode("utf-8", errors="replace").rstrip("\r")
        data.extend(chunk)


def escape_protocol_text(text: str) -> str:
    """Preserve full file content inside DistRes' newline-based TCP protocol."""
    return text.replace("\\", "\\\\").replace("\r", "\\r").replace("\n", "\\n")


def unescape_protocol_text(text: str) -> str:
    """Convert escaped server text back into editable file content."""
    output: list[str] = []
    i = 0
    while i < len(text):
        if text[i] == "\\" and i + 1 < len(text):
            i += 1
            if text[i] == "n":
                output.append("\n")
            elif text[i] == "r":
                output.append("\r")
            else:
                output.append(text[i])
        else:
            output.append(text[i])
        i += 1
    return "".join(output)


def connect_and_authenticate(username: str, password: str) -> socket.socket:
    """Open a TCP socket to DistResServer.exe and authenticate it."""
    sock = socket.create_connection((DISTRES_HOST, DISTRES_PORT), timeout=4)
    send_line(sock, f"AUTH {username} {password}")
    response = recv_line(sock)
    if response != "OK AUTH":
        sock.close()
        raise PermissionError(response)
    # After login, socket operations can block while the C++ lock is waiting.
    sock.settimeout(None)
    return sock


def current_time() -> str:
    """Human-readable time for the live server dashboard."""
    return time.strftime("%H:%M:%S")


def parse_write_version(response: str) -> str:
    """Extract vN from responses such as OK WRITE v3."""
    parts = response.split()
    return parts[-1] if len(parts) >= 3 and parts[-1].startswith("v") else "-"


class ServerMonitor:
    """Read-only view of the DistRes server activity for the demo dashboard."""

    def __init__(self):
        self.lock = threading.Lock()
        self.clients: dict[str, dict] = {}
        self.events: list[dict] = []
        self.resource_version = "-"

    def connect_client(self, session_id: str, username: str) -> None:
        with self.lock:
            self.clients[session_id] = {
                "sessionId": session_id[:8],
                "username": username,
                "state": "connected",
                "reading": False,
                "writing": False,
                "waiting": "",
                "subscribed": False,
                "connectedAt": current_time(),
                "lastAction": "AUTH accepted",
            }
            self._record_locked("AUTH", f"{username} authenticated and connected", username)

    def disconnect_client(self, session_id: str) -> None:
        with self.lock:
            client = self.clients.pop(session_id, None)
            if client:
                self._record_locked("DISCONNECT", f"{client['username']} disconnected", client["username"])

    def set_waiting(self, session_id: str, wait_type: str) -> None:
        with self.lock:
            client = self.clients.get(session_id)
            if not client:
                return
            client["state"] = f"waiting for {wait_type}"
            client["waiting"] = wait_type
            client["lastAction"] = f"requested {wait_type} lock"
            self._record_locked("WAIT", f"{client['username']} is waiting for {wait_type} access", client["username"])

    def set_reading(self, session_id: str) -> None:
        with self.lock:
            client = self.clients.get(session_id)
            if not client:
                return
            client["state"] = "reading"
            client["reading"] = True
            client["waiting"] = ""
            client["lastAction"] = "READ lock granted"
            self._record_locked("READ LOCK", f"{client['username']} received shared read access", client["username"])

    def release_read(self, session_id: str) -> None:
        with self.lock:
            client = self.clients.get(session_id)
            if not client:
                return
            client["state"] = "connected"
            client["reading"] = False
            client["waiting"] = ""
            client["lastAction"] = "READ lock released"
            self._record_locked("READ RELEASE", f"{client['username']} released shared read access", client["username"])

    def set_writing(self, session_id: str) -> None:
        with self.lock:
            client = self.clients.get(session_id)
            if not client:
                return
            client["state"] = "writing"
            client["writing"] = True
            client["waiting"] = ""
            client["lastAction"] = "WRITE lock granted"
            self._record_locked("WRITE LOCK", f"{client['username']} received exclusive write access", client["username"])

    def release_write(self, session_id: str, action: str, version: str = "-") -> None:
        with self.lock:
            client = self.clients.get(session_id)
            if not client:
                return
            if version != "-":
                self.resource_version = version
            client["state"] = "connected"
            client["writing"] = False
            client["waiting"] = ""
            client["lastAction"] = action
            self._record_locked("WRITE RELEASE", f"{client['username']} {action}", client["username"])

    def set_subscribed(self, session_id: str) -> None:
        with self.lock:
            client = self.clients.get(session_id)
            if not client:
                return
            client["subscribed"] = True
            client["lastAction"] = "SUBSCRIBE accepted"
            self._record_locked("SUBSCRIBE", f"{client['username']} subscribed for update events", client["username"])

    def record_read(self, session_id: str) -> None:
        with self.lock:
            client = self.clients.get(session_id)
            if not client:
                return
            client["lastAction"] = "READ_FULL completed"
            self._record_locked("READ", f"{client['username']} read the full resource", client["username"])

    def record_event_delivery(self, session_id: str, event: str) -> None:
        with self.lock:
            client = self.clients.get(session_id)
            username = client["username"] if client else "unknown"
            self._record_locked("EVENT UPDATE", f"delivered to {username}: {event}", username)

    def record_error(self, session_id: str, message: str) -> None:
        with self.lock:
            client = self.clients.get(session_id)
            username = client["username"] if client else "unknown"
            if client:
                client["waiting"] = ""
                client["lastAction"] = message
            self._record_locked("ERROR", message, username)

    def snapshot(self) -> dict:
        with self.lock:
            clients = list(self.clients.values())
            active_readers = [c["username"] for c in clients if c["reading"]]
            active_writers = [c["username"] for c in clients if c["writing"]]
            waiting_reads = [c["username"] for c in clients if c["waiting"] == "read"]
            waiting_writes = [c["username"] for c in clients if c["waiting"] == "write"]
            return {
                "generatedAt": current_time(),
                "distresHost": DISTRES_HOST,
                "distresPort": DISTRES_PORT,
                "resource": "ProductSpecification.txt",
                "resourceVersion": self.resource_version,
                "connectedClients": len(clients),
                "activeReaders": active_readers,
                "activeWriter": active_writers[0] if active_writers else "",
                "waitingReads": waiting_reads,
                "waitingWrites": waiting_writes,
                "subscriberCount": sum(1 for c in clients if c["subscribed"]),
                "clients": sorted(clients, key=lambda c: c["connectedAt"]),
                "events": list(reversed(self.events[-40:])),
            }

    def _record_locked(self, event_type: str, message: str, username: str = "") -> None:
        self.events.append({
            "time": current_time(),
            "type": event_type,
            "username": username,
            "message": message,
        })
        self.events = self.events[-80:]


monitor = ServerMonitor()


class LiveSession:
    """One browser user mapped to one command socket and one subscription socket."""

    def __init__(self, username: str, password: str):
        self.id = uuid.uuid4().hex
        self.username = username
        self.password = password
        self.command_socket = connect_and_authenticate(username, password)
        self.subscription_socket: socket.socket | None = None
        self.event_queue: queue.Queue[str] = queue.Queue()
        self.closed = False
        self.reading = False
        self.editing = False
        self.subscribed = False
        monitor.connect_client(self.id, username)

    def read(self) -> str:
        """Ask the C++ server to read ProductSpecification.txt."""
        try:
            send_line(self.command_socket, "READ_FULL")
            response = recv_line(self.command_socket)
            if not response.startswith("DATA_FULL "):
                raise RuntimeError(response)
            monitor.record_read(self.id)
            return unescape_protocol_text(response[len("DATA_FULL "):])
        except Exception as exc:
            monitor.record_error(self.id, f"READ failed: {exc}")
            raise

    def begin_read(self) -> str:
        """Acquire a server-side read lock and return the shared file content."""
        monitor.set_waiting(self.id, "read")
        try:
            send_line(self.command_socket, "BEGIN_READ")
            response = recv_line(self.command_socket)
            if not response.startswith("READ_DATA "):
                raise RuntimeError(response)
            self.reading = True
            monitor.set_reading(self.id)
            return unescape_protocol_text(response[len("READ_DATA "):])
        except Exception as exc:
            monitor.record_error(self.id, f"BEGIN_READ failed: {exc}")
            raise

    def end_read(self) -> str:
        """Release this browser user's server-side read lock."""
        send_line(self.command_socket, "END_READ")
        response = recv_line(self.command_socket)
        if response.startswith("OK READ_RELEASED"):
            self.reading = False
            monitor.release_read(self.id)
        return response

    def begin_write(self) -> str:
        """Acquire the server-side writer lock and return editable file content."""
        monitor.set_waiting(self.id, "write")
        try:
            send_line(self.command_socket, "BEGIN_WRITE")
            response = recv_line(self.command_socket)
            if not response.startswith("EDIT_DATA "):
                raise RuntimeError(response)
            self.editing = True
            monitor.set_writing(self.id)
            return unescape_protocol_text(response[len("EDIT_DATA "):])
        except Exception as exc:
            monitor.record_error(self.id, f"BEGIN_WRITE failed: {exc}")
            raise

    def commit_write(self, text: str) -> str:
        """Replace the shared file while this session holds the writer lock."""
        send_line(self.command_socket, f"COMMIT_WRITE {escape_protocol_text(text)}")
        response = recv_line(self.command_socket)
        if response.startswith("OK WRITE"):
            self.editing = False
            monitor.release_write(self.id, f"committed {parse_write_version(response)}", parse_write_version(response))
        return response

    def cancel_write(self) -> str:
        """Release the writer lock without changing ProductSpecification.txt."""
        send_line(self.command_socket, "CANCEL_WRITE")
        response = recv_line(self.command_socket)
        self.editing = False
        monitor.release_write(self.id, "cancelled write lock")
        return response

    def subscribe(self) -> str:
        """Register a separate observer socket for publish-subscribe updates."""
        if self.subscribed:
            return "OK SUBSCRIBED"

        sub = connect_and_authenticate(self.username, self.password)
        send_line(sub, "SUBSCRIBE")
        response = recv_line(sub)
        if response != "OK SUBSCRIBED":
            sub.close()
            raise RuntimeError(response)

        self.subscription_socket = sub
        self.subscribed = True
        monitor.set_subscribed(self.id)
        threading.Thread(target=self._subscription_loop, args=(sub,), daemon=True).start()
        return response

    def close(self) -> None:
        """Close the live browser session and its DistRes command socket."""
        if self.closed:
            return
        self.closed = True
        try:
            if self.reading:
                self.end_read()
            if self.editing:
                self.cancel_write()
            if self.subscription_socket:
                try:
                    send_line(self.subscription_socket, "QUIT")
                    self.subscription_socket.close()
                except OSError:
                    pass
            send_line(self.command_socket, "QUIT")
            self.command_socket.close()
            monitor.disconnect_client(self.id)
        except OSError:
            pass

    def _subscription_loop(self, sub: socket.socket) -> None:
        """Keep a subscriber socket open and forward events to the browser."""
        try:
            while not self.closed:
                event = recv_line(sub)
                self.event_queue.put(event)
                monitor.record_event_delivery(self.id, event)
        except Exception as exc:
            if not self.closed:
                self.event_queue.put(f"EVENT ERROR detail={exc}")
                monitor.record_error(self.id, f"subscription failed: {exc}")


sessions: dict[str, LiveSession] = {}
sessions_lock = threading.Lock()


class LiveDistResHandler(SimpleHTTPRequestHandler):
    """Serve the live UI and translate browser API calls into DistRes TCP commands."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(LIVE_FRONTEND_DIR), **kwargs)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self.send_json({"status": "live-ui-ready", "distresPort": DISTRES_PORT})
            return
        if parsed.path == "/api/server-state":
            self.send_json(monitor.snapshot())
            return
        if parsed.path.startswith("/api/events/"):
            self.handle_events(parsed.path.rsplit("/", 1)[-1])
            return
        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/login":
            self.handle_login()
            return
        if parsed.path == "/api/read":
            self.handle_read()
            return
        if parsed.path == "/api/begin-read":
            self.handle_begin_read()
            return
        if parsed.path == "/api/end-read":
            self.handle_end_read()
            return
        if parsed.path == "/api/subscribe":
            self.handle_subscribe()
            return
        if parsed.path == "/api/begin-write":
            self.handle_begin_write()
            return
        if parsed.path == "/api/write":
            self.handle_write()
            return
        if parsed.path == "/api/cancel-write":
            self.handle_cancel_write()
            return
        if parsed.path == "/api/logout":
            self.handle_logout()
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Endpoint not found")

    def handle_login(self) -> None:
        payload = self.read_json_body()
        try:
            session = LiveSession(payload["username"], payload["password"])
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=HTTPStatus.UNAUTHORIZED)
            return
        with sessions_lock:
            sessions[session.id] = session
        self.send_json({"sessionId": session.id, "username": session.username})

    def handle_read(self) -> None:
        payload = self.read_json_body()
        session = self.session_from_payload(payload)
        if not session:
            return
        self.send_json({"content": session.read()})

    def handle_begin_read(self) -> None:
        payload = self.read_json_body()
        session = self.session_from_payload(payload)
        if not session:
            return
        self.send_json({"content": session.begin_read()})

    def handle_end_read(self) -> None:
        payload = self.read_json_body()
        session = self.session_from_payload(payload)
        if not session:
            return
        self.send_json({"response": session.end_read()})

    def handle_subscribe(self) -> None:
        payload = self.read_json_body()
        session = self.session_from_payload(payload)
        if not session:
            return
        self.send_json({"response": session.subscribe()})

    def handle_begin_write(self) -> None:
        payload = self.read_json_body()
        session = self.session_from_payload(payload)
        if not session:
            return
        self.send_json({"content": session.begin_write()})

    def handle_write(self) -> None:
        payload = self.read_json_body()
        session = self.session_from_payload(payload)
        if not session:
            return
        text = str(payload.get("text", ""))
        self.send_json({"response": session.commit_write(text)})

    def handle_cancel_write(self) -> None:
        payload = self.read_json_body()
        session = self.session_from_payload(payload)
        if not session:
            return
        self.send_json({"response": session.cancel_write()})

    def handle_logout(self) -> None:
        payload = self.read_json_body()
        session = self.session_from_payload(payload)
        if not session:
            return
        session.close()
        with sessions_lock:
            sessions.pop(session.id, None)
        self.send_json({"ok": True})

    def handle_events(self, session_id: str) -> None:
        """Stream live DistRes notifications to the browser using Server-Sent Events."""
        with sessions_lock:
            session = sessions.get(session_id)
        if not session:
            self.send_error(HTTPStatus.NOT_FOUND, "Unknown session")
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        while not session.closed:
            try:
                event = session.event_queue.get(timeout=20)
            except queue.Empty:
                self.wfile.write(b": heartbeat\n\n")
                self.wfile.flush()
                continue
            self.wfile.write(f"data: {event}\n\n".encode("utf-8"))
            self.wfile.flush()

    def session_from_payload(self, payload: dict) -> LiveSession | None:
        session_id = str(payload.get("sessionId", ""))
        with sessions_lock:
            session = sessions.get(session_id)
        if not session:
            self.send_json({"error": "Unknown or expired session"}, status=HTTPStatus.UNAUTHORIZED)
            return None
        return session

    def read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw)

    def send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 8200), LiveDistResHandler)
    print("Serving live DistRes UI at http://127.0.0.1:8200")
    server.serve_forever()


if __name__ == "__main__":
    main()
