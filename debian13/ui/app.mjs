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
  if (payload?.error?.code === 'agent_disconnected') return payload.error.message;
  if (payload?.error?.code === 'connection_refused') return payload.error.message;
  if (payload?.error?.code === 'model_not_found') return payload.error.message;
  if (payload?.error?.code === 'out_of_memory') return payload.error.message;
  return typeof payload?.error === 'string'
    ? payload.error
    : typeof payload?.error?.message === 'string'
      ? payload.error.message
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
    getOllamaStatus: () => request('ollama'),
    getAgents: () => request('agents'),
    getOriginalAgents: () => request('original-agents'),
    getOriginalAgentAttempts: () => request('original-agent-attempts'),
    getIntegrations: () => request('integrations'),
    getTasks: () => request('tasks'),
    getAlexCapabilities: () => request('alex/capabilities'),
    dispatchToAlex: (taskId) => request(`tasks/${encodeURIComponent(taskId)}/dispatch`, {method: 'POST'}),
    createTask: (task) => post('tasks', task),
    getTask: (taskId) => request(`tasks/${encodeURIComponent(taskId)}`),
    getEvents: () => request('events'),
    getMessages: (sessionId) => request(`sessions/${encodeURIComponent(sessionId)}/messages`),
    getSessions: () => request('sessions'),
    cancelTask: (taskId) => request(`tasks/${encodeURIComponent(taskId)}/cancel`, { method: 'POST' }),
    chatStream,
    vision: (agent, message, image) => post('vision', { profile: agent, message, image }),
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
    unavailable: 'Model niedostępny',
    configured: 'Model skonfigurowany (połączenie jeszcze niezweryfikowane)',
    model_missing: 'Model niedostępny',
    model_not_found: 'Model Ollama niepobrany',
    connection_refused: 'Ollama nie odpowiada',
    unavailable: 'Ollama niedostępna',
    invalid_response: 'Nieprawidłowa odpowiedź Ollamy',
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
    const name = isUser
      ? (message.channel === 'all' ? 'Wszyscy' : 'Ollama lokalna')
      : message.source === 'ollama'
        ? 'Ollama lokalna'
        : AGENT_PROFILES.find((agent) => agent.id === message.agent)?.name ?? 'Agent';
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
    detail.textContent = `${task.title || task.kind} · ${task.agent} · ${task.id}`;
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
      if (task.agent === 'alex' && task.status === 'queued') {
        const dispatch = document.createElement('button');
        dispatch.type = 'button';
        dispatch.className = 'task-action task-dispatch';
        dispatch.textContent = 'Przekaż Alexowi';
        dispatch.disabled = !alexDispatchSupported;
        dispatch.setAttribute('aria-label', `Przekaż zadanie ${task.id} oryginalnemu Alexowi`);
        dispatch.addEventListener('click', () => void dispatchWorkToAlex(task.id, dispatch));
        actions.append(dispatch);
      }
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
    empty.textContent = 'Brak zapisanych zadań do przeglądu.';
    fragment.append(empty);
  }
  list.replaceChildren(fragment);
  setText('tasks-count', `${tasks.length} zadań · trwały zapis SQLite, bez uruchomionych workerów`);
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
  setText('events-count', `${events.length} zdarzeń · trwały dziennik SQLite`);
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

async function refreshChatHistory(activeId = activeSessionId) {
  try {
    const payload = await api.getSessions();
    if (!Array.isArray(payload.sessions)) throw new ApiError('Nieprawidłowy format historii sesji.');
    writeHistory(payload.sessions.map((session) => ({
      id: session.id,
      title: session.title || 'Nowa rozmowa',
    })));
  } catch {
    // Keep the browser-side index available when using a compatible older backend.
  }
  renderHistory(activeId);
}

const api = createApiClient();
let alexDispatchSupported = false;
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

