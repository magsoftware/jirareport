# DEVELOP - Przewodnik dla developerow

## 1. Cel dokumentu

Ten dokument wprowadza developera w aktualny stan projektu `jirareport`.

Skupia sie na:
- architekturze,
- glownych przeplywach aplikacji,
- modelach domenowych,
- portach i adapterach,
- konfiguracji,
- miejscach, w ktorych najczesciej bedzie rozwijany system.

Wymagania biznesowe sa opisane w `docs/PRD.md`.

## 2. Co robi aplikacja

`jirareport` to CLI do raportowania worklogow z Jira dla wielu skonfigurowanych spaces.

Aktualne use-case'y:
- `daily` - generuje raw snapshot i odswieza materializacje miesieczne,
- `monthly` - przelicza jeden miesiac,
- `backfill` - przelicza miesiace z jawnie wskazanego zakresu,
- `sync sheets` - publikuje raw worklogi do rocznych spreadsheetow Google Sheets,
- `sync bigquery` - laduje miesieczne datasety Parquet do BigQuery i odswieza widoki.

## 3. Struktura projektu

```text
src/jirareport/
  domain/
  application/
  infrastructure/
    google/
  interfaces/cli/
  main.py

docs/
  PRD.md
  DEVELOP.md
  SHEETS_INTEGRATION.md
  BUSINESS_OVERVIEW.md

tests/
  unit/
  integration/
```

## 4. Architektura wysokiego poziomu

Projekt stosuje lekka architekture warstwowa typu ports-and-adapters.

Zasady:
- `domain` nie zna bibliotek zewnetrznych ani I/O,
- `application` orkiestruje use-case'i i materializacje,
- `infrastructure` implementuje integracje,
- `interfaces` wystawia CLI i sklada zaleznosci.

To nie jest ciezkie DDD. To pragmatyczny podzial odpowiedzialnosci.

## 5. Warstwa domenowa

Pliki:
- `src/jirareport/domain/models.py`
- `src/jirareport/domain/ports.py`
- `src/jirareport/domain/time_range.py`

Glowne modele:
- `MonthId` - identyfikator miesiaca, walidacja `YYYY-MM`, nawigacja po miesiacach,
- `DateRange` - inkluzywny zakres dat,
- `JiraSpace` - biznesowa przestrzen raportowa (`key`, `name`, `slug`),
- `Issue` - minimalny model issue potrzebny do mapowania worklogow,
- `WorklogEntry` - znormalizowany worklog po stronie domeny,
- `DailyRawSnapshot` - snapshot raw dla konkretnego dnia i zakresu,
- `TicketWorklogReport` - bookings zgrupowane pod ticketem,
- `MonthlyWorklogReport` - raport miesieczny dla jednego `MonthId`,
- `WorksheetData`, `SpreadsheetPublishRequest`, `SpreadsheetTarget` - modele publikacji do Sheets.

Wazne szczegoly `WorklogEntry`:
- `ended_at` jest liczone w adapterze Jira jako `started_at + duration_seconds`,
- `started_date` i `ended_date` sa pochodne od dat w lokalnej strefie raportowej,
- `crosses_midnight` pozwala wykryc wpisy przechodzace przez granice dnia,
- `duration_hours` jest zaokraglane do 2 miejsc.

## 6. Porty domenowe

Plik:
- `src/jirareport/domain/ports.py`

Porty:
- `WorklogSource`
- `JsonReportStorage`
- `CuratedDatasetStorage`
- `SpreadsheetPublisher`
- `SpreadsheetResolver`
- `WorklogWarehouse`

Znaczenie:
- use-case nie wie, czy dane sa z Jira, z fake source albo innego backendu,
- use-case nie wie, czy zapis idzie lokalnie czy do GCS,
- use-case nie wie, czy publisherem jest Google Sheets czy inna implementacja,
- use-case nie wie, czy warehouse to BigQuery czy testowy fake.

## 7. Logika zakresow dat

Plik:
- `src/jirareport/domain/time_range.py`

Najwazniejsze funkcje:
- `current_date(timezone_name)`
- `month_range(month)`
- `rolling_window(reference_date)`
- `active_months(reference_date)`
- `explicit_range(start, end)`
- `months_in_range(window)`

