# Alex — bezpieczne przekazywanie zadań (protokół handoff v1)

Moduł `alex_handoff.py` **nie tworzy nowego Alexa**. Przewiduje komunikację
z rzeczywistym, oryginalnym agentem powiązanym z
`u6930438163-code/AI_Studio_BastillaOS`, wykorzystując HTTPS i osobny
token operatora. Wskazanie profilu `Alex` albo rekord
`status=running` w starym rejestrze NIE dowodzi działania modelu AI.

## Stan źródłowego systemu

W źródłowym projekcie znaleziono endpointy
`GET /api/agent-tasks` i `POST /api/agent-tasks/run`.
Istniejący `/agent-tasks/run` jest mechanizmem do ograniczonych
zadań demonstracyjnych / operacji lokalnych i **nie potwierdza**
obsługi programistycznego cyklu Issue → zmiana kodu → testy → PR.
Dlatego ten adapter nigdy nie używa tego endpointu, by udawać
wykonanie polecenia właściciela.

**Wymagany kontrakt po stronie uruchomionego oryginalnego Alexa**
(nieobecny lub niepotwierdzony):

`GET /api/agent-tasks/capabilities` zwraca:

```json
{
  "sourceRepository": "u6930438163-code/AI_Studio_BastillaOS",
  "agent": "Alex",
  "protocolVersion": 1,
  "capabilities": ["debian13_issue_to_pr"]
}
```

`POST /api/agent-tasks/submit` przyjmuje jedno zlecenie z
`mode=pull_request_proposal`, nagłówkiem `Idempotency-Key` = UUID zadania,
`purchaseAuthorized=false` i `autoMerge=false`, a następnie
musi odpowiedzieć:

```json
{
  "accepted": true,
  "agent": "Alex",
  "capability": "debian13_issue_to_pr",
  "taskId": "oryginalne-id-zadania"
}
```

Potwierdzenie `accepted=true` oznacza wyłącznie **przyjęcie przez
zdalne API**, a nie wykonanie przez model ani istnienie PR. Nie można
uznawać zewnętrznego serwera ani workera za działający na podstawie
samych testów z użyciem mocka.

## Aktywacja (dopiero po potwierdzeniu serwera Alexa)

Przy włączonym protokole po stronie *istniejącego* Alexa ustaw w
chronionym środowisku operatora:

```sh
export ALEX_EXISTING_API_URL=https://ZWERYFIKOWANY-HOST.example/api
export ALEX_EXISTING_API_TOKEN='SEKRET_Z_MENEDZERA_SEKRETOW'
export ALEX_ALLOW_TASK_DISPATCH=1
```

Podany adres jest **przykładem, nie działającym serwerem**.
Nigdy nie zapisuj tokenu w Issues, pliku README, kodzie JavaScript ani
commicie. Compose domyślnie ustawia `ALEX_ALLOW_TASK_DISPATCH=0`
i nie wysyła zadań.

Po uruchomieniu Debian 13 i konfiguracji proxy UI:

- `GET /api/v1/alex/capabilities` — pokazuje, czy oryginalne API
  zadeklarowało odpowiednią funkcjonalność.
- `POST /api/v1/tasks/{uuid}/dispatch` — tylko zadanie `agent=alex`,
  `status=queued`, po wyraźnym kliknięciu i potwierdzeniu operatora w GUI.
- `GET /api/v1/tasks/{uuid}` — zwraca zapisany identyfikator zadania
  zdalnego i `agentExecutionVerified=false`.

Nie wykonuje zakupów, nie daje prawa do płatności, nie uruchamia
konsoli ani automatycznego merge. Zlecenie pozostaje pod kontrolą
operatora. Jeśli capabilities brakuje, **wysyłanie jest zablokowane**
i prawdziwy Alex nie dostaje żadnego polecenia.

W obecnym GitHub Issue #6 znajduje się dokładna treść żądania
właściciela. Nie używaj go jako zgody na zakup.

## Test bez limitu Alexa (tylko test umowy protokołu)

```sh
python3 -m unittest discover -s debian13/system/tests -p 'test_alex_handoff.py' -v
python3 -m unittest discover -s debian13/system/tests -v
node --test debian13/ui/dev_server.test.mjs
```

Test tworzy na loopback **lokalny serwer testowy** imitujący wyłącznie
protokół, sprawdza autoryzację, idempotentne przekazanie, odrzucenie
starego API bez wymaganej funkcji, możliwość operatora wyłączenia
wysyłania, brak zgody na zakupy i brak fałszywego statusu wykonania.

**Test nie wykorzystuje limitu oryginalnego Alexa i nie wywołuje go.**
Do rzeczywistego testu potrzebny będzie działający, prawidłowo
skonfigurowany serwer z tym kontraktem oraz ręczna zgoda operatora na
wysłanie konkretnego zadania.
