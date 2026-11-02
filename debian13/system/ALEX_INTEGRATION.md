# Oryginalny Alex — połączenie z niezależnym Debian 13

## Co zostało znalezione

Oryginalny agent właściciela jest zdefiniowany w repozytorium
[`u6930438163-code/AI_Studio_BastillaOS/.github/agents/Alex.agent.md`](https://github.com/u6930438163-code/AI_Studio_BastillaOS/blob/main/.github/agents/Alex.agent.md)
jako agent GitHub Copilot. Zawiera zakres architektury, integracji API,
koordynacji pozostałych agentów i wymogi weryfikacji zmian.

Istniejący projekt udostępnia w `server.ts` endpoint
`GET /api/agent-tasks` do odczytu rejestru zadań. Rejestr został
zaimplementowany w `src/kernel/agentTasks.ts`: jego zadania mają statusy
`queued/running/completed/failed`. **Status `running` w tym rejestrze
nie jest dowodem uruchomienia modelu AI ani pracy agenta programistycznego**.
Znana implementacja rejestru wykonuje tylko ograniczone operacje lokalne,
np. weryfikację pliku lub utworzenie artefaktu. Nie potwierdza, że Alex
potrafi samodzielnie kończyć GitHub Issues albo programować Debian 13.

Nowy Debian 13 pozostaje niezależnym systemem. Skopiowano **instrukcje
agenta**, a nie stary kod systemu, jego serwer czy pliki danych.
Plik `.github/agents/Alex.agent.md` pozwala wybrać istniejącą
konfigurację Alexa w obsługiwanym środowisku GitHub Copilot; nie uruchamia
samodzielnie procesu.

## MCP — bezpieczny odczyt rzeczywistych danych

`debian13/system/mcp_server.py` udostępnia oprócz narzędzi systemowych:

- `alex_existing_status` — informacja, czy źródłowe API i rejestr zadań
  są dostępne; liczba zadań ze statusem `running`, bez twierdzenia, że
  działa model AI.
- `alex_existing_tasks` — najwyżej 50 rekordów oryginalnego Alexa;
  bez logów innych agentów, treści plików, tokenów i operacji zapisujących.

Do skonfigurowania przez operatora w środowisku uruchomieniowym:

```sh
export ALEX_EXISTING_API_URL=https://twoj-zweryfikowany-serwer.example/api
# Jeśli serwer tego wymaga, ustaw ALEX_EXISTING_API_TOKEN
# w menedżerze sekretów, a nie w repozytorium ani w wiadomości czatu.
export DEBIAN13_SYSTEM_API_URL=http://127.0.0.1:8080
# Wymagany również DEBIAN13_API_TOKEN API nowego systemu.
python3 debian13/system/mcp_server.py
```

Adres przykładowy **nie jest aktywnym adresem serwera**. Najpierw potwierdź
działanie istniejącego deploymentu, jego autoryzację i odpowiedzi API.
Nie używaj starego repozytorium do rozbudowy niezależnego Debiana.

Propozycja dla ChatGPT Pro: odczyt MCP przez zweryfikowany,
uwierzytelniony HTTPS serwer pośredniczący. Ten kod aktualnie implementuje
**tylko stdio**; połączenie z ChatGPT wymaga osobnej usługi MCP, uwierzytelniania,
uprawnień na koncie i ręcznej konfiguracji w ustawieniach ChatGPT.
Nie wystawiaj tego procesu w sieci bez zabezpieczeń.
Brak podłączonego klienta = brak potwierdzonej integracji.

## Przekazywanie zadania Alexowi

Pełne polecenie właściciela znajduje się w
[Issue #6](https://github.com/mmitek515-netizen/Debian_13/issues/6).
Jego treści nie wolno skracać, zmieniać ani traktować jako zaakceptowanych
płatności. Programistyczne wykonanie przez Alexa wymaga dostępnego
GitHub Copilot coding agent lub innego jawnie skonfigurowanego, osobnego
uruchomionego workera, autoryzacji do repozytorium i zielonych testów CI.
Istniejące GitHub workflow `debian13-agent-task.yml` tworzy plan,
a nie commity. Dopóki Alex nie utworzy własnego commita i PR,
wykonanie polecenia przez Alexa jest **niepotwierdzone**.

## Zakupy i akceptacja właściciela

Alex **może przygotowywać rekomendacje zakupowe**, lecz nie ma uprawnień
do samoistnych wydatków. Każdy wniosek musi zawierać:

1. Zweryfikowanego realnego dostawcę, produkt/usługę, link do oferty,
   walutę, kwotę jednorazową oraz przewidywaną kwotę cykliczną.
2. Uzasadnienie wpływu na rozwój nowego Debian 13 i darmowe alternatywy.
3. Jawny status `proposed`, `approved` albo `rejected`; domyślnie
   `proposed`. Brak odpowiedzi **nigdy** nie oznacza akceptacji.
4. Oddzielną, jednoznaczną zgodę właściciela dla **konkretnej kwoty
   i transakcji**. Przekroczenie ceny, zmiana sprzedawcy lub okresu
   rozliczeniowego wymaga nowej zgody.
5. Nawet po zgodzie zakup wykonać można dopiero z osobnym, uprawnionym
   narzędziem płatniczym i potwierdzonymi zabezpieczeniami. W przeciwnym
   razie Alex jedynie przekazuje link operatorowi.

Sformułowanie „zakup coś, jeśli poprawi” z Issue #6 **nie stanowi zgody**
na żaden wydatek. Nie można zakładać, że „firma pozaziemska” jest
istniejącym podmiotem handlowym. Dla obecnego MCP: wszystkie narzędzia
są tylko do odczytu; nie ma możliwości zatwierdzania ani kupowania.

## Testy

```sh
python3 -m unittest discover -s debian13/system/tests -v
docker compose -f debian13/system/compose.yaml config --quiet
```

Testy `test_alex_bridge.py` sprawdzają realne lokalne wywołanie HTTP
testowego serwera, kontrolę tokenu, brak przekierowań, filtrowanie rekordów
i brak narzędzi zapisujących. **Nie** są testem połączenia z uruchomionym
Alexem w chmurze.
