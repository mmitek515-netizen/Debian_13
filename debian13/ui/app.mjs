export const AGENT_PROFILES = Object.freeze([
  { id: 'aria', name: 'Aria', role: 'Modele i transport AI' },
  { id: 'astyria', name: 'Astyria', role: 'Interfejs i ergonomia' },
  { id: 'aurelius', name: 'Aurelius', role: 'Bezpieczeństwo i testy' },
  { id: 'alex', name: 'Alex', role: 'Architektura i integracja' },
]);

const SESSION_KEY = 'debian13-chat-session';
const HISTORY_KEY = 'debian13-chat-history';
const SESSION_ID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

export class ApiError extends Error {
  constructor(message, status = 0) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

function apiErrorMessage(payload, status) {
  if (status === 401) return 'Brak autoryzacji API (401). Skonfiguruj DEBIAN13_API_TOKEN wyłącznie po stronie serwera proxy.';
  if (status === 403) return 'API odrzuciło uprawnienia (403). Sprawdź dostęp operatora.';
  if (status === 404) return 'Backend nie udostępnia tego endpointu (404).';
  return typeof payload?.error === 'string'
    ? payload.error
    : `Żądanie nie powiodło się (HTTP ${status}).`;
}

export function createApiClient({ fetchImpl = globalThis.fetch, baseUrl = '' } = {}) {
  async function fetchRequest(path, options) {
    try {
      return await fetchImpl(`${baseUrl}/api/v1/${path}`, options);
    } catch (error) {
      if (error?.name === 'AbortError') throw error;
      throw new ApiError('Runtime nieosiągalny — sprawdź połączenie z API.');
    }
  }

  async function request(path, options) {
    const response = await fetchRequest(path, options);
    let payload;
    try {
      payload = await response.json();
    } catch {
      throw new ApiError('Runtime zwrócił nieprawidłową odpowiedź.', response.status);
    }
    if (!response.ok) {
      throw new ApiError(apiErrorMessage(payload, response.status), response.status);
    }
    return payload;
  }

  function post(path, body) {
    return request(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  }

  async function chatStream(message, agent, sessionId, onEvent, signal) {
    const body = { message, agent };
    if (sessionId) body.session_id = sessionId;
    const response = await fetchRequest('chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    });

    if (!response.ok) {
      let payload;
      try {
        payload = await response.json();
      } catch {
        throw new ApiError('Runtime zwrócił nieprawidłową odpowiedź.', response.status);
      }
      throw new ApiError(apiErrorMessage(payload, response.status), response.status);
    }
    if (!response.headers.get('content-type')?.toLowerCase().includes('text/event-stream') || !response.body) {
      throw new ApiError('Runtime nie zwrócił strumienia odpowiedzi.', response.status);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    const dispatch = (block) => {
      let event = 'message';
      const data = [];
      for (const line of block.split(/\r?\n/)) {
        if (line.startsWith('event:')) event = line.slice(6).trim();
        if (line.startsWith('data:')) data.push(line.slice(5).trimStart());
      }
      if (!data.length) return;
      let payload;
      try {
        payload = JSON.parse(data.join('\n'));
      } catch {
        throw new ApiError('Runtime wysłał nieprawidłowe zdarzenie czatu.');
      }
      onEvent({ event, payload });
    };

    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      let separator;
      while ((separator = /\r?\n\r?\n/.exec(buffer))) {
        dispatch(buffer.slice(0, separator.index));
        buffer = buffer.slice(separator.index + separator[0].length);
      }
      if (done) break;
    }
    if (buffer.trim()) dispatch(buffer);
  }

  return Object.freeze({
    getStatus: () => request('status'),
    getAgents: () => request('agents'),
    getIntegrations: () => request('integrations'),
    getTasks: () => request('tasks'),
    getTask: (taskId) => request(`tasks/${encodeURIComponent(taskId)}`),
    getEvents: () => request('events'),
    getMessages: (sessionId) => request(`sessions/${encodeURIComponent(sessionId)}/messages`),
    cancelTask: (taskId) => request(`tasks/${encodeURIComponent(taskId)}/cancel`, { method: 'POST' }),
    chatStream,
    terminal: (command) => post('terminal', { command }),
  });
}

export function getInitialAgentStatuses() {
  return AGENT_PROFILES.map((agent) => ({
    ...agent,
    status: 'unknown',
    worker: 'unknown',
  }));
}

function agentStatusLabel(agent) {
  const profile = agent.status === 'profile_configured'
    ? 'Profil skonfigurowany'
    : 'Profil: stan nieznany';
  const worker = agent.worker === 'not_running'
    ? 'Worker nieuruchomiony'
    : agent.worker === 'running'
      ? 'Worker uruchomiony'
      : 'Worker: stan nieznany';
  return { profile, worker };
}

function renderAgentProfiles(list, agents = getInitialAgentStatuses()) {
  if (!list) return;
  const fragment = document.createDocumentFragment();
  for (const agent of agents) {
    const item = document.createElement('li');
    item.className = 'agent-card';
    item.dataset.agent = agent.id;

    const nameRow = document.createElement('div');
    nameRow.className = 'agent-name-row';
    const dot = document.createElement('span');
    dot.className = 'agent-state-dot';
    dot.setAttribute('aria-hidden', 'true');
    const name = document.createElement('span');
    name.textContent = agent.name;
    nameRow.append(dot, name);

    const role = document.createElement('p');
    role.className = 'agent-role';
    role.textContent = agent.role;
    const labels = agentStatusLabel(agent);
    const profile = document.createElement('p');
    profile.className = 'agent-state';
    profile.textContent = labels.profile;
    const worker = document.createElement('p');
    worker.className = 'worker-state';
    worker.textContent = labels.worker;

    item.append(nameRow, role, profile, worker);
    fragment.append(item);
  }
  list.replaceChildren(fragment);
}

function setText(id, text) {
  const element = document.getElementById(id);
  if (element) element.textContent = text;
}

function connectionState(state, label) {
  const element = document.getElementById('connection-status');
  if (!element) return;
  element.dataset.state = state;
  const text = element.querySelector('span:last-child');
  if (text) text.textContent = label;
  setText('sidebar-runtime-label', label);
}

function modelStatusLabel(model) {
  const statusLabels = {
    not_configured: 'Brak skonfigurowanego modelu',
    unavailable: 'Ollama niedostępna',
    model_missing: 'Model niedostępny',
    model_available: 'Model dostępny lokalnie',
  };
  const label = statusLabels[model?.status] ?? 'Stan modelu nieznany';
  const inference = model?.inference === 'verified'
    ? 'inferencja zweryfikowana'
    : 'inferencja niezweryfikowana';
  return `${label} · ${inference}`;
}

function renderRuntimeStatus(status) {
  const application = status.application?.status === 'running'
    ? `${status.application.product ?? 'Aplikacja'} działa`
    : 'Aplikacja niedostępna';
  const osRuntime = status.operating_system?.runtime;
  const distribution = osRuntime?.distribution ?? 'dystrybucja nieznana';
  const boot = osRuntime?.debian_13_boot_verified === true
    ? 'boot Debian 13 potwierdzony'
    : 'boot Debian 13 niepotwierdzony';
  setText('application-status', application);
  setText('os-status', `${distribution} · ${boot}`);
  setText('model-status', modelStatusLabel(status.model));
  setText('task-storage-status', status.task_state ?? 'Stan pamięci zadań nieznany');
  setText('status-error', '');
  connectionState('connected', 'API dostępne');
}

function appendTranscript(kind, title, content = '') {
  const transcript = document.getElementById('chat-transcript');
  if (!transcript) return null;
  transcript.querySelector('.empty-state')?.remove();
  const entry = document.createElement('article');
  entry.className = `transcript-entry transcript-${kind}`;
  const heading = document.createElement('p');
  heading.className = 'transcript-heading';
  heading.textContent = title;
  const text = document.createElement('p');
  text.className = 'transcript-text';
  text.textContent = content;
  entry.append(heading, text);
  transcript.append(entry);
  transcript.scrollTop = transcript.scrollHeight;
  return { entry, heading, text };
}

function renderTranscriptMessages(messages) {
  const transcript = document.getElementById('chat-transcript');
  if (!transcript) return;
  transcript.replaceChildren();
  for (const message of messages) {
    if (!['user', 'assistant'].includes(message.role) || typeof message.content !== 'string') continue;
    const isUser = message.role === 'user';
    const name = AGENT_PROFILES.find((agent) => agent.id === message.agent)?.name ?? 'Agent';
    appendTranscript(
      isUser ? 'user' : 'assistant',
      isUser ? `Ty · ${name}` : `${name} · ${message.source ?? 'API'}`,
      message.content,
    );
  }
  if (!transcript.children.length) {
    const empty = document.createElement('p');
    empty.className = 'empty-state';
    empty.textContent = 'Ta sesja nie ma jeszcze zapisanych wiadomości.';
    transcript.append(empty);
  }
}

function renderTerminal(command, output, isError = false) {
  const terminal = document.getElementById('terminal-output');
  if (!terminal) return;
  terminal.querySelector('.terminal-hint')?.remove();
  const entry = document.createElement('p');
  const prompt = document.createElement('span');
  prompt.className = 'prompt-mark';
  prompt.setAttribute('aria-hidden', 'true');
  prompt.textContent = isError ? '!' : '$';
  const commandText = document.createElement('span');
  commandText.textContent = ` ${command}`;
  entry.append(prompt, commandText);
  const result = document.createElement('pre');
  result.className = isError ? 'terminal-error' : 'terminal-result';
  result.textContent = output;
  terminal.append(entry, result);
  terminal.scrollTop = terminal.scrollHeight;
}

function renderTasks(tasks) {
  const list = document.getElementById('task-list');
  if (!list) return;
  const fragment = document.createDocumentFragment();
  for (const task of tasks) {
    const item = document.createElement('li');
    item.className = 'task-item';
    item.dataset.taskId = task.id;
    const detail = document.createElement('span');
    detail.textContent = `${task.kind} · ${task.agent} · ${task.id}`;
    const status = document.createElement('span');
    status.className = `task-state task-${task.status}`;
    status.textContent = task.status;
    const actions = document.createElement('span');
    actions.className = 'task-actions';
    if (typeof task.id === 'string' && SESSION_ID_PATTERN.test(task.id)) {
      const reconnect = document.createElement('button');
      reconnect.type = 'button';
      reconnect.className = 'task-action';
      reconnect.textContent = 'Pobierz status';
      reconnect.setAttribute('aria-label', `Pobierz status zadania ${task.id}`);
      reconnect.addEventListener('click', () => void refreshTaskStatus(task.id, reconnect));
      actions.append(reconnect);
      if (['queued', 'running'].includes(task.status)) {
        const cancel = document.createElement('button');
        cancel.type = 'button';
        cancel.className = 'task-action task-cancel';
        cancel.textContent = 'Anuluj';
        cancel.setAttribute('aria-label', `Anuluj zadanie ${task.id}`);
        cancel.addEventListener('click', () => void cancelWorkTask(task.id, cancel));
        actions.append(cancel);
      }
    }
    item.append(detail, status, actions);
    fragment.append(item);
  }
  if (!tasks.length) {
    const empty = document.createElement('li');
    empty.className = 'empty-state';
    empty.textContent = 'Brak zadań w bieżącym procesie.';
    fragment.append(empty);
  }
  list.replaceChildren(fragment);
  setText('tasks-count', `${tasks.length} zadań · pamięć procesu`);
  setText('tasks-error', '');
}

function renderEvents(events) {
  const list = document.getElementById('event-list');
  if (!list) return;
  const fragment = document.createDocumentFragment();
  for (const event of events) {
    if (
      typeof event?.type !== 'string'
      || typeof event.agent !== 'string'
      || typeof event.task_id !== 'string'
    ) continue;
    const item = document.createElement('li');
    item.className = 'event-item';
    const detail = document.createElement('span');
    const agent = AGENT_PROFILES.find((profile) => profile.id === event.agent)?.name ?? event.agent;
    detail.textContent = `${event.type} · ${agent}`;
    const metadata = document.createElement('span');
    metadata.className = 'event-metadata';
    const time = new Date(event.at);
    const timestamp = Number.isNaN(time.getTime()) ? 'czas nieznany' : time.toLocaleString('pl-PL');
    metadata.textContent = `${timestamp} · ${event.task_id}`;
    item.append(detail, metadata);
    fragment.append(item);
  }
  if (!fragment.childNodes.length) {
    const empty = document.createElement('li');
    empty.className = 'empty-state';
    empty.textContent = events.length
      ? 'Brak zdarzeń o rozpoznanym formacie.'
      : 'API nie zarejestrowało jeszcze zdarzeń.';
    fragment.append(empty);
  }
  list.replaceChildren(fragment);
  setText('events-count', `${events.length} zdarzeń · pamięć procesu`);
  setText('events-error', '');
}

function readHistory() {
  try {
    const history = JSON.parse(localStorage.getItem(HISTORY_KEY) ?? '[]');
    return Array.isArray(history)
      ? history.filter((item) => item && SESSION_ID_PATTERN.test(item.id) && typeof item.title === 'string').slice(0, 20)
      : [];
  } catch {
    return [];
  }
}

function writeHistory(history) {
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(history.slice(0, 20)));
  } catch {
    setText('chat-feedback', 'Indeks historii nie może zostać zapisany w przeglądarce.');
  }
}

function renderHistory(activeId = '') {
  const list = document.getElementById('chat-history');
  if (!list) return;
  const history = readHistory();
  list.replaceChildren();
  if (!history.length) {
    const empty = document.createElement('li');
    empty.className = 'history-empty';
    empty.textContent = 'Brak zapisanych rozmów.';
    list.append(empty);
    return;
  }
  for (const item of history) {
    const row = document.createElement('li');
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'history-button';
    button.textContent = item.title;
    button.dataset.sessionId = item.id;
    if (item.id === activeId) button.setAttribute('aria-current', 'true');
    button.addEventListener('click', () => void loadHistory(item.id));
    row.append(button);
    list.append(row);
  }
}

const api = createApiClient();
let activeSessionId = '';
let activeChatController = null;
let activeChatTaskId = '';
let activeChatCancelMessage = '';

async function loadStatus() {
  connectionState('loading', 'Ładowanie statusu…');
  setText('status-error', '');
  for (const id of ['application-status', 'os-status', 'model-status', 'task-storage-status']) {
    setText(id, 'Ładowanie…');
  }
  try {
    renderRuntimeStatus(await api.getStatus());
  } catch (error) {
    connectionState('error', error.status === 401 ? 'Wymagana autoryzacja' : 'Runtime niedostępny');
    for (const id of ['application-status', 'os-status', 'model-status', 'task-storage-status']) {
      setText(id, 'Niedostępny');
    }
    setText('status-error', error.message);
  }
}

async function loadAgents() {
  setText('agent-count', 'Ładowanie profili…');
  setText('agent-error', '');
  renderAgentProfiles(document.getElementById('agent-list'));
  try {
    const payload = await api.getAgents();
    if (!Array.isArray(payload.agents)) throw new ApiError('Nieprawidłowy format listy profili.');
    const agents = payload.agents;
    renderAgentProfiles(document.getElementById('agent-list'), agents);
    const workers = agents.filter(({ worker }) => worker === 'running').length;
    setText('agent-count', `${agents.length} profili · ${workers} workerów uruchomionych`);
  } catch (error) {
    setText('agent-count', 'Profile niedostępne');
    setText('agent-error', error.message);
    renderAgentProfiles(document.getElementById('agent-list'));
  }
}

async function loadIntegrations() {
  const list = document.getElementById('integration-list');
  if (!list) return;
  list.replaceChildren();
  try {
    const response = await api.getIntegrations();
    if (!Array.isArray(response.integrations)) throw new ApiError('Nieprawidłowa odpowiedź integracji.');
    const issueUrls = {
      mcp: 'https://github.com/mmitek515-netizen/Debian_13/issues/4',
      gpt_actions: 'https://github.com/mmitek515-netizen/Debian_13/issues/5',
      codex: 'https://github.com/mmitek515-netizen/Debian_13/issues/3',
    };
    for (const item of response.integrations) {
      const entry = document.createElement('li');
      entry.className = 'agent-card';
      const label = document.createElement('strong');
      label.textContent = item.name;
      const status = document.createElement('p');
      status.className = 'agent-state';
      status.textContent = item.connected === true
        ? 'Połączenie potwierdzone'
        : 'Niepołączono · ' + item.status;
      const description = document.createElement('p');
      description.className = 'agent-role';
      description.textContent = item.description;
      entry.append(label, status, description);
      if (issueUrls[item.id]) {
        const issue = document.createElement('a');
        issue.href = issueUrls[item.id];
        issue.target = '_blank';
        issue.rel = 'noopener noreferrer';
        issue.textContent = 'Zgłoszenie GitHub';
        entry.append(issue);
      }
      list.append(entry);
    }
    setText('integration-error', '');
  } catch (error) {
    setText('integration-error', error.message);
  }
}

async function loadTasks() {
  setText('tasks-count', 'Ładowanie…');
  setText('tasks-error', '');
  try {
    const payload = await api.getTasks();
    if (!Array.isArray(payload.tasks)) throw new ApiError('Nieprawidłowy format listy zadań.');
    renderTasks(payload.tasks);
    return null;
  } catch (error) {
    setText('tasks-count', 'Zadania niedostępne');
    setText('tasks-error', error.message);
    const list = document.getElementById('task-list');
    if (list) list.replaceChildren();
    return error;
  }
}

async function loadEvents() {
  setText('events-count', 'Pobieranie zdarzeń…');
  setText('events-error', '');
  const list = document.getElementById('event-list');
  if (list) {
    const loading = document.createElement('li');
    loading.className = 'empty-state';
    loading.textContent = 'Pobieranie zdarzeń z API…';
    list.replaceChildren(loading);
  }
  try {
    const payload = await api.getEvents();
    if (!Array.isArray(payload.events)) throw new ApiError('Nieprawidłowy format dziennika zdarzeń.');
    renderEvents(payload.events);
    return null;
  } catch (error) {
    setText('events-count', 'Zdarzenia niedostępne');
    setText('events-error', error.message);
    if (list) list.replaceChildren();
    return error;
  }
}

async function refreshWork() {
  const button = document.getElementById('refresh-tasks');
  if (button?.disabled) return;
  if (button) {
    button.disabled = true;
    button.textContent = 'Łączenie…';
  }
  setText('work-connection-state', 'Ponowne łączenie z API…');
  const [tasksError, eventsError] = await Promise.all([loadTasks(), loadEvents()]);
  const error = tasksError ?? eventsError;
  setText('work-connection-state', error
    ? error.status === 401
      ? 'Brak autoryzacji — skonfiguruj DEBIAN13_API_TOKEN po stronie serwera proxy.'
      : error.status === 403
        ? 'Dostęp do Work został odrzucony przez API.'
        : error.status === 404
          ? 'Ten backend nie udostępnia części funkcji Work.'
          : 'Połączenie z Work niedostępne. Użyj „Ponów połączenie”.'
    : 'Połączono z API. Zadania i zdarzenia odświeżone.');
  if (button) {
    button.textContent = error ? 'Ponów połączenie' : 'Odśwież';
    button.disabled = false;
  }
  return !error;
}

async function refreshTaskStatus(taskId, button) {
  button.disabled = true;
  try {
    const payload = await api.getTask(taskId);
    if (!payload.task || payload.task.id !== taskId || typeof payload.task.status !== 'string') {
      throw new ApiError('API zwróciło nieprawidłowy status zadania.');
    }
    const item = button.closest('[data-task-id]');
    const status = item?.querySelector('.task-state');
    if (status) {
      status.textContent = payload.task.status;
      status.className = `task-state task-${payload.task.status}`;
    }
    setText('work-connection-state', `Status zadania pobrany z API: ${payload.task.status}.`);
    setText('tasks-error', '');
  } catch (error) {
    setText('tasks-error', error.message);
    setText('work-connection-state', error.status === 404
      ? 'Szczegółowy status zadania nie jest dostępny w tym backendzie.'
      : error.message);
  } finally {
    button.disabled = false;
  }
}

async function cancelWorkTask(taskId, button) {
  button.disabled = true;
  setText('work-connection-state', 'Wysyłanie żądania anulowania do API…');
  try {
    const payload = await api.cancelTask(taskId);
    if (!payload.task || payload.task.id !== taskId) {
      throw new ApiError('API nie potwierdziło zadania do anulowania.');
    }
    await refreshWork();
    setText('work-connection-state', `API przyjęło żądanie anulowania: ${payload.task.status}.`);
  } catch (error) {
    setText('tasks-error', error.message);
    setText('work-connection-state', error.status === 404
      ? 'Ten backend nie obsługuje anulowania zadań.'
      : error.message);
    button.disabled = false;
  }
}

async function refreshDashboard() {
  await Promise.all([loadStatus(), loadAgents(), loadIntegrations(), loadTasks()]);
}

async function loadHistory(sessionId) {
  if (!SESSION_ID_PATTERN.test(sessionId)) return;
  setText('chat-feedback', 'Pobieranie historii rozmowy…');
  try {
    const payload = await api.getMessages(sessionId);
    if (!Array.isArray(payload.messages)) throw new ApiError('Nieprawidłowy format historii rozmowy.');
    activeSessionId = sessionId;
    try {
      sessionStorage.setItem(SESSION_KEY, sessionId);
    } catch {
      setText('chat-feedback', 'Historia dostępna do końca tej karty przeglądarki.');
    }
    renderTranscriptMessages(payload.messages);
    renderHistory(activeSessionId);
    showView('chat');
    setText('chat-feedback', 'Historia pobrana z pamięci API.');
  } catch (error) {
    const history = readHistory().filter((item) => item.id !== sessionId);
    writeHistory(history);
    renderHistory(activeSessionId);
    setText('chat-feedback', error.status === 404
      ? 'Ta sesja wygasła lub backend został uruchomiony ponownie.'
      : error.message);
  }
}

function recordHistory(sessionId, title) {
  const history = readHistory().filter((item) => item.id !== sessionId);
  history.unshift({ id: sessionId, title: title.slice(0, 64) || 'Nowa rozmowa' });
  writeHistory(history);
  renderHistory(sessionId);
  try {
    sessionStorage.setItem(SESSION_KEY, sessionId);
  } catch {
    setText('chat-feedback', 'Sesja działa, ale nie może zostać zapisana w karcie przeglądarki.');
  }
}

function showView(view) {
  const ids = { chat: 'chat-view', work: 'work-view', terminal: 'terminal-view', settings: 'settings-view' };
  for (const [name, id] of Object.entries(ids)) {
    const section = document.getElementById(id);
    if (section) section.hidden = name !== view;
  }
  for (const button of document.querySelectorAll('[data-view]')) {
    const active = button.dataset.view === view;
    button.classList.toggle('is-active', active);
    if (button.classList.contains('nav-button')) {
      if (active) button.setAttribute('aria-current', 'page');
      else button.removeAttribute('aria-current');
    } else {
      button.setAttribute('aria-pressed', String(active));
    }
  }
  const titles = { chat: 'W czym mogę pomóc?', work: 'Work', terminal: 'Terminal', settings: 'Status systemu' };
  setText('page-title', titles[view] ?? titles.chat);
}

function setMobileSidebar(open) {
  const sidebar = document.getElementById('sidebar');
  const menu = document.getElementById('mobile-menu');
  const backdrop = document.getElementById('sidebar-backdrop');
  if (!sidebar || !menu || !backdrop) return;
  const isMobile = window.matchMedia('(max-width: 760px)').matches;
  sidebar.classList.toggle('is-open', isMobile && open);
  sidebar.inert = isMobile && !open;
  sidebar.setAttribute('aria-hidden', String(isMobile && !open));
  menu.setAttribute('aria-expanded', String(isMobile && open));
  menu.setAttribute('aria-label', isMobile && open ? 'Zamknij panel boczny' : 'Otwórz panel boczny');
  backdrop.hidden = !(isMobile && open);
  document.body.classList.toggle('sidebar-open', isMobile && open);
}

function setCollapsedSidebar(collapsed) {
  const layout = document.getElementById('app-layout');
  const button = document.getElementById('sidebar-collapse');
  if (!layout || !button) return;
  layout.dataset.collapsed = String(collapsed);
  button.setAttribute('aria-expanded', String(!collapsed));
  button.setAttribute('aria-label', collapsed ? 'Rozwiń panel boczny' : 'Zwiń panel boczny');
  button.title = collapsed ? 'Rozwiń panel boczny' : 'Zwiń panel boczny';
}

function bindNavigation() {
  const menu = document.getElementById('mobile-menu');
  const backdrop = document.getElementById('sidebar-backdrop');
  const collapse = document.getElementById('sidebar-collapse');
  const sidebar = document.getElementById('sidebar');
  const media = window.matchMedia('(max-width: 760px)');
  menu?.addEventListener('click', () => setMobileSidebar(!sidebar?.classList.contains('is-open')));
  backdrop?.addEventListener('click', () => setMobileSidebar(false));
  collapse?.addEventListener('click', () => {
    const collapsed = document.getElementById('app-layout')?.dataset.collapsed === 'true';
    setCollapsedSidebar(!collapsed);
    try {
      localStorage.setItem('debian13-sidebar-collapsed', String(!collapsed));
    } catch {
      // The panel remains usable when browser storage is disabled.
    }
  });
  document.querySelectorAll('[data-view]').forEach((button) => {
    button.addEventListener('click', () => {
      showView(button.dataset.view);
      if (button.dataset.view === 'work') void refreshWork();
      setMobileSidebar(false);
    });
  });
  document.getElementById('new-chat')?.addEventListener('click', () => {
    activeSessionId = '';
    try {
      sessionStorage.removeItem(SESSION_KEY);
    } catch {
      // Starting a chat does not depend on session storage.
    }
    renderHistory();
    renderTranscriptMessages([]);
    showView('chat');
    setText('chat-feedback', 'Nowa sesja zostanie utworzona przez API po wysłaniu wiadomości.');
    document.getElementById('chat-message')?.focus();
    setMobileSidebar(false);
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && sidebar?.classList.contains('is-open')) {
      setMobileSidebar(false);
      menu?.focus();
    }
  });
  media.addEventListener('change', () => setMobileSidebar(false));
  try {
    setCollapsedSidebar(localStorage.getItem('debian13-sidebar-collapsed') === 'true');
  } catch {
    setCollapsedSidebar(false);
  }
  setMobileSidebar(false);
}

