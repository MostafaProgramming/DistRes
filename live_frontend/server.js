const serverEl = {
  status: document.getElementById("server-status"),
  connectedClients: document.getElementById("connected-clients"),
  activeReadersCount: document.getElementById("active-readers-count"),
  activeReaders: document.getElementById("active-readers"),
  activeWriter: document.getElementById("active-writer"),
  writerDetail: document.getElementById("writer-detail"),
  waitingReads: document.getElementById("waiting-reads"),
  waitingWrites: document.getElementById("waiting-writes"),
  waitingWritesCount: document.getElementById("waiting-writes-count"),
  subscriberCount: document.getElementById("subscriber-count"),
  resourceVersion: document.getElementById("resource-version"),
  lastRefresh: document.getElementById("last-refresh"),
  clientTable: document.getElementById("client-table"),
  events: document.getElementById("server-events"),
};

function listText(values) {
  return values && values.length ? values.join(", ") : "None";
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderClients(clients) {
  if (!clients.length) {
    serverEl.clientTable.innerHTML = '<tr><td colspan="5">No connected clients.</td></tr>';
    return;
  }

  serverEl.clientTable.innerHTML = clients.map((client) => `
    <tr>
      <td><strong>${escapeHtml(client.username)}</strong></td>
      <td>${escapeHtml(client.sessionId)}</td>
      <td><span class="state-pill ${stateClass(client.state)}">${escapeHtml(client.state)}</span></td>
      <td>${client.subscribed ? "Yes" : "No"}</td>
      <td>${escapeHtml(client.lastAction)}</td>
    </tr>
  `).join("");
}

function stateClass(state) {
  if (state.includes("writing")) return "state-writing";
  if (state.includes("reading")) return "state-reading";
  if (state.includes("waiting")) return "state-waiting";
  return "state-connected";
}

function renderEvents(events) {
  if (!events.length) {
    serverEl.events.textContent = "Waiting for activity...";
    return;
  }

  serverEl.events.innerHTML = events.map((event) => `
    <div class="server-event">
      <span>${escapeHtml(event.time)}</span>
      <strong>${escapeHtml(event.type)}</strong>
      <p>${escapeHtml(event.message)}</p>
    </div>
  `).join("");
}

async function refreshServerState() {
  try {
    const response = await fetch("/api/server-state", { cache: "no-store" });
    const state = await response.json();

    serverEl.status.textContent = `Monitoring ${state.distresHost}:${state.distresPort}`;
    serverEl.connectedClients.textContent = state.connectedClients;
    serverEl.activeReadersCount.textContent = state.activeReaders.length;
    serverEl.activeReaders.textContent = listText(state.activeReaders);
    serverEl.activeWriter.textContent = state.activeWriter || "None";
    serverEl.writerDetail.textContent = state.activeWriter || "None";
    serverEl.waitingReads.textContent = listText(state.waitingReads);
    serverEl.waitingWrites.textContent = listText(state.waitingWrites);
    serverEl.waitingWritesCount.textContent = state.waitingWrites.length;
    serverEl.subscriberCount.textContent = state.subscriberCount;
    serverEl.resourceVersion.textContent = state.resourceVersion;
    serverEl.lastRefresh.textContent = `Last refresh: ${state.generatedAt}`;

    renderClients(state.clients);
    renderEvents(state.events);
  } catch (error) {
    serverEl.status.textContent = `Dashboard offline: ${error.message}`;
  }
}

refreshServerState();
setInterval(refreshServerState, 1000);
