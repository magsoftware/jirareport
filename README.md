# JiraReport

CLI do generowania raportow worklogow z Jira w formacie JSON.

Aktualny stan projektu:
- generowanie `daily raw snapshot` z ruchomego okna od poczatku poprzedniego miesiaca do wskazanej daty,
- generowanie raportow miesiecznych JSON,
- storage do lokalnego filesystemu albo do Google Cloud Storage,
- logowanie przez `loguru`,
- testy `pytest` z coverage.

Docelowo projekt ma tez publikowac dane do Google Sheets. Warstwa architektoniczna jest pod to przygotowana, ale adapter Sheets nie jest jeszcze zaimplementowany.

## Wymagania

- Python `3.13`
- `uv`
- dostep do Jira Cloud
- dla backendu `gcs`: dostep do projektu Google Cloud i bucketu GCS

## Setup projektu

1. Sklonuj repozytorium.
2. Zainstaluj zaleznosci:

```bash
uv sync --group dev
```

3. Utworz lokalny plik `.env`.

Najwygodniej:

```bash
cp .env.example .env
```

Przykladowa konfiguracja:

```dotenv
JIRA_BASE_URL=https://twoja-firma.atlassian.net
JIRA_EMAIL=twoj.email@firma.pl
JIRA_API_TOKEN=twoj_token_api
JIRA_PROJECT_KEY=LA004832

REPORT_TIMEZONE=Europe/Warsaw

# Backend storage: local albo gcs
REPORT_STORAGE_BACKEND=local

# Uzywane dla backendu local
REPORT_OUTPUT_DIR=reports

# Uzywane dla backendu gcs
GCS_BUCKET_NAME=twoj-bucket
GCS_BUCKET_PREFIX=jirareport
```

## Pierwsze uruchomienie testowe

Najprostszy start lokalny:

1. Ustaw backend na lokalny:

```dotenv
REPORT_STORAGE_BACKEND=local
REPORT_OUTPUT_DIR=reports
```

2. Wygeneruj dzienny snapshot:

```bash
uv run jirareport daily --date 2026-03-11
```

3. Albo wygeneruj raport miesieczny:

```bash
uv run jirareport monthly --month 2026-03
```

Wyniki trafia wtedy lokalnie do katalogu `reports/`, zgodnie ze struktura:

- `reports/raw/daily/YYYY/MM/YYYY-MM-DD.json`
- `reports/derived/monthly/YYYY/YYYY-MM.json`

Wazne:
- komenda `daily` zapisuje nie tylko raw snapshot,
- ta sama komenda przebudowuje tez raporty miesieczne dla wszystkich miesiecy objetych ruchem okna rekalkulacji.

Przyklad:
- `uv run jirareport daily --date 2026-03-11`
- okno danych: `2026-02-01 .. 2026-03-11`
- wynik:
  - `2026-02.json` zawiera worklogi z lutego 2026,
  - `2026-03.json` zawiera worklogi z marca 2026 do dnia `2026-03-11` wlacznie.

To oznacza, ze raporty w `derived/monthly` po daily run:
- dla poprzedniego miesiaca moga byc kompletne,
- dla biezacego miesiaca sa raportem narastajacym do dnia uruchomienia.

Wazna zasada zapisu:
- `raw/daily` jest append-only po dacie snapshotu,
- `derived/monthly` jest nadpisywanym widokiem "latest state" dla danego miesiaca.

Przyklad:
- `daily --date 2026-03-11` tworzy `raw/daily/2026/03/2026-03-11.json`
- `daily --date 2026-03-12` tworzy `raw/daily/2026/03/2026-03-12.json`
- ale raporty:
  - `derived/monthly/2026/2026-02.json`
  - `derived/monthly/2026/2026-03.json`
  sa zapisywane pod tymi samymi sciezkami i nadpisywane nowa wersja.

## Testy

Uruchomienie wszystkich testow:

```bash
uv run pytest
```

Uruchomienie pojedynczego pliku testowego:

```bash
uv run pytest tests/unit/test_services.py
```

## Ruff

Sprawdzenie stylu i podstawowych problemow statycznych:

```bash
uv run ruff check .
```

Automatyczne poprawki dla bezpiecznych przypadkow:

```bash
uv run ruff check . --fix
```

## mypy

Sprawdzenie typowania:

```bash
uv run mypy src tests
```

## Coverage

Coverage jest skonfigurowane w `pyproject.toml`.

Aktualne wymaganie:
- minimum `90%`

Uruchomienie:

```bash
uv run pytest
```

Raport coverage jest wyswietlany w terminalu przez `pytest-cov`.

## Uzycie CLI

Raport dzienny:

```bash
uv run jirareport daily
uv run jirareport daily --date 2026-03-11
```

Raport miesieczny:

