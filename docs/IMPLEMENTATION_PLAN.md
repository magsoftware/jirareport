# Implementation Plan

## Goal

Wdrozyc docelowy model raportowania:

- `GCS/raw` przechowuje dzienne snapshoty JSON
- `GCS/curated` przechowuje pelne miesieczne zbiory worklogow w `Parquet`
- `BigQuery` przechowuje trwała tabele `worklogs`
- `BigQuery` wystawia widoki raportowe
- `Looker Studio` jest docelowa warstwa prezentacji
- `Google Sheets` pozostaje warstwa pomocnicza z miesiecznym raw data

## Operational Modes

Nalezy zaimplementowac dwa niezalezne tryby pracy:

### 1. Nightly Operational Mode

Tryb uruchamiany codziennie z GitHub Actions.

Cel:

- pobrac aktualne dane z Jira
- odswiezyc aktywne miesiace
- zaladowac dane do BigQuery
- odswiezyc Google Sheets dla aktywnych miesiecy

### 2. Backfill / Historical Rebuild Mode

Tryb uruchamiany recznie dla historii lub awaryjnego odtworzenia danych.

Cel:

- pobrac dane dla jawnie zadanego zakresu dat
- przebudowac miesieczne datasety dla zadanego przedzialu
- zaladowac lub odswiezyc dane w BigQuery

Przyklad:

- pelne pobranie roku `2025-01-01` do `2025-12-31`

## Business Date Rules

Logika aktywnych miesiecy nie moze byc tylko prostym `current_month +
previous_month`.

Obowiazuja nastepujace reguly:

- w danym miesiacu mozliwe sa korekty dla poprzedniego miesiaca
- nie zakladamy korekt dla miesiecy starszych niz poprzedni miesiac
- pierwszy dzien nowego miesiaca jest specjalnym przypadkiem domykajacym
  miesiac sprzed dwoch miesiecy

Przyklad dla kwietnia 2026:

- `2026-03-31`: aktywne miesiace to `2026-02` i `2026-03`
- `2026-04-01`: aktywne miesiace to nadal `2026-02` i `2026-03`
- `2026-04-02`: aktywne miesiace to `2026-03` i `2026-04`

Wniosek:

- `1.04` to ostatni raz, kiedy przetwarzamy luty i marzec
- od `2.04` nie przetwarzamy juz lutego

Ta logika musi byc zaimplementowana centralnie i pokryta testami.

## CLI Changes

Nalezy rozszerzyc CLI o jawne tryby operacyjne i historyczne.

Rekomendowany kierunek:

- zachowac tryb codzienny dla pipeline nightly
- dodac tryb z zakresem dat `--from` / `--to`
- zachowac mozliwosc przebudowy pojedynczego miesiaca

Przykladowy docelowy zestaw:

- `jirareport daily`
  - tryb operacyjny z logika aktywnych miesiecy
- `jirareport daily --date 2026-04-01`
  - uruchomienie operacyjne dla konkretnej daty referencyjnej
- `jirareport backfill --from 2025-01-01 --to 2025-12-31`
  - przebudowa historyczna dla zadanego zakresu
- `jirareport monthly --month 2025-02`
  - reczna przebudowa pojedynczego miesiaca

Jesli nie chcemy dodawac osobnej komendy `backfill`, mozna rozszerzyc istniejaca
komende o `--from` i `--to`, ale osobny tryb bedzie czytelniejszy.

## Phases

## Phase 1: Time Logic And Domain Rules

1. Wydzielic centralna logike wyznaczania aktywnych miesiecy.
2. Zaimplementowac specjalny przypadek pierwszego dnia miesiaca.
3. Dodac funkcje wyznaczajace miesiace dla:
   - trybu nightly
   - trybu backfill
4. Dodac testy graniczne dla:
   - `2026-03-31`
   - `2026-04-01`
   - `2026-04-02`
   - zakresu historycznego `2025-01-01` do `2025-12-31`

## Phase 2: Curated Monthly Dataset In GCS

