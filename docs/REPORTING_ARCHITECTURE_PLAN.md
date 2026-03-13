# Reporting Architecture Plan

## Goal

Zbudowac prosty, tani i audytowalny model raportowania worklogow z Jira, w
ktorym:

- Google Sheets nie jest zrodlem prawdy
- historia danych nie ginie przy kolejnych synchronizacjach
- korekty za poprzedni miesiac sa obslugiwane bez komplikowania logiki
- raporty miesieczne daja sie latwo wyjasnic podczas rozliczen z klientem

## Business Assumption

Przyjmujemy nastepujacy aksjomat biznesowy:

- w danym miesiacu mozliwe sa korekty dla poprzedniego miesiaca
- nie zakladamy korekt dla miesiecy starszych niz poprzedni miesiac

Przyklad:

- w marcu moga pojawic sie korekty za luty
- nie zakladamy korekt za styczen
- raport za luty staje sie finalny po zakonczeniu okresu korekt, praktycznie
  na poczatku kwietnia
- 1 kwietnia to jest ostatni dzien, w ktorym przetwarzamy raport za luty
- od 2 kwietnia raport za luty traktujemy jako zamkniety i nie aktualizujemy go
  wiecej

Z tego wynika najprostsza regula przetwarzania:

- codziennie przeliczamy tylko miesiac biezacy i poprzedni
- miesiecy starszych nie ruszamy

## Recommended Architecture

Docelowy model:

1. Jira jest zrodlem danych.
2. GitHub Actions uruchamia nightly pipeline.
3. Pipeline pobiera worklogi z Jira.
4. Dane sa zapisywane do Google Cloud Storage.
5. Dane raportowe sa przechowywane w formacie Parquet.
6. Agregacje raportowe sa liczone w DuckDB.
7. Google Sheets jest tylko warstwa prezentacji dla biznesu.

## Why This Model

Ten model jest lepszy od samego Google Sheets jako zrodla raportow, bo:

- nie tracimy historii podczas kolejnych synchronizacji
- da sie odtworzyc wyliczenia z surowych danych
- korekty za poprzedni miesiac sa obslugiwane naturalnie
- koszt jest niski, bo nie utrzymujemy stale wlaczonej bazy danych
- agregacje sa prostsze niz przy utrzymywaniu zlozonych formul w Sheets

## Storage Layers

Proponowane warstwy danych:

- `raw`
  - archiwalne snapshoty wejscia z Jira
- `curated`
  - oczyszczone, miesieczne worklogi gotowe do raportowania
- `marts`
  - gotowe, finalne zestawy raportowe do prezentacji i eksportu

## Proposed GCS Layout

```text
gs://BUCKET/jirareport/raw/daily/space=<slug>/year=2026/month=03/date=2026-03-12/snapshot.json
gs://BUCKET/jirareport/curated/worklogs/space=<slug>/year=2026/month=03/worklogs.parquet
gs://BUCKET/jirareport/marts/monthly/space=<slug>/year=2026/month=03/by_issue.parquet
gs://BUCKET/jirareport/marts/monthly/space=<slug>/year=2026/month=03/by_issue_author.parquet
gs://BUCKET/jirareport/marts/monthly/space=<slug>/year=2026/month=03/by_author.parquet
gs://BUCKET/jirareport/marts/monthly/space=<slug>/year=2026/month=03/author_daily.parquet
gs://BUCKET/jirareport/marts/monthly/space=<slug>/year=2026/month=03/team_daily.parquet
gs://BUCKET/jirareport/marts/monthly/space=<slug>/year=2026/month=03/metadata.json
```

## Data Scope Per Nightly Run

Kazde nocne uruchomienie powinno:

- pobrac dane z Jira dla miesiaca biezacego i poprzedniego
- nadpisac `curated` dla tych dwoch miesiecy
- przeliczyc `marts` tylko dla tych dwoch miesiecy
- opublikowac do Google Sheets tylko te miesiace, ktore sa w aktywnym oknie
  korekt