Kluczowa regula:
- standardowo `rolling_window` obejmuje poprzedni miesiac i biezacy miesiac do `reference_date`,
- 1. dnia miesiaca okno cofa sie o dodatkowy miesiac i konczy na ostatnim dniu poprzedniego miesiaca.

Przyklady:
- `2026-03-14` -> `2026-02-01 .. 2026-03-14`
- `2026-04-01` -> `2026-02-01 .. 2026-03-31`

Ta regula jest centralna dla logiki operacyjnej, testow i dokumentacji biznesowej.

## 8. Warstwa aplikacyjna

Pliki:
- `src/jirareport/application/services.py`
- `src/jirareport/application/serializers.py`
- `src/jirareport/application/parquet_serializers.py`
- `src/jirareport/application/spreadsheets.py`

## 8.1. `DailySnapshotService`

Glowny use-case operacyjny.

Odpowiedzialnosci:
- wyliczenie `rolling_window`,
- pobranie worklogow z `WorklogSource`,
- zapis raw snapshot JSON,
- przebudowa wszystkich raportow miesiecznych z okna,
- wygenerowanie miesiecznych Parquetow.

Artefakty:
- `spaces/<key>/<slug>/raw/daily/YYYY/MM/YYYY-MM-DD.json`
- `spaces/<key>/<slug>/derived/monthly/YYYY/YYYY-MM.json`
- `curated/worklogs/space=<slug>/year=YYYY/month=MM/worklogs.parquet`

## 8.2. `MonthlyReportService`

Use-case ad hoc dla pojedynczego miesiaca.

Odpowiedzialnosci:
- wyliczenie pelnego zakresu miesiaca,
- pobranie worklogow tylko z tego miesiaca,
- zapis JSON i Parquet dla jednego `MonthId`.

## 8.3. `BackfillService`

Use-case historyczny.

Odpowiedzialnosci:
- przyjecie jawnego `DateRange`,
- pobranie worklogow dla calosci zakresu,
- przebudowa wszystkich miesiecy przecietych zakresem,
- brak tworzenia raw snapshotu dziennego.

## 8.4. `SheetsSyncService`

Use-case publikacji do Google Sheets.

Istotne cechy:
- buduje snapshot w pamieci, nie korzysta z zapisanych plikow JSON,
- przyjmuje albo `reference_date`, albo jawny `DateRange`,
- rozdziela dane na lata,
- dla kazdego roku buduje osobny `SpreadsheetPublishRequest`,
- publikuje tylko miesieczne zakladki raw.

Aktualny model Sheets:
- spreadsheet per `space` per rok,
- worksheet per miesiac o tytule `01`, `02`, ...,
- zawartosc: surowe worklogi z headerem.

## 8.5. `BigQuerySyncService`

Use-case publikacji do BigQuery.

Istotne cechy:
- korzysta z juz zapisanych plikow Parquet,
- operuje na miesiacach aktywnych albo wskazanych zakresem,
- dla kazdego miesiaca laduje slice do tabeli,
- po zaladowaniu odswieza zestaw widokow.

## 8.6. Serializacja JSON

Plik:
- `src/jirareport/application/serializers.py`

Kontrakty:
- `serialize_daily_snapshot(snapshot)`
- `serialize_monthly_report(report)`
- `serialize_worklog(entry, snapshot_date=None)`

JSON jest czytelny dla ludzi i trzymany jako artefakt raportowy / audytowy.

## 8.7. Serializacja Parquet

Plik:
- `src/jirareport/application/parquet_serializers.py`

Parquet jest wersja analityczna danych miesiecznych:
- plaski model,
- jawny schema,
- kompresja `snappy`,
- przygotowanie do BigQuery.

## 8.8. Budowa payloadu dla Sheets

Plik:
- `src/jirareport/application/spreadsheets.py`

Najwazniejsze elementy:
- `years_for_snapshot(snapshot)` zwraca wszystkie lata obecne w oknie,
- `build_spreadsheet_request(snapshot, spreadsheet_id, year)` buduje payload dla jednego spreadsheetu rocznego,
- tytuly worksheets to dwucyfrowe numery miesiecy.

Uwaga:
- obecne `SHEETS_INTEGRATION.md` musi byc interpretowane zgodnie z tym modulem,
- nie ma tu agregatow `monthly_summary` ani `daily_summary`.

