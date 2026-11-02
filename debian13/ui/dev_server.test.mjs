import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const repositoryRoot = fileURLToPath(new URL('../../', import.meta.url));
const TEST_SESSION_ID = '123e4567-e89b-42d3-a456-426614174000';
const TEST_TASK_ID = '123e4567-e89b-42d3-a456-426614174001';

async function reserveLoopbackPort() {
  const server = createServer();
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  const { port } = server.address();
  await new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  return port;
}

async function startUpstreamDouble(t) {
  const requests = [];
  const server = createServer(async (request, response) => {
    const chunks = [];
    for await (const chunk of request) chunks.push(chunk);
    requests.push({
      method: request.method,
      url: request.url,
      contentType: request.headers['content-type'] ?? null,
      authorization: request.headers.authorization ?? null,
      body: Buffer.concat(chunks).toString('utf8'),
    });
    if (request.url === '/api/v1/chat/stream') {
      response.writeHead(200, {
        'Content-Type': 'text/event-stream; charset=utf-8',
        'X-Upstream-Header': 'must-not-be-relayed',
      });
      response.write('event: meta\ndata: {"session_id":"123e4567-e89b-42d3-a456-426614174000"}\n\n');
      setTimeout(() => {
        response.end('event: done\ndata: {"source":"local_command"}\n\n');
      }, 100);
      return;
    }
    response.writeHead(200, {
      'Content-Type': 'text/html; charset=utf-8',
      'X-Upstream-Header': 'must-not-be-relayed',
    });
    response.end(JSON.stringify({ ok: true, path: request.url }));
  });
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  t.after(() => new Promise((resolve, reject) =>
    server.close((error) => error ? reject(error) : resolve())));
  return { port: server.address().port, requests };
}

async function startUiProxy(t, apiPort, apiToken = '') {
  const port = await reserveLoopbackPort();
  const child = spawn('python3', ['debian13/ui/dev_server.py'], {
    cwd: repositoryRoot,
    env: {
      ...process.env,
      DEBIAN13_API_PORT: String(apiPort),
      DEBIAN13_API_TOKEN: apiToken,
      DEBIAN13_UI_PORT: String(port),
    },
    stdio: 'ignore',
  });
  t.after(async () => {
    if (child.exitCode !== null || child.signalCode !== null) return;
    const exited = once(child, 'exit');
    child.kill('SIGTERM');
    let timeout;
    await Promise.race([
      exited,
      new Promise((resolve) => {
        timeout = setTimeout(resolve, 2000);
      }),
    ]);
    clearTimeout(timeout);
  });

  const baseUrl = `http://127.0.0.1:${port}`;
  let lastError;
  for (let attempt = 0; attempt < 40; attempt += 1) {
    if (child.exitCode !== null) throw new Error(`UI proxy exited with ${child.exitCode}`);
    try {
      const response = await fetch(`${baseUrl}/`, { signal: AbortSignal.timeout(500) });
      if (response.ok) return baseUrl;
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
  throw new Error(`UI proxy did not start: ${lastError?.message ?? 'unknown error'}`);
}

test('real loopback proxy allows only contract routes and normalizes upstream headers', async (t) => {
  const upstream = await startUpstreamDouble(t);
  const baseUrl = await startUiProxy(t, upstream.port);

  const status = await fetch(`${baseUrl}/api/v1/status`);
  assert.equal(status.status, 200);
  assert.equal(status.headers.get('content-type'), 'application/json; charset=utf-8');
  assert.equal(status.headers.get('x-upstream-header'), null);
  assert.equal(status.headers.get('content-security-policy')?.includes("default-src 'self'"), true);
  assert.deepEqual(await status.json(), { ok: true, path: '/api/v1/status' });
  assert.equal(upstream.requests[0].authorization, null, 'the proxy must not forward a browser-supplied token by default');

  const chat = await fetch(`${baseUrl}/api/v1/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message: '/help', agent: 'aria' }),
  });
  assert.equal(chat.status, 200);
  assert.equal((await chat.json()).path, '/api/v1/chat');
  assert.equal(upstream.requests[1].contentType, 'application/json');
  assert.deepEqual(JSON.parse(upstream.requests[1].body), { message: '/help', agent: 'aria' });

  const stream = await fetch(`${baseUrl}/api/v1/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message: '/help', agent: 'aria' }),
  });
  assert.equal(stream.status, 200);
  assert.equal(stream.headers.get('content-type'), 'text/event-stream; charset=utf-8');
  assert.equal(stream.headers.get('x-upstream-header'), null);
  const reader = stream.body.getReader();
  const firstEvent = await reader.read();
  assert.equal(firstEvent.done, false, 'SSE headers and first event should arrive before upstream closes');
  assert.match(new TextDecoder().decode(firstEvent.value), /event: meta/);
  let remainingText = '';
  let streamDone = false;
  while (!streamDone) {
    const next = await reader.read();
    streamDone = next.done;
    if (next.value) remainingText += new TextDecoder().decode(next.value);
  }
  assert.match(remainingText, /event: done/);

  const history = await fetch(`${baseUrl}/api/v1/sessions/${TEST_SESSION_ID}/messages`);
  assert.equal(history.status, 200);
  assert.equal((await history.json()).path, `/api/v1/sessions/${TEST_SESSION_ID}/messages`);

  const events = await fetch(`${baseUrl}/api/v1/events`);
  assert.equal(events.status, 200);
  assert.deepEqual(await events.json(), { ok: true, path: '/api/v1/events' });

  const task = await fetch(`${baseUrl}/api/v1/tasks/${TEST_TASK_ID}`);
  assert.equal(task.status, 200);
  assert.deepEqual(await task.json(), { ok: true, path: `/api/v1/tasks/${TEST_TASK_ID}` });

  const denied = await fetch(`${baseUrl}/api/v1/agents/extra`);
  assert.equal(denied.status, 404);
  assert.deepEqual(await denied.json(), { error: 'Nie znaleziono endpointu API.' });
  const invalidSession = await fetch(`${baseUrl}/api/v1/sessions/not-a-uuid/messages`);
  assert.equal(invalidSession.status, 404);
  const invalidTask = await fetch(`${baseUrl}/api/v1/tasks/not-a-uuid`);
  assert.equal(invalidTask.status, 404);
  assert.equal(upstream.requests.length, 6, 'disallowed paths must not reach the upstream API');
});

