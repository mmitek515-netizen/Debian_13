# Debian 13 — niezależny interfejs

Interfejs w [`ui/`](ui/) łączy się z wersjonowanym API Debian 13 v1, bez
korzystania z API starszej aplikacji Bastilla OS 2. Używa kontraktu backendu
z PR #97, commit
[`664b7b6`](https://github.com/mmitek515-netizen/Bastilla_OS_2/commit/664b7b621c85b5e1a745a28c6845b67a33fc2e2c);
ten etap nie kopiuje ani nie zmienia jego plików backendu.

## Uruchomienie sesji AI w GitHub Codespaces (nowa, samodzielna ścieżka)

Dla najnowszego serwera w `debian13/system/server.py` i interfejsu
`debian13/ui` nie trzeba używać starego backendu z innego repo.
Otwórz Codespace dla `mmitek515-netizen/Debian_13`, gałęzi
`feature/dialog-triady-vision-memory` (PR #14), i
wykonaj w terminalu repozytorium:

```bash
bash debian13/start-ai-session.sh
```

Jeżeli Codespaces otworzył katalog `debian13/` jako główny, użyj
`bash start-ai-session.sh`. Skrypt generuje prywatny token
operatora (jeśli nie jest już ustawiony), buduje API w Dockerze, uruchamia
Ollamę i automatycznie pobiera tekstowy `qwen2.5-coder:1.5b`, następnie
uruchamia prywatny serwer interfejsu na porcie `3000`.
W Codespaces otwórz panel **Ports** i kliknij przekierowany **prywatny** port
`3000`. Nie zmieniaj jego widoczności na publiczną.

**Zasoby:** pierwszy start wymaga Dockera, pobrania obrazu i modelu, wolnego
dysku, pamięci oraz dostępu do internetu. Na CPU odpowiedzi mogą być powolne.
`OLLAMA_MODEL` pozwala wybrać inny model. Vision jest opcjonalne; sam zapis
skryptu w repozytorium nie uruchamia systemu.

Po starcie sprawdź GUI, terminal, lokalny protokół MCP i czat z lokalną Ollamą:

```bash
DEBIAN13_API_PORT=8080 python3 debian13/system/check_priority_runtime.py --ollama-chat
```

To tworzy cztery krótkie sesje w historii. Bez flagi `--ollama-chat` sprawdzane
są tylko GUI, terminal i MCP. Wynik nie dowodzi pracy oryginalnych workerów ani
zdalnego połączenia ChatGPT. Szczegóły i inne porty:
[`docs/OLLAMA_FREE_AND_AGENT_DIALOG.md`](docs/OLLAMA_FREE_AND_AGENT_DIALOG.md).

**Inny provider AI:** aby użyć zewnętrznego OpenAI-compatible API zamiast
lokalnej Ollamy, ustaw `MODEL_CHAT_URL` (pełny adres
HTTPS `/v1/chat/completions`), `MODEL_API_KEY` i
`MODEL_NAME` w prywatnych zmiennych środowiskowych Codespaces,
a następnie wykonaj to samo polecenie. Nie wklejaj kluczy do GitHub Issues.
Po stronie backendu obrazy wymagają dodatkowo `VISION_MODEL_NAME`
wskazującego model obsługujący obrazy.

**Obecne ograniczenia:** odpowiedzi tekstowe trafiają z prawdziwego endpointu
modelu do GUI przez zgodny format SSE, ale kompletna odpowiedź pojawia się po
inferencji (bez tokenowego streamingu). Historia i kolejka Work są zapisywane
w lokalnej SQLite; samo zapisanie zadania nie oznacza pracy agenta.
Profile agentów nie są autonomicznymi workerami. Dostępność rzeczywistego
modelu i inferencję Vision trzeba zweryfikować po uruchomieniu Codespace.

## Alternatywna dokumentacja starszego prototypu GUI

### Uruchomienie starego backendu demonstracyjnego

Uruchom zgodny backend API na `127.0.0.1:8765` (źródło z powyższego commita
udostępnia `python3 debian13/server.py`), a następnie z katalogu repozytorium:

```sh
npm run dev:debian13-ui
```

Otwórz `http://127.0.0.1:4174`. UI i serwer pośredniczący wiążą się wyłącznie z
loopbackiem. Serwer pośredniczy wyłącznie w jawnie dozwolonych trasach UI i nie zastępuje
ani nie implementuje API. Dla wdrożenia UI i API muszą być na tym samym originie
albo za zaufanym reverse proxy przekazującym te ścieżki.
Dla oddzielnego, uwierzytelnionego API czatu z PR #95 proxy może dodać token
operatora skonfigurowany wyłącznie po stronie serwera przez `DEBIAN13_API_TOKEN`.
Nie umieszczaj tokenu w przeglądarce ani wiadomości czatu; zmienna pozostaje
pusta dla demonstracyjnego API z PR #97.

UI pobiera status, profile, zadania i zdarzenia z `GET /api/v1/status`,
`/agents`, `/tasks` i `/events`. Work pokazuje rzeczywiste, ograniczone zdarzenia
cyklu życia zadań zwracane przez `/events`; ręczne odświeżenie nie jest strumieniem
na żywo, a zdarzenia są pamięcią procesu, nie dziennikiem systemowym. Czat wysyła
`POST /api/v1/chat/stream` z `{message, agent}` oraz
opcjonalnym `session_id`; zdarzenia SSE `meta`, `delta`, `done` i `error` są
przekazywane bez buforowania. Historię bieżącej sesji pobiera
`GET /api/v1/sessions/{uuid}/messages`. Terminal używa
`POST /api/v1/terminal` z `{command}`.

Panel boczny ma nawigację Czat/Work/Terminal/Ustawienia, historię sesji i
zwijany tryb desktopowy; na telefonie otwiera się jako dostępne klawiaturą
menu. Historia w API jest przechowywana w pamięci backendu i wygasa, a
przeglądarka przechowuje tylko identyfikatory i tytuły znanych sesji. Work
pokazuje rzeczywiste zadania z `/tasks`, ale nie uruchamia planów ani kroków:
kontrakt v1 nie ma API do wieloetapowego Work. Czat wybiera jeden profil;
grupowe „Wszyscy” jest wyłączone, ponieważ kontrakt nie obsługuje broadcastu.
Profile agentów nie oznaczają aktywnych workerów. UI pokazuje błędy API i nie
zastępuje braku modelu odpowiedzią pozorną.

Work może odświeżyć status pojedynczego zadania i zażądać anulowania wyłącznie,
gdy backend udostępnia `GET /api/v1/tasks/{uuid}` oraz beztreściowe
`POST /api/v1/tasks/{uuid}/cancel` z PR #95. Pythonowe demo PR #97 nie ma tych
tras; UI zgłasza wtedy brak endpointu i nie twierdzi, że zadanie anulowano.
Lokalne zatrzymanie strumienia SSE również nie jest potwierdzeniem anulowania
po stronie serwera.

## Testy

```sh
npm run test:debian13-ui
```

Testy HTTP używają jawnie oznaczonego lokalnego test-double i sprawdzają
przekazywanie SSE bez buforowania, historię, reconnect/anulowanie zadań,
serwerowe przekazywanie autoryzacji, dozwolone `pwd`, odrzucone `id`, limit
body oraz HTTP 503 bez modelu. Test-double nie jest dowodem aktywnego modelu
ani workera.

Rzeczywisty przegląd UI wykonano w Chromium 156.0.8078.0 z przypiętym backendem
`664b7b6`, bez skonfigurowanego modelu. Poziomy overflow nie wystąpił, a
composer pozostał przy dolnej krawędzi widoku przy wszystkich wymiarach:

- [320 × 900](ui/previews/debian13-chat-ui-320.png)
- [360 × 900](ui/previews/debian13-chat-ui-360.png)
- [412 × 900](ui/previews/debian13-chat-ui-412.png)
- [1440 × 1000](ui/previews/debian13-chat-ui-1440.png)

Przetestowano widoczny lokalny `/help`, błąd strumienia bez modelu, odtwarzanie
historii, `pwd`, odrzucenie `id`, widoki Work/Ustawienia, otwieranie panelu
bocznego na telefonie, Escape i zwijanie panelu na desktopie. Screenshoty pokazują
rzeczywisty interfejs i lokalną odpowiedź `/help`, nie inferencję modelu.

Work event-log screenshots captured 2026-11-02 from UI SHA `b0cf22d` in Chromium
156.0.8078.0, using the pinned API with Ollama not configured. They show three
real task lifecycle events generated by `/help`, not simulated worker activity:

- [320 × 900](ui/previews/debian13-work-events-320.png)
- [1440 × 1000](ui/previews/debian13-work-events-1440.png)

Auth/reconnect previews captured in HeadlessChrome 156 on 2026-11-02 from UI commit
`23d8942`, using a local HTTP test-double deliberately returning 401. On
320/360/412 px the mobile drawer was opened; the 1440 px view uses the desktop
sidebar. These are fixture error states, not proof of a live or authenticated
backend:

- [320 × 900](ui/previews/debian13-work-auth-320.png)
- [360 × 900](ui/previews/debian13-work-auth-360.png)
- [412 × 900](ui/previews/debian13-work-auth-412.png)
- [1440 × 1000](ui/previews/debian13-work-auth-1440.png)

Browser interaction checks also confirmed that Work retries after a 401,
displays the authorization requirement, and does not lose its error state;
chat receives `cancelled` from a local HTTP fixture after requesting task
cancellation. At 320/360/412/1440 px, document width equaled viewport width;
the chat composer bottom measured 831/900, 841/900, 841/900 and 947/1000 px.
The fixture is not PR #95's running backend or a model.

## Niewykonane

- Nie przygotowano ISO, VM ani bootu Debian 13; nie uruchomiono MCP ani AI Studio.
- Cztery role to profile; backend v1 jawnie raportuje workery jako
  `not_running`. Nie uruchomiono czterech procesów agentów.
- Nie uruchomiono płatnych usług ani nie dokonano zakupów. Każdy wydatek wymaga
  osobnej uprzedniej akceptacji.
