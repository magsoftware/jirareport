# DEVELOP - Developer Introduction

## 1. Cel dokumentu

Ten dokument wprowadza dewelopera w aktualny stan projektu `jirareport`.

Opisuje:
- strukture katalogow,
- glowny przeplyw aplikacji,
- modele domenowe,
- use case'y i uslugi aplikacyjne,
- adaptery infrastrukturalne,
- wzorce projektowe i abstrakcje,
- miejsca, w ktorych najlatwiej rozwijac system.

To nie jest dokument produktowy. Wymagania biznesowe sa opisane w `docs/PRD.md`.

## 2. Czym jest ten projekt

`jirareport` to CLI do pobierania worklogow z Jira i budowania raportow JSON.

Aktualnie system umie:
- generowac dzienny raw snapshot,
- generowac raport miesieczny,
- zapisywac wynik lokalnie albo do Google Cloud Storage,
- logowac przebieg przez `loguru`.

Projekt publikuje dane rowniez do Google Sheets przez osobny use case i komende
CLI `sync sheets`.

## 3. Architektura wysokiego poziomu

Projekt jest podzielony na lekkie warstwy:

- `domain`
- `application`
- `infrastructure`
- `interfaces`

To jest w praktyce lekka odmiana:
- `ports and adapters`
- `hexagonal architecture`
- `service layer`

Zasada jest prosta:
- `domain` nie zna szczegolow technicznych,
- `application` sklada logike biznesowa z abstrakcji,
- `infrastructure` implementuje integracje,
- `interfaces` wystawia CLI.

## 4. Struktura katalogow

Aktualna struktura:

```text
src/jirareport/
  domain/
  application/
  infrastructure/
  interfaces/cli/
  main.py

tests/
  integration/
  unit/

docs/
  PRD.md
  DEVELOP.md
```

### 4.1. `src/jirareport/domain`

Warstwa domenowa zawiera:
- modele domenowe,
- porty/protokoly,
- logike operowania na zakresach dat.

Pliki:
- `models.py`
- `ports.py`
- `time_range.py`

### 4.2. `src/jirareport/application`

Warstwa aplikacyjna zawiera:
- use case'y,
- serwisy budujace raporty,
- serializatory JSON.

Pliki:
- `services.py`
- `serializers.py`

### 4.3. `src/jirareport/infrastructure`

Warstwa infrastrukturalna zawiera:
- konfiguracje aplikacji,
- klienta Jira,
- storage lokalny i GCS,
- konfiguracje logowania.

Pliki:
- `config.py`
- `jira_client.py`
- `storage.py`
- `logging_config.py`

### 4.4. `src/jirareport/interfaces/cli`

Warstwa interfejsu zawiera:
- parser argumentow,
- komendy CLI,
- skladanie zaleznosci.

Plik:
- `app.py`

### 4.5. `tests`

Testy sa rozdzielone na:
- `unit`
- `integration`

Testy integracyjne sa nadal lekkie:
- nie ida do prawdziwej sieci,
- testuja integracje z adapterem przy fake session.

## 5. Główny przepływ aplikacji

Punkt wejscia:
- `src/jirareport/main.py`

Entry point pakietu:
- `jirareport = "jirareport.main:main"` w `pyproject.toml`

Przeplyw wywolania:

1. Uzytkownik uruchamia CLI.
2. `interfaces/cli/app.py` parsuje argumenty.
3. `load_settings()` buduje konfiguracje z `.env` i zmiennych srodowiskowych.
4. `_build_source()` tworzy adapter Jira.
5. `build_storage()` tworzy storage lokalny albo GCS.
6. CLI uruchamia odpowiedni use case:
   - `DailySnapshotService`
   - `MonthlyReportService`
7. Use case pobiera worklogi przez port `WorklogSource`.
8. Use case serializuje wynik do JSON.
9. Use case zapisuje JSON przez port `ReportStorage`.
10. CLI loguje rezultat i konczy proces.

## 5A. Main Use Case

Glowny use case projektu na dzis to:
- codzienna generacja raw snapshotu worklogow,
- oraz przebudowa raportow miesiecznych dla miesiecy dotknietych zakresem danych.

Technicznie odpowiada za to:
- `DailySnapshotService`

Biznesowo ten use case rozwiazuje problem:
- worklogi moga byc bukowane lub poprawiane wstecz,
- dlatego raport miesieczny nie moze byc budowany tylko z "dzisiejszych zmian",
- potrzebna jest codzienna rekalkulacja z ruchomego okna.