```bash
uv run jirareport monthly
uv run jirareport monthly --month 2026-03
```

Domyslne zachowanie:
- `daily` bierze date biezaca w strefie `REPORT_TIMEZONE`,
- `monthly` bierze biezacy miesiac w strefie `REPORT_TIMEZONE`.

## Integracje

### Jira

Aktualnie zaimplementowane.

Wymagane:
- Jira Cloud,
- adres instancji, np. `https://twoja-firma.atlassian.net`,
- konto uzytkownika z dostepem do projektu,
- API token dla tego konta,
- uprawnienia do odczytu issue i worklogow w projekcie.

Wymagane zmienne:
- `JIRA_BASE_URL`
- `JIRA_EMAIL`
- `JIRA_API_TOKEN`
- `JIRA_PROJECT_KEY`

Rekomendacje:
- uzywaj osobnego konta technicznego albo dedykowanego tokenu,
- ogranicz dostep konta tylko do potrzebnych projektow i danych,
- nie commituj `.env`.

Oficjalne materialy:
- Atlassian API tokens: https://support.atlassian.com/atlassian-account/docs/manage-api-tokens-for-your-atlassian-account/
- Jira Cloud auth i API tokeny: https://developer.atlassian.com/cloud/jira/platform/deprecation-notice-basic-auth-and-cookie-based-auth/

### Google Cloud Storage

Aktualnie zaimplementowane.

Wymagane:
- projekt GCP,
- wlaczony billing,
- bucket GCS,
- tozsamosc, z ktorej aplikacja bedzie korzystac,
- uprawnienia do zapisu obiektow do bucketu.

Wymagane zmienne:
- `REPORT_STORAGE_BACKEND=gcs`
- `GCS_BUCKET_NAME`
- `GCS_BUCKET_PREFIX`

Autoryzacja w kodzie opiera sie o Application Default Credentials.

Lokalnie mozesz uzyc:
- `gcloud auth application-default login`
- albo `GOOGLE_APPLICATION_CREDENTIALS=/sciezka/do/pliku.json`

Docelowo w GitHub Actions rekomendowane jest:
- GitHub OIDC + Workload Identity Federation
- bez dlugowiecznych kluczy `service-account.json`

Oficjalne materialy:
- ADC: https://cloud.google.com/docs/authentication/provide-credentials-adc
- `gcloud auth application-default login`: https://docs.cloud.google.com/sdk/gcloud/reference/auth/application-default/login
- tworzenie bucketu: https://docs.cloud.google.com/storage/docs/creating-buckets
- IAM dla Cloud Storage: https://docs.cloud.google.com/storage/docs/access-control/iam-permissions
- Workload Identity Federation dla deployment pipelines: https://docs.cloud.google.com/iam/docs/workload-identity-federation-with-deployment-pipelines
- GitHub Action do auth z GCP: https://github.com/google-github-actions/auth

### Google Sheets

Jeszcze niezaimplementowane w kodzie, ale to planowana integracja docelowa.

Wymagane beda:
- projekt GCP,
- wlaczony Google Sheets API,
- najpewniej takze Google Drive API, jesli skrypt ma tworzyc albo przenosic arkusze,
- konto serwisowe albo federowana tozsamosc GCP,
- arkusz Google Sheets udostepniony tej tozsamosci,
- identyfikator arkusza `spreadsheet_id`.

Planowany model:
- `raw_worklogs` jako dane szczegolowe,
- `monthly_summary` jako agregaty miesieczne,
- opcjonalnie `daily_summary`.

Oficjalne materialy:
- Sheets API quickstart: https://developers.google.com/workspace/sheets/api/quickstart/python
- przyklad wymagania wlaczenia API i udostepnienia arkusza tozsamosci serwisowej: https://docs.cloud.google.com/application-integration/docs/gcp-tasks/configure-sheets-get-task

## Co trzeba skonfigurowac po stronie GCP

### Minimalna konfiguracja dla GCS

1. Utworz projekt GCP albo wybierz istniejacy.
2. Wlacz billing.
3. Utworz bucket GCS.
4. Przygotuj tozsamosc aplikacyjna:
   - lokalnie: user ADC albo service account,
   - w GitHub Actions: Workload Identity Federation, najlepiej z impersonacja service account.
5. Nadaj uprawnienia do bucketu.

Minimalnie praktycznie potrzebujesz uprawnien pozwalajacych na:
- odczyt metadanych bucketu,
- tworzenie obiektow,
- opcjonalnie listowanie obiektow.

W praktyce najczesciej:
- tworzysz service account dla aplikacji,
- przyznajesz mu role odpowiednia do bucketu lub obiektow,
- zapisujesz nazwe bucketu w `GCS_BUCKET_NAME`.

### Rekomendowana konfiguracja dla GitHub Actions

