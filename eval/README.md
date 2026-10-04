# Ewaluacja KontrOferty

`datasets/manifest.json` opisuje 24 syntetyczne rodziny dokumentów AV, po dwie oferty w każdej. Dokumenty obejmują język polski i angielski, pozycje cenowe, przypisy, skany, negacje, brakujące warunki, ceny netto/brutto, kaucje, raty, terminy i aneksy. Manifest zawiera sumy kontrolne źródeł i adnotacji; runner sprawdza je przed pomiarem.

## Własny przebieg

Uruchom polecenia z katalogu głównego po instalacji według README. `--live` wykonuje rzeczywiste, odpłatne wywołania dostawcy. Ustaw klucz oraz aktualne stawki i limity konta przed uruchomieniem. Każdemu przebiegowi nadaj nowy katalog, aby zachować porównywalne dane.

```powershell
psst GOOGLE_AI_STUDIO_API_KEY -- .venv/Scripts/python.exe eval/run.py --split all --live --output results/new-regression --post-tuning-regression
psst GOOGLE_AI_STUDIO_API_KEY -- .venv/Scripts/python.exe eval/compare_methods.py --live --predictions results/new-regression --output results/new-method-comparison
psst GOOGLE_AI_STUDIO_API_KEY -- .venv/Scripts/python.exe eval/live_demo.py --output eval/results/new-pdf-demo
psst GOOGLE_AI_STUDIO_API_KEY -- .venv/Scripts/python.exe eval/performance.py --live --repetitions 5 --output eval/results/new-performance
```

Wyniki zawierają hashe wejść, wersje parsera, modelu, promptu i schematu, czasy, zużycie tokenów oraz błędy. Flaga `--retry-errors` w runnerze zachowuje udane predykcje i archiwizuje błędne próby przed ponowieniem. Wyniki własnych uruchomień pozostają lokalne w `eval/results`; raporty w `eval/reports`.

## Interpretacja

Korpus i oczekiwane odpowiedzi powstały z pomocą AI. Podział obejmuje 12 rodzin rozwojowych i 12 pierwotnie odłożonych do oceny. Ponieważ wyniki tego drugiego zbioru posłużyły później do poprawiania aplikacji, kolejne pomiary na nim są regresją po dostrajaniu. Materiały korzystają ze wspólnych szablonów i nie stanowią reprezentatywnej próby rynku.

`compare_methods.py` osobno porównuje stan wyniku i zbiór zwycięzców. Różnica klasyfikacji nie musi oznaczać innego wyboru wykonawcy. Odtworzenie autorskich adnotacji przez silnik mierzy obliczenia; nie jest pomiarem pracy człowieka.

`performance.py` mierzy parsowanie, AI, walidację źródeł i porównanie. Pomiar nie obejmuje uploadu HTTP, kolejki, zapisu, logowania ani renderowania przeglądarki. Przy pięciu powtórzeniach p95 metodą najbliższej rangi jest maksimum obserwacji. Koszt tokenów według skonfigurowanych stawek nie obejmuje hostingu, przechowywania ani OCR.

Obecność cytatu nie potwierdza prawdziwości warunku ani poprawności jego interpretacji. Przy ocenie własnych dokumentów uwzględnij niezależny przegląd adnotacji i rzeczywiste zadania użytkowników.
