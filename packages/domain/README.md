# Silnik KontrOferty

Silnik odpowiada na trzy pytania organizatora: które oferty spełniają wymagania,
czy wybór utrzymuje się przy różnych odpowiedziach wykonawców i gdzie przebiega
próg zmiany wyniku. Do każdej zmiany może pokazać konkretny dopuszczalny scenariusz.
Kwoty, wspólne niewiadome, remisy i kompletność analizy są obliczane niezależnie
od modelu AI odczytującego dokumenty.

Publiczne wejście: `evaluate(dict | ComparisonModel) -> dict`. `demo_model()`
zwraca fikcyjny model ofert A/B/C używany w demonstratorze. Kod nie korzysta z sieci,
AI, bazy danych ani uprawnień. `models.py` stanowi ścisły kontrakt Pydantic.

## Kwoty i zakres

Kwoty modelu są w najmniejszych jednostkach waluty, dla PLN w groszach.
`money_to_minor("700.01") == 70001`. Parser używa Decimal, a przeliczenie
każdej pozycji po jawnym podatku i kursie używa ROUND_HALF_UP. Netto wymaga
stawki i źródła. Inna waluta wymaga pasującego kursu, daty i źródła. Kaucja,
raty płatności i koszt anulowania pozostają poza ceną usługi. Zwrotna kaucja
nie otrzymuje podatku usługi. Kwoty harmonogramu podlegają zadeklarowanej
podstawie netto/brutto oferty.

Zakres techniczny jest oddzielny od liczby uczestników i mikrofonów.
Jeśli wymagany czas lub zakres nie jest znany, wynik jest niepełny.
Momenty zawierają pełną datę i strefę. Czas lokalny w nieistniejącej lub
dwuznacznej godzinie zmiany czasu wymaga jawnego offsetu UTC.

## Operatory

- `literal`: `value`.
- `var`: `name`, odwołanie do jednej wspólnej zmiennej scenariusza.
- `sum`: `args`; `mul`: dokładnie dwa elementy `args`.
- `if`: `condition`, `then`, `otherwise`.
- `eq`, `ne`, `lt`, `lte`, `gt`, `gte`: `left`, `right`.
- `and`, `or`: `args`; `not`: `arg`.
- `date`: `value`, opcjonalnie `timezone`.

Inne operatory i dodatkowe pola operatora nie przechodzą walidacji.
Warunki logiczne nie zamieniają liczb w booleany. `True` nie jest równe `1`.
Nie ma eval, wykonywania kodu ani importów na podstawie treści modelu.

## Dziedziny i kompletność

Dziedziny `enum` są dokładnie enumerowane. Powtórzone wartości i różne
zapisy tej samej liczby są normalizowane. Ograniczenia modelu odrzucają
niedopuszczalne konfiguracje przed oceną ofert. Wszystkie oferty odczytują
tę samą wartość wspólnej zmiennej. Dziedzina wymaga źródła albo jawnego
założenia użytkownika oraz osobnego pola `complete`.

Jedna dziedzina `interval` wspiera koszty afiniczne. Solver tworzy punkty
remisu, granice budżetu, ograniczeń i reprezentantów przedziałów. `step`
oznacza siatkę dyskretną; jednostka `minor` domyślnie przyjmuje krok 1.
Dla ciągłych ilości i niecałkowitych przeliczeń uwzględniane są także wszystkie
granice zaokrąglenia. Same surowe progi przecięcia cen nie wystarczają,
ponieważ zaokrąglenie może tworzyć dodatkowe remisy.

Granice analityczne używają dokładnych ułamków wymiernych. Próg `1/3`
pozostaje `1/3`, a nie przybliżeniem Decimal, które mogłoby zgubić punkt
spełniający równość. Takie wartości w świadkach są serializowane jako
napisy `licznik/mianownik` i można je ponownie wczytać jako wartość enum.
Zwykłe dziesiętne ceny pozostają obsługiwane przez Decimal.