function bindChatForm() {
  const form = document.getElementById('chat-form');
  if (!form) return;
  const message = document.getElementById('chat-message');
  message?.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      form.requestSubmit();
    }
  });
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const agent = document.getElementById('chat-agent');
    const submit = document.getElementById('chat-submit');
    const stop = document.getElementById('chat-stop');
    const feedback = document.getElementById('chat-feedback');
    const text = message?.value.trim();
    if (!text || !agent || !feedback || activeChatController) return;

    const controller = new AbortController();
    activeChatController = controller;
    activeChatTaskId = '';
    activeChatCancelMessage = '';
    const agentName = AGENT_PROFILES.find((profile) => profile.id === agent.value)?.name ?? agent.value;
    const userMessage = text;
    appendTranscript('user', `Ty · ${agentName}`, userMessage);
    const responseBubble = appendTranscript('assistant', `${agentName} · łączenie`);
    submit.hidden = true;
    stop.hidden = false;
    feedback.textContent = 'Łączenie ze strumieniem API…';
    let responseText = '';
    let receivedDone = false;
    let receivedCancelled = false;
    let responseSource = '';
    let responseAgent = agentName;
    let responseSessionId = '';

    try {
      await api.chatStream(userMessage, agent.value, activeSessionId, ({ event: streamEvent, payload }) => {
        if (streamEvent === 'meta' && typeof payload.session_id === 'string') {
          responseSessionId = payload.session_id;
          if (typeof payload.task_id === 'string' && SESSION_ID_PATTERN.test(payload.task_id)) {
            activeChatTaskId = payload.task_id;
          }
        } else if (streamEvent === 'delta' && typeof payload.text === 'string') {
          responseText += payload.text;
          if (responseBubble) responseBubble.text.textContent = responseText;
          const transcript = document.getElementById('chat-transcript');
          if (transcript) transcript.scrollTop = transcript.scrollHeight;
        } else if (streamEvent === 'done') {
          receivedDone = true;
          responseSessionId = payload.session_id ?? responseSessionId;
          responseSource = payload.source ?? '';
          responseAgent = AGENT_PROFILES.find((profile) => profile.id === payload.agent)?.name ?? responseAgent;
        } else if (streamEvent === 'cancelled') {
          receivedCancelled = true;
          responseSessionId = payload.session_id ?? responseSessionId;
          if (responseBubble) {
            responseBubble.heading.textContent = `${agentName} · anulowano przez API`;
            if (!responseText) responseBubble.text.textContent = 'API potwierdziło przerwanie zadania.';
          }
        } else if (streamEvent === 'error') {
          throw new ApiError(typeof payload.error === 'string' ? payload.error : 'Strumień czatu zakończył się błędem.');
        }
      }, controller.signal);
      if (receivedCancelled) {
        if (responseSessionId && SESSION_ID_PATTERN.test(responseSessionId)) {
          activeSessionId = responseSessionId;
          recordHistory(responseSessionId, userMessage);
        }
        feedback.textContent = 'API potwierdziło anulowanie zadania.';
        return;
      }
      if (!receivedDone) throw new ApiError('Strumień zakończył się przed potwierdzeniem odpowiedzi.');
      if (responseBubble) responseBubble.heading.textContent = `${responseAgent} · ${responseSource || 'API'}`;
      if (responseSessionId && SESSION_ID_PATTERN.test(responseSessionId)) {
        activeSessionId = responseSessionId;
        recordHistory(responseSessionId, userMessage);
      }
      message.value = '';
      feedback.textContent = responseSource === 'ollama'
        ? 'Odpowiedź modelu lokalnego; rozmowa zapisana w pamięci API.'
        : 'Odpowiedź lokalnej obsługi polecenia API.';
    } catch (error) {
      if (error?.name === 'AbortError') {
        if (responseBubble) responseBubble.heading.textContent = `${agentName} · strumień przerwany lokalnie`;
        feedback.textContent = activeChatCancelMessage
          || 'Zatrzymano odbiór strumienia. Backend nie potwierdził anulowania zadania.';
      } else {
        if (!responseText && responseBubble) responseBubble.entry.remove();
        else if (responseBubble) responseBubble.heading.textContent = `${agentName} · odpowiedź nieukończona`;
        appendTranscript('error', `Błąd API${error.status ? ` · HTTP ${error.status}` : ''}`, error.message);
        feedback.textContent = error.status === 503
          ? 'Model niedostępny — API nie wygenerowało odpowiedzi.'
          : error.message;
      }
    } finally {
      activeChatController = null;
      activeChatTaskId = '';
      submit.hidden = false;
      stop.hidden = true;
      stop.disabled = false;
      stop.textContent = 'Zatrzymaj';
      await loadTasks();
    }
  });
  document.getElementById('chat-stop')?.addEventListener('click', async (event) => {
    const stop = event.currentTarget;
    if (!activeChatController || stop.disabled) return;
    const controller = activeChatController;
    const taskId = activeChatTaskId;
    if (!taskId) {
      activeChatCancelMessage = 'Brak ID zadania do anulowania. Zatrzymano odbiór strumienia; anulowanie serwera nie jest potwierdzone.';
      controller.abort();
      return;
    }
    stop.disabled = true;
    stop.textContent = 'Anulowanie…';
    setText('chat-feedback', 'Wysyłanie żądania anulowania do API…');
    try {
      const payload = await api.cancelTask(taskId);
      if (payload.task?.id !== taskId) throw new ApiError('API nie potwierdziło zadania do anulowania.');
      if (activeChatController !== controller) return;
      setText('chat-feedback', `API przyjęło anulowanie (${payload.task.status}); oczekiwanie na zdarzenie SSE.`);
    } catch (error) {
      if (activeChatController !== controller) return;
      controller.abort();
      activeChatCancelMessage = error.status === 404
        ? 'Ten backend nie udostępnia anulowania zadania. Zatrzymano odbiór strumienia lokalnie; anulowanie serwera nie jest potwierdzone.'
        : error.status === 401 || error.status === 403
          ? `${error.message} Zatrzymano odbiór strumienia; anulowanie serwera nie jest potwierdzone.`
          : `${error.message} Zatrzymano odbiór strumienia; anulowanie serwera nie jest potwierdzone.`;
      setText('chat-feedback', activeChatCancelMessage);
    }
  });
}

