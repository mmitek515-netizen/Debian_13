# Cztery oryginalne AI + lokalna Ollama (integracja bez automatycznych płatności)

## Status

Ten moduł jest proponowaną integracją na gałęzi PR #14, współpracującą
z **PR #19** w `u6930438163-code/AI_Studio_BastillaOS`.
Dopóki oba PR nie zostaną świadomie wdrożone oraz nie zostanie wykonany
test z prawdziwym serwerem, **nie ma potwierdzonej pracy agentów**.

**Nie wymaga OpenAI API ani klucza OpenAI**. Dedykowany worker źródłowy
wymusza `providers: ['ollama']` niezależnie od konfiguracji głównego
czatu Bastilla. Nie uruchamia płatnego Gemini, xAI ani OpenAI.
Ollama wymaga hosta (komputer, VPS lub serwer) i odpowiedniego modelu.
Płatny fallback OpenAI jest wyłączony i niezaimplementowany. API OpenAI
ma osobne rozliczenie od subskrypcji ChatGPT.

## Źródłowy serwer (AI Studio BastillaOS)

W bezpiecznych, prywatnych zmiennych środowiskowych (NIE w repozytorium):

- `DEBIAN13_ORIGINAL_WORKERS_ENABLED=1` — opt-in dopiero po uruchomieniu Ollamy.
- `DEBIAN13_ORIGINAL_AGENTS_TOKEN` — nowy, losowy token (min. 32 znaki).
- `LLM_PROVIDERS=ollama` — zalecane dla źródłowego serwera, zwłaszcza
  gdy nie chcesz opłacać modeli chmurowych w pozostałych modułach.
- `OLLAMA_MODEL` — niewielki, rzeczywiście pobrany model (dobierz do RAM).
- Lokalna Ollama powinna być osiągalna wyłącznie w zaufanej sieci hosta.

Nie używaj w tym celu niebezpiecznego `/api/triad/message` ze starszej
aplikacji: mógł wykonywać polecenia. Integracja obsługuje **tylko**
uwierzytelnioną kolejkę `/api/agent-tasks/*` (review bez shella).

## Serwer Debian 13

W sekretnych zmiennych środowiskowych po stronie API Debiana 13:

- `ALEX_EXISTING_API_URL=https://twoj-prywatny-serwer.example/api`
  lub `http://127.0.0.1:3000/api` przy działaniu obu usług na tym samym hoście.
- `ORIGINAL_AGENTS_API_TOKEN` — **ta sama wartość**, co
  `DEBIAN13_ORIGINAL_AGENTS_TOKEN` w źródłowym serwerze. Nigdy nie
  umieszczaj jej w wiadomości ChatGPT, GitHub Issue ani kodzie.
- `ORIGINAL_AGENTS_ALLOW_REVIEW=1` — jawne uruchomienie przekazywania
  zadań przez operatora po weryfikacji konfiguracji.

Następnie uruchom prywatną konsolę Debian 13 i otwórz zakładkę Work.
Utwórz zadanie z wybranym agentem, kliknij „Wyślij do AI”, a potem
„Sprawdź oryginalne AI”. API sprawdza rzeczywiste zdolności serwera:
`debian13_review_task_v1`, cztery nazwy, identyczne docelowe repo i
brak domyślnych ról lub custom instructions.

Stany `queued` i `running` **nie potwierdzają odpowiedzi modelu**.
Dopiero `completed` z nazwą providera, modelu i zapisaną treścią
dokumentuje wygenerowaną analizę. **Analiza nie jest commitem, PR,
rootem, zakupem ani ukończeniem projektu.** Do prawdziwego programowania
przez AI potrzebny będzie oddzielny kontrolowany worker GitHub z testami.

## Kontrole bezpieczeństwa

- Wystawianie publicznego HTTP i automatyczne przekazywanie kluczy zabronione.
- Zdalny serwer wyłącznie HTTPS z autoryzacją lub lokalna pętla loopback.
- Brak autoryzacji lub niezgodność celu repo => zatrzymanie przekazania.
- Brak automatycznego scalenia, zakupów, shella i opłat za fallback.
- Oryginalna czwórka startuje bez przydzielonych ról i promptów.
