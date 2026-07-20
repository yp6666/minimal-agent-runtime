const state = {
  sessions: [],
  activeSessionId: null,
  running: false,
  pendingDelete: null,
};

const elements = {
  sessionList: document.querySelector("#session-list"),
  newSession: document.querySelector("#new-session"),
  conversationTitle: document.querySelector("#conversation-title"),
  messages: document.querySelector("#messages"),
  composer: document.querySelector("#composer"),
  input: document.querySelector("#message-input"),
  send: document.querySelector("#send-button"),
  traceList: document.querySelector("#trace-list"),
  stepCount: document.querySelector("#step-count"),
  todoList: document.querySelector("#todo-list"),
  todoCount: document.querySelector("#todo-count"),
  healthDot: document.querySelector("#health-dot"),
  healthLabel: document.querySelector("#health-label"),
  healthDetail: document.querySelector("#health-detail"),
  deleteDialog: document.querySelector("#delete-dialog"),
  deleteDialogDescription: document.querySelector("#delete-dialog-description"),
  cancelDelete: document.querySelector("#cancel-delete"),
  confirmDelete: document.querySelector("#confirm-delete"),
  toast: document.querySelector("#toast"),
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || `HTTP ${response.status}`);
  return body;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderText(value) {
  return escapeHtml(value).replace(
    /(https?:\/\/[^\s<]+)/g,
    '<a href="$1" target="_blank" rel="noopener noreferrer">$1</a>',
  );
}

function showToast(message) {
  elements.toast.textContent = message;
  elements.toast.classList.add("visible");
  window.setTimeout(() => elements.toast.classList.remove("visible"), 3200);
}

function formatDate(value) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function titleFromFirstMessage(message) {
  return Array.from(message.trim()).slice(0, 2).join("") || "新会话";
}

function renderSessions() {
  elements.sessionList.innerHTML = state.sessions
    .map(
      (session) => `
        <div class="session-row ${session.id === state.activeSessionId ? "active" : ""}">
          <button class="session-item ${session.id === state.activeSessionId ? "active" : ""}"
            type="button" data-session-id="${escapeHtml(session.id)}">
            <span class="session-title">${escapeHtml(session.title)}</span>
            <span class="session-date">${formatDate(session.updated_at)}</span>
          </button>
          <button class="delete-session" type="button"
            data-delete-session-id="${escapeHtml(session.id)}"
            data-delete-session-title="${escapeHtml(session.title)}"
            aria-label="删除会话 ${escapeHtml(session.title)}" title="删除会话">×</button>
        </div>`,
    )
    .join("");
}

function visibleMessages(messages) {
  return messages.filter(
    (message) =>
      ["user", "assistant"].includes(message.role) &&
      message.content &&
      (!message.tool_calls || message.tool_calls.length === 0),
  );
}

function scrollMessagesToBottom(behavior = "auto") {
  window.requestAnimationFrame(() => {
    elements.messages.scrollTo({
      top: elements.messages.scrollHeight,
      behavior,
    });
  });
}

function renderMessages(messages, { scrollBehavior = "auto" } = {}) {
  const visible = visibleMessages(messages);
  if (!visible.length) {
    elements.messages.innerHTML = `
      <div class="empty-state">
        <p class="empty-kicker">一条输入，多步完成</p>
        <h3>让模型决定何时动手</h3>
        <p>试试“查北京天气，如果下雨就帮我记一个带伞待办”。</p>
      </div>`;
    return;
  }
  elements.messages.innerHTML = visible
    .map(
      (message) => `
        <article class="message ${message.role}">
          <p class="message-meta">${message.role === "user" ? "YOU" : "MINIAGENT"} · ${formatDate(message.created_at)}</p>
          <div class="message-body">${renderText(message.content)}</div>
        </article>`,
    )
    .join("");
  scrollMessagesToBottom(scrollBehavior);
}

