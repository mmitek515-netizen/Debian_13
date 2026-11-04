# Debian 13 — automatyczne Issues i Pull Requesty z AI

**Repozytorium:** `mmitek515-netizen/Debian_13`.
Ten mechanizm nie zmienia aktualnego silnika odpowiedzi, uruchomionej
Ollamy, MCP ani istniejących `.github/workflows/debian13-agent-task.yml`
i `debian13-codex-issue.yml`. Jest dodatkiem dla **prawdziwych zmian kodu**.

## Uwierzytelnienie na GitHubie

Workflow `.github/workflows/debian13-original-agents.yml` używa
`GITHUB_TOKEN` dostarczonego automatycznie przez GitHub Actions.
W kroku analizowania Issue ma tylko odczyt; **osobne** zadanie publikacji
dostaje prawo tworzenia Issues, gałęzi i PR. Model **nie otrzymuje**
GitHub tokena ani nie wykonuje poleceń powłoki.

Repozytorium → Settings → Actions → General → Workflow permissions:
włącz możliwość tworzenia i zatwierdzania Pull Requestów przez GitHub
Actions, jeśli jest dostępna i chcesz, aby workflow publikował PR.
Nie ma automatycznego scalenia ani zatwierdzenia PR.

## Podłącz działający silnik odpowiedzi — nie wymuszamy Ollamy/OpenAI

Przed pierwszym uruchomieniem utwórz prywatne GitHub Actions secrets:

- `DEBIAN13_MODEL_CHAT_URL` — **osiągalny z GitHub-hosted runnera
  HTTPS** endpoint zgodny z OpenAI `/v1/chat/completions`, należący do
  Twojej usługi; nie link do panelu GitHub/AI Studio. Endpoint musi być
  chroniony autoryzacją.
- `DEBIAN13_MODEL_API_KEY` — token uwierzytelniający do **tej usługi**,
  nie musi być kluczem OpenAI. Nigdy nie publikuj go w plikach i Issues.

Repository variable `DEBIAN13_MODEL_NAME`: dokładna nazwa modelu
obsługiwanego przez powyższy endpoint. Możesz używać istniejącego
darmowego/zewnętrznego silnika; o opłatach decyduje wybrany backend,
a nie format API. **Nie podawaj klucza OpenAI o zerowym saldzie.**

GitHub-hosted runner nie ma dostępu do Ollamy uruchomionej na
`127.0.0.1` Twojego komputera/serwera. Aby użyć lokalnego modelu,
potrzebujesz własnego bezpiecznego runnera z dostępem do hosta
albo prywatnej, uwierzytelnionej bramy HTTPS. **Nie publikuj
niezabezpieczonego portu Ollamy 11434 w internecie.**

## Jak uruchomić po scaleniu PR

Otwórz **Actions → Debian 13 — AI Issues and draft PRs → Run workflow**.

**Nowe Issue:** wybierz `mode=issue`, jednego z
`alex`, `aria`, `astyria`, `aurelius`, a w `goal`
wpisz konkretny cel. Model przygotuje treść, a GitHub Actions
utworzy Issue z prefiksem `[AI proposal][agent]`.
To **propozycja AI**, a nie wykonane zadanie.

**Issue → PR:** wybierz `mode=patch`, numer istniejącego Issue
oraz profil agenta. Model zwróci maksymalnie trzy kompletne
zmienione pliki w dopuszczonych katalogach `debian13/`.
Odizolowane zadanie uruchomi testy Python i Node. Jeśli przejdą
i istnieje faktyczna różnica kodu, GitHub Actions utworzy nową
gałąź i **Draft Pull Request**. Bez zakupów, bez roota, bez
automatycznego merge.

**Automatyczny start z Issue:** administrator repo może utworzyć
etykiety `ai:run`, `agent:alex`, `agent:aria`, `agent:astyria`,
`agent:aurelius`. Użytkownik tworzy Issue i dodaje etykietę jednego
agenta (lub tytuł zaczynający się od `[Alex]` itd.). Samo dodanie
`ai:run` uruchomi workflow, **tylko gdy autorem Issue jest
`mmitek515-netizen`**. Etykieta nie uruchomi zadań dla Issue
obcych użytkowników ani nie zmusi modelu do odpowiedzi.

## Co jest oryginalnym agentem?

Workflow kieruje zadanie do **profilu** Alex/Aria/Astyria/Aurelius
i podłączonego prawdziwego modelu. **Nie podszywa się** pod oddzielne
oryginalne procesy z AI Studio: aby właśnie one były wykonawcami,
`DEBIAN13_MODEL_CHAT_URL` musi wskazywać ich rzeczywistą, sprawdzoną
bramę wykonawczą obsługującą odpowiedni profil. Sam prefiks Issue
czy nazwa commita nie dowodzą oryginalnego wykonawcy.

Przed uznaniem agenta za aktywnego trzeba wykonać produkcyjny test
z autoryzowanym modelem i potwierdzić w logach: realną odpowiedź,
zawartość kodu, przejście CI i nowy PR. Kod i test mockowanego
modelu **nie potwierdzają pracy w chmurze ani 24/7**.

## Bezpieczeństwo

- Żadne automatyczne merge, zakupy, hasła czy zmiany workflow przez model.
- Zmiany ograniczone do 3 tekstowych plików w `debian13/`,
  maksymalnie 42 kB na przebieg, bez dowolnych skryptów.
- Testy wykonują się **bez tokenu zapisu**; publikacja dopiero po sukcesie.
- Wszystkie PR-y są `draft` i wymagają przeglądu człowieka.
- GitHub Actions może wymagać dodatkowego ustawienia pozwalającego
  `GITHUB_TOKEN` tworzyć PR.
- Jeśli nie ma działającego dostawcy modeli, workflow zgłosi
  brak konfiguracji zamiast symulować AI.
