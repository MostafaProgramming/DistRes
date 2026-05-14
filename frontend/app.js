const state = {
  // distres_run.json is loaded here after launch_frontend.ps1 prepares it.
  data: null,
  index: 0,
  playing: false,
  timer: null,
};

// Store DOM references once so render functions can update the dashboard quickly.
const els = {
  server: document.getElementById("server-label"),
  total: document.getElementById("event-total"),
  phase: document.getElementById("phase-label"),
  play: document.getElementById("play"),
  prev: document.getElementById("prev"),
  next: document.getElementById("next"),
  reset: document.getElementById("reset"),
  scrubber: document.getElementById("scrubber"),
  counter: document.getElementById("counter"),
  clock: document.getElementById("clock"),
  activeClient: document.getElementById("active-client"),
  spotlightTitle: document.getElementById("spotlight-title"),
  spotlightBody: document.getElementById("spotlight-body"),
  summary: document.getElementById("summary"),
  notifications: document.getElementById("notifications"),
  clients: document.getElementById("client-grid"),
  timeline: document.getElementById("timeline-list"),
  file: document.getElementById("file-content"),
  refreshFile: document.getElementById("refresh-file"),
};

function event() {
  // Return the currently selected replay event, or null before data loads.
  return state.data?.events?.[state.index] ?? null;
}

function phaseLabel(category) {
  // Convert event categories from generate_frontend_data.py into UI labels.
  if (category === "connect") return "Client Connection";
  if (category === "subscribe") return "Pub-Sub Subscription";
  if (category === "read") return "Shared Read Access";
  if (category === "write") return "Exclusive Write Access";
  if (category === "notify") return "Update Notification";
  return "Distributed Demo";
}

function setIndex(index) {
  // Clamp timeline navigation so Previous/Next cannot move outside the dataset.
  const total = state.data?.events?.length ?? 0;
  state.index = Math.min(Math.max(index, 0), Math.max(total - 1, 0));
  render();
}

function stop() {
  // Stop automatic playback but leave the selected event visible.
  state.playing = false;
  clearInterval(state.timer);
  state.timer = null;
  render();
}

function togglePlay() {
  if (!state.data) return;
  if (state.playing) {
    stop();
    return;
  }
  state.playing = true;
  // Advance through events at a fixed interval for a simple replay mode.
  state.timer = setInterval(() => {
    if (state.index >= state.data.events.length - 1) {
      stop();
      return;
    }
    setIndex(state.index + 1);
  }, 900);
  render();
}

function renderSummary() {
  // Summary cards connect frontend evidence to the implementation report.
  const summary = state.data.summary;
  const cards = [
    ["Client Nodes", state.data.metadata.clientCount, "Independent distributed clients"],
    ["Reads", summary.reads, "Server-hosted file queries"],
    ["Writes", summary.writes, "Exclusive server-side updates"],
    ["Notifications", summary.notifications, "Pub-sub events received"],
    ["Resource Updates", summary.resourceUpdates, "Appended shared-file writes"],
  ];
  els.summary.innerHTML = cards.map(([label, value, caption]) => `
    <article class="summary-card">
      <span>${label}</span>
      <strong>${value}</strong>
      <p>${caption}</p>
    </article>
  `).join("");
}

function renderClients(current) {
  // Each card shows what one distributed client did during the demo run.
  els.clients.innerHTML = state.data.clients.map((client) => {
    const clientEvents = state.data.events.filter((item) => item.client === client.username);
    const reads = clientEvents.filter((item) => item.category === "read").length;
    const writes = clientEvents.filter((item) => item.category === "write").length;
    const notifications = clientEvents.filter((item) => item.category === "notify").length;
    const active = current?.client === client.username;
    return `
      <article class="client-card ${active ? "active" : ""}">
        <span>Client Node</span>
        <strong>${client.username}</strong>
        <p>Reads: ${reads} | Writes: ${writes} | Notifications: ${notifications}</p>
      </article>
    `;
  }).join("");
}

function renderTimeline(current) {
  // The timeline is the main replay evidence: one card per generated event.
  els.timeline.innerHTML = state.data.events.map((item, index) => `
    <article class="event-card ${item.category} ${index === state.index ? "current" : ""}">
      <span>#${item.id} | ${phaseLabel(item.category)} | ${(item.elapsedMs / 1000).toFixed(2)}s</span>
      <strong>${item.client}</strong>
      <p>${item.detail}</p>
    </article>
  `).join("");

  const selected = els.timeline.querySelector(".current");
  selected?.scrollIntoView({ block: "nearest" });
}

function renderNotifications() {
  // Show only notification events that have occurred up to the current replay point.
  const visible = state.data.events
    .slice(0, state.index + 1)
    .filter((item) => item.category === "notify")
    .slice(-8)
    .reverse();

  els.notifications.innerHTML = visible.length ? visible.map((item) => `
    <article class="event-card notify">
      <span>${item.client}</span>
      <strong>EVENT UPDATE received</strong>
      <p>${item.detail}</p>
    </article>
  `).join("") : `<article class="event-card"><p>No notifications replayed yet.</p></article>`;
}

function render() {
  if (!state.data) return;
  const current = event();
  const total = state.data.events.length;

  els.server.textContent = state.data.metadata.server;
  els.total.textContent = total;
  els.phase.textContent = current ? phaseLabel(current.category) : "Ready";
  els.play.textContent = state.playing ? "Pause" : "Play";
  els.scrubber.max = Math.max(total - 1, 0);
  els.scrubber.value = state.index;
  els.counter.textContent = `Event ${state.index + 1} / ${total}`;
  els.clock.textContent = `t = ${((current?.elapsedMs ?? 0) / 1000).toFixed(2)}s`;
  els.activeClient.textContent = current ? `${current.client} | ${phaseLabel(current.category)}` : "No active event";
  els.spotlightTitle.textContent = current ? phaseLabel(current.category) : "Ready";
  els.spotlightBody.textContent = current?.detail ?? "No event selected.";

  renderSummary();
  renderClients(current);
  renderTimeline(current);
  renderNotifications();
}

async function refreshFile() {
  try {
    // The local API returns the latest server-hosted ProductSpecification.txt.
    const response = await fetch(`/api/shared-file?ts=${Date.now()}`, { cache: "no-store" });
    const data = await response.json();
    els.file.textContent = data.content;
  } catch {
    els.file.textContent = state.data?.resource?.content ?? "Shared file unavailable.";
  }
}

async function load() {
  // Replay data is generated from logs by generate_frontend_data.py.
  const response = await fetch(`data/distres_run.json?ts=${Date.now()}`, { cache: "no-store" });
  state.data = await response.json();
  render();
  refreshFile();
}

els.play.addEventListener("click", togglePlay);
els.prev.addEventListener("click", () => { stop(); setIndex(state.index - 1); });
els.next.addEventListener("click", () => { stop(); setIndex(state.index + 1); });
els.reset.addEventListener("click", () => { stop(); setIndex(0); });
els.scrubber.addEventListener("input", (e) => { stop(); setIndex(Number(e.target.value)); });
els.refreshFile.addEventListener("click", refreshFile);

load().catch((error) => {
  els.spotlightTitle.textContent = "Replay data missing";
  els.spotlightBody.textContent = `Run launch_frontend.ps1 or generate_frontend_data.py. ${error.message}`;
});
