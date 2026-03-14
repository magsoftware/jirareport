# JiraReport

CLI do pobierania worklogow z Jira, zapisu raportow JSON oraz publikacji do
Google Sheets.

## Co robi

- generuje `daily raw snapshot` z ruchomego okna raportowego
- przebudowuje `derived/monthly` jako nadpisywany widok miesieczny
- zapisuje dane lokalnie albo do Google Cloud Storage
- publikuje dane do Google Sheets w modelu `spreadsheet per year`

## Wymagania

- Python `3.13`
- `uv`
- dostep do Jira Cloud
- opcjonalnie: GCS i Google Sheets

## Szybki start

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
- `reports/raw/daily/YYYY/MM/YYYY-MM-DD.json`
- `reports/derived/monthly/YYYY/YYYY-MM.json`

## Komendy

```bash
uv run jirareport daily
uv run jirareport daily --date 2026-03-11

uv run jirareport monthly
uv run jirareport monthly --month 2026-03

uv run jirareport sync sheets
uv run jirareport sync sheets --date 2026-03-11
```

Zasady:
- `daily` zapisuje raw snapshot i odswieza wszystkie miesiace z `rolling_window`
- `monthly` generuje pojedynczy raport miesieczny
- `sync sheets` publikuje snapshot do Google Sheets
- bez `--space` komendy dzialaja dla wszystkich przestrzeni z `config/spaces.yaml`
- `--space` przyjmuje `key` albo `slug`, np. `LA009644` albo `data-fixer`

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

## Jakosc

```bash
uv run ruff check .
uv run mypy src tests
uv run pytest
```

Coverage gate:
- `>= 90%`

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
