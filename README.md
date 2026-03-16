# JiraReport

CLI do pobierania worklogow z Jira, zapisu raportow JSON oraz publikacji do Google Sheets i BigQuery.

## Co robi system

`jirareport` to zautomatyzowany pipeline do raportowania worklogow z Jiry dla wielu skonfigurowanych przestrzeni (spaces). System:

1. **Pobiera dane z Jiry** — wydobywa worklogi z JQL z uwzglednieniem strefy czasowej
2. **Tworzy surowe snapshoty** — generuje `daily raw snapshot` z ruchomego okna raportowego (domyslnie 90 dni)
3. **Materializuje raporty miesieczne** — tworzy podsumowania miesieczne jako wersje nadpisywane
4. **Eksportuje do Parquet** — serializuje dane do skompresowanych plikow Parquet (Apache Arrow) o schemacie flat-table, przystosowanych do analizy w BI
5. **Laduje do BigQuery** — importuje zaszyfrowane datasety do BigQuery, partycjonuje po dacie, tworzy indeksy
6. **Generuje widoki Looker** — automatycznie tworzy widoki SQL w BigQuery, gotowe do wizualizacji w Looker
7. **Publikuje do Google Sheets** — synchronizuje snapshoty worklogow do rocznych skoroszytow z formulamis SUBTOTAL

## Przeplywy pracy

### Daily (operacyjny)
```
Jira (JQL) → raw/daily/YYYY-MM-DD.json
         ↓
         → derived/monthly/YYYY-MM.parquet (curated dataset)
         ↓
         → (opcjonalnie) Google Sheets sync
         ↓
         → (opcjonalnie) BigQuery table update
```

### BigQuery & Looker
```
derived/monthly/*.parquet → BigQuery worklogs table
                         ↓
                         → Automatic views (by space, by author, etc.)
                         ↓
                         → Looker dashboards & reports
```

## Modele danych

### Plik JSON (raw/daily)
Struktura: `List[DailyRawSnapshot]` — worklogi z dnia z metadanymi issue'u, autora, czasu.

### Plik Parquet (derived/monthly)
Flat-table schema (17 kolumn):
- Identyfikatory: `worklog_id`, `issue_key`, `author_account_id`
- Metadane: `space_key`, `space_name`, `space_slug`, `issue_summary`, `issue_type`, `author_name`
- Czasowe: `started_at`, `ended_at`, `started_date`, `ended_date`, `crosses_midnight`, `report_month`
- Obliczenia: `duration_seconds`, `duration_hours`

Kompresja: Snappy (szybka, standardowa dla BigQuery)

## Wymagania

- Python `3.13`
- `uv`
- dostep do Jira Cloud
- opcjonalnie: GCS i Google Sheets

## Szybki start

### Lokalna instalacja (bez cloud storage)

1. Zainstaluj zaleznosci:

```bash
uv sync --group dev
```

2. Utworz `.env`:

```bash
cp .env.example .env
```

3. Minimalna konfiguracja lokalna:

```dotenv
JIRA_BASE_URL=https://twoja-firma.atlassian.net
JIRA_EMAIL=twoj.email@firma.pl
JIRA_API_TOKEN=twoj_token_api
REPORT_TIMEZONE=Europe/Warsaw
JIRA_SPACES_CONFIG_PATH=config/spaces.yaml

REPORT_STORAGE_BACKEND=local
REPORT_OUTPUT_DIR=reports
```

4. Skonfiguruj przestrzenie raportowe w [config/spaces.yaml](config/spaces.yaml):

```yaml
spaces:
  - key: LA004832
    name: Click Price
    slug: click-price
    google_sheets_ids:
      2026: click-price-sheet-id

  - key: LA009644
    name: Data Fixer
    slug: data-fixer
    board_id: 1354
    google_sheets_ids:
      2026: data-fixer-sheet-id
```

5. Uruchom raport:

```bash
uv run jirareport daily --date 2026-03-11
```

Wyniki trafiaja do:
- `reports/spaces/{slug}/raw/daily/YYYY/MM/YYYY-MM-DD.json`
- `reports/spaces/{slug}/derived/monthly/YYYY/YYYY-MM.parquet`