function traceDescription(trace) {
  const payload = trace.payload || {};
  if (trace.event_type === "run_started") return payload.input || "收到用户输入";
  if (trace.event_type === "llm_tool_decision") {
    return (payload.calls || []).map((call) => `${call.name}(${JSON.stringify(call.arguments)})`).join(" · ");
  }
  if (trace.event_type === "tool_finished") {
    const status = payload.result?.ok ? "成功" : payload.result?.error_code || "失败";
    return `${payload.tool_name} · ${status}`;
  }
  if (trace.event_type === "final_answer") return "生成最终回复";
  if (trace.event_type === "llm_error") return payload.error || "模型调用失败";
  if (trace.event_type === "step_limit_reached") return "达到最大循环步数";
  return trace.event_type;
}

function renderTraces(traces) {
  elements.stepCount.textContent = String(traces.length);
  if (!traces.length) {
    elements.traceList.innerHTML = '<li class="trace-empty">运行任务后，这里会显示每一步决策。</li>';
    return;
  }
  elements.traceList.innerHTML = traces
    .map(
      (trace) => `
        <li class="trace-item">
          <span class="trace-kind">STEP ${trace.step} · ${escapeHtml(trace.event_type)}</span>
          <span class="trace-detail">${escapeHtml(traceDescription(trace))}</span>
          <span class="trace-time">${trace.duration_ms == null ? "—" : `${trace.duration_ms} ms`}</span>
        </li>`,
    )
    .join("");
}

function renderTodos(todos) {
  elements.todoCount.textContent = String(todos.length);
  if (!todos.length) {
    elements.todoList.innerHTML = '<li class="todo-empty">还没有待办</li>';
    return;
  }
  elements.todoList.innerHTML = todos
    .map(
      (todo) => `
        <li class="todo-item ${todo.status === "completed" ? "completed" : ""}">
          <span class="todo-check" aria-hidden="true">${todo.status === "completed" ? "✓" : "○"}</span>
          <div>
            <span class="todo-title">${escapeHtml(todo.title)}</span>
            ${todo.due_date ? `<span class="todo-date">${escapeHtml(todo.due_date)}</span>` : ""}
          </div>
        </li>`,
    )
    .join("");
}

async function loadSession(sessionId) {
  state.activeSessionId = sessionId;
  renderSessions();
  const data = await api(`/api/sessions/${encodeURIComponent(sessionId)}`);
  elements.conversationTitle.textContent = data.session.title;
  renderMessages(data.messages);
  renderTraces(data.traces);
  renderTodos(data.todos);
}

async function loadSessions() {
  state.sessions = await api("/api/sessions?user_id=demo-user");
  if (!state.sessions.length) {
    const created = await api("/api/sessions", {
      method: "POST",
      body: JSON.stringify({ user_id: "demo-user", title: "新会话" }),
    });
    state.sessions = [created];
  }
  const candidate = state.sessions.some((item) => item.id === state.activeSessionId)
    ? state.activeSessionId
    : state.sessions[0].id;
  await loadSession(candidate);
}

async function createSession() {
  const created = await api("/api/sessions", {
    method: "POST",
    body: JSON.stringify({ user_id: "demo-user", title: "新会话" }),
  });
  state.sessions.unshift(created);
  await loadSession(created.id);
  elements.input.focus();
}

function openDeleteDialog(sessionId, title) {
  state.pendingDelete = { sessionId, title };
  elements.deleteDialogDescription.textContent =
    `“${title}”中的消息、待办和执行轨迹将被永久删除。`;
  elements.deleteDialog.showModal();
  window.requestAnimationFrame(() => elements.cancelDelete.focus());
}