## 9. Warstwa infrastrukturalna

## 9.1. Konfiguracja

Plik:
- `src/jirareport/infrastructure/config.py`

`load_settings()` sklada:
- `JiraSettings`
- `StorageSettings`
- `SheetsSettings`
- `BigQuerySettings`
- `timezone_name`
- `configured_spaces`

`ConfiguredSpace` laczy:
- domenowy `JiraSpace`,
- opcjonalny `board_id`,
- mapowanie `google_sheets_ids`.

Walidowane sa m.in.:
- wymagane zmienne Jira,
- backend storage,
- istnienie i schema `config/spaces.yaml`,
- unikalnosc `key` i `slug`,
- typy identyfikatorow arkuszy.

## 9.2. Jira adapter

Plik:
- `src/jirareport/infrastructure/jira_client.py`

Adapter:
- buduje JQL `project = "<KEY>" AND worklogDate >= ... AND worklogDate <= ...`,
- pobiera issues z paginacja,
- dla kazdego issue pobiera worklogi z paginacja,
- mapuje payload do `WorklogEntry`,
- konwertuje `started_at` do strefy raportowej,
- filtruje po lokalnej dacie `started_at.date()`.

To oznacza, ze przynaleznosc do dnia i miesiaca zawsze wynika z daty lokalnej po konwersji.

## 9.3. Storage

Plik:
- `src/jirareport/infrastructure/storage.py`

Dostepne backendy:
- `LocalJsonReportStorage`
- `LocalCuratedDatasetStorage`
- `GcsJsonReportStorage`
- `GcsCuratedDatasetStorage`

Warstwa aplikacyjna widzi tylko porty.

## 9.4. Google Sheets adapter

Plik:
- `src/jirareport/infrastructure/google/sheets_client.py`

Elementy:
- `GoogleSheetsPublisher`
- `GoogleSheetsResolver`

Zachowanie publish:
- pobiera metadane spreadsheetu,
- tworzy brakujace worksheets,
- czysci cala zakladke,
- zapisuje dane od `A1`,
- naklada lekkie formatowanie i filtr.

Zachowanie resolve:
- najpierw probuje uzyc ID skonfigurowanego dla roku,
- gdy go brakuje, tworzy nowy spreadsheet i loguje jego URL / ID.

## 9.5. BigQuery adapter

Plik:
- `src/jirareport/infrastructure/google/bigquery_client.py`

Zachowanie:
- tworzy tabele, jesli nie istnieja,
- tabela jest partycjonowana po `started_date`,
- tabela jest klastrowana po `space_slug`, `author_name`, `issue_key`,
- przed zaladowaniem miesiaca usuwa aktualny slice,
- po loadzie sprawdza duplikaty `worklog_id`,
- utrzymuje widoki globalne i per space.

## 10. CLI

Plik:
- `src/jirareport/interfaces/cli/app.py`

Dostepne komendy:

```text
jirareport daily [--date YYYY-MM-DD] [--space KEY_OR_SLUG]
jirareport monthly [--month YYYY-MM] [--space KEY_OR_SLUG]
jirareport backfill --from YYYY-MM-DD --to YYYY-MM-DD [--space KEY_OR_SLUG]
jirareport sync sheets [--date YYYY-MM-DD | --from YYYY-MM-DD --to YYYY-MM-DD] [--space KEY_OR_SLUG]
jirareport sync bigquery [--date YYYY-MM-DD | --from YYYY-MM-DD --to YYYY-MM-DD] [--space KEY_OR_SLUG]
```

Zasady:
- `--space` filtruje po `key` lub `slug`,
- brak `--space` oznacza uruchomienie dla wszystkich spaces z konfiguracji,
- `sync` nie pozwala mieszac `--date` z `--from/--to`.

## 11. End-to-end flow

## 11.1. Flow `daily`

1. CLI parsuje argumenty i laduje konfiguracje.
2. Dla kazdego wybranego `space` buduje `JiraWorklogSource`, storage JSON i storage Parquet.
3. `DailySnapshotService` wylicza `rolling_window`.
4. Jira adapter pobiera issues i worklogi.
5. Snapshot raw jest zapisywany do JSON.
6. Wszystkie miesiace z okna sa materializowane do JSON i Parquet.
7. CLI loguje wynik.