### Integracja BigQuery & Looker

Dodaj do `.env`:

```dotenv
GOOGLE_APPLICATION_CREDENTIALS=/sciezka/do/service-account.json
BIGQUERY_PROJECT_ID=my-project
BIGQUERY_DATASET=jira_analytics
BIGQUERY_ENABLED=true
```

Wtedy komendy BigQuery beda dostepne:

```bash
uv run jirareport sync bigquery --date 2026-03-11
```

### Integracja Google Sheets

Dodaj do `.env`:

```dotenv
GOOGLE_APPLICATION_CREDENTIALS=/sciezka/do/service-account.json
GOOGLE_SHEETS_ENABLED=true
GOOGLE_SHEETS_TITLE_PREFIX=Jira Worklog Analytics
```

Wtedy synchr do Sheets bedzie dostepna:

```bash
uv run jirareport sync sheets --date 2026-03-11
```

## Komendy CLI

### Daily — codziennie raport operacyjny
```bash
uv run jirareport daily
uv run jirareport daily --date 2026-03-11
uv run jirareport daily --space LA004832
uv run jirareport daily --space click-price
```
Zachowanie:
- Pobiera worklogi z ostatnich 90 dni (rolling window, konfigurowalny)
- Zapisuje raw snapshot do `raw/daily/YYYY/MM/YYYY-MM-DD.json`
- Przebudowuje **wszystkie** pliki miesięczne w rolling window do `derived/monthly/YYYY/YYYY-MM.parquet`
- Opcjonalnie sync do Google Sheets i BigQuery (jeśli skonfigurowane)

### Backfill — historyczne przeliczenia
```bash
uv run jirareport backfill --from 2025-01-01 --to 2025-12-31
uv run jirareport backfill --from 2025-01-01 --to 2025-12-31 --space LA004832
```
Zachowanie:
- Pobiera worklogi z jawnie wskazanego przedziału
- Przebudowuje **każdy** miesiąc, którego dotyczy przedział
- Zapisuje Parquet do `derived/monthly/YYYY/`
- Nie publikuje do Google Sheets (tylko do BigQuery, jeśli skonfigurowany)

### Monthly — jedno-miesięczne przeliczenie
```bash
uv run jirareport monthly
uv run jirareport monthly --month 2026-03
uv run jirareport monthly --space data-fixer
```
Zachowanie:
- Przebudowuje **jeden** miesiąc (bieżący, jeśli nie podano `--month`)
- Zapisuje Parquet do `derived/monthly/YYYY/YYYY-MM.parquet`

### Sync sheets — publikacja do Google Sheets
```bash
uv run jirareport sync sheets
uv run jirareport sync sheets --date 2026-03-11
uv run jirareport sync sheets --from 2025-01-01 --to 2025-12-31
uv run jirareport sync sheets --space LA009644
```
Zachowanie:
- Pobiera aktualne worklogi z rolling window (lub podanego przedziału)
- Publikuje do Google Sheets za rok `--date` (lub bieżący rok)
- Tabele: `raw_worklogs`, `daily_summary`, `monthly_summary`, `metadata`
- Tworzy NOWY spreadsheet, jeśli nie istnieje dla roku w `config/spaces.yaml`

### Sync BigQuery — ładowanie do Data Warehouse
```bash
uv run jirareport sync bigquery
uv run jirareport sync bigquery --date 2026-03-11
uv run jirareport sync bigquery --from 2025-01-01 --to 2025-12-31
uv run jirareport sync bigquery --space click-price
```
Zachowanie:
- Ładuje curated monthly Parquet do BigQuery `worklogs` table
- Partycjonowana po `started_date`, klastrowana po `space_slug`, `author_name`, `issue_key`
- Automatycznie tworzy/odświeża widoki SQL (by space, by author, monthly summary)
- Widoki dostępne w Looker do budowy dashboardów
- Usuwa stare dane za dany miesiąc (replace pattern)

## Flagi globalne

```
--debug     Włącza debug logging (wypisuje JQL wysyłane do Jiry)
```

## Google Sheets

Wymagane zmienne lokalne:

