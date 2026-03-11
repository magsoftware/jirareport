# PRD - Jira Worklog Reporting PoC

## 1. Cel dokumentu

Ten dokument opisuje ustalenia dla PoC raportowania bukowan z Jiry.

Celem systemu jest codzienne generowanie raportow worklogow:
- per ticket,
- per osoba,
- per miesiac,
- z mozliwoscia publikacji do Google Sheets,
- z archiwizacja surowych danych raportowych poza samym arkuszem.

Dokument obejmuje:
- zakres funkcjonalny,
- model danych,
- rekomendowana architekture,
- sposob skladowania danych,
- zalozenia integracji z Google,
- standardy implementacyjne,
- plan wdrozenia.

## 2. Kontekst biznesowy

Podstawowa potrzeba biznesowa:
- uzyskanie informacji o bukowaniach per ticket per osoba w zadanym miesiacu.

Domyslne zachowanie:
- raport generowany jest dla aktualnego miesiaca.

Wymaganie dodatkowe:
- musi istniec mozliwosc wygenerowania raportu dla wskazanego miesiaca z przeszlosci.

Istotna cecha danych:
- pracownicy moga bukowac czas wstecz,
- czesto zdarza sie bukowanie w marcu za wczesniejsze dni marca,
- rzadziej, ale nadal mozliwe, jest bukowanie w marcu za dni z lutego.

Wniosek:
- nie nalezy budowac raportu miesiecznego jako prostego dopisywania "nowego dnia",
- konieczna jest codzienna rekalkulacja z odpowiednio szerokiego okna danych.

## 3. Zakres funkcjonalny

System ma dostarczac:

1. Raport miesieczny worklogow z Jiry.
2. Raport dzienny typu raw snapshot do archiwizacji.
3. Eksport wyjsciowy w formacie JSON.
4. Logowanie z uzyciem `loguru`.
5. Strukture projektu gotowa do rozwoju i uruchamiania w GitHub Actions.
6. Testy automatyczne w katalogu `tests`.
7. Coverage i quality gates w CI.

Raport ma zawierac co najmniej:
- numer ticketu,
- tytul ticketu,
- informacje o bukowaniach,
- kto bukowal,
- data i godzina rozpoczecia,
- data i godzina zakonczenia,
- czas trwania.

## 4. Dane wejsciowe z Jiry

Zrodlem prawdy sa worklogi z Jiry.

Zakladany model pojedynczego wpisu:
- `started` z Jiry jako czas rozpoczecia,
- `timeSpentSeconds` jako czas trwania,
- `ended_at` wyliczany jako `started_at + timeSpentSeconds`.

Wszystkie operacje na datach i miesiacach musza byc wykonywane w jawnie ustawionej strefie czasowej.

Rekomendacja:
- domyslna strefa czasowa `Europe/Warsaw`.

Powod:
- runner GitHub Actions dziala w UTC,
- granice dni i miesiecy bez jawnej strefy czasowej beda podatne na bledy.

## 5. Model raportowania

### 5.1. Raport raw

Rekomendowany kanoniczny format raw:
- jeden rekord = jeden worklog.

Przykladowe pola:
- `worklog_id`
- `issue_key`
- `summary`
- `author`
- `author_account_id`
- `started_at`
- `ended_at`
- `duration_seconds`
- `duration_hours`
- `snapshot_date`
- `month`

Ten model jest preferowany nad modelem:
- jeden ticket z osadzona lista worklogow jako jedyne zrodlo prawdy.

Powod:
- model rekordowy lepiej nadaje sie do agregacji,
- ulatwia publikacje do Google Sheets,
- ulatwia testowanie i pozniejsza rozbudowe.

### 5.2. Raport miesieczny

Raport miesieczny jest widokiem pochodnym budowanym z danych raw.

Moze byc udostepniany w dwoch odmianach:
- `raw_worklogs` jako pelna lista rekordow,
- `monthly_summary` jako agregacja per miesiac / ticket / osoba.