## 11.2. Flow `monthly`

1. CLI rozwiazuje `MonthId`.
2. `MonthlyReportService` buduje `month_range`.
3. System pobiera worklogi tylko z tego miesiaca.
4. Powstaja dwa artefakty: JSON i Parquet.

## 11.3. Flow `backfill`

1. CLI buduje jawny `DateRange`.
2. `BackfillService` pobiera dane dla calego zakresu.
3. Wszystkie miesiace przeciete zakresem sa przeliczane.
4. Nie jest tworzony daily raw snapshot.

## 11.4. Flow `sync sheets`

1. CLI rozwiazuje `reference_date` albo `DateRange`.
2. `SheetsSyncService` buduje snapshot w pamieci.
3. Snapshot jest dzielony na lata przez `years_for_snapshot`.
4. `SpreadsheetResolver` znajduje lub tworzy spreadsheet roczny.
5. `GoogleSheetsPublisher` publikuje worksheets miesieczne.

## 11.5. Flow `sync bigquery`

1. CLI ustala aktywne miesiace albo miesiace z zakresu.
2. `BigQuerySyncService` czyta odpowiednie Parquety ze storage.
3. Kazdy miesiac ladowany jest jako oddzielny slice.
4. Na koncu odswiezane sa widoki raportowe.

## 12. Artefakty w buckecie i na storage

Ta sekcja opisuje dokladnie, jakie pliki powstaja na storage lokalnym albo w buckecie GCS.

Z perspektywy use-case'ow nie ma roznicy, czy backendem jest filesystem czy GCS:
- dla local pliki trafiaja pod `REPORT_OUTPUT_DIR`,
- dla GCS obiekty trafiaja do `gs://<bucket>/<prefix>/...`

## 12.1. Daily raw snapshot

Komenda:
- `jirareport daily`

Tworzony jest jeden plik raw snapshot per `space` i per `reference_date`:
- `spaces/<space_key>/<space_slug>/raw/daily/YYYY/MM/YYYY-MM-DD.json`

Przyklad:
- `spaces/LA004832/click-price/raw/daily/2026/03/2026-03-14.json`

Semantyka:
- to jest historyczny snapshot "co system widzial w dniu uruchomienia",
- plik jest nowy dla kazdego dnia,
- ten artefakt nie nadpisuje poprzednich dni.

## 12.2. Derived monthly JSON

Komendy:
- `jirareport daily`
- `jirareport monthly`
- `jirareport backfill`

Tworzone lub nadpisywane sa raporty miesieczne JSON:
- `spaces/<space_key>/<space_slug>/derived/monthly/YYYY/YYYY-MM.json`

Przyklad:
- `spaces/LA004832/click-price/derived/monthly/2026/2026-03.json`

Semantyka:
- to jest widok pochodny dla miesiaca,
- kolejne przeliczenia tego samego miesiaca nadpisuja ten sam plik,
- nie przechowujemy osobnej historii wersji miesiecy na poziomie nazwy pliku.

## 12.3. Curated monthly Parquet

Komendy:
- `jirareport daily`
- `jirareport monthly`
- `jirareport backfill`

Tworzone lub nadpisywane sa miesieczne datasety Parquet:
- `curated/worklogs/space=<space_slug>/year=YYYY/month=MM/worklogs.parquet`

Przyklad:
- `curated/worklogs/space=click-price/year=2026/month=03/worklogs.parquet`

Semantyka:
- to jest plaski dataset analityczny,
- jest to glowny input dla `sync bigquery`,
- kolejne przeliczenia tego samego miesiaca nadpisuja ten sam Parquet.

## 12.4. Co nie jest zapisywane na storage przez `sync sheets`

Komenda:
- `jirareport sync sheets`

Ta komenda:
- nie zapisuje nowych plikow JSON,
- nie zapisuje nowych Parquetow,
- nie czyta wprost zapisanych snapshotow JSON,
- buduje snapshot w pamieci i publikuje go bezposrednio do Google Sheets.

## 12.5. Co czyta `sync bigquery`

Komenda:
- `jirareport sync bigquery`

Ta komenda nie liczy worklogow od zera z Jira.

