# Debian 13 — niezależny system operacyjny

Nowe, niezależne repozytorium rozwoju systemu opartego na Debianie 13 (Trixie). Nie kopiować starej aplikacji Bastilla OS 2 ani jej architektury.

## Zakres planowanej migracji
- Wyodrębnić wyłącznie kod i dokumentację nowego systemu z `mmitek515-netizen/Bastilla_OS_2/debian13/`.
- Przejrzeć gałęzie `setup/debian13-agent-environment`, `copilot/debian-13-gui-ux-improvements` i `copilot/misja-aurelius-debian-13`; przenosić tylko sprawdzone zmiany.
- Przenieść i dostosować niezależne środowisko Codespaces, testy CI i konfigurację Debian 13.
- Zaplanować interfejs responsywny, dwukierunkowy czat z agentami, rozwijane menu, interaktywne skrypty, diagnostykę, MCP, Codex i GPT Actions.
- Uruchomić testy, weryfikację bezpieczeństwa i rzeczywisty boot przed ogłoszeniem gotowości.

## Stan
Repozytorium docelowe zostało przygotowane; pełna migracja i scalanie gałęzi nie są jeszcze potwierdzone. Konfiguracja środowiska nie jest działającym systemem ani obrazem ISO.

Źródło początkowych ustaleń: https://github.com/mmitek515-netizen/Bastilla_OS_2/blob/main/debian13/README.md
