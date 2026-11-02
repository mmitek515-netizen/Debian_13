# Debian 13 Work — trwała kolejka planów, bez pozornego wykonywania zadań

Ten moduł zapisuje zlecenia operatora w bazie SQLite na **prywatnym wolumenie**
`/workspace/.debian13-work.sqlite3`. Przy `docker compose up` wolumen
`debian13-workspace` zachowuje dane po ponownym uruchomieniu kontenera.
Nie wykonuj `docker compose down -v` dla środowiska produkcyjnego,
ponieważ usuwa wolumen i przechowywane zadania.

## Bezpieczeństwo i ograniczenia

**Zadanie w Work NIE uruchamia agenta AI.** Zadania są tylko propozycjami
wymagającymi przeglądu. Utrzymywane pola:
`status=queued` lub `cancelled`,
`execution=not_started`, `requires_approval=1`.
Nie ma obecnie etapów `running` ani `completed` dla prac agentów,
ponieważ w tym komponencie nie zainstalowano ich rzeczywistego wykonawcy.

Nie ma automatycznych zakupów, płatności, wywołań powłoki, tworzenia
GitHub Issues ani wysyłania poleceń do Copilota. Wniosek zakupowy
z Issue #6 wymaga oddzielnej zgody na konkretnego sprzedawcę i kwotę
przed jakąkolwiek transakcją.

API wymaga tokenu operatora `DEBIAN13_API_TOKEN`.
Proxy przeglądarki trzyma sekret po stronie serwera, a nie w JavaScript.
Baza SQLite ma uprawnienia `0600`; serwer działa bez root w obrazie
Docker. Nie wystawiaj portu API ani UI publicznie bez uwierzytelnienia,
TLS i oceny bezpieczeństwa.

## Rzeczywiste endpointy API

- `GET /api/v1/tasks` — lista do 100 najnowszych zadań.
- `POST /api/v1/tasks` — rejestracja zadania, **HTTP 201**, pole
  `executionStarted=false`.
- `GET /api/v1/tasks/{uuid}` — stan konkretnego zadania.
- `POST /api/v1/tasks/{uuid}/cancel` — idempotentne anulowanie.
- `GET /api/v1/events` — do 100 ostatnich zdarzeń z trwałej bazy.
- Narzędzie MCP `debian13_work_tasks` — wyłącznie odczyt zadań,
  bez operacji zapisu ani wykonywania.

Tworzenie zadania:

```json
{
  "agent": "alex",
  "kind": "development",
  "title": "Integracja nowego Debian 13",
  "description": "Przygotuj architekturę, testy i przegląd zmian."
}
```

Dozwolone profile: `alex`, `aria`, `astyria`, `aurelius`.
Dozwolone rodzaje: `development`, `bugfix`, `audit`, `research`.
Tytuł ma od 1 do 120 znaków, opis od 1 do 2000 znaków.
Inne pola są odrzucane. Dziennik nie jest strumieniem na żywo.
Limit magazynu wynosi 2000 rekordów, a historia 5000 zdarzeń.
Baza nie jest szyfrowana — przechowuj ją tylko w zaufanym środowisku.

## Testy

```sh
python3 -m unittest discover -s debian13/system/tests -v
node --test debian13/ui/dev_server.test.mjs
docker compose -f debian13/system/compose.yaml config --quiet
```

Testy sprawdzają rzeczywiste HTTP, autoryzację, walidację danych, zapis,
odczyt po odtworzeniu obiektu `WorkStore`, usuwanie z kolejki bez
powielania zdarzeń, izolację proxy i brak uruchomienia workerów.

## Następny etap

Do prawdziwego wykonania programistycznego należy osobno podłączyć
autoryzowany, izolowany proces agenta, który pobierze zlecenie z kolejki
i przygotuje Pull Request z zielonym CI. Należy rozdzielić akceptację
planu od akceptacji operacji mutujących i od ewentualnych zakupów.
Nie utożsamiaj konfiguracji profilu Alex z działającym procesem AI.
