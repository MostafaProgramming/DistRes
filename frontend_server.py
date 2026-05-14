from __future__ import annotations

import json
from datetime import datetime
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent
FRONTEND_DIR = ROOT / "frontend"
PRODUCT_FILE = ROOT / "ProductSpecification.txt"


class DistResHandler(SimpleHTTPRequestHandler):
    """Serve the static dashboard and a tiny API for the live shared file."""

    def __init__(self, *args, **kwargs):
        # Static files are served from DistRes/frontend.
        super().__init__(*args, directory=str(FRONTEND_DIR), **kwargs)

    def do_GET(self) -> None:
        """Route API requests separately from normal dashboard assets."""
        parsed = urlparse(self.path)
        if parsed.path == "/api/shared-file":
            self.handle_shared_file()
            return
        super().do_GET()

    def handle_shared_file(self) -> None:
        """Return the current server-hosted ProductSpecification.txt content."""
        content = PRODUCT_FILE.read_text(encoding="utf-8", errors="replace")
        stats = PRODUCT_FILE.stat()
        self.send_json(
            {
                "path": PRODUCT_FILE.name,
                "content": content,
                "size": stats.st_size,
                "updatedAt": datetime.fromtimestamp(stats.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            }
        )

    def send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        """Send JSON responses with no caching so demos show fresh file data."""
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)


def main() -> None:
    """Start the local evidence server used by the visualiser."""
    server = ThreadingHTTPServer(("127.0.0.1", 8100), DistResHandler)
    print("Serving DistRes frontend at http://localhost:8100")
    server.serve_forever()


if __name__ == "__main__":
    main()