### 5.3. Raport dzienny

Raport dzienny nie oznacza "tylko worklogi z jednego dnia".

Raport dzienny oznacza:
- snapshot danych pobrany danego dnia,
- zapisany jako stan systemu "as of today".

## 6. Strategia pobierania danych

### 6.1. Czego nie robimy

Nie rekomenduje sie:
- pobierania tylko biezacego dnia,
- prostego dopisywania nowych danych do miesiaca bez rekalkulacji,
- budowy miesiecznego raportu tylko na podstawie "dzisiejszych zmian".

Powod:
- worklogi moga byc dopisywane i poprawiane wstecz,
- raport miesieczny moze sie rozjechac z rzeczywistym stanem Jiry.

### 6.2. Rekomendowany model

Codzienny job powinien pobierac dane z ruchomego okna rekalkulacji.

Rekomendowane warianty:
- wariant prosty: od pierwszego dnia poprzedniego miesiaca do teraz,
- wariant bardziej odporny: ostatnie 45-60 dni.

Rekomendacja na start:
- od pierwszego dnia poprzedniego miesiaca do teraz.

Przyklad:
- jesli job uruchamia sie 11 marca 2026, pobiera dane od `2026-02-01` do `2026-03-11`.

To pozwala:
- uwzglednic korekty z biezacego miesiaca,
- uwzglednic opoznione bukowania do poprzedniego miesiaca,
- uproscic logike codziennej aktualizacji.

## 7. Proces dzienny

Rekomendowany dzienny workflow:

1. Pobranie danych z Jiry z ruchomego okna rekalkulacji.
2. Zapis raw snapshot do storage.
3. Rekalkulacja raportow miesiecznych dla miesiecy dotknietych zakresem danych.
4. Publikacja danych do Google Sheets.
5. Logowanie metryk kontrolnych.

Metryki kontrolne:
- liczba issue,
- liczba worklogow,
- laczna liczba godzin,
- zakres dat,
- liczba rekordow zapisanych do storage,
- liczba rekordow opublikowanych do Sheets.

## 8. Skladowanie danych

### 8.1. Zasada ogolna

Google Sheet nie powinien byc glownym magazynem danych.

Rekomendacja:
- raw data przechowywac poza Sheet,
- Google Sheet traktowac jako warstwe prezentacyjna i robocza.

### 8.2. Rekomendacja storage

Priorytet rekomendacji:

1. Google Cloud Storage jako docelowy storage raw data.
2. Google Drive Shared Drive jako prostszy storage dla PoC.
3. GitHub Actions artifacts tylko pomocniczo, nie jako archiwum docelowe.

### 8.3. Rekomendacja praktyczna

Na start dla PoC:
- mozna uzyc `Google Drive Shared Drive`.

Docelowo:
- preferowany jest `Google Cloud Storage`.

Uzasadnienie:
- GCS jest lepszy jako magazyn maszynowy,
- lepiej obsluguje retencje, wersjonowanie i automatyzacje,
- Drive jest wygodniejszy do recznego podgladu, ale slabszy jako canonical storage.

### 8.4. Struktura katalogow storage

Rekomendowana struktura:

- `raw/daily/YYYY/MM/YYYY-MM-DD.json`
- `derived/monthly/YYYY/YYYY-MM.json`

Przyklad:

- `raw/daily/2026/03/2026-03-11.json`
- `derived/monthly/2026/2026-03.json`

W przypadku Drive lub GCS nalezy zachowac analogiczna strukture logiczna.

## 9. Format danych

### 9.1. Format startowy

Na start rekomendowany jest:
- `JSON` dla snapshotow raw,
- `JSON` dla raportow miesiecznych,
- spłaszczone rekordy dla publikacji do Sheets.

### 9.2. Format docelowy przy wzroscie wolumenu

Jesli wolumen danych wzrosnie, raw data mozna przeniesc do:
- `JSONL`.