test('real loopback proxy injects only its configured operator token and forwards bodyless cancel', async (t) => {
  const upstream = await startUpstreamDouble(t);
  const fixtureToken = 'fixture-only-operator-token';
  const baseUrl = await startUiProxy(t, upstream.port, fixtureToken);

  const response = await fetch(`${baseUrl}/api/v1/tasks/${TEST_TASK_ID}/cancel`, {
    method: 'POST',
    headers: { Authorization: ['Bear', 'er browser-supplied-token'].join('') },
  });
  assert.equal(response.status, 200);
  assert.equal((await response.json()).path, `/api/v1/tasks/${TEST_TASK_ID}/cancel`);
  assert.equal(upstream.requests.length, 1);
  assert.equal(upstream.requests[0].authorization, ['Bear', 'er fixture-only-operator-token'].join(''));
  assert.equal(upstream.requests[0].contentType, null);
  assert.equal(upstream.requests[0].body, '');
});

test('real loopback proxy rejects a body on task cancellation before forwarding', async (t) => {
  const upstream = await startUpstreamDouble(t);
  const baseUrl = await startUiProxy(t, upstream.port);
  const response = await fetch(`${baseUrl}/api/v1/tasks/${TEST_TASK_ID}/cancel`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: '{}',
  });
  assert.equal(response.status, 400);
  assert.deepEqual(await response.json(), { error: 'Anulowanie zadania nie przyjmuje treści.' });
  assert.equal(upstream.requests.length, 0);
});

test('real loopback proxy rejects oversized writes before forwarding', async (t) => {
  const upstream = await startUpstreamDouble(t);
  const baseUrl = await startUiProxy(t, upstream.port);
  const response = await fetch(`${baseUrl}/api/v1/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: 'x'.repeat(16_385),
  });
  assert.equal(response.status, 413);
  assert.deepEqual(await response.json(), { error: 'Żądanie przekracza limit rozmiaru.' });
  assert.equal(upstream.requests.length, 0);
});