Aktualny model dzialania:
- job dzienny bierze zakres od pierwszego dnia poprzedniego miesiaca do wskazanej daty,
- zapisuje raw snapshot jako stan "as of today",
- przebudowuje wszystkie miesiace znajdujace sie w tym zakresie.

Wazna konsekwencja:
- po daily run powstaja nie tylko pliki `raw`,
- powstaja tez pliki `derived/monthly` dla miesiecy objetych zakresem.

Przyklad:
- `daily --date 2026-03-11`
- zakres: `2026-02-01 .. 2026-03-11`
- wynik:
  - `2026-02.json` zawiera worklogi przypisane do lutego,
  - `2026-03.json` zawiera worklogi przypisane do marca do `2026-03-11` wlacznie.

To znaczy, ze:
- raport poprzedniego miesiaca moze byc pelny,
- raport biezacego miesiaca jest raportem narastajacym do dnia uruchomienia.

Z perspektywy storage:
- `raw/daily` zachowuje historię uruchomien,
- `derived/monthly` przechowuje aktualny, nadpisywany widok miesiaca.

W praktyce to oznacza:
- raw snapshot jest canonical source dla danego uruchomienia,
- raport miesieczny jest widokiem pochodnym.

Drugim use case'em jest:
- `MonthlyReportService`

Ten use case sluzy do:
- wygenerowania jednego raportu miesiecznego na zadany miesiac,
- np. dla re-run, odtworzenia albo lokalnej analizy.

## 5B. End-to-End Processing Flow

Ponizej opis pelnego flow przetwarzania danych od wejscia do wyniku.

### Wejscie

Uzytkownik albo workflow GitHub Actions uruchamia:
- `jirareport daily`
- albo `jirareport monthly`

CLI przyjmuje opcjonalnie:
- `--date` dla snapshotu dziennego,
- `--month` dla raportu miesiecznego.

### Krok 1. Parsowanie polecenia

Warstwa:
- `interfaces/cli/app.py`

CLI:
- parsuje argumenty,
- ustala tryb pracy,
- wlacza logowanie.

### Krok 2. Zaladowanie konfiguracji

Warstwa:
- `infrastructure/config.py`

System pobiera:
- konfiguracje Jira,
- konfiguracje storage,
- strefe czasowa raportu.

Na tym etapie surowe zmienne srodowiskowe sa mapowane do:
- `AppSettings`
- `JiraSettings`
- `StorageSettings`

### Krok 3. Zlozenie zaleznosci

Warstwa:
- `interfaces/cli/app.py`

CLI buduje:
- `JiraWorklogSource`
- `LocalJsonStorage` albo `GcsJsonStorage`

To jest moment, w ktorym abstrakcje domenowe sa laczone z konkretnymi adapterami.

### Krok 4. Uruchomienie use-case'u

Jesli wybrano `daily`:
- uruchamiany jest `DailySnapshotService.generate(reference_date)`

Jesli wybrano `monthly`:
- uruchamiany jest `MonthlyReportService.generate(month)`

### Krok 5. Wyznaczenie zakresu danych

Warstwa:
- `domain/time_range.py`

Use case oblicza:
- `rolling_window(reference_date)` dla `daily`
- `month_range(month)` dla `monthly`

To jest krytyczny moment, bo determinuje:
- jakie dane beda pobrane z Jira,
- jakie miesiace beda przebudowane.

### Krok 6. Pobranie danych z Jira

Warstwa:
- `infrastructure/jira_client.py`

Adapter Jira:
- buduje JQL dla worklogow,
- pobiera liste issue z paginacja,
- dla kazdego issue pobiera worklogi z paginacja,
- mapuje payloady HTTP do `WorklogEntry`.

Na tym etapie:
- `started_at` jest konwertowane do strefy raportowej,
- `ended_at` jest wyliczane,
- wpisy sa filtrowane po lokalnej dacie.

### Krok 7. Budowa modelu wewnetrznego

Warstwa:
- `application/services.py`

Use case buduje:
- `DailyRawSnapshot`
- albo `MonthlyWorklogReport`

Dla snapshotu dziennego dodatkowo:
- wyznaczane sa wszystkie miesiace w zakresie,
- dla kazdego miesiaca budowany jest osobny `MonthlyWorklogReport`.

### Krok 8. Serializacja do JSON

