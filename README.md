# KontrOferta

KontrOferta pomaga organizatorowi wydarzenia porównać pełny zakres ofert i ustalić, o co zapytać wykonawcę przed wyborem. Google Gemini odczytuje warunki wraz z cytatami. Silnik deterministyczny oblicza koszty, wykonalność, remisy i progi zmiany wyniku. Organizator sprawdza źródła i zatwierdza konkretną wersję decyzji.

**DEFOZO SOFTWARE HOUSE · Michał Kiełtyka**

[Otwórz demo](https://kontroferta.34.116.152.48.sslip.io/#/cases) · [Film, prezentacja i instrukcja](https://kontroferta.34.116.152.48.sslip.io/materials/) · [Pobierz kod](https://kontroferta.34.116.152.48.sslip.io/materials/KontrOferta-source.zip)

## Jak działa porównanie

1. Określ datę, strefę czasową, zakres wydarzenia, budżet i termin gotowości.
2. Dodaj oferty i dokumenty PDF, PNG, JPEG, TXT lub Markdown. Wskaż, którego dokumentu dotyczy aneks.
3. Po zatwierdzeniu przekazania treści do Gemini uruchom analizę.
4. Sprawdź cytaty przy ustaleniach. Popraw odczyt lub jednostkę i potwierdź kluczowe warunki.
5. Porównaj scenariusze oraz pytania do wykonawców. Skopiuj pytanie i zapisz otrzymaną odpowiedź; aplikacja nie wysyła korespondencji.
6. Zatwierdź decyzję i pobierz PDF lub JSON. Nowy aneks kieruje zależne ustalenia do ponownego sprawdzenia, a historia zachowuje poprzednie wersje.

Koszt, zakres i termin są widoczne w jednej sprawie. Analiza scenariuszy pokazuje, czy odpowiedź wykonawcy zmieni wybór, zanim organizator potwierdzi zamówienie. Przykład demonstracyjny: A kosztuje 4800 PLN, jeśli technik jest w cenie, albo 6000 PLN przy dopłacie 1200 PLN. B kosztuje 5500 PLN. Dopłata 700 PLN daje remis, a 701 PLN zmienia zwycięzcę na B. Oferta C nie spełnia terminu gotowości.

## Demo

Wybierz **Wypróbuj w osobnej sesji**, a następnie **Importuj dokumenty demonstracyjne**. Powstanie własna sprawa z czterema fikcyjnymi PDF. Analiza tej sprawy korzysta z Gemini. Oddzielny zapisany przykład działa bez nowej inferencji. Suwak scenariusza symuluje odpowiedź; odpowiedź wykonawcy zapisuje się osobno.

Publiczne demo przyjmuje wyłącznie udostępnione fikcyjne dokumenty. Pozwala na dwie sprawy w sesji, sesję przez 12 godzin i przechowywanie danych przez 24 godziny od ostatniej zmiany. Dzienne limity modelu wynoszą 5 USD dla demonstratora i 1 USD na konto gościa, według UTC. Po zakończeniu pracy pobierz raport, aby zachować go poza sesją.

## Konfiguracja

Własne uruchomienie wymaga klucza Google AI Studio i losowego sekretu sesji. Nazwy ustawień oraz wartości niesekretne zawiera [.env.example](.env.example). W poleceniach poniżej `psst` przekazuje sekrety jako zmienne środowiskowe. Nie zapisuj kluczy w repozytorium.

Ustaw `GOOGLE_AI_STUDIO_API_KEY` w swoim magazynie sekretów. Sekret sesji można wygenerować w PowerShell bez wypisywania go:

```powershell
$sessionSecret = [Convert]::ToBase64String([System.Security.Cryptography.RandomNumberGenerator]::GetBytes(48))
$sessionSecret | psst set KONTROFERTA_SESSION_SECRET --stdin
```

Analiza nowych dokumentów korzysta z płatnego API według warunków konta dostawcy. Konfiguracja zawiera limity na sprawę, konto i dzień oraz datowane stawki do szacowania kosztów tokenów. Przed własnym uruchomieniem ustaw limity odpowiednie dla swojego konta.

## Docker z lokalnym logowaniem testowym

Wymagania: Docker z Compose oraz skonfigurowane zmienne sekretów.

```powershell
psst GOOGLE_AI_STUDIO_API_KEY KONTROFERTA_SESSION_SECRET -- docker compose -p kontroferta-local -f compose.yaml -f compose.local.yaml up --build -d
```

Otwórz `http://localhost:8280`. Dostawca OIDC na `localhost:8281` tworzy syntetyczne tożsamości: wpisz własny identyfikator testowy. Oba porty są związane z loopback. Zestaw uruchamia API, worker, interfejs, Caddy i automatyczną obsługę kopii danych. W razie konfliktu ustaw `APP_PORT`, `LOCAL_OIDC_PORT` lub `LOCAL_DOCKER_SUBNET`.

Zatrzymanie zachowujące dane:

```powershell
psst GOOGLE_AI_STUDIO_API_KEY KONTROFERTA_SESSION_SECRET -- docker compose -p kontroferta-local -f compose.yaml -f compose.local.yaml down
```

## Uruchomienie lokalne na Windows

Wymagania: Node 24.13 lub nowszy, Python 3.12, uv, magazyn sekretów psst i Tesseract z językami `pol+eng`. Tesseract powinien być w PATH albo w `C:\Program Files\Tesseract-OCR`.

```powershell
uv sync --frozen --python 3.12
npm ci --prefix apps/web
npm ci --prefix apps/auth
.venv/Scripts/python.exe -m scripts.bootstrap
.venv/Scripts/python.exe -m playwright install chromium
npm run build --prefix apps/web
.venv/Scripts/python.exe -m alembic upgrade head
psst GOOGLE_AI_STUDIO_API_KEY KONTROFERTA_SESSION_SECRET -- .venv/Scripts/python.exe scripts/start_local.py
```

Otwórz `http://localhost:8080`. Launcher uruchamia API, worker, lokalny OIDC i maintenance. Ctrl+C zatrzymuje procesy potomne. Dane trafiają do `.data/`, a logi techniczne do `.runtime/`.

## Własny host i logowanie OIDC

Lokalny dostawca tożsamości służy do testów. Dla własnych użytkowników skonfiguruj zewnętrzny OIDC, callback `APP_BASE_URL/api/auth/callback`, zakres `openid profile email` i PKCE S256.

```powershell
$env:APP_BASE_URL = 'https://twoja-domena.example'
$env:SITE_ADDRESS = 'twoja-domena.example'
$env:OIDC_ISSUER = 'https://twoj-dostawca.example/realm'
$env:OIDC_CLIENT_ID = 'kontroferta'
psst GOOGLE_AI_STUDIO_API_KEY KONTROFERTA_SESSION_SECRET OIDC_CLIENT_SECRET -- docker compose -f compose.yaml -f compose.production.yaml up --build -d
```

Skieruj DNS domeny na host i udostępnij porty HTTP/HTTPS zgodnie z konfiguracją Compose. Caddy obsługuje TLS. API i worker korzystają ze wspólnego trwałego wolumenu SQLite na jednym hoście. Sesje są serwerowe; ciasteczka mają HttpOnly, SameSite i Secure pod HTTPS. Publiczny demonstrator korzysta z odrębnych sesji gościa, bez lokalnego OIDC.

## Utrzymanie i odzyskiwanie danych

Sprawdzaj `/api/health`, stan usług przez `docker compose ps` oraz logi API i workera przez `docker compose logs --tail 50 api worker`. Dostępność publicznego adresu zależy od utrzymania hosta, DNS i certyfikatu.

Maintenance sprawdza retencję co godzinę, tworzy spójną kopię dziennie i wygasza rozpoznane kopie po 7 dniach. Domyślna retencja spraw wynosi 90 dni bez zmian, a danych demo 24 godziny. Ustawienia: `CASE_RETENTION_DAYS`, `DEMO_RETENTION_HOURS`, `BACKUP_RETENTION_DAYS`, `BACKUP_PATH` i `MAINTENANCE_INTERVAL_SECONDS`.

Polecenia lokalnej obsługi danych:

```powershell
.venv/Scripts/python.exe -m scripts.backup create .runtime/backup
.venv/Scripts/python.exe -m scripts.backup restore .runtime/backup .runtime/restored --deletion-registry .data/kontroferta.db
.venv/Scripts/python.exe -m scripts.retention
.venv/Scripts/python.exe -m scripts.backup prune .data/backups
```

`retention` i `backup prune` pokazują plan; `--apply` wykonuje usuwanie. Restore sprawdza integralność, unieważnia sesje i odtwarza do osobnego katalogu. `--deletion-registry` musi wskazywać aktualną bazę, aby wcześniej usunięte dane nie wróciły z kopii. `docker compose down` zachowuje wolumeny; `down -v` je usuwa. Przed aktualizacją wykonaj kopię, a po niej sprawdź zdrowie usług oraz dostęp do zachowanej sprawy i jej źródeł.

## Architektura i testy

- `apps/web`: React/TypeScript, Vite, formularze, źródła PDF i porównanie ofert.
- `apps/api`: FastAPI, OIDC, uprawnienia, pliki i wersjonowane dane SQLAlchemy.
- `apps/worker`: trwałe zadania analizy z kontrolą rewizji.
- `packages/domain`: [silnik deterministyczny](packages/domain/README.md), kwoty w najmniejszych jednostkach waluty, Decimal i jawne zaokrąglenia.
- `packages/contracts/openapi.json`: kontrakt API.
- `fixtures/demo` i `eval/datasets`: autorskie, syntetyczne dokumenty.

```powershell
.venv/Scripts/python.exe -m pytest -q
npm test --prefix apps/web
npm run build --prefix apps/web
```

Weryfikacja eksportu z 4 października 2026: 184/184 testy backendu, 2/2 testy interfejsu i kompilacja TypeScript/Vite. Testy backendu korzystają z kontrolowanych odpowiedzi modelu i tożsamości, bez płatnej inferencji. [Instrukcja ewaluacji](eval/README.md) opisuje uruchamianie własnych pomiarów na dostarczonym korpusie.

AI może błędnie odczytać warunek lub jednostkę. Cytat potwierdza obecność fragmentu w dokumencie; interpretację i kluczowe warunki zatwierdza użytkownik. Wyniki na fikcyjnych danych opisują ten korpus, nie skuteczność dla dowolnych ofert.

[Prywatność](docs/PRIVACY.md) · [Wykorzystanie AI](AI_USAGE.md) · [Biblioteki i atrybucje](THIRD_PARTY.md)