Powody:
- latwiejsze strumieniowanie,
- lepsza obsluga duzej liczby rekordow,
- wygodniejsze ETL.

Na etapie PoC nie rekomenduje sie:
- `Parquet`,
- ciezkich rozwiazan analitycznych.

## 10. Model Google Sheets

Nie rekomenduje sie:
- jednego arkusza per dzien.

Powody:
- slaba uzytecznosc,
- duza liczba zakladek,
- gorsze filtrowanie i agregacje,
- trudniejsze utrzymanie.

Rekomendowany uklad skoroszytu:

1. `raw_worklogs`
- jeden wiersz = jeden worklog
- dane szczegolowe do filtrowania i audytu

2. `monthly_summary`
- agregaty per miesiac / ticket / osoba

3. `daily_summary`
- opcjonalne agregaty per dzien

Arkusz ma byc warstwa raportowa, nie glownym magazynem danych.

## 11. Integracja z Google

### 11.1. Google Sheets

Google Sheets sluzy do:
- przegladania danych,
- filtrowania,
- prostych agregacji,
- pracy operacyjnej.

### 11.2. Google Drive / GCS

Storage dla plikow JSON sluzy do:
- archiwizacji raw snapshotow,
- przechowywania raportow pochodnych,
- utrzymania kanonicznego zrodla danych poza arkuszem.

### 11.3. Autoryzacja

Docelowo rekomendowana jest autoryzacja:
- GitHub Actions OIDC + Google Workload Identity Federation.

Nie rekomenduje sie jako rozwiazania docelowego:
- dlugowiecznych kluczy `service-account.json` trzymanych jako sekrety.

## 12. Architektura aplikacji

Projekt powinien zostac uporzadkowany w lekka architekture warstwowa.

Rekomendowana struktura:

- `src/jirareport/domain/`
- `src/jirareport/application/`
- `src/jirareport/infrastructure/`
- `src/jirareport/interfaces/cli/`
- `tests/`

### 12.1. Warstwa domain

Zawiera:
- modele domenowe,
- typy,
- logike zwiazana z datami i okresami,
- obiekty raportowe.

Przykladowe modele:
- `Issue`
- `WorklogEntry`
- `MonthRange`
- `MonthlyWorklogReport`
- `DailySnapshot`

### 12.2. Warstwa application

Zawiera use case'y:
- `GenerateMonthlyReport`
- `GenerateDailySnapshot`
- `PublishToSheets`

### 12.3. Warstwa infrastructure

Zawiera adaptery do:
- Jira API,
- Google Sheets,
- Google Drive albo GCS,
- storage lokalnego,
- logowania.

### 12.4. Warstwa interfaces

Zawiera:
- CLI,
- parser argumentow,
- komendy wywolywane lokalnie i z GitHub Actions.

## 13. Wzorce projektowe

Nalezy stosowac sprawdzone i lekkie wzorce projektowe.

Rekomendowane wzorce:
- Adapter dla integracji z Jira i Google,
- Factory dla budowy klientow i konfiguracji,
- Service / Use Case dla logiki aplikacyjnej,
- Serializer dla wyjscia JSON.

Nie rekomenduje sie:
- nadmiernie rozbudowanego DDD,
- CQRS,
- zbyt ciezkiej architektury niewspolmiernej do skali PoC.

## 14. Standardy implementacyjne

Wymagania implementacyjne:

- stosowac Google Python Style Guide,
- stosowac konsekwentne typowanie,
- utrzymywac funkcje w granicach okolo 20-30 linii,
- utrzymywac jasny podzial odpowiedzialnosci,
- unikac "god functions",
- pisac kod gotowy do uruchamiania w GitHub Actions.

Rekomendacje techniczne:
- `dataclass` dla modeli,
- male serwisy i mappers,
- jawna walidacja danych wejsciowych,
- retry z backoff dla integracji zewnetrznych,
- konsekwentne daty w ISO 8601.