Warstwa:
- `application/serializers.py`

Modele domenowe sa zamieniane na payload JSON zgodny z kontraktem raportu.

To jest osobny etap celowo oddzielony od:
- pobierania danych,
- obliczen domenowych,
- zapisu do storage.

### Krok 9. Zapis raportu

Warstwa:
- `infrastructure/storage.py`

Payload JSON jest zapisywany przez port `ReportStorage` do:
- lokalnego filesystemu,
- albo GCS.

Sciezki sa wyznaczane w use-case'ach:
- `raw/daily/YYYY/MM/YYYY-MM-DD.json`
- `derived/monthly/YYYY/YYYY-MM.json`

W przypadku use-case'u dziennego zapis obejmuje:
- jeden plik raw snapshot,
- jeden lub wiecej plikow miesiecznych w `derived/monthly`.

Liczba plikow w `derived/monthly` zalezy od tego, ile miesiecy przecina `rolling_window`.

Wazna semantyka zapisu:
- plik raw ma nazwe zalezną od `snapshot_date`, wiec kolejne uruchomienia tworza nowe pliki,
- plik monthly ma nazwe zalezną tylko od `MonthId`, wiec kolejne uruchomienia nadpisuja ten sam plik dla danego miesiaca.

Przyklad:
- uruchomienie `daily --date 2026-03-11` tworzy:
  - `raw/daily/2026/03/2026-03-11.json`
  - `derived/monthly/2026/2026-02.json`
  - `derived/monthly/2026/2026-03.json`

- uruchomienie `daily --date 2026-03-12` tworzy:
  - `raw/daily/2026/03/2026-03-12.json`
  - nadpisuje `derived/monthly/2026/2026-02.json`
  - nadpisuje `derived/monthly/2026/2026-03.json`

### Krok 10. Wynik i logowanie

Warstwa:
- `interfaces/cli/app.py`
- `infrastructure/logging_config.py`

CLI:
- loguje wynik,
- zwraca kod wyjscia `0`,
- konczy proces.

### Podsumowanie flow

W skrocie:

1. CLI przyjmuje komende.
2. Konfiguracja laduje ustawienia.
3. CLI sklada adaptery.
4. Use case wyznacza zakres dat.
5. Adapter Jira pobiera i mapuje worklogi.
6. Use case buduje modele raportowe.
7. Serializer tworzy JSON.
8. Storage zapisuje wynik.
9. CLI loguje rezultat.

## 6. Domain layer

### 6.1. `MonthId`

Plik:
- `src/jirareport/domain/models.py`

To lekki identyfikator miesiaca:
- `year`
- `month`

Odpowiedzialnosci:
- walidacja numeru miesiaca,
- parsowanie `YYYY-MM`,
- wyznaczanie poprzedniego i nastepnego miesiaca,
- sprawdzanie, czy data nalezy do miesiaca.

To jest celowy obiekt wartosci, zeby nie rozpraszac po kodzie:
- surowych stringow `YYYY-MM`,
- logiki przechodzenia miedzy miesiacami.

### 6.2. `DateRange`

Reprezentuje zakres dat:
- `start`
- `end`

Odpowiedzialnosci:
- walidacja `end >= start`,
- sprawdzanie, czy data nalezy do zakresu.

Jest uzywany jako wspolny kontrakt dla:
- okna rekalkulacji,
- pelnego miesiaca.

### 6.3. `Issue`

Minimalny model issue potrzebny do raportowania:
- `key`
- `summary`

Nie modelujemy pelnego issue z Jiry, bo raport nie potrzebuje wiecej danych.

### 6.4. `WorklogEntry`

Najwazniejszy model domenowy.

Zawiera:
- `worklog_id`
- `issue_key`
- `issue_summary`
- `author_name`
- `author_account_id`
- `started_at`
- `ended_at`
- `duration_seconds`

Wazna decyzja:
- `ended_at` jest zawsze wyliczane w adapterze na podstawie `started_at + duration_seconds`

W modelu jest tez property:
- `duration_hours`

### 6.5. `DailyRawSnapshot`

Model surowego snapshotu dziennego.

Zawiera:
- `project_key`
- `snapshot_date`
- `window`
- `generated_at`
- `timezone_name`
- `worklogs`

To jest stan danych "as of today", a nie raport tylko z jednego dnia.

### 6.6. `TicketWorklogReport`

Model agregujacy worklogi dla pojedynczego ticketu.