1. Utworz service account dla workflow.
2. Skonfiguruj Workload Identity Pool i Provider dla GitHub.
3. Ogranicz zaufanie do konkretnego repozytorium i workflow przez warunki atrybutow.
4. Nadaj workflow mozliwosc impersonacji service account.
5. Nadaj temu service account tylko potrzebne role do GCS i przyszlego Sheets.

To jest preferowane rozwiazanie wzgledem sekretu z kluczem JSON.

## Co trzeba skonfigurowac po stronie Google Sheets

### Minimalna konfiguracja

1. W projekcie GCP wlacz `Google Sheets API`.
2. Jesli planujesz tworzenie lub przenoszenie arkuszy albo prace na plikach Drive, wlacz tez `Google Drive API`.
3. Przygotuj tozsamosc aplikacyjna:
   - service account,
   - albo service account uzywany przez GitHub OIDC / Workload Identity Federation.
4. Utworz arkusz docelowy albo wybierz istniejacy.
5. Udostepnij arkusz emailowi service account z uprawnieniem co najmniej `Editor`.
6. Zapisz `spreadsheet_id` z URL arkusza.

Przyklad:
- URL: `https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/edit`
- potrzebna wartosc: `SPREADSHEET_ID`

### Dodatkowe rekomendacje

- trzymaj raw data poza arkuszem, w GCS,
- traktuj Sheets jako warstwe raportowa,
- przygotuj w skoroszycie zakladki:
  - `raw_worklogs`
  - `monthly_summary`
  - `daily_summary`

## Rekomendowana konfiguracja lokalna vs CI

### Lokalnie

Najprostsza opcja:
- backend `local` i zapis do `reports/`

Jesli chcesz od razu testowac GCS:
- skonfiguruj ADC przez:

```bash
gcloud auth application-default login
```

### GitHub Actions

Rekomendowany model:
- `google-github-actions/auth`
- `permissions: id-token: write`
- Workload Identity Federation
- service account z minimalnymi rolami

## Struktura projektu

```text
src/jirareport/domain
src/jirareport/application
src/jirareport/infrastructure
src/jirareport/interfaces/cli
tests/
docs/PRD.md
```

## Dokumentacja projektowa

Pelne ustalenia funkcjonalne i architektoniczne sa w:
- `docs/PRD.md`

## GitHub Actions

Repo zawiera dwa workflow:

- `.github/workflows/ci.yml`
- `.github/workflows/daily-report.yml`

### CI

Workflow `ci.yml`:
- uruchamia sie dla `push` na `main`,
- uruchamia sie dla `pull_request`,
- instaluje zaleznosci przez `uv`,
- uruchamia `ruff`,
- uruchamia `mypy`,
- uruchamia testy i coverage.

Quality gates w CI:
- `ruff check .`
- `mypy src tests`
- `pytest` z coverage `>= 90%`

### Daily report

Workflow `daily-report.yml`:
- uruchamia sie codziennie wedlug `cron`,
- mozna go uruchomic recznie przez `workflow_dispatch`,
- loguje sie do GCP przez OIDC,
- uruchamia `uv run jirareport daily`,
- zapisuje raporty do GCS.

Semantyka workflow dziennego:
- zapisuje raw snapshot dla dnia uruchomienia,
- przebudowuje raporty miesieczne dla miesiecy wchodzacych w zakres rekalkulacji,
- dlatego po jednym daily run mozna otrzymac wiecej niz jeden plik w `derived/monthly`.

Dodatkowo:
- pliki w `raw/daily` narastaja dzien po dniu,
- pliki w `derived/monthly` sa traktowane jako aktualny stan raportu miesiecznego i sa nadpisywane.

### Co trzeba ustawic w GitHub

#### GitHub Secrets

Wymagane sekrety:
- `JIRA_BASE_URL`
- `JIRA_EMAIL`
- `JIRA_API_TOKEN`
- `GCP_WORKLOAD_IDENTITY_PROVIDER`
- `GCP_SERVICE_ACCOUNT_EMAIL`

#### GitHub Variables

Rekomendowane zmienne repozytorium:
- `JIRA_PROJECT_KEY`
- `REPORT_TIMEZONE`
- `GCS_BUCKET_NAME`
- `GCS_BUCKET_PREFIX`

### Co trzeba ustawic po stronie GCP dla workflow

1. Utworzyc service account dla GitHub Actions.
2. Nadac mu dostep do bucketu GCS.
3. Skonfigurowac Workload Identity Pool.
4. Skonfigurowac Workload Identity Provider dla GitHub.
5. Zezwolic providerowi na impersonacje service account.
6. Wpisac identyfikatory providera i service account do sekretow GitHub.

### Uwaga o Google Sheets

Workflow dzienny nie publikuje jeszcze do Google Sheets, bo adapter Sheets nie zostal jeszcze zaimplementowany w kodzie.
