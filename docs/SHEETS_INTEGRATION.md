# SHEETS_INTEGRATION - aktualny model Google Sheets

## 1. Cel dokumentu

Ten dokument opisuje rzeczywista, aktualnie zaimplementowana integracje `jirareport` z Google Sheets.

Opisuje:
- model danych wysylanych do Sheets,
- sposob rozdzialu po spaces, latach i miesiacach,
- lifecycle spreadsheetow,
- reguly publikacji i formatowania,
- ograniczenia obecnej wersji.

Dokument celowo opisuje stan faktyczny kodu, nie historyczny plan.

## 2. Rola Google Sheets w systemie

Google Sheets jest warstwa publikacji i pracy operacyjnej.

Nie jest:
- source of truth,
- archiwum historycznych uruchomien,
- miejscem przechowywania danych analitycznych dla BigQuery.

Kanoniczne artefakty pozostaja poza Sheets:
- raw snapshoty JSON,
- derived monthly JSON,
- curated monthly Parquet.

## 3. Granulacja publikacji

Aktualny model:
- jeden spreadsheet per `space` per rok,
- w spreadsheetcie jedna zakladka per miesiac z aktywnego zakresu,
- kazda zakladka zawiera surowe worklogi dla jednego miesiaca tego roku.

Przyklad dla `Click Price`:
- `Jira Worklog Analytics - Click Price 2026`
- zakladki `01`, `02`, `03` itd.

## 4. Co publikujemy

Publikowane sa tylko surowe worklogi miesieczne.

Aktualna implementacja nie publikuje:
- `monthly_summary`,
- `daily_summary`,
- `metadata`,
- zakladek README / dashboard / charts.

Jesli taka funkcjonalnosc zostanie dodana, dokument trzeba zaktualizowac razem z kodem.

## 5. Zrodlo danych do publikacji

`sync sheets` nie czyta zapisanych plikow JSON ze storage.

Proces:
1. pobiera worklogi z Jira przez `WorklogSource`,
2. buduje `DailyRawSnapshot` w pamieci,
3. dzieli snapshot na lata i miesiace,
4. publikuje wynik bezposrednio do Google Sheets API.

Korzysci:
- brak zaleznosci od poprzednio zapisanych plikow,
- jeden przebieg logiki datowej i mapowania,
- prostszy model operacyjny.

## 6. Zakres danych

## 6.1. Tryb operacyjny

`jirareport sync sheets --date YYYY-MM-DD`

Uzywa:
- `rolling_window(reference_date)`

Standardowo:
- od pierwszego dnia poprzedniego miesiaca do `reference_date`.

Wyjatek na pierwszy dzien miesiaca:
- zakres obejmuje dwa poprzednie miesiace,
- konczy sie na ostatnim dniu poprzedniego miesiaca.

## 6.2. Tryb jawnego zakresu

`jirareport sync sheets --from YYYY-MM-DD --to YYYY-MM-DD`

Uzywa:
- jawnego, inkluzywnego `DateRange`

Ten tryb sluzy glownie do:
- publikacji historycznej,
- odtworzen,
- audytu,
- diagnozy danych na pograniczu miesiecy / lat.

## 7. Rozdzial po latach

Plik:
- `src/jirareport/application/spreadsheets.py`

Funkcja:
- `years_for_snapshot(snapshot)`

Regula:
- lata sa wyznaczane z miesiecy przecietych przez okno raportowe,
- jeden sync moze wiec aktualizowac wiecej niz jeden spreadsheet.

Przyklad:
- `reference_date = 2026-01-05`
- okno: `2025-12-01 .. 2026-01-05`
- wynik:
  - spreadsheet `2025` dla miesiaca `12`
  - spreadsheet `2026` dla miesiaca `01`

## 8. Rozdzial po miesiacach

Funkcja:
- `_months_for_year(snapshot, year)`

Regula:
- dla kazdego roku publikowane sa tylko miesiace nalezace do tego roku i obecne w oknie,
- tytul worksheetu jest dwucyfrowym numerem miesiaca.

Przyklady:
- luty -> `02`
- pazdziernik -> `10`

## 9. Format worksheetu

Kazdy worksheet ma:
- pierwszy wiersz z headerem,
- kolejne wiersze z surowymi worklogami.

Dokladna kolejnosc kolumn:
1. `snapshot_date`
2. `window_start`
3. `window_end`
4. `generated_at`
5. `timezone`
6. `month`
7. `issue_key`
8. `summary`
9. `issue_type`
10. `author`
11. `author_account_id`
12. `worklog_id`
13. `started_at`
14. `ended_at`
15. `started_date`
16. `ended_date`
17. `crosses_midnight`
18. `duration_seconds`
19. `duration_hours`

Granulacja:
- jeden wiersz = jeden worklog.

## 10. Mapowanie danych

Mapowanie odbywa sie w `_raw_row(...)`.

Najwazniejsze zasady:
- `month` pochodzi z lokalnego `started_at` w formacie `YYYY-MM`,
- `summary` i `issue_type` pochodza z aktualnego payloadu issue z Jira,
- `crosses_midnight` jest serializowane jako `TRUE` / `FALSE`,
- `duration_hours` jest liczba zmiennoprzecinkowa,
- `started_at` i `ended_at` sa w ISO 8601 bez ulamkow sekund.