Przyklad operacyjny:

- run z 31 marca przelicza marzec i luty
- run z 1 kwietnia nadal przelicza kwiecien i luty, jezeli chcemy domknac luty
  ostatnim przebiegiem
- od 2 kwietnia nie przeliczamy juz lutego
- od 2 kwietnia aktywne sa tylko kwiecien i marzec

To eliminuje potrzebe przebudowy calego roku przy kazdym runie.

## Base Reporting Dataset

Glowne zrodlo raportow miesiecznych powinno byc zapisane jako:

- `worklogs.parquet`

Przykladowe kolumny:

- `space_key`
- `space_slug`
- `snapshot_date`
- `issue_key`
- `issue_summary`
- `author_name`
- `author_account_id`
- `worklog_id`
- `started_at`
- `ended_at`
- `started_date`
- `month`
- `duration_seconds`
- `duration_hours`
- `crosses_midnight`

## Monthly Report Outputs

Na bazie `worklogs.parquet` powinny powstawac miesieczne agregacje:

- `by_issue`
  - `issue_key`, `issue_summary`, `total_hours`
- `by_issue_author`
  - `issue_key`, `issue_summary`, `author_name`, `total_hours`
- `by_author`
  - `author_name`, `total_hours`
- `author_daily`
  - `date`, `author_name`, `total_hours`
- `team_daily`
  - `date`, `author_name`, `total_hours`

Opcjonalnie:

- `billable_base`
  - plaski widok audytowy dla rozliczen
- `anomalies`
  - wpisy potencjalnie podejrzane, np. bardzo dlugie dni lub wpisy crossing
    midnight

## Google Sheets Role

Google Sheets powinno byc tylko warstwa prezentacji.

Rekomendowany model:

- `1 spreadsheet per year per space`
- osobne worksheety dla kazdego typu raportu i miesiaca

Worksheety dla miesiaca powinny byc rozdzielone per typ danych, a nie laczone
w jednej zakladce.

Przykladowy zestaw worksheetow dla stycznia:

- `01_raw`
- `01_issue`
- `01_issue_author`
- `01_author`
- `01_author_daily`
- `01_team_daily`

Opcjonalne dodatkowe worksheety:

- `summary`
- `metadata`

Kluczowa zasada:

- miesieczne raw dane i miesieczne agregaty trafiaja do osobnych worksheetow
- nie laczymy wielu roznych tabel raportowych w jednym worksheet
- nie traktujemy Sheets jako glownego magazynu danych historycznych

## Why Not Cloud SQL First

Cloud SQL lub Postgres to poprawne rozwiazanie techniczne, ale na tym etapie
jest zbyt ciezkie operacyjnie i kosztowo jak na nightly reporting.

Na start lepsze sa:

- GCS jako storage
- Parquet jako format raportowy
- DuckDB jako silnik agregacji batchowej

## Recommended First Implementation

Najprostszy etap wdrozenia:

1. Zachowac archiwalne snapshoty JSON jako `raw`.
2. Dodac zapis miesiecznych `worklogs.parquet`.
3. Liczyc agregacje miesieczne w DuckDB.
4. Zapisywac gotowe wyniki do `marts`.
5. Publikowac do Google Sheets tylko miesieczne widoki potrzebne biznesowi.

## Definition Of "Marts"

`Marts` oznacza tutaj `data marts`, czyli gotowe, wyspecjalizowane zestawy
danych przygotowane pod konkretny cel raportowy.

W tym projekcie:

- `raw` to surowe dane z Jira
- `curated` to dane oczyszczone i uporzadkowane
- `marts` to finalne tabele raportowe, np. `by_issue` albo `by_author`

Najprosciej:

- `raw` = co przyszlo z systemu
- `curated` = dane przygotowane do obrobki
- `marts` = dane gotowe do czytania przez biznes
