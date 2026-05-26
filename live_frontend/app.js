let sessionId = "";
let events = null;
let hasSubscribed = false;
let hasReadLock = false;
let hasWriteLock = false;

const el = {
  status: document.getElementById("connection-status"),
  username: document.getElementById("username"),
  password: document.getElementById("password"),
  login: document.getElementById("login"),
  logout: document.getElementById("logout"),
  beginRead: document.getElementById("begin-read"),
  endRead: document.getElementById("end-read"),
  subscribe: document.getElementById("subscribe"),
  beginWrite: document.getElementById("begin-write"),
  saveWrite: document.getElementById("save-write"),
  cancelWrite: document.getElementById("cancel-write"),
  fileEditor: document.getElementById("file-editor"),
  lockStatus: document.getElementById("lock-status"),
  events: document.getElementById("events"),
};

function setConnected(connected, username = "") {
  el.status.textContent = connected ? `Connected as ${username}` : "Not connected";
  el.login.disabled = connected;
  el.logout.disabled = !connected;
  el.subscribe.disabled = !connected;
  setAccessState("idle", connected);
  if (!connected) {
    hasSubscribed = false;
    el.fileEditor.value = "Connect, then read ProductSpecification.txt.";
    el.lockStatus.textContent = "No active read or write lock.";
    el.events.textContent = "Connect, then subscribe to receive committed write events.";
  }
}

function setAccessState(mode, connected = Boolean(sessionId)) {
  hasReadLock = mode === "reading";
  hasWriteLock = mode === "writing";
  el.fileEditor.disabled = !hasWriteLock;
  el.beginRead.disabled = !connected || hasReadLock || hasWriteLock;
  el.endRead.disabled = !connected || !hasReadLock;
  el.beginWrite.disabled = !connected || hasReadLock || hasWriteLock;
  el.saveWrite.disabled = !connected || !hasWriteLock;
  el.cancelWrite.disabled = !connected || !hasWriteLock;

  if (hasReadLock) {
    el.lockStatus.textContent = "Read lock held by this client. Other readers may join; writers must wait.";
  } else if (hasWriteLock) {
    el.lockStatus.textContent = "Write lock held by this client. Edit the file, then save or cancel.";
  } else {
    el.lockStatus.textContent = "No active read or write lock.";
  }
}

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || `HTTP ${response.status}`);
  }
  return data;
}

function addEvent(message) {
  if (message === "EVENT HEARTBEAT" || message === "OK SUBSCRIBED") {
    return;
  }
  if (el.events.textContent === "Connect, then subscribe to receive committed write events." ||
      el.events.textContent === "Subscribed. Waiting for committed write events.") {
    el.events.textContent = "";
  }
  const item = document.createElement("div");
  item.className = "event";
  item.innerHTML = formatEvent(message);
  el.events.prepend(item);
}

function formatEvent(message) {
  const tokens = Object.fromEntries(
    message.split(" ")
      .filter((part) => part.includes("="))
      .map((part) => {
        const [key, ...rest] = part.split("=");
        return [key, rest.join("=")];
      })
  );

  if (!message.startsWith("EVENT UPDATE")) {
    return `<strong>${escapeHtml(message)}</strong>`;
  }

  return `
    <strong>${escapeHtml(tokens.version || "update")} committed</strong>
    <span>Writer: ${escapeHtml(tokens.writer || "unknown")}</span>
    <span>Resource: ${escapeHtml(tokens.resource || "ProductSpecification.txt")}</span>
    <span>Operation: ${escapeHtml(tokens.operation || "write")} at ${escapeHtml(tokens.time || "")}</span>
    <span>Detail: ${escapeHtml(tokens.detail || "file updated")}</span>
  `;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function login() {
  try {
    const data = await postJson("/api/login", {
      username: el.username.value.trim(),
      password: el.password.value,
    });
    sessionId = data.sessionId;
    setConnected(true, data.username);
  } catch (error) {
    el.status.textContent = `Login failed: ${error.message}`;
  }
}

async function subscribe() {
  const data = await postJson("/api/subscribe", { sessionId });
  hasSubscribed = true;
  el.subscribe.disabled = true;
  el.events.textContent = "Subscribed. Waiting for committed write events.";

  // EventSource keeps a live connection open for server-pushed notifications.
  events = new EventSource(`/api/events/${sessionId}`);
  events.onmessage = (event) => addEvent(event.data);
  addEvent(data.response);
}

async function logout() {
  if (events) {
    events.close();
    events = null;
  }
  if (hasReadLock) {
    await postJson("/api/end-read", { sessionId }).catch(() => {});
  }
  if (hasWriteLock) {
    await postJson("/api/cancel-write", { sessionId }).catch(() => {});
  }
  if (sessionId) {
    await postJson("/api/logout", { sessionId }).catch(() => {});
  }
  sessionId = "";
  hasSubscribed = false;
  setConnected(false);
}

async function readFile() {
  el.lockStatus.textContent = "Waiting for the server to grant the read lock. If another client is writing, this reader must wait.";
  const data = await postJson("/api/begin-read", { sessionId });
  el.fileEditor.value = data.content;
  setAccessState("reading");
}

async function stopReading() {
  const data = await postJson("/api/end-read", { sessionId });
  setAccessState("idle");
  el.lockStatus.textContent = `${data.response}. Read lock released.`;
}

async function beginWrite() {
  el.lockStatus.textContent = "Waiting for the server to grant the writer lock. Active readers must stop before this writer can edit.";
  const data = await postJson("/api/begin-write", { sessionId });
  el.fileEditor.value = data.content;
  setAccessState("writing");
}

async function writeFile() {
  const data = await postJson("/api/write", {
    sessionId,
    text: el.fileEditor.value,
  });
  setAccessState("idle");
  el.lockStatus.textContent = `${data.response}. Writer lock released.`;
}

async function cancelWrite() {
  const data = await postJson("/api/cancel-write", { sessionId });
  setAccessState("idle");
  el.lockStatus.textContent = `${data.response}. Writer lock released without saving.`;
}

el.login.addEventListener("click", login);
el.logout.addEventListener("click", logout);
el.subscribe.addEventListener("click", () => subscribe().catch((e) => el.events.textContent = e.message));
el.beginRead.addEventListener("click", () => readFile().catch((e) => el.lockStatus.textContent = e.message));
el.endRead.addEventListener("click", () => stopReading().catch((e) => el.lockStatus.textContent = e.message));
el.beginWrite.addEventListener("click", () => beginWrite().catch((e) => el.lockStatus.textContent = e.message));
el.saveWrite.addEventListener("click", () => writeFile().catch((e) => el.lockStatus.textContent = e.message));
el.cancelWrite.addEventListener("click", () => cancelWrite().catch((e) => el.lockStatus.textContent = e.message));

setConnected(false);