Więcej niż jeden przedział, nieliniowy koszt albo warunek kosztu zależny od
ciągłej zmiennej wymaga doprecyzowania lub osobnego zweryfikowanego solvera.
Nie uruchamia się wtedy pozornej kompletnej analizy na kilku próbkach.
Osiągnięcie limitu kombinacji lub liczby wymaganych podziałów zaokrąglenia
daje stan niepełny. `scenario_count` dla metody analitycznej oznacza liczbę
obliczonych reprezentantów, nie liczbę wszystkich rzeczywistych wartości.

Wynik niepełny ma puste `robust_feasible` i `common_winners` oraz
`unique_winner: null`. Obserwowane przecięcie jest osobno nazwane
`provisional_common_winners`. Pusty zbiór dopuszczalnych scenariuszy daje
`inconsistent`; brak wykonalnej oferty we wszystkich dopuszczalnych
scenariuszach daje `no_feasible_offer`.

## Pytania i świadkowie

Ranking dokładnych skończonych gałęzi implementuje D(T) z planu: wspólny
współzwycięzca oznacza 0, niezależnie od liczby różnych zestawów zwycięzców.
Ranking rozstrzyga remisy jawną trudnością i stabilnym ID. Jeśli pojedyncze
pytania nie zmniejszają D, analizowane są ich pary. Odpowiedź „nie wiem” nie
zmniejsza zbioru scenariuszy. Braki modelu mają pierwszeństwo i nie dostają
zmyślonego wyniku liczbowego wpływu.

Świadkowie zawsze pochodzą z dopuszczalnych, obliczonych konfiguracji.
`winner_change` wymaga niepustych, rozłącznych zbiorów zwycięzców;
`tie_change` i `feasibility_change` są oddzielnymi kategoriami. Gdy trzy
zestawy zwycięzców przecinają się parami, ale nie łącznie, wynik pokazuje
wieloscenariuszowy świadek `no_common_winner`. Pytanie ujawnia również
pozostałe zmienione niewiadome. Wyszukiwanie preferuje małą liczbę zmian,
ale `minimality_proven` pozostaje fałszywe.

## Weryfikacja i wydajność

`python -m pytest tests/test_engine.py tests/test_vectorized.py -q` sprawdza kwoty przykładowych ofert, podatki,
waluty, kaucje, wspólne zmienne, pakiety, puste zbiory, remisy, ranking,
XOR, trzy scenariusze, godziny przez północ, DST, błędne operatory i pełność.
Testy Hypothesis porównują skończony silnik z niezależną enumeracją oraz
sprawdzają dokładne wymierne granice równości.

Dla skończonych dziedzin o co najmniej 1000 kombinacji silnik może obliczyć
wszystkie konfiguracje na tablicach liczb całkowitych NumPy. Jest to pełna
enumeracja. Kontrole granic przed każdą operacją zapobiegają przepełnieniu,
a podatki, kursy i zaokrąglenia używają dokładnych ułamków. Nieobsługiwane
wyrażenia i wartości poza bezpiecznymi granicami wracają do obliczeń
Decimal/Fraction. Wyświetlane scenariusze i świadkowie są dodatkowo
przeliczane ścieżką referencyjną. Testy różnicowe, także Hypothesis,
porównują wyniki, świadków i ranking obu ścieżek. `accelerated=False`
wymusza ścieżkę referencyjną do diagnostyki.

Ranking uwzględnia wszystkie odpowiedzi. Lista gałęzi pytania pokazywana
w interfejsie ma limit `max_display_scenarios`; pola `branch_count` oraz
`branches_truncated_for_display` jawnie opisują ograniczenie prezentacji.

Powtarzalny pomiar: `python -m scripts.benchmark_engine --repetitions 20 --profile`.
Wynik opisuje środowisko, liczbę powtórzeń i obliczenia silnika, bez HTTP,
bazy danych i interfejsu. Własne pomiary należy wykonywać na modelach
odpowiadających przewidywanemu obciążeniu. Pomiar silnika nie ocenia
jakości ekstrakcji AI.
