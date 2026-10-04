# Prywatność i kontrola danych

Autorem rozwiązania zgłoszonego przez DEFOZO SOFTWARE HOUSE jest Michał Kiełtyka. Poniżej opisano przepływ danych i domyślne ustawienia aplikacji.

Oryginały, odczyt OCR, cytaty, ustalenia i decyzje trafiają do prywatnego lokalnego wolumenu aplikacji. API sprawdza członkostwo także przy pobraniu plików, raportu i zdarzeń joba. Właściciel udostępnia jednorazowe zaproszenie redaktorowi lub obserwatorowi. Obserwator nie może zmieniać danych. Decyzję zatwierdza właściciel.

Przed analizą użytkownik zatwierdza przekazanie treści do Google Gemini. Model otrzymuje tekst stron, identyfikatory i, dla OCR, obrazy stron. Nie ma narzędzi do sieci, kodu ani wiadomości. `store=false` wyłącza przechowywanie interakcji przez ten mechanizm API; nie obiecuje całkowitego braku retencji dostawcy. Wykorzystanie danych zależy od warunków konta Google. Przed realnym pilotem należy sprawdzić plan usługi i warunki przetwarzania.

Domyślnie sprawy wygasają po 90 dniach bez aktywności, a kopie demonstracyjne po 24 godzinach. Usunięcie sprawy obejmuje pliki, strony, OCR, cytaty, cache, migawki i pochodne wyniki. Pozostaje identyfikator usunięcia i czas, potrzebne do zastosowania usunięcia po odtworzeniu backupu. Backupy powinny wygasać w ciągu 7 dni. System nie może wycofać kopii pobranej przez odbiorcę.

Logi zawierają identyfikatory zadania, model, etapy, czas, typ błędu i zużycie. Nie należy logować dokumentów, pełnych odpowiedzi modelu, tokenów ani kluczy. Klucze pochodzą z psst, nie trafiają do `VITE_*` ani repozytorium.

Zapisany publiczny przykład zawiera wyłącznie fikcyjne oferty i jest tak oznaczony. Osobny tryb interaktywnego demo tworzy losową tożsamość gościa i jego sesję po stronie serwera. Nie wymaga danych osobowych ani hasła. Gość może analizować wyłącznie udostępnione fikcyjne PDF. Jego dokumenty, źródła i decyzje są oddzielone od pozostałych sesji. Usunięcie treści zachowuje nietreściowe rozliczenie kosztu, aby ponowne założenie sprawy nie omijało limitu.

Konfiguracja publicznego demo dopuszcza dwie sprawy na sesję. Sesje trwają 12 godzin, a sprawy wygasają po 24 godzinach od ostatniej zapisanej zmiany. Kopie bezpieczeństwa wygasają po 7 dniach. Dzienne limity modelu ograniczają nowe analizy, zachowując dostęp do już zapisanej pracy. Zamknięcie prywatnego okna lub wylogowanie usuwa możliwość powrotu do anonimowej sesji, więc raport należy pobrać wcześniej.

Lokalny provider OIDC służy do testów. Realny pilot na dokumentach klientów wymaga produkcyjnego providera i odrębnego sprawdzenia warunków przetwarzania. Publiczne demo z syntetycznymi plikami nie jest takim pilotem.