## 15. Logowanie

Logowanie ma byc zrealizowane przez `loguru`.

Rekomendowane poziomy:
- `INFO` dla startu i konca procesu,
- `WARNING` dla bledow czesciowych i pomijanych rekordow,
- `ERROR` dla problemow krytycznych,
- `DEBUG` dla paginacji, filtrow dat i szczegolow technicznych.

Logowanie powinno dzialac:
- do stdout w GitHub Actions,
- opcjonalnie do pliku w srodowisku developerskim.

## 16. Testy

Testy powinny znajdowac sie w osobnym katalogu `tests`, zgodnie ze standardem projektow Python.

Rekomendowany podzial:
- `tests/unit/`
- `tests/integration/`
- `tests/fixtures/`

Rekomendowany zestaw narzedzi:
- `pytest`
- `pytest-cov`
- `pytest-mock`
- `responses` albo `requests-mock`
- opcjonalnie `freezegun` do testow czasu

Zakres testow:
- zakresy dat i filtrowanie po miesiacach,
- obsluga stref czasowych,
- wyliczanie `ended_at`,
- paginacja worklogow,
- serializacja JSON,
- use case'y raportowe,
- mockowana integracja z Google.

## 17. Coverage

Nalezy wdrozyc coverage w CI.

Rekomendacja:
- prog globalny na start: `85%`,
- dla domeny i use case'ow dazyc do `95%+`.

Coverage powinno byc elementem quality gate.

## 18. CLI i uruchamianie

Rekomendowany interfejs CLI:

- `jirareport report monthly`
- `jirareport report monthly --month YYYY-MM`
- `jirareport report daily --date YYYY-MM-DD`
- `jirareport sync sheets --input path/to/report.json`

Mozliwe jest rowniez uruchamianie przez jeden workflow GitHub Actions, ktory wykonuje kolejne kroki:
- extract raw,
- build derived reports,
- publish to Sheets.

## 19. GitHub Actions

Projekt ma byc przygotowany do codziennego uruchamiania w GitHub Actions.

Rekomendowany podzial workflow:

1. `ci.yml`
- lint,
- testy,
- coverage,
- quality gates

2. `daily-report.yml`
- harmonogram dzienny,
- pobranie danych,
- zapis raw,
- rekalkulacja raportow miesiecznych,
- publikacja do Google

Uwagi operacyjne:
- nie ustawac harmonogramu idealnie na poczatku godziny,
- logowac czas uruchomienia i zakres przetworzonych danych,
- zapewnic idempotentnosc zapisu raportow.

## 20. Kolejnosc wdrozenia

Rekomendowana kolejnosc implementacji:

1. Refaktoryzacja struktury projektu i konfiguracji.
2. Wydzielenie modeli domenowych i warstwy application.
3. Implementacja raportu miesiecznego JSON.
4. Implementacja dziennego raw snapshot.
5. Dodanie `loguru`.
6. Dodanie testow i coverage.
7. Dodanie adapterow Google Sheets oraz Drive lub GCS.
8. Dodanie workflow GitHub Actions.
9. Uzupelnienie dokumentacji operacyjnej.

## 21. Ostateczne rekomendacje

Finalne ustalenia:

- canonical source of truth: dzienne raw snapshoty,
- raport miesieczny: widok pochodny nadpisywany codziennie,
- storage raw:
  - PoC: Google Drive Shared Drive,
  - docelowo: Google Cloud Storage,
- Google Sheet:
  - warstwa prezentacyjna,
  - nie glowny magazyn danych,
- codzienny zakres pobierania:
  - od pierwszego dnia poprzedniego miesiaca do teraz,
  - alternatywnie 45-60 dni przy potrzebie wiekszej odpornosci,
- nie stosowac modelu "arkusz per dzien",
- startowy format danych: JSON,
- przy wzroscie wolumenu rozważyć JSONL.

