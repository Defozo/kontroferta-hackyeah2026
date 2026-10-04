# Wykorzystanie AI

KontrOferta · DEFOZO SOFTWARE HOUSE · Michał Kiełtyka

## Analiza ofert

Google Gemini `gemini-3.8-flash`, przez SDK `google-genai` i Interactions API, proponuje ustalenia z dokumentów, wymagania ze swobodnego opisu i treść pytań. Każdy wynik ma wersję promptu i schematu. Ranking ofert i obliczenia wykonuje silnik deterministyczny, a decyzję zatwierdza użytkownik.

Przed analizą użytkownik akceptuje przekazanie dokumentów do dostawcy modelu. Szczegóły przechowywania i kontroli dostępu opisuje [polityka danych](docs/PRIVACY.md). Polecenia zawarte w dokumentach są traktowane jako niezaufana treść. Aplikacja nie wykonuje kodu otrzymanego od modelu.

Cytaty podlegają sprawdzeniu obecności w źródle. Użytkownik weryfikuje interpretację, kwoty, jednostki i zakres usługi. Zapisane potwierdzenie dotyczy konkretnej rewizji sprawy; nowe materiały mogą wymagać ponownego przeglądu.

## Dane i materiały demonstracyjne

Oferty demonstracyjne i korpus ewaluacji są syntetyczne, przygotowane z pomocą AI. Zapisany przykład nie wykonuje nowej inferencji. Własna sesja demo importuje cztery fikcyjne PDF i uruchamia Gemini dopiero po zgodzie użytkownika. Suwak pokazuje symulację warunków, a przykładowe odpowiedzi dostawców w nagraniu są fikcyjne.

Film prezentacyjny pokazuje rzeczywisty interfejs. Lektor to syntetyczny głos Bella z ElevenLabs, model `eleven_multilingual_v2`, bez klonowania głosu autora. Cichy podkład tego filmu jest kompozycją syntetyzowaną lokalnie przez kod. Prezentacja zawiera edytowalne obiekty Artifact Tool i ekrany aplikacji; PDF tworzy ReportLab, a montaż wykorzystuje FFmpeg. Atrybucje znajdują się w [THIRD_PARTY.md](THIRD_PARTY.md), a [materiały konkursowe](https://kontroferta.34.116.152.48.sslip.io/materials/) są dostępne osobno.

## Powstanie projektu

AI wspierała analizę planu, implementację, przygotowanie materiałów syntetycznych, testy, diagnozę błędów i dokumentację. Autor odpowiada za zgłaszane rozwiązanie. Projekt korzystał z wcześniejszych materiałów planistycznych i katalogu usług.