1. Rozszerzyc warstwe storage o zapis `Parquet`.
2. Zapisac pelny miesieczny zbior worklogow do:
   - `gs://.../curated/worklogs/space=<slug>/year=YYYY/month=MM/worklogs.parquet`
3. Utrzymac obecne `raw` snapshoty JSON.
4. Upewnic sie, ze miesieczny dataset jest idempotentny:
   - rerun miesiaca nadpisuje ten sam zbior
5. Pokryc testami:
   - liczbe rekordow
   - sumy godzin
   - spojnosc z `raw` snapshotami

## Phase 3: Application Services

1. Zmienic use case `daily`, aby:
   - nadal generowal `raw` snapshot
   - jednoczesnie przebudowywal `curated` dla aktywnych miesiecy
2. Dodac use case backfill:
   - zakres `from/to`
   - iteracja po miesiacach w zakresie
3. Zachowac use case pojedynczego miesiaca:
   - do recznych napraw i rerunow
4. Ujednolicic logowanie:
   - start i koniec fazy
   - data referencyjna
   - miesiace objete runem
   - liczba worklogow
   - sciezki zapisanych artefaktow

## Phase 4: BigQuery Load

1. Dodac konfiguracje BigQuery:
   - `project_id`
   - `dataset`
   - nazwa tabeli `worklogs`
2. Przygotowac schemat `worklogs`.
3. Ustalic model ladowania:
   - trwala tabela `worklogs`
   - partycjonowanie po `started_date`
   - opcjonalne klastrowanie po `space_slug`, `author_name`, `issue_key`
4. Ladowac do BigQuery tylko aktywne miesiace w nightly.
5. W trybie backfill ladowac wszystkie miesiace wynikajace z zakresu.
6. Zapewnic idempotencje:
   - replace/upsert dla miesiaca
   - brak duplikacji po `worklog_id`

## Phase 5: BigQuery Views

1. Zdefiniowac widoki raportowe:
   - `by_issue`
   - `by_issue_author`
   - `by_author`
   - `author_daily`
   - `team_daily`
2. Opcjonalnie:
   - `billable_base`
   - `anomalies`
3. Widoki maja byc liczone dynamicznie na bazie trwałej tabeli `worklogs`.
4. Nie tworzyc na start osobnych trwałych tabel agregacyjnych per rok i
   miesiac.
5. Dopiero przy realnym problemie wydajnosci rozwazyc:
   - materialized views
   - batchowo odswiezane tabele pomocnicze

## Phase 6: Google Sheets Simplification

1. Zmienic role Google Sheets na czysto pomocnicza.
2. `1 spreadsheet per year per space`.
3. Worksheety `01` do `12` zawieraja pelny miesieczny zbior worklogow.
4. Sync ma aktualizowac tylko worksheety aktywnych miesiecy.
5. W trybie backfill dopuscic odbudowe wybranych worksheetow miesiecznych.
6. Sheets nie powinny byc zrodlem raportow agregowanych.

## Phase 7: GitHub Actions Pipeline

1. Przebudowac nightly workflow na fazy:
   - `fetch raw snapshot`
   - `build curated monthly parquet`
   - `load BigQuery`
   - `ensure BigQuery views`
   - `sync Google Sheets`
2. Zachowac `workflow_dispatch` z parametrami:
   - `report_date`
   - docelowo `from_date`
   - docelowo `to_date`
3. Rozdzielic operacyjnie:
   - run nightly
   - run backfill
4. Dodac czytelne logi konca kazdej fazy i flush logowania.
5. Utrzymac concurrency i timeouty.

## Phase 8: Looker Studio

1. Zbudowac datasource na BigQuery.
2. Zbudowac dashboardy dla:
   - godzin per issue
   - godzin per issue i autor
   - godzin per autor
   - godzin autora per day
   - godzin per dzien i osoba
3. Dodac filtry:
   - `space`
   - `month`
   - `author`
   - `issue_key`
4. Potwierdzic z biznesem, ze Looker Studio staje sie glownym widokiem
   raportowym.

## Phase 9: Migration And Rollout

