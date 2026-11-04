# Debian 13 — niezależna konsola systemowa i projekt OS

**Uruchamialna aplikacja developerska** dla nowego, niezależnego projektu
Debian 13. Zawiera realny Python HTTP API, GUI (czat, Work, diagnostyka,
terminal ograniczony), trwałą kolejkę SQLite, konfigurację czterech
**oryginalnych** agentów właściciela i integracje MCP/AI.

> Uczciwy stan: to NIE jest ukończony, bootowalny system operacyjny,
> obraz ISO, wirtualna maszyna ani uruchomiony autonomiczny agent.
> Skrypty uruchamiają aplikację na hoście z Pythonem (najlepiej Debian 13).
> Testy CI budują i uruchamiają serwer na bazie Debiana 13.

## Start — jedna komenda, bez Dockera i bez Copilota

W nowym Codespace utworzonym z tego repo albo lokalnym terminalu:

```bash
bash debian13/start-local.sh
```

Gdy repozytorium jest już katalogiem roboczym `debian13/`:

```bash
bash start-local.sh
```

Otwórz GUI `http://127.0.0.1:3000`. W Codespaces w panelu **Ports**
otwórz **prywatny** przekierowany port 3000. Nie zmieniaj go na publiczny.
Backend jest prywatny i dostępny wyłącznie na `127.0.0.1:8765`;
token jest automatycznie generowany i przechowywany w prywatnym pliku
`~/.local/state/debian13/operator-token`, nigdy w repozytorium.
`Ctrl+C` zamyka oba procesy. Baza zadań Work zachowuje dane między
uruchomieniami w `~/.local/share/debian13/workspace`.

```bash
bash debian13/start-local.sh --check
python3 -m unittest discover -s debian13/system/tests -v
node --test debian13/ui/dev_server.test.mjs
```

**Wymagania:** Python 3.10+; przeglądarka. Do samego startu aplikacji
nie potrzeba Dockera, npm, płatnego planu GitHub ani klucza API.

## Procesor poleceń SVL (Python)

W projekcie jest dostępna eksperymentalna, **tylko-do-odczytu** warstwa SVL
5.6.0-QuantumWheel, zaadaptowana z kodu dostarczonego przez operatora.
Uruchomienie zwykłego serwera Debian 13 udostępnia uwierzytelnione
`POST /api/v1/svl/command` z JSON, np. `{"command":"status"}`.
Obsługiwane polecenia: `pomoc`, `status`, `metryka -inf inf`,
`diagnostyka`, `integracje`, `agenci`, `zadania`.
W GUI te same wywołania są dostępne z terminala przez `svl status`,
`svl metryka -inf inf` i podobne, a w oknie czatu przez
`/svl status`, `/svl diagnostyka` i `/svl agenci`.
Do tych poleceń nie jest wymagany model AI ani API OpenAI;
żądanie przechodzi przez prywatne proxy GUI i istniejącą
autoryzację backendu. To nie zastępuje autonomicznego wykonania
zadań przez agentów.

Trasa korzysta z istniejącej autoryzacji API. Przykładowe wywołanie
z hosta, **po załadowaniu prawidłowego tokenu tylko do środowiska terminala**:

```bash
curl -fsS http://127.0.0.1:8765/api/v1/svl/command \
  -H "Authorization: Bearer $DEBIAN13_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command":"metryka -inf inf"}'
```

Wynik zawiera `processor: "SVL"` i `execution: "read_only"`. 
**SVL nie uruchamia shella, workerów, nie przyznaje root ani nie
dokonuje zakupów.** Statusy agentów i integracji są odczytywane z aktualnych
modułów Debian 13; niepotwierdzone połączenia pozostają oznaczone jako
niezweryfikowane. Wynik +1456% z prototypu nie był benchmarkiem i nie jest
prezentowany jako zmierzony wzrost wydajności.

Testy: `python3 -m unittest discover -s debian13/system/tests -v`.
Wdrożenie do `main` wymaga przeglądu PR i pozytywnego CI.

## Podłączanie modelu AI — oddzielnie od startu aplikacji