Zawiera:
- `issue_key`
- `summary`
- `bookings`

Dodatkowo liczy:
- `total_duration_hours`

### 6.7. `MonthlyWorklogReport`

Model raportu miesiecznego.

Zawiera:
- `project_key`
- `month`
- `generated_at`
- `timezone_name`
- `tickets`

## 7. Domain ports i abstrakcje

Plik:
- `src/jirareport/domain/ports.py`

To jest kluczowy element architektury.

Zdefiniowane sa dwa protokoly:

### 7.1. `WorklogSource`

Kontrakt:

```python
fetch_worklogs(window: DateRange) -> list[WorklogEntry]
```

Use case nie wie, czy dane pochodza z:
- Jira API,
- pliku,
- fixture testowej,
- innego systemu.

Zna tylko ten interfejs.

### 7.2. `ReportStorage`

Kontrakt:

```python
write_json(path: str, payload: dict[str, Any]) -> str
```

Use case nie wie, czy zapis idzie do:
- lokalnego filesystemu,
- GCS,
- innego docelowego storage.

To jest podstawowy mechanizm separacji logiki od technologii.

## 8. Logika zakresów dat

Plik:
- `src/jirareport/domain/time_range.py`

Tu siedzi logika datowa wspolna dla calego systemu.

### 8.1. `current_date(timezone_name)`

Zwraca lokalna date dla wskazanej strefy czasowej.

To wazne, bo runner GitHub Actions dziala w UTC.

### 8.2. `month_range(month)`

Buduje pelny zakres dat dla miesiaca.

Przyklad:
- `2026-03` -> `2026-03-01` do `2026-03-31`

### 8.3. `rolling_window(reference_date)`

Buduje ruchome okno rekalkulacji:
- od pierwszego dnia poprzedniego miesiaca
- do wskazanej daty

Przyklad:
- `2026-03-11` -> `2026-02-01 .. 2026-03-11`

To jest celowa decyzja biznesowo-techniczna:
- pozwala lapac opoznione bukowania i korekty.

### 8.4. `months_in_range(window)`

Zwraca wszystkie miesiace dotkniete danym zakresem.

To pozwala use case'owi dziennemu przebudowac kilka raportow miesiecznych po jednym pobraniu raw data.

## 9. Application layer

### 9.1. Dlaczego istnieje osobna warstwa application

To tutaj siedzi:
- orkiestracja,
- skladanie modeli,
- decyzje o tym, co zapisac i pod jaka sciezka.

Nie chcemy, aby taka logika siedziala:
- w CLI,
- w adapterze Jira,
- w storage.

### 9.2. `DailySnapshotService`

Plik:
- `src/jirareport/application/services.py`

To glowny use case dzienny.

Odpowiedzialnosci:
- wyliczenie `rolling_window`,
- pobranie worklogow przez `WorklogSource`,
- utworzenie `DailyRawSnapshot`,
- zapis raw snapshot,
- przebudowa raportow miesiecznych dla miesiecy dotknietych oknem.

To najwazniejszy use case do uruchamiania codziennego joba.

Wynik zwracany jest przez:
- `DailySnapshotResult`

Zawiera on:
- sciezke snapshotu,
- sciezki raportow miesiecznych,
- liczbe worklogow.

### 9.3. `MonthlyReportService`

Drugi glowny use case.

Odpowiedzialnosci:
- wyliczenie pelnego miesiaca,
- pobranie worklogow z tego zakresu,
- zbudowanie `MonthlyWorklogReport`,
- zapis raportu JSON.

Wynik:
- `MonthlyReportResult`

### 9.4. Funkcje pomocnicze w `services.py`

Najwazniejsze:
- `_build_monthly_report()`
- `_sorted_tickets()`
- `_sort_worklogs()`
- `_daily_snapshot_path()`
- `_monthly_report_path()`

Te funkcje nie sa klasami celowo.

To jest swiadoma decyzja:
- logika jest stateless,
- nie potrzebuje osobnych obiektow,
- funkcje sa krotsze i czytelniejsze.

## 10. Serializacja JSON

Plik:
- `src/jirareport/application/serializers.py`

Ta warstwa odpowiada za mapowanie modeli domenowych do JSON payload.

Najwazniejsze funkcje:
- `serialize_worklog()`
- `serialize_daily_snapshot()`
- `serialize_monthly_report()`