Ona:
- czyta gotowe Parquety z `curated/worklogs/...`,
- laduje je do BigQuery,
- odswieza widoki.

To oznacza, ze przed `sync bigquery` odpowiednie miesiace musza juz byc wyliczone przez:
- `daily`,
- `monthly`,
- albo `backfill`.

## 13. Zasady przeliczania miesiecy

Ta sekcja opisuje, co dokladnie jest przeliczane przy kazdej komendzie.

## 13.1. `daily`

`daily`:
- wylicza `rolling_window(reference_date)`,
- pobiera worklogi z calego okna,
- zapisuje jeden raw snapshot,
- przelicza wszystkie miesiace przeciete przez to okno,
- dla kazdego takiego miesiaca zapisuje JSON i Parquet.

Typowy przyklad:
- `jirareport daily --date 2026-03-14`
- okno: `2026-02-01 .. 2026-03-14`
- przeliczane miesiace:
  - `2026-02`
  - `2026-03`

Specjalny przypadek:
- `jirareport daily --date 2026-04-01`
- okno: `2026-02-01 .. 2026-03-31`
- przeliczane miesiace:
  - `2026-02`
  - `2026-03`

To jest celowe:
- run z 1. dnia miesiaca domyka poprzedni miesiac,
- nie liczy jeszcze kwietnia.

## 13.2. `monthly`

`monthly`:
- przelicza tylko jeden wskazany miesiac,
- nie tworzy raw snapshotu dziennego,
- zapisuje tylko:
  - jeden derived monthly JSON,
  - jeden curated monthly Parquet.

Przyklad:
- `jirareport monthly --month 2026-03`
- przeliczany miesiac:
  - tylko `2026-03`

## 13.3. `backfill`

`backfill`:
- przyjmuje jawny zakres `--from` / `--to`,
- pobiera worklogi dla calego zakresu,
- przelicza wszystkie miesiace przeciete zakresem,
- nie tworzy raw snapshotu dziennego.

Przyklad:
- `jirareport backfill --from 2025-12-15 --to 2026-02-10`
- przeliczane miesiace:
  - `2025-12`
  - `2026-01`
  - `2026-02`

## 14. Kiedy aktualizowany jest Google Sheets

Google Sheets jest aktualizowany tylko przez:
- `jirareport sync sheets`

Ani `daily`, ani `monthly`, ani `backfill` same z siebie nie publikuja do Sheets.

## 14.1. `sync sheets --date`

Przy `--date`:
- system liczy `rolling_window(reference_date)`,
- pobiera worklogi z Jira,
- buduje snapshot w pamieci,
- rozdziela dane na lata i miesiace,
- publikuje roczne spreadsheety i miesieczne zakladki raw.

Przyklad:
- `jirareport sync sheets --date 2026-03-14`
- aktualizowany spreadsheet:
  - `2026`
- aktualizowane zakladki:
  - `02`
  - `03`

Przyklad granicy roku:
- `jirareport sync sheets --date 2026-01-05`
- okno: `2025-12-01 .. 2026-01-05`
- aktualizowane spreadsheety:
  - `2025`
  - `2026`

## 14.2. `sync sheets --from --to`

Przy jawnym zakresie:
- system nie uzywa `rolling_window`,
- bierze dokladnie podany zakres,
- aktualizuje wszystkie lata i miesiace obecne w tym zakresie.

To jest tryb do:
- historycznego odtworzenia,
- publikacji naprawczej,
- diagnozy.

## 14.3. Co dokladnie jest aktualizowane w Google Sheets

Aktualizowane sa:
- spreadsheety przypisane do danego `space` i roku,
- miesieczne zakladki raw o tytulach `01`, `02`, `03` itd.

Publisher dla kazdej zakladki:
1. czysci cala zakladke,
2. zapisuje caly aktualny dataset od `A1`,
3. naklada formatowanie.

To znaczy:
- sync sheets jest idempotentny,
- nie dopisuje nowych wierszy appendem,
- zawsze materializuje aktualny stan dla danego miesiaca w danym spreadsheetcie.

## 15. Kiedy aktualizowany jest BigQuery

BigQuery jest aktualizowany tylko przez:
- `jirareport sync bigquery`

Ani `daily`, ani `monthly`, ani `backfill`, ani `sync sheets` same z siebie nie laduja danych do BigQuery.