Bez modelu API uczciwie zwraca `503 provider_not_configured` podczas
rozmowy. GUI i Work nadal działają. Aby korzystać z prawdziwego modelu,
ustaw po stronie serwera zmienne:

```bash
export MODEL_CHAT_URL="https://TWOJ-DOSTAWCA/v1/chat/completions"
export MODEL_API_KEY="SEKRET_UMIESZCZONY_W_SEKRETACH"
export MODEL_NAME="nazwa-modelu"
bash debian13/start-local.sh
```

Adres i klucz powyżej to **przykłady**. Nie wklejaj sekretów do GitHub
ani do AI Studio w plikach źródłowych. Wspierane jest też uruchomienie
z Docker Compose + Ollama poprzez `bash debian13/start-ai-session.sh`;
domyślny model Vision 11B wymaga znaczącej pamięci. Szczegóły w
[`debian13/README.md`](debian13/README.md).

## Oryginalni agenci AI właściciela

Konfiguracje źródłowych agentów **Alex, Aria, Astyria, Aurelius** w
`.github/agents/*.agent.md` zostały zaadaptowane z repozytorium
`u6930438163-code/AI_Studio_BastillaOS`. NIE są nowymi agentami ChatGPT.
Nie kopiujemy starego systemu ani nie utożsamiamy pliku profilu z
pracującym workerem.

W ustawieniach GUI widać osobny status źródła dla każdego agenta.
`GET /api/v1/original-agents` oddziela dostępność rejestru zadań od
rzeczywistego wykonania przez model. Dopóki prawdziwe API źródła i worker
nie zostały potwierdzone, każdy agent ma status **niepodłączony**.
Ustawienia źródłowego API opisują:
[`debian13/system/ALEX_INTEGRATION.md`](debian13/system/ALEX_INTEGRATION.md)
i [`debian13/system/ALEX_HANDOFF.md`](debian13/system/ALEX_HANDOFF.md).
Potwierdzenie źródłowego rejestru nie potwierdza inferencji.

**Zakupy są tylko propozycjami** — każda rzeczywista transakcja wymaga
oddzielnej zgody właściciela z podaną kwotą i dostawcą. Nie ma integracji
płatniczej ani automatycznych zakupów.

## Google AI Studio — ważne ograniczenie

Można **importować kod** repozytorium w Google AI Studio → Build →
**Add files (+)** → **Import from GitHub**. Projekt zawiera zarówno
statyczne GUI HTML/CSS/JS, jak i osobny backend Python. AI Studio
korzysta z własnego środowiska do budowania aplikacji; **import repo
nie uruchomi automatycznie skryptów Pythona, Dockera, Ollamy ani
oryginalnych agentów**. W AI Studio trzeba przygotować odpowiedni
frontend/proxy lub uruchomić API osobno i bezpiecznie je połączyć.
Nie deklaruj działającej synchronizacji, dopóki nie potwierdzisz jej
w ustawieniach i z GitHubem.

## Architektura i stan

- `debian13/ui/` — responsywny interfejs czatu, Work, terminala i statusu.
- `debian13/system/server.py` — uwierzytelniony HTTP API.
- `debian13/system/work_store.py` — trwała kolejka planów z SQLite
  (**nie wykonuje autonomicznie poleceń**).
- `debian13/system/original_agents.py` — diagnostyka czterech istniejących
  agentów, bez wymyślonych statusów.
- `debian13/system/alex_handoff.py` — bramka przekazania zadań wymagająca
  prawdziwego źródłowego endpointu, obsługiwanej funkcji i autoryzacji.
- `debian13/system/mcp_server.py` — tylko odczyt danych przez stdio MCP.
- `.github/workflows/debian13-validation.yml` — testy na Debian 13,
  test rzeczywistej aplikacji i budowy kontenera.

**Pełne uruchomienie samodzielnego systemu operacyjnego** (boot/ISO,
sterowniki, instalacja i cały cykl agenta) nadal wymaga odrębnych etapów
i weryfikacji sprzętowej; sukces CI aplikacji nie jest takim dowodem.