async function confirmDeleteSession() {
  if (!state.pendingDelete) return;
  const { sessionId, title } = state.pendingDelete;
  elements.confirmDelete.disabled = true;
  try {
    await api(`/api/sessions/${encodeURIComponent(sessionId)}`, { method: "DELETE" });
    state.sessions = state.sessions.filter((session) => session.id !== sessionId);
    if (state.activeSessionId === sessionId) state.activeSessionId = null;
    state.pendingDelete = null;
    elements.deleteDialog.close();
    await loadSessions();
    showToast(`已删除会话“${title}”`);
  } finally {
    elements.confirmDelete.disabled = false;
  }
}

function setRunning(running) {
  state.running = running;
  elements.send.disabled = running;
  elements.input.disabled = running;
  elements.messages.setAttribute("aria-busy", String(running));
  elements.send.querySelector("span:first-child").textContent = running ? "运行中" : "运行";
}

async function sendMessage(message) {
  setRunning(true);
  const current = await api(`/api/sessions/${encodeURIComponent(state.activeSessionId)}`);
  const isFirstUserMessage = !current.messages.some((item) => item.role === "user");
  if (isFirstUserMessage) {
    const title = titleFromFirstMessage(message);
    const session = state.sessions.find((item) => item.id === state.activeSessionId);
    if (session) session.title = title;
    elements.conversationTitle.textContent = title;
    renderSessions();
  }
  renderMessages(
    [
      ...current.messages,
      { role: "user", content: message, created_at: new Date().toISOString(), tool_calls: [] },
      { role: "assistant", content: "● ● ●", created_at: new Date().toISOString(), tool_calls: [] },
    ],
    { scrollBehavior: "smooth" },
  );
  try {
    const data = await api(`/api/sessions/${encodeURIComponent(state.activeSessionId)}/chat`, {
      method: "POST",
      body: JSON.stringify({ message }),
    });
    renderMessages(data.messages, { scrollBehavior: "smooth" });
    renderTraces(data.traces);
    renderTodos(data.todos);
    await loadSessions();
  } catch (error) {
    showToast(error.message);
    await loadSession(state.activeSessionId);
  } finally {
    setRunning(false);
    elements.input.focus();
  }
}

async function checkHealth() {
  try {
    const health = await api("/api/health");
    const missing = health.missing_credentials || [];
    elements.healthDot.classList.add(missing.length ? "error" : "ok");
    elements.healthLabel.textContent = missing.length ? "需要配置" : "运行时就绪";
    elements.healthDetail.textContent = missing.length
      ? `缺少 ${missing.join("、")}`
      : `${health.model} · ${health.tools.length} tools · ${health.weather_endpoint_mode}`;
  } catch (error) {
    elements.healthDot.classList.add("error");
    elements.healthLabel.textContent = "运行时不可用";
    elements.healthDetail.textContent = error.message;
  }
}

elements.sessionList.addEventListener("click", (event) => {
  const deleteButton = event.target.closest("[data-delete-session-id]");
  if (deleteButton && !state.running) {
    openDeleteDialog(
      deleteButton.dataset.deleteSessionId,
      deleteButton.dataset.deleteSessionTitle,
    );
    return;
  }
  const button = event.target.closest("[data-session-id]");
  if (button && !state.running) loadSession(button.dataset.sessionId).catch((error) => showToast(error.message));
});

elements.newSession.addEventListener("click", () => {
  if (!state.running) createSession().catch((error) => showToast(error.message));
});

elements.cancelDelete.addEventListener("click", () => {
  state.pendingDelete = null;
  elements.deleteDialog.close();
});

elements.confirmDelete.addEventListener("click", () => {
  confirmDeleteSession().catch((error) => showToast(error.message));
});

elements.deleteDialog.addEventListener("close", () => {
  if (!elements.confirmDelete.disabled) state.pendingDelete = null;
});

elements.composer.addEventListener("submit", (event) => {
  event.preventDefault();
  const message = elements.input.value.trim();
  if (!message || state.running) return;
  elements.input.value = "";
  sendMessage(message);
});

elements.input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    elements.composer.requestSubmit();
  }
});

Promise.all([checkHealth(), loadSessions()]).catch((error) => showToast(error.message));
