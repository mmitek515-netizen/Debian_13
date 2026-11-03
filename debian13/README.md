# Debian 13 — niezależna aplikacja developerska

To jest uruchamialna aplikacja developerska z Pythonowym API i GUI, a nie
ukończony system operacyjny: repozytorium nie dostarcza bootowalnego ISO ani
zweryfikowanej maszyny wirtualnej. Profile Alex, Aria, Astyria i Aurelius nie
potwierdzają działających workerów AI.

## Szybki start

W katalogu głównym repozytorium uruchom:

```sh
bash debian13/start-local.sh
```

Jeśli bieżącym katalogiem jest `debian13/`, użyj `bash start-local.sh`.
Otwórz `http://127.0.0.1:3000`; w Codespaces wybierz prywatny port 3000.
`Ctrl+C` zatrzymuje API i GUI.

Wymagany jest Python 3.10 lub nowszy. Docker, npm, płatny plan GitHub i klucz
API nie są potrzebne do startu. Bez skonfigurowanego providera AI czat zwraca
informację o niedostępności modelu; Work i ograniczony terminal nadal działają.
API nasłuchuje wyłącznie na loopbackie. Token operatora jest generowany lokalnie
i przechowywany poza repozytorium w `~/.local/state/debian13/operator-token`;
zadania Work są przechowywane w SQLite pod
`~/.local/share/debian13/workspace`.

## Opcjonalny provider AI

Aby użyć zgodnego z OpenAI API providera, ustaw jego adres HTTPS, klucz i nazwę
modelu w środowisku serwera, a następnie uruchom aplikację:

```sh
export MODEL_CHAT_URL="https://provider.example/v1/chat/completions"
export MODEL_API_KEY="ustaw-klucz-jako-sekret"
export MODEL_NAME="nazwa-modelu"
bash debian13/start-local.sh
```

Wiadomości, a w przypadku Vision także obrazy, zostaną wysłane do wybranego
providera. Nie zapisuj kluczy w repozytorium ani w zgłoszeniach.

Alternatywnie `bash debian13/start-ai-session.sh` uruchamia wariant Docker
Compose z Ollamą. Wymaga Docker Engine i Compose v2 oraz może pobrać duży model
przy pierwszym uruchomieniu. Szczegóły konfiguracji kontenera, API i testów
izolacji opisuje [`system/README.md`](system/README.md).

## Funkcje i ograniczenia

- `system/server.py` udostępnia uwierzytelnione API HTTP; token nie jest
  umieszczany w kodzie przeglądarki.
- `system/work_store.py` przechowuje zadania i zdarzenia w SQLite. Dodanie
  zadania nie uruchamia agenta, kodu ani zakupów.
- `system/mcp_server.py` udostępnia narzędzia MCP tylko do odczytu przez stdio.
- `system/gpt-actions.openapi.json` opisuje kontrakt GPT Actions; obecność
  schematu nie potwierdza podłączenia GPT.
- Integracja z istniejącym Alex wymaga skonfigurowanego endpointu i jawnego
  przekazania zadania. Sam profil ani rejestr zadań nie dowodzą wykonania przez
  AI.
- GUI zawiera czat, Work, ograniczony terminal i ustawienia. Brak providera,
  działających workerów, MCP klienta lub połączenia GPT/Codex jest raportowany
  jako ograniczenie, a nie zastępowany symulowanym sukcesem.
- Nie uruchomiono tutaj zakupów ani płatnych usług. Każdy zakup wymaga
  wcześniejszej, jednoznacznej zgody właściciela na konkretny wydatek.

## Weryfikacja lokalna

Z katalogu głównego repozytorium:

```sh
bash debian13/start-local.sh --check
python3 -m unittest discover -s debian13/system/tests -p 'test_*.py' -v
node --test debian13/ui/dev_server.test.mjs
```

Testy lokalne sprawdzają API, Work/SQLite, integracje i proxy GUI przy użyciu
testowych endpointów. Nie są dowodem działającego zewnętrznego modelu, agenta,
GPT Actions, Codex, publicznego CI ani bootowania Debian 13. Te elementy należy
zweryfikować osobno w odpowiednim środowisku i na konkretnym commicie.

### Rzeczywisty podgląd GUI

Zrzuty wykonano w przeglądarce Chromium przez Playwright, 2026-11-03, na
lokalnie uruchomionym API i GUI z drzewa roboczego opartego na commicie
`f6e4c80`, bez skonfigurowanego modelu. To rzeczywiste widoki aplikacji, nie
makiety ani dowód inferencji.
Wymiary dokumentu były równe szerokościom okna przy 320, 360, 412 i 1440 px.
Na 320 px otworzono też mobilny panel i nawigowano do widoku Work; po wyborze
widoku panel się zamknął.

- Chat, 320 × 900: [`ui/previews/debian13-chat-ui-320.png`](ui/previews/debian13-chat-ui-320.png)
- Chat, 360 × 900: [`ui/previews/debian13-chat-ui-360.png`](ui/previews/debian13-chat-ui-360.png)
- Chat, 412 × 900: [`ui/previews/debian13-chat-ui-412.png`](ui/previews/debian13-chat-ui-412.png)
- Chat, 1440 × 1000: [`ui/previews/debian13-chat-ui-1440.png`](ui/previews/debian13-chat-ui-1440.png)
- Otwarta nawigacja mobilna, 320 × 900: [`ui/previews/debian13-chat-nav-320.png`](ui/previews/debian13-chat-nav-320.png)
- Work po utworzeniu zadania przeglądowego i zdarzeniu `task_queued`, 360 × 900:
  [`ui/previews/debian13-work-ui-360.png`](ui/previews/debian13-work-ui-360.png)
- Ustawienia: rzeczywisty stan czterech niepodłączonych agentów i integracji, 1440 × 1000:
  [`ui/previews/debian13-agents-status-1440.png`](ui/previews/debian13-agents-status-1440.png)
