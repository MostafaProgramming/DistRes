# DistRes

DistRes is a distributed resource access and synchronisation engine for 6CM604 Course Work 2. It extends the earlier ConRes coursework idea from local concurrency into a client-server distributed system.

Multiple client nodes connect to one server node over TCP sockets. The server owns the user credentials and the shared distributed file, `ProductSpecification.txt`, so clients must request access through the server rather than reading or writing the file directly.

## Key Features

- TCP client-server communication using Winsock
- server-side authentication for distributed client nodes
- server-hosted shared resource file
- concurrent read access for multiple clients
- exclusive write access for one client at a time
- writer-aware readers-writer lock to prevent race conditions
- publish-subscribe update notifications after committed writes
- retry logic when the server is temporarily unavailable
- replayable frontend visualiser for demonstration evidence
- live browser client for real read/write use and notifications

## Coursework Requirement Mapping

| DistRes requirement | Implementation |
| --- | --- |
| Distributed node communication | `DistResClient.exe` communicates with `DistResServer.exe` over TCP. |
| Client-server coordination | `DistResServer` accepts sockets and creates a worker thread per client. |
| Server-hosted credentials | `UserStore` validates usernames and passwords on the server. |
| Server-hosted shared file | `ResourceRepository` controls access to `ProductSpecification.txt`. |
| Multiple concurrent readers | `ReadGuard` and `WriterFairRWLock::acquireRead()` allow shared read access. |
| One writer at a time | `WriteGuard` and `WriterFairRWLock::acquireWrite()` enforce exclusive writes. |
| Publish-subscribe updates | `PubSubBroker` sends `EVENT UPDATE` messages to subscribed clients. |
| Fault tolerance | `connectWithRetry()` retries failed server connections. |
| Demonstration evidence | Logs are converted into `distres_run.json` for the frontend replay. |

## Requirements

- Windows PowerShell
- `g++` with C++20 support
- Python 3
- A browser for the frontend visualiser

## Build

From the `DistRes` folder:

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

This creates:

```text
DistResServer.exe
DistResClient.exe
```

## Run Automatic Demo

```powershell
powershell -ExecutionPolicy Bypass -File .\run_demo.ps1
```

This will:

1. build the project
2. start the server node
3. launch four client nodes: `alice`, `ben`, `chen`, and `dina`
4. make each client read, write, and read again
5. capture evidence logs in `logs/`
6. stop the server after the clients finish

## Run Frontend Visualiser

```powershell
powershell -ExecutionPolicy Bypass -File .\launch_frontend.ps1
```

Then open:

```text
http://localhost:8100
```

The visualiser shows:

- distributed client nodes
- server node and shared resource
- event-by-event replay
- read/write evidence
- publish-subscribe notifications
- current `ProductSpecification.txt` contents

## Run Live Browser Client

```powershell
powershell -ExecutionPolicy Bypass -File .\launch_live_ui.ps1
```

Then open:

```text
http://localhost:8200
```

This UI lets browser users actually use DistRes:

- log in as a client node
- explicitly subscribe to server-published update events
- start and stop a held read session for `ProductSpecification.txt`
- request the exclusive writer lock
- edit and save the shared file through the server
- receive live `EVENT UPDATE` subscriber notifications

For a strong demonstration, open two browser windows and log in as different users. Click Subscribe in the window that should observe updates, start reading in one window, request the write lock in the other, then stop reading to show the queued writer receiving exclusive access and publishing an update event.

## Manual Client Demo

Open one terminal for the server:

```powershell
.\DistResServer.exe
```

Open another terminal for a client:

```powershell
.\DistResClient.exe alice pass1
```

Client commands:

```text
read
write updated valve tolerance to 0.04mm
quit
```

You can open more client terminals:

```powershell
.\DistResClient.exe ben pass2
.\DistResClient.exe chen pass3
.\DistResClient.exe dina pass4
```

## Protocol Summary

DistRes uses a simple line-based TCP protocol:

| Command | Meaning |
| --- | --- |
| `AUTH username password` | Authenticate the client with the server. |
| `READ` | Request the current shared file contents. |
| `WRITE text` | Ask the server to append an update to the shared file. |
| `READ_FULL` | Request full file contents for the live browser editor. |
| `BEGIN_READ` | Acquire a shared read lock and return file contents. |
| `END_READ` | Release this client's shared read lock. |
| `BEGIN_WRITE` | Acquire the writer lock and return editable file contents. |
| `COMMIT_WRITE text` | Replace the shared file and release the writer lock. |
| `CANCEL_WRITE` | Release the writer lock without saving. |
| `SUBSCRIBE` | Register for update notifications. |
| `QUIT` | Close the client session. |
| `EVENT UPDATE vN ...` | Server notification after a committed write. |

## Demo Explanation

The most important point is that clients never directly open `ProductSpecification.txt`. Every read or write request goes through the server.

This matters because the server can enforce:

- authentication before access
- multiple readers at the same time
- one writer at a time
- publish-subscribe notifications after writes
- consistent evidence for the frontend replay