async function loadOriginalAgents() {
  const list = document.getElementById('original-agent-list');
  if (!list) return;
  setText('original-agent-error', '');
  try {
    const response = await api.getOriginalAgents();
    if (!Array.isArray(response.agents) || response.agents.length !== 4) {
      throw new ApiError('Źródło nie podało kompletu czterech oryginalnych agentów.');
    }
    const fragment = document.createDocumentFragment();
    for (const agent of response.agents) {
      const item = document.createElement('li');
      item.className = 'agent-card';
      const heading = document.createElement('strong');
      heading.textContent = agent.name;
      const role = document.createElement('p');
      role.className = 'agent-role';
      role.textContent = agent.role;
      const status = document.createElement('p');
      status.className = 'agent-state';
      status.textContent = agent.workerVerified === true
        ? 'Zweryfikowany proces AI'
        : response.registryReachable
          ? 'Rejestr źródłowy dostępny · praca AI niepotwierdzona'
          : 'Oryginalny agent niepodłączony';
      const details = document.createElement('p');
      details.className = 'worker-state';
      details.textContent = `Zadania w rejestrze: ${Number(agent.tasksInRegistry) || 0}; uruchomione workery: niepotwierdzone`;
      item.append(heading, role, status, details);
      fragment.append(item);
    }
    list.replaceChildren(fragment);
    const attemptsList = document.getElementById('original-agent-attempts');
    if (attemptsList) {
      const attempts = await api.getOriginalAgentAttempts();
      const rows = document.createDocumentFragment();
      for (const attempt of attempts.attempts ?? []) {
        const row = document.createElement('li');
        row.className = 'event-item';
        const agentName = AGENT_PROFILES.find((profile) => profile.id === attempt.agent)?.name ?? attempt.agent;
        const detail = document.createElement('span');
        detail.textContent = `${agentName} · ${attempt.status}`;
        const time = document.createElement('span');
        time.className = 'event-metadata';
        time.textContent = attempt.at;
        row.append(detail, time);
        rows.append(row);
      }
      if (!rows.childNodes.length) {
        const empty = document.createElement('li');
        empty.className = 'empty-state';
        empty.textContent = 'Brak prób rozmowy.';
        rows.append(empty);
      }
      attemptsList.replaceChildren(rows);
    }
  } catch (error) {
    list.replaceChildren();
    setText('original-agent-error', error.message);
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

async function refreshAlexCapabilities() {
  alexDispatchSupported = false;
  try {
    const response = await api.getAlexCapabilities();
    const state = response.alex;
    alexDispatchSupported = state?.configured === true && state?.supported === true;
    setText('alex-dispatch-state', alexDispatchSupported
      ? 'Oryginalny Alex udostępnia protokół przekazania zadania. Nie potwierdzono jednak pracy modelu AI.'
      : 'Oryginalny Alex nie udostępnia obecnie bezpiecznego wysyłania zadań. Przycisk przekazania jest zablokowany.');
  } catch (error) {
    setText('alex-dispatch-state', 'Nie można sprawdzić połączenia z oryginalnym Alexem: ' + error.message);
  }
  return alexDispatchSupported;
}

async function dispatchWorkToAlex(taskId, button) {
  if (!alexDispatchSupported || button.disabled) return;
  const approved = window.confirm(
    'Czy przekazać to zadanie do oryginalnego Alexa? Nie oznacza to zgody na zakup, scalanie ani wykonywanie płatności.'
  );
  if (!approved) return;
  button.disabled = true;
  setText('work-connection-state', 'Weryfikacja odbioru zadania przez serwer Alexa…');
  try {
    const result = await api.dispatchToAlex(taskId);
    if (!result.alexSubmission || result.executionStarted !== false) {
      throw new ApiError('Brak potwierdzenia przyjęcia zadania przez oryginalne API Alexa.');
    }
    setText('work-connection-state', 'Oryginalny serwer Alexa przyjął zadanie. Wykonanie przez AI i PR pozostają niepotwierdzone.');
    await refreshWork();
  } catch (error) {
    setText('tasks-error', error.message);
    setText('work-connection-state', error.message);
  } finally {
    button.disabled = false;
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
  const [tasksError, eventsError] = await Promise.all([loadTasks(), loadEvents(), refreshAlexCapabilities()]);
  // The buttons were initially rendered before reading actual remote capabilities.
  if (!tasksError) await loadTasks();
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
  await Promise.all([loadStatus(), loadAgents(), loadOriginalAgents(), loadIntegrations(), loadTasks()]);
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
    const priorChannel = payload.messages.find((message) => message.role === 'user')?.channel;
    const channelSelect = document.getElementById('chat-agent');
    if (channelSelect && ['ollama', 'all', 'aria', 'alex', 'astyria', 'aurelius'].includes(priorChannel)) {
      channelSelect.value = priorChannel;
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
  void refreshChatHistory(sessionId);
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
      if (button.dataset.view === 'settings') void refreshDashboard();
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

async function prepareVisionImage(file) {
  if (!['image/jpeg', 'image/png'].includes(file?.type)) {
    throw new ApiError('Vision obsługuje tylko obrazy JPEG i PNG.');
  }
  if (file.size > 8 * 1024 * 1024) {
    throw new ApiError('Zdjęcie przekracza limit 8 MB. Wybierz mniejszy plik.');
  }
  const objectUrl = URL.createObjectURL(file);
  try {
    const image = new Image();
    await new Promise((resolve, reject) => {
      image.onload = resolve;
      image.onerror = () => reject(new ApiError('Nie można odczytać wybranego zdjęcia.'));
      image.src = objectUrl;
    });
    const width = image.naturalWidth;
    const height = image.naturalHeight;
    if (!width || !height) throw new ApiError('Obraz nie zawiera poprawnych wymiarów.');
    const scale = Math.min(1, 1280 / Math.max(width, height));
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(width * scale));
    canvas.height = Math.max(1, Math.round(height * scale));
    const context = canvas.getContext('2d');
    if (!context) throw new ApiError('Przeglądarka nie umożliwia przetworzenia zdjęcia.');
    context.fillStyle = '#ffffff';
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    const uri = canvas.toDataURL('image/jpeg', 0.78);
    const encoded = uri.split(',', 2)[1] ?? '';
    if (!encoded || encoded.length > 4 * Math.ceil((2 * 1024 * 1024) / 3)) {
      throw new ApiError('Obraz po przetworzeniu jest za duży. Wybierz mniejszy plik.');
    }
    return { mime_type: 'image/jpeg', base64: encoded };
  } finally {
    URL.revokeObjectURL(objectUrl);
  }
}

function bindChatForm() {
  const form = document.getElementById('chat-form');
  if (!form) return;
  const message = document.getElementById('chat-message');
  const attachment = document.getElementById('chat-image');
  const preview = document.getElementById('chat-image-preview');
  const thumbnail = document.getElementById('chat-image-thumbnail');
  const fileName = document.getElementById('chat-image-name');
  let previewUrl = '';
  const clearAttachment = () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = '';
    if (attachment) attachment.value = '';
    if (thumbnail) thumbnail.removeAttribute('src');
    if (preview) preview.hidden = true;
  };
  attachment?.addEventListener('change', () => {
    clearAttachmentPreviewOnly();
    const file = attachment.files?.[0];
    if (!file) return;
    if (!['image/png', 'image/jpeg'].includes(file.type) || file.size > 8 * 1024 * 1024) {
      setText('chat-feedback', 'Wybierz obraz JPEG/PNG o rozmiarze do 8 MB.');
      attachment.value = '';
      return;
    }
    previewUrl = URL.createObjectURL(file);
    if (thumbnail) thumbnail.src = previewUrl;
    if (fileName) fileName.textContent = file.name;
    if (preview) preview.hidden = false;
  });
  function clearAttachmentPreviewOnly() {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = '';
    if (thumbnail) thumbnail.removeAttribute('src');
    if (preview) preview.hidden = true;
  }
  document.getElementById('chat-image-remove')?.addEventListener('click', clearAttachment);
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
    const file = attachment?.files?.[0] ?? null;
    if (file) {
      clearAttachment();
      feedback.textContent = 'Vision nie jest skonfigurowane dla lokalnego kanału tekstowego. Nie wysłano obrazu ani nie wygenerowano odpowiedzi.';
      return;
    }

    const controller = new AbortController();
    activeChatController = controller;
    activeChatTaskId = '';
    activeChatCancelMessage = '';
    const agentName = AGENT_PROFILES.find((profile) => profile.id === agent.value)?.name ?? agent.value;
    const channelName = agent.value === 'ollama'
      ? 'Ollama lokalna'
      : agent.value === 'all'
        ? 'Wszyscy'
        : agentName;
    const userMessage = text;
    appendTranscript('user', `Ty · ${channelName}`, userMessage);
    const responseBubble = appendTranscript('assistant', `${channelName} · łączenie`);
    submit.hidden = true;
    stop.hidden = false;
    feedback.textContent = 'Łączenie ze strumieniem API…';
    let responseText = '';
    let receivedDone = false;
    let receivedCancelled = false;
    let responseSource = '';
    let responseAgent = channelName;
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
          responseAgent = payload.source === 'ollama'
            ? 'Ollama lokalna'
            : AGENT_PROFILES.find((profile) => profile.id === payload.agent)?.name ?? responseAgent;
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
        ? agent.value === 'all'
          ? 'Odpowiedź lokalnej Ollamy; oryginalni agenci są odłączeni. Historia zapisana w lokalnej bazie SQLite.'
          : 'Odpowiedź lokalnej Ollamy; historia zapisana w lokalnej bazie SQLite.'
        : responseSource === 'model_provider'
          ? 'Odpowiedź podłączonego dostawcy AI; brak zapisu historii sesji.'
          : 'Odpowiedź API.';
    } catch (error) {
      if (error?.name === 'AbortError') {
        if (responseBubble) responseBubble.heading.textContent = `${agentName} · strumień przerwany lokalnie`;
        feedback.textContent = activeChatCancelMessage
          || 'Zatrzymano odbiór strumienia. Backend nie potwierdził anulowania zadania.';
      } else {
        if (!responseText && responseBubble) responseBubble.entry.remove();
        else if (responseBubble) responseBubble.heading.textContent = `${agentName} · odpowiedź nieukończona`;
        appendTranscript('error', `Błąd API${error.status ? ` · HTTP ${error.status}` : ''}`, error.message);
        feedback.textContent = error.message;
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
      activeChatCancelMessage = 'Strumień przerwany. Backend zamknął połączenie z lokalnym modelem; anulowanie oryginalnych agentów nie dotyczy tej sesji.';
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

function bindWorkCreateForm() {
  const form = document.getElementById('work-create-form');
  if (!form) return;
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const button = document.getElementById('work-create-submit');
    const agent = document.getElementById('work-task-agent')?.value;
    const kind = document.getElementById('work-task-kind')?.value;
    const title = document.getElementById('work-task-title')?.value.trim();
    const description = document.getElementById('work-task-description')?.value.trim();
    if (!agent || !kind || !title || !description || button.disabled) return;
    button.disabled = true;
    setText('work-create-feedback', 'Zapisuję zadanie w bazie API…');
    try {
      const result = await api.createTask({ agent, kind, title, description });
      if (!result.task?.id || result.executionStarted !== false) {
        throw new ApiError('API nie potwierdziło bezpiecznej rejestracji zadania.');
      }
      document.getElementById('work-task-title').value = '';
      document.getElementById('work-task-description').value = '';
      await refreshWork();
      setText('work-create-feedback', 'Zadanie zapisane. Agent AI NIE został uruchomiony; oczekuje na przegląd operatora.');
    } catch (error) {
      setText('work-create-feedback', error.message);
    } finally {
      button.disabled = false;
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
  bindWorkCreateForm();
  void refreshChatHistory();
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