1. Najpierw uruchomic nowa sciezke rownolegle do obecnej.
2. Zweryfikowac zgodnosc:
   - liczby worklogow
   - sum godzin
   - poprawnosci danych w Google Sheets
   - poprawnosci danych w BigQuery
3. Po potwierdzeniu:
   - ograniczyc Sheets do raw miesiecznego
   - uznac Looker Studio za docelowy raport

## Regression Risks

Najwazniejsze ryzyka:

1. Bledna logika aktywnych miesiecy na granicy miesiaca.
2. Pominięcie lutego lub marca w runie `2026-04-01`.
3. Duplikacja worklogow przy ponownym ladowaniu miesiaca.
4. Rozjazd miedzy `raw JSON`, `curated Parquet` i `BigQuery`.
5. Bledy timezone przy worklogach crossing midnight.
6. Dalsze traktowanie Google Sheets jako zrodla prawdy mimo nowej architektury.

## Test Plan

### Unit Tests

1. Wyznaczanie aktywnych miesiecy dla dat granicznych.
2. Wyznaczanie listy miesiecy dla zakresu `from/to`.
3. Serializacja do `Parquet`.
4. Mapowanie danych do BigQuery schema.
5. Mapowanie miesiaca na worksheet `01`...`12`.

### Integration Tests

1. `daily` dla daty zwyklej, np. `2026-03-12`.
2. `daily` dla daty granicznej `2026-04-01`.
3. `daily` dla daty `2026-04-02`.
4. `backfill --from 2025-01-01 --to 2025-12-31`.
5. Zaladowanie miesiaca do testowej tabeli BigQuery.
6. Synchronizacja testowego spreadsheetu rocznego.

### Business Validation

1. Zgodnosc liczby worklogow z Jira.
2. Zgodnosc sum godzin per miesiac.
3. Zgodnosc agregacji `by_issue`, `by_author`, `author_daily`.
4. Potwierdzenie, ze run z `2026-04-01` nadal obejmuje luty i marzec.
5. Potwierdzenie, ze run z `2026-04-02` obejmuje juz tylko marzec i kwiecien.

## GCP Work Required

Po stronie GCP nalezy przygotowac:

1. API:
   - `Cloud Storage`
   - `BigQuery`
   - `Google Sheets API`
   - `Google Drive API`
2. Bucket GCS:
   - bucket raportowy
   - prefix, np. `jirareport/`
3. BigQuery:
   - dataset, np. `jirareport`
   - uprawnienia do tworzenia i ladowania tabel
4. Service account dla GitHub Actions:
   - zapis/odczyt do GCS
   - zapis/odczyt do BigQuery
   - dostep do Google Sheets i Google Drive
5. Workload Identity Federation dla repo `magsoftware/jirareport`
6. Udostepnienie docelowych spreadsheetow service accountowi
7. Przygotowanie Looker Studio:
   - datasource do BigQuery
   - dashboardy

## GitHub Configuration Required

Po stronie GitHub nalezy ustawic:

### Secrets

- `JIRA_BASE_URL`
- `JIRA_EMAIL`
- `JIRA_API_TOKEN`
- `GCP_WORKLOAD_IDENTITY_PROVIDER`
- `GCP_SERVICE_ACCOUNT_EMAIL`

### Variables

- `GCS_BUCKET_NAME`
- `GCS_BUCKET_PREFIX`
- `REPORT_TIMEZONE`
- `GOOGLE_SHEETS_TITLE_PREFIX`
- docelowo:
  - `BIGQUERY_PROJECT_ID`
  - `BIGQUERY_DATASET`

## Recommended Delivery Order

1. Logika aktywnych miesiecy i testy graniczne.
2. `curated/worklogs.parquet`.
3. Tryb backfill `from/to`.
4. Load do `BigQuery.worklogs`.
5. Widoki BigQuery.
6. Uproszczenie Google Sheets do `01`...`12`.
7. Dashboardy Looker Studio.
8. Odbior biznesowy i odlaczenie starego modelu summary w Sheets.