Po co osobny serializer:
- use case nie miesza logiki biznesowej z formatowaniem wyjscia,
- latwiej zmienic kształt JSON bez ruszania pobierania danych,
- latwiej dopisac kolejne formaty wyjsciowe.

## 11. Infrastructure layer

### 11.1. `config.py`

Odpowiada za:
- `load_dotenv()`
- pobranie zmiennych srodowiskowych,
- zbudowanie typowanej konfiguracji.

Najwazniejsze modele konfiguracji:
- `JiraSettings`
- `StorageSettings`
- `AppSettings`

Wazna decyzja:
- konfiguracja jest od razu mapowana do dataclass,
- reszta systemu nie pracuje na surowym `os.getenv`.

### 11.2. `jira_client.py`

To adapter implementujacy port `WorklogSource`.

Klasa:
- `JiraWorklogSource`

Odpowiedzialnosci:
- budowa JQL dla okna worklogow,
- pobieranie issue z paginacja,
- pobieranie worklogow dla issue z paginacja,
- mapowanie payloadu HTTP do modeli domenowych,
- konwersja czasu do wskazanej strefy czasowej,
- retry dla requestow GET.

Wazne decyzje:

1. Klient filtruje po `worklogDate` na poziomie JQL.
2. Po stronie aplikacji i tak wykonywana jest lokalna filtracja po `started_at.date()`.
3. `started_at` jest przeliczane do strefy raportowej.
4. `ended_at` jest wyliczane lokalnie.

To jest istotne, bo granice dni i miesiecy sa liczone w `Europe/Warsaw`, a nie w surowym offsetcie z odpowiedzi Jira.

### 11.3. `storage.py`

To adapter implementujacy port `ReportStorage`.

Implementacje:
- `LocalJsonStorage`
- `GcsJsonStorage`

Factory:
- `build_storage()`

Wazne decyzje:
- use case nie tworzy sam storage,
- CLI sklada implementacje przez factory,
- JSON jest zapisywany w jednej funkcji `_to_json()`,
- backendi maja ten sam kontrakt `write_json()`.

### 11.4. `logging_config.py`

Centralna konfiguracja `loguru`.

Odpowiada za:
- usuniecie domyslnych sinkow,
- ustawienie poziomu `INFO` lub `DEBUG`,
- logowanie do stdout.

To podejscie dobrze pasuje do lokalnego uruchamiania i do GitHub Actions.

## 12. Interface layer

Plik:
- `src/jirareport/interfaces/cli/app.py`

To jest warstwa skladania aplikacji.

Odpowiedzialnosci:
- zdefiniowanie parsera CLI,
- zaladowanie konfiguracji,
- zbudowanie adapterow,
- uruchomienie odpowiedniego use case.

Komendy:
- `daily`
- `monthly`

Najwazniejsze funkcje:
- `main()`
- `_build_parser()`
- `_build_source()`
- `_run_daily()`
- `_run_monthly()`

Wazna decyzja architektoniczna:
- `_run_daily()` i `_run_monthly()` pracuja na portach `WorklogSource` i `ReportStorage`, a nie na konkretnych klasach.

To ulatwia:
- testy,
- mockowanie,
- wymiane adapterow.

## 13. Design patterns i decyzje projektowe

### 13.1. Ports and Adapters

Najwazniejszy wzorzec w projekcie.

Porty:
- `WorklogSource`
- `ReportStorage`

Adaptery:
- `JiraWorklogSource`
- `LocalJsonStorage`
- `GcsJsonStorage`

Korzyść:
- use case nie zalezy od technologii.

### 13.2. Service Layer / Use Case

Use case'y sa zaimplementowane jako klasy serwisowe:
- `DailySnapshotService`
- `MonthlyReportService`

Korzyść:
- jedna klasa = jedna odpowiedzialnosc operacyjna,
- latwo testowac bez CLI i bez realnych integracji.

### 13.3. Factory

Factory jest zastosowana w lekkiej formie:
- `build_storage()`
- `_build_source()`

Korzyść:
- skladanie zaleznosci jest skupione w jednym miejscu.

### 13.4. Value Objects

`MonthId` i `DateRange` sa de facto prostymi value objects.

Korzyść:
- mniej surowych stringow i tuple dat,
- mniej bledow na granicach miesiecy i zakresow.

### 13.5. Serializer

Serializacja JSON siedzi osobno od use case'ow.

Korzyść:
- oddzielenie modelu wewnetrznego od formatu wyjsciowego.

