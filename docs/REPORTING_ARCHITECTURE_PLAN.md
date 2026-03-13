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
5. W GCS przechowujemy archiwalne snapshoty JSON oraz pelne miesieczne zbiory
   worklogow.
6. Miesieczne dane raportowe sa ladowane do BigQuery.
7. Looker Studio jest docelowa warstwa raportowa i dashboardowa.
8. Google Sheets jest tylko warstwa pomocnicza dla osob preferujacych ten
   interfejs.

## Why This Model

Ten model jest lepszy od samego Google Sheets jako zrodla raportow, bo:

- nie tracimy historii podczas kolejnych synchronizacji
- da sie odtworzyc wyliczenia z surowych danych
- korekty za poprzedni miesiac sa obslugiwane naturalnie
- koszt jest niski, bo nie utrzymujemy stale wlaczonej bazy danych
- raporty biznesowe sa liczone w BigQuery zamiast w zlozonych arkuszach
- Looker Studio staje sie docelowym widokiem dla raportow rozliczeniowych

## Storage Layers

Proponowane warstwy danych:

- `raw`
  - archiwalne snapshoty wejscia z Jira
- `curated`
  - oczyszczone, miesieczne worklogi gotowe do raportowania
- `reporting`
  - warstwa tabel raportowych w BigQuery

## Proposed GCS Layout

```text
gs://BUCKET/jirareport/raw/daily/space=<slug>/year=2026/month=03/date=2026-03-12/snapshot.json
gs://BUCKET/jirareport/curated/worklogs/space=<slug>/year=2026/month=03/worklogs.parquet
```

Warstwa raportowa w BigQuery powinna byc budowana na bazie `curated`.

## Data Scope Per Nightly Run

Kazde nocne uruchomienie powinno:

- pobrac dane z Jira dla miesiaca biezacego i poprzedniego
- nadpisac `curated` dla tych dwoch miesiecy
- zaladowac lub odswiezyc dane raportowe w BigQuery tylko dla tych dwoch
  miesiecy
- opublikowac do Google Sheets tylko miesieczne raw dane dla miesiecy, ktore sa
  w aktywnym oknie korekt

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

## BigQuery Report Outputs

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

## BigQuery Persistence Model

W BigQuery nie rekomendujemy tworzenia osobnych trwalych tabel per rok i
miesiac dla kazdego raportu agregowanego.

Najprostszy i najbardziej czytelny model:

- `worklogs` jako trwała tabela z pelnym zbiorem worklogow
- partycjonowanie po dacie, np. `started_date`
- opcjonalne klastrowanie po `space_slug`, `author_name`, `issue_key`

Agregacje typu:

- `by_issue`
- `by_issue_author`
- `by_author`
- `author_daily`
- `team_daily`

powinny byc utrzymywane jako widoki BigQuery liczone na biezaco.

To oznacza:

- trwale dane w BigQuery to tabela `worklogs`
- raporty agregowane sa generowane dynamicznie przy odczycie
- po korekcie danych za poprzedni miesiac widoki od razu pokazuja aktualny stan

Jesli kiedys pojawi sie potrzeba optymalizacji, agregacje mozna przeniesc do:

- materialized views
- batchowo odswiezanych tabel pomocniczych

Na obecna skale danych zwykle nie bedzie to potrzebne.

## Google Sheets Role

Google Sheets powinno byc tylko warstwa pomocnicza i kontrolna.

Rekomendowany model:

- `1 spreadsheet per year per space`
- `12` worksheetow z miesiecznymi raw danymi
- nazwy worksheetow:
  - `01`
  - `02`
  - `03`
  - ...
  - `12`

Kazdy worksheet miesieczny zawiera pelny miesieczny zbior worklogow.

Kluczowa zasada:

- Sheets nie jest zrodlem prawdy
- Sheets nie jest glowna warstwa raportowa
- Sheets sluzy osobom, ktore chca recznie przegladac, kopiowac albo dodatkowo
  przetwarzac miesieczne raw dane
- docelowe raporty biznesowe sa prezentowane w Looker Studio

## Why Not Cloud SQL First

Cloud SQL lub Postgres to poprawne rozwiazanie techniczne, ale na tym etapie
jest zbyt ciezkie operacyjnie i kosztowo jak na nightly reporting.

Na start lepsze sa:

- GCS jako storage
- Parquet jako format miesiecznych danych raportowych
- BigQuery jako warstwa raportowa
- Looker Studio jako warstwa prezentacji

## Recommended First Implementation

Najprostszy etap wdrozenia:

1. Zachowac archiwalne snapshoty JSON jako `raw`.
2. Dodac zapis miesiecznych `worklogs.parquet`.
3. Ladowac miesieczne dane raportowe do BigQuery.
4. Zbudowac raporty i dashboardy w Looker Studio.
5. Publikowac do Google Sheets tylko miesieczne raw dane jako warstwe
   pomocnicza.