## 15.1. `sync bigquery --date`

Przy `--date`:
- system wyznacza `active_months(reference_date)`,
- czyta Parquety dla tych miesiecy,
- laduje je do BigQuery,
- odswieza widoki.

Przyklad:
- `jirareport sync bigquery --date 2026-03-14`
- ladowane miesiace:
  - `2026-02`
  - `2026-03`

Przyklad dla 1. dnia miesiaca:
- `jirareport sync bigquery --date 2026-04-01`
- aktywne miesiace wynikaja z `rolling_window(2026-04-01)`,
- ladowane miesiace:
  - `2026-02`
  - `2026-03`

## 15.2. `sync bigquery --from --to`

Przy jawnym zakresie:
- system bierze wszystkie miesiace przeciete zakresem,
- dla kazdego miesiaca czyta odpowiedni Parquet,
- dla kazdego miesiaca wymienia slice w BigQuery.

Przyklad:
- `jirareport sync bigquery --from 2025-12-15 --to 2026-02-10`
- ladowane miesiace:
  - `2025-12`
  - `2026-01`
  - `2026-02`

## 15.3. Co dokladnie robi load do BigQuery

Dla kazdego `space` i miesiaca:
1. system czyta `curated/worklogs/space=<slug>/year=YYYY/month=MM/worklogs.parquet`,
2. usuwa aktualny slice z tabeli dla `space_slug` i `report_month`,
3. laduje nowy Parquet,
4. sprawdza duplikaty `worklog_id`,
5. po zakonczeniu wszystkich miesiecy odswieza widoki.

To znaczy:
- BigQuery jest aktualizowane na podstawie juz przeliczonych danych,
- `sync bigquery` jest wtornym krokiem po przeliczeniu danych,
- brak odpowiedniego Parqueta oznacza, ze najpierw trzeba uruchomic `daily`, `monthly` albo `backfill`.

## 16. Typowy harmonogram operacyjny

Najbardziej logiczny operacyjny przebieg dla danego dnia jest taki:

1. `jirareport daily`
2. `jirareport sync sheets`
3. `jirareport sync bigquery`

Znaczenie:
- `daily` tworzy i odswieza artefakty raportowe,
- `sync sheets` publikuje aktualny stan operacyjny dla biznesu,
- `sync bigquery` publikuje aktualny stan analityczny z Parquetow.

Alternatywy:
- jesli potrzebujesz tylko odswiezyc arkusze, mozesz uruchomic samo `sync sheets`,
- jesli potrzebujesz tylko zasilic analityke z gotowych Parquetow, mozesz uruchomic samo `sync bigquery`,
- jesli naprawiasz historie, zwykle najpierw idzie `backfill`, a potem targety zewnetrzne.

## 17. Najczestsze miejsca zmian

Jesli zmieniasz:
- format JSON -> sprawdz `application/serializers.py`, testy unit i dokumentacje,
- logike okna dat -> sprawdz `domain/time_range.py`, testy i `PRD.md`,
- strukture Sheets -> sprawdz `application/spreadsheets.py`, `google/sheets_client.py`, testy i `SHEETS_INTEGRATION.md`,
- schema Parquet / BigQuery -> sprawdz `parquet_serializers.py`, `bigquery_client.py`, testy i dokumentacje analityczna,
- konfiguracje spaces -> sprawdz `config/spaces.yaml`, `infrastructure/config.py` i README.

## 18. Testy

Najwazniejsze pliki:
- `tests/unit/test_cli.py`
- `tests/unit/test_google_sheets.py`
- `tests/unit/test_storage.py`
- `tests/unit/test_services.py`
- `tests/unit/test_jira_helpers.py`
- `tests/unit/test_time_range.py`
- `tests/unit/test_bigquery_client.py`
- `tests/integration/test_jira_client.py`

Testy sa oparte glownie na fake adapterach i mockowanych odpowiedziach.

## 19. Praktyczne uwagi rozwojowe

Przed wieksza zmiana sprawdz trzy rzeczy:
- czy zmiana psuje rozdzielenie per `space`,
- czy zmiana zachowuje zgodnosc z logika strefy czasowej,
- czy dokumentacja nadal opisuje implementacje, a nie plan sprzed kilku iteracji.