## 14. Dlaczego nie ma tu ciezszego DDD

Projekt jest mały i celowo unika:
- rozbudowanych agregatow,
- repozytoriow domenowych,
- event busow,
- CQRS.

To bylby przerost formy nad trescia.

Obecny poziom abstrakcji jest wystarczajacy, bo:
- use case'y sa proste,
- integracje sa nieliczne,
- domena jest relatywnie mala.

## 15. Jak rozwijac projekt

### 15.1. Dodanie nowego storage

Jesli chcesz dodac nowy backend zapisu:

1. Zaimplementuj port `ReportStorage`.
2. Dodaj implementacje w `infrastructure/storage.py` albo osobnym pliku.
3. Rozszerz `build_storage()`.
4. Dodaj testy adaptera.

### 15.2. Dodanie nowego zrodla danych

Jesli chcesz pobierac worklogi z innego systemu:

1. Zaimplementuj port `WorklogSource`.
2. Zwroc `list[WorklogEntry]`.
3. Podmien skladanie w CLI lub dodaj nowy tryb konfiguracji.

### 15.3. Dodanie Google Sheets

Rekomendowane podejscie:

1. Dodaj nowy port, jesli publikacja ma byc osobnym use case'em.
2. Dodaj adapter `GoogleSheetsPublisher` w `infrastructure`.
3. Dodaj use case typu `PublishMonthlyReportToSheets`.
4. Nie mieszaj publikacji do Sheets z adapterem Jira ani ze storage raw data.

Najlepiej zachowac ten podzial:
- Jira = pobieranie
- Storage = utrwalenie raw / derived data
- Sheets = publikacja widoku raportowego

### 15.4. Dodanie nowych formatow raportow

Jesli potrzebny bedzie:
- JSONL,
- CSV,
- payload pod Sheets,

to najlepsze miejsce to:
- osobny serializer,
- ewentualnie osobny use case publikacji.

## 16. Testy

Projekt ma:
- testy jednostkowe dla modeli, zakresow dat i uslug,
- testy adapterow storage,
- lekkie testy integracyjne dla adaptera Jira,
- testy CLI.

Aktualne narzedzia:
- `pytest`
- `pytest-cov`
- `ruff`
- `mypy`

Jakościowe bramki:
- `ruff check .`
- `mypy src tests`
- `pytest` z coverage `>= 90%`

## 17. Gdzie szukac zmian

### Jesli zmienia sie logika zakresu dat

Patrz:
- `domain/time_range.py`
- testy w `tests/unit/test_time_range.py`

### Jesli zmienia sie format JSON

Patrz:
- `application/serializers.py`
- testy use case'ow

### Jesli zmienia sie logika raportu dziennego lub miesiecznego

Patrz:
- `application/services.py`
- `tests/unit/test_services.py`

### Jesli zmienia sie integracja z Jira

Patrz:
- `infrastructure/jira_client.py`
- `tests/integration/test_jira_client.py`
- `tests/unit/test_jira_helpers.py`

### Jesli zmienia sie storage

Patrz:
- `infrastructure/storage.py`
- `tests/unit/test_storage.py`
- `tests/unit/test_storage_helpers.py`

### Jesli zmienia sie sposob uruchamiania

Patrz:
- `interfaces/cli/app.py`
- `src/jirareport/main.py`
- `.github/workflows/`

## 18. Ważne ograniczenia aktualnej wersji

Obecnie nie ma jeszcze:
- adaptera Google Sheets,
- workflow publikacji do Sheets,
- osobnego mechanizmu delta sync,
- zaawansowanego cache warstwy API.

To jest swiadomy etap projektu, nie brak przypadkowy.

## 19. Podsumowanie architektoniczne

Najwazniejsze zasady tego kodu:

- logika biznesowa nie zna technologii storage ani HTTP,
- use case'y operuja na portach,
- adaptery mapuja swiat zewnetrzny do modeli domenowych,
- CLI tylko sklada zaleznosci i uruchamia proces,
- zakresy dat i miesiecy maja osobne obiekty wartosci,
- testy i quality gates sa traktowane jako czesc implementacji.

Jesli rozwijasz ten projekt, trzymaj ten kierunek:
- nowe integracje jako adaptery,
- nowe operacje jako osobne use case'y,
- nowe formaty jako serializatory lub publishery,
- bez mieszania warstw i bez wciskania logiki biznesowej do CLI albo klientow HTTP.