```dotenv
GOOGLE_APPLICATION_CREDENTIALS=/sciezka/do/service-account.json
GOOGLE_SHEETS_ENABLED=true
GOOGLE_SHEETS_TITLE_PREFIX=Jira Worklog Analytics
```

Zachowanie:
- identyfikatory spreadsheetow sa mapowane per przestrzen i rok w `config/spaces.yaml`
- jesli brakuje ID dla roku, aplikacja utworzy nowy spreadsheet i zaloguje jego URL
- zakladki:
  - `raw_worklogs`
  - `monthly_summary`
  - `daily_summary`
  - `metadata`
- `monthly_summary` i `daily_summary` maja wiersz `VISIBLE_TOTALS` z formulami
  `SUBTOTAL`, wiec sumy dzialaja po filtrowaniu

## BigQuery & Looker

Wymagane zmienne lokalne:

```dotenv
GOOGLE_APPLICATION_CREDENTIALS=/sciezka/do/service-account.json
BIGQUERY_PROJECT_ID=my-project
BIGQUERY_DATASET=jira_analytics
BIGQUERY_ENABLED=true
```

Infrastruktura:
- **Tabela `worklogs`** — zawiera wszystkie miesieczne worklogi (partycjonowana po `started_date`)
- **Widoki diagnostyczne** — automatycznie tworzone per space i autor
- **Looker Studio** — podłącz BigQuery query do Looker dla interaktywnych dashboardów

Schemat BigQuery (17 kolumn):
```
space_key, space_name, space_slug,
issue_key, issue_summary, issue_type,
author_name, author_account_id,
worklog_id, started_at, ended_at,
started_date, ended_date, crosses_midnight,
duration_seconds, duration_hours, report_month
```

Pipeline BigQuery:
```
Parquet bytes → BigQuery LoadJob → worklogs table
                                ↓
                                → Automatic views (SQL)
                                ↓
                                → Looker dashboards
```

## Przechowywanie danych — Parquet

Plikow Parquet nie edytuje się ręcznie. System tworzy je automatycznie:
- Ścieżka: `reports/spaces/{space_slug}/derived/monthly/YYYY/YYYY-MM.parquet`
- Format: Apache Parquet z kompresją Snappy
- Cel: Optimized storage dla BigQuery i analizy BI
- Schema: Flat-table (17 kolumn, wyszczególnione wyżej)

Czytanie dla debugowania:
```python
import pyarrow.parquet as pq
table = pq.read_table("2026-03.parquet")
print(table.to_pandas())
```

## Jakosc

```bash
uv run ruff check .
uv run mypy src tests
uv run pytest
```

Coverage gate:
- `>= 90%`

## Storage — lokale vs Google Cloud Storage

System obsługuje dwa backendy przechowywania:

### Local storage (domyślne)
```dotenv
REPORT_STORAGE_BACKEND=local
REPORT_OUTPUT_DIR=reports
```
Struktura:
```
reports/
  spaces/
    click-price/
      raw/daily/2026/03/2026-03-11.json
      derived/monthly/2026/2026-03.parquet
    data-fixer/
      raw/daily/2026/03/2026-03-11.json
      derived/monthly/2026/2026-03.parquet
```

### Google Cloud Storage
```dotenv
REPORT_STORAGE_BACKEND=gcs
GCS_BUCKET=my-reports-bucket
GCS_BUCKET_PREFIX=jira-analytics/
```
Struktura: Taka sama, ale pliki na GCS (gs://bucket/prefix/...).

Obie metody zapisują:
- JSON surowych snapów (`raw/daily`)
- Parquet curated datasets (`derived/monthly`)
- Są gotowe do synchru do BigQuery

## Dokumentacja

- [PRD.md](docs/PRD.md)
- [DEVELOP.md](docs/DEVELOP.md)
- [SHEETS_INTEGRATION.md](docs/SHEETS_INTEGRATION.md)
- [BUSINESS_OVERVIEW.md](docs/BUSINESS_OVERVIEW.md)

## GitHub Actions

Repo zawiera workflowy:
- [ci.yml](.github/workflows/ci.yml)
- [daily-report.yml](.github/workflows/daily-report.yml)

Automatyczna publikacja do Google Sheets w GitHub Actions nie jest jeszcze
podlaczona do workflow.
