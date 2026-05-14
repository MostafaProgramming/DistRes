from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "logs"
DATA_DIR = ROOT / "frontend" / "data"
PRODUCT_FILE = ROOT / "ProductSpecification.txt"

# The visualiser expects the same four automatic clients launched by run_demo.ps1.
CLIENTS = [
    {"id": 1, "username": "alice", "password": "pass1"},
    {"id": 2, "username": "ben", "password": "pass2"},
    {"id": 3, "username": "chen", "password": "pass3"},
    {"id": 4, "username": "dina", "password": "pass4"},
]


def load_text(path: Path) -> str:
    """Read a text file safely; missing logs simply produce empty evidence."""
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def add_event(events: list[dict], category: str, client: str, detail: str) -> None:
    """Append one replay event in the format consumed by frontend/app.js."""
    events.append(
        {
            "id": len(events) + 1,
            "elapsedMs": len(events) * 420,
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "category": category,
            "client": client,
            "detail": detail,
        }
    )


def parse_client_log(client: dict) -> list[dict]:
    """Convert one client's terminal log into replayable dashboard events."""
    username = client["username"]
    text = load_text(LOG_DIR / f"client-{username}.out.txt")
    events: list[dict] = []

    # Connection/authentication is inferred because this log is only created
    # after run_demo.ps1 successfully launches the authenticated client process.
    add_event(events, "connect", username, f"{username} connected to the DistRes server and authenticated.")

    # A subscription acknowledgement proves this client registered for pub-sub.
    if "OK SUBSCRIBED" in text:
        add_event(events, "subscribe", username, f"{username} subscribed to server update notifications.")

    # The C++ clients print recognisable response strings; these counts become
    # the high-level evidence cards in the visual replay.
    read_count = len(re.findall(r"received DATA", text))
    write_count = len(re.findall(r"received OK WRITE", text))
    notifications = re.findall(r"notification: (EVENT UPDATE [^\n]+)", text)

    for index in range(read_count):
        add_event(events, "read", username, f"{username} completed server-hosted READ #{index + 1}.")

    for index in range(write_count):
        add_event(events, "write", username, f"{username} completed exclusive WRITE #{index + 1}.")

    for notification in notifications:
        add_event(events, "notify", username, f"{username} received {notification}.")

    return events


def build_dataset() -> dict:
    """Build the complete JSON dataset for the DistRes replay visualiser."""
    events: list[dict] = []
    for client in CLIENTS:
        events.extend(parse_client_log(client))

    # Give the UI a deterministic event order and spacing for replay controls.
    events.sort(key=lambda event: (event["elapsedMs"], event["client"], event["category"]))
    for index, event in enumerate(events, start=1):
        event["id"] = index
        event["elapsedMs"] = (index - 1) * 420

    product_text = load_text(PRODUCT_FILE)
    writes = [line for line in product_text.splitlines() if "distributed-update-from-" in line]
    notifications = [event for event in events if event["category"] == "notify"]

    return {
        "metadata": {
            "project": "DistRes",
            "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "server": "127.0.0.1:54000",
            "clientCount": len(CLIENTS),
            "eventCount": len(events),
        },
        "clients": CLIENTS,
        "summary": {
            "reads": len([event for event in events if event["category"] == "read"]),
            "writes": len([event for event in events if event["category"] == "write"]),
            "notifications": len(notifications),
            "resourceUpdates": len(writes),
        },
        "events": events,
        "resource": {
            "path": "ProductSpecification.txt",
            "content": product_text,
        },
    }


def main() -> None:
    """Write frontend/data/distres_run.json after the automatic demo finishes."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    dataset = build_dataset()
    (DATA_DIR / "distres_run.json").write_text(json.dumps(dataset, indent=2), encoding="utf-8")
    print(DATA_DIR / "distres_run.json")


if __name__ == "__main__":
    main()