function bindTerminalForm() {
  const form = document.getElementById('terminal-form');
  if (!form) return;
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const commandInput = document.getElementById('terminal-command');
    const submit = document.getElementById('terminal-submit');
    const feedback = document.getElementById('terminal-feedback');
    const command = commandInput?.value.trim();
    if (!command || !feedback) return;
    submit.disabled = true;
    feedback.textContent = 'Wysyłanie do ograniczonego API terminala…';
    try {
      const result = await api.terminal(command);
      if (typeof result.output !== 'string') throw new ApiError('API nie zwróciło wyniku tekstowego.');
      renderTerminal(command, result.output);
      commandInput.value = '';
      feedback.textContent = 'Polecenie obsłużone bez uruchamiania powłoki.';
    } catch (error) {
      renderTerminal(command, error.message, true);
      feedback.textContent = error.message;
    } finally {
      submit.disabled = false;
      await loadTasks();
    }
  });
}

if (typeof document !== 'undefined') {
  renderAgentProfiles(document.getElementById('agent-list'));
  bindNavigation();
  bindChatForm();
  bindTerminalForm();
  renderHistory();
  document.getElementById('refresh-status')?.addEventListener('click', refreshDashboard);
  document.getElementById('refresh-tasks')?.addEventListener('click', refreshWork);
  void refreshDashboard();
  let savedSession = '';
  try {
    savedSession = sessionStorage.getItem(SESSION_KEY) ?? '';
  } catch {
    // The API-backed chat remains available without browser storage.
  }
  if (SESSION_ID_PATTERN.test(savedSession)) void loadHistory(savedSession);
}