Miesieczna przynaleznosc worklogu jest liczona po:
- `entry.started_date`

To wazne dla wpisow przebiegajacych przez polnoc.

## 11. Sortowanie danych

Worklogi w worksheetach sa sortowane deterministycznie po:
- `started_at`,
- `issue_key`,
- `author_name`,
- `worklog_id`.

Cel:
- stabilny output,
- przewidywalne diffy przy porownaniach,
- czytelniejszy arkusz dla ludzi.

## 12. Lifecycle spreadsheetu

## 12.1. Rozwiazywanie targetu

Plik:
- `src/jirareport/infrastructure/google/sheets_client.py`

Klasa:
- `GoogleSheetsResolver`

Zachowanie:
- jesli dla roku istnieje ID w `config/spaces.yaml`, jest uzywane bez zmian,
- jesli ID brakuje, aplikacja tworzy nowy spreadsheet,
- nowy spreadsheet ma tytul `<GOOGLE_SHEETS_TITLE_PREFIX> - <SPACE_NAME> <YEAR>`.

Przyklad:
- `Jira Worklog Analytics - Click Price 2026`

Po automatycznym utworzeniu:
- ID pozostaje tylko w runtime,
- aplikacja loguje URL i ID,
- maintainer powinien dopisac ID do `config/spaces.yaml`.

## 12.2. Tworzenie worksheets

Klasa:
- `GoogleSheetsPublisher`

Publisher:
- pobiera metadane spreadsheetu,
- sprawdza, czy wymagane zakladki miesieczne istnieja,
- tworzy brakujace zakladki przez `batchUpdate`.

## 12.3. Aktualizacja worksheets

Dla kazdej zakladki publisher:
1. czysci cala zakladke,
2. zapisuje caly payload od `A1`,
3. naklada formatowanie.

To jest model `full refresh per worksheet`, nie append.

Powod:
- worklogi moga byc dodawane i poprawiane wstecz,
- append nie gwarantowalby poprawnosci danych.

## 13. Formatowanie i UX arkusza

Publisher naklada lekkie formatowanie:
- reset formatowania w wypelnionym zakresie,
- zamrozenie naglowka,
- kolorowanie naglowka,
- auto-resize kolumn,
- podstawowy filter.

Dodatkowo:
- formuly sa lokalizowane zalezne od locale spreadsheetu,
- dla locale `pl_PL` zamieniany jest separator `,` na `;`.

Obecna implementacja nie dodaje:
- chartow,
- frozen columns,
- footer totals,
- tabel przestawnych,
- conditional formatting zaleznego od tresci.

## 14. Konfiguracja

## 14.1. Globalna konfiguracja

Potrzebne pola srodowiskowe:
- `GOOGLE_SHEETS_ENABLED`
- `GOOGLE_SHEETS_TITLE_PREFIX`
- `GOOGLE_APPLICATION_CREDENTIALS` lub inna poprawna autoryzacja Google

`GOOGLE_SHEETS_ENABLED`:
- jesli nie jest ustawione, aplikacja uznaje Sheets za wlaczone, gdy przynajmniej jeden `space` ma `google_sheets_ids`.

## 14.2. Konfiguracja per space

Plik:
- `config/spaces.yaml`

Przyklad:

```yaml
spaces:
  - key: LA004832
    name: Click Price
    slug: click-price
    google_sheets_ids:
      2025: spreadsheet-id-2025
      2026: spreadsheet-id-2026
```

Mapowanie jest jawne per:
- `space`
- rok

Nie ma runtime lookupu po nazwie z Google Drive.

## 15. Ograniczenia obecnej wersji

Obecna integracja ma kilka waznych ograniczen:
- publikuje tylko raw worklogi,
- nie zapisuje historii synchronizacji w samym arkuszu,
- nie utrzymuje readonly metadata tab,
- nie pobiera danych ze storage, tylko zawsze z Jira,
- nie ma retry / backoff specyficznego dla Sheets API w tej warstwie,
- nowo utworzone spreadsheety nie sa automatycznie utrwalane w `config/spaces.yaml`.

## 16. Implikacje dla rozwoju

Jesli chcesz rozwinac integracje Sheets, zacznij od pytania:
- czy ma pozostac "raw operational workbook",
- czy ma stac sie workbookiem raportowym z agregatami i dashboardami.

W pierwszym przypadku zmiany wejda glownie do:
- `application/spreadsheets.py`
- `google/sheets_client.py`
- `tests/unit/test_google_sheets.py`

W drugim przypadku trzeba tez zaktualizowac:
- `PRD.md`
- `DEVELOP.md`
- ten dokument
- testy use-case'ow i CLI

## 17. Kryteria poprawnego dzialania

Integracja dziala poprawnie, jezeli:

1. dla kazdego wybranego `space` publikuje tylko jego dane,
2. dla kazdego roku uzywa wlasciwego spreadsheetu lub tworzy nowy,
3. dla kazdego miesiaca publikuje osobna zakladke,
4. kolejne uruchomienia nadpisuja zawartosc zakladki, nie duplikuja wierszy,
5. sync na pograniczu lat aktualizuje wszystkie potrzebne spreadsheety,
6. kolumny i kolejnosc danych pozostaja zgodne z `MONTHLY_RAW_HEADERS`.
