# PRD - JiraReport

## 1. Cel dokumentu

Ten dokument opisuje aktualne wymagania produktowe dla `jirareport`.

Nadrzedny cel narzedzia:
- dostarczac wiarygodny raport worklogow z Jira dla wskazanych przestrzeni biznesowych,
- zachowac kanoniczne dane poza Google Sheets,
- umozliwic codzienna rekalkulacje danych z uwzglednieniem opoznionych bukowan i korekt,
- przygotowac dane do dalszej analityki w BigQuery.

Dokument obejmuje:
- problem biznesowy,
- glownych uzytkownikow i ich potrzeby,
- zakres funkcjonalny,
- wymagania danych i raportowania,
- wymagania integracyjne,
- kryteria akceptacji.

## 2. Problem biznesowy

Organizacja potrzebuje stabilnego sposobu raportowania czasu zabukowanego w Jira:
- per space,
- per ticket,
- per osoba,
- per dzien,
- per miesiac.

Glowny problem:
- worklogi nie sa wpisywane tylko "na biezaco",
- pracownicy czesto bokuja czas wstecz,
- starsze wpisy moga byc poprawiane,
- raport miesieczny zbudowany przez proste dopisywanie nowych rekordow bylby bledny.

Wniosek biznesowy:
- raportowanie musi byc oparte na rekalkulacji calego okna danych,
- Google Sheets nie moze byc jedynym zrodlem danych,
- potrzebna jest oddzielna warstwa archiwizacji i warstwa publikacji.

## 3. Uzytkownicy i odbiorcy

Glowne grupy odbiorcow:
- liderzy i managerowie potrzebujacy widoku godzin per ticket / osoba / miesiac,
- osoby operacyjne weryfikujace konkretne worklogi,
- analitycy i developerzy potrzebujacy danych do dalszego przetwarzania,
- automaty GitHub Actions uruchamiajace proces raportowy.

## 4. Zakres produktu

## 4.1. Funkcje w zakresie

Produkt ma umiec:
- pobierac worklogi z Jira dla wielu skonfigurowanych spaces,
- generowac dzienny snapshot raw,
- generowac raporty miesieczne JSON,
- generowac kuratorowane miesieczne datasety Parquet,
- publikowac dane do Google Sheets,
- ladowac miesieczne datasety Parquet do BigQuery,
- obslugiwac lokalny storage i Google Cloud Storage,
- uruchamiac wszystko przez CLI i workflow automatyczne.

## 4.2. Funkcje poza zakresem

Poza zakresem biezacej wersji pozostaja:
- edycja danych w Jira lub w arkuszach,
- workflow akceptacji godzin,
- raportowanie kosztowe, billingowe lub fakturowe,
- dashboardy i wykresy zarzadzane przez aplikacje,
- synchronizacja zwrotna z Sheets do Jira albo do storage.

## 5. Model biznesowy danych

## 5.1. Zrodlo prawdy

Zrodlem prawdy sa worklogi z Jira.

Pojedynczy rekord raportowy musi zawierac co najmniej:
- `worklog_id`,
- `issue_key`,
- `summary`,
- `issue_type`,
- `author`,
- `author_account_id`,
- `started_at`,
- `ended_at`,
- `started_date`,
- `ended_date`,
- `duration_seconds`,
- `duration_hours`.

## 5.2. Strefa czasowa

Wszystkie granice dni, miesiecy i lat musza byc liczone w jawnie skonfigurowanej strefie czasowej.

Domyslna strefa:
- `Europe/Warsaw`

Powod:
- runner CI dziala niezaleznie od lokalnej strefy,
- rok / miesiac / dzien raportowy musza byc wyliczane deterministycznie.

## 5.3. Space jako podstawowa jednostka biznesowa

Narzedzie nie raportuje calej Jira "hurtowo".

Raportowanie jest organizowane per skonfigurowany `space`, identyfikowany przez:
- `key`,
- `name`,
- `slug`.

Kazdy `space` ma:
- osobny zakres biznesowy,
- osobne artefakty raportowe,
- osobne mapowanie do Google Sheets,
- wspolny zestaw kredencjali Jira.

## 6. Wymagania raportowe

## 6.1. Daily raw snapshot

`daily` musi tworzyc snapshot typu "stan na dany dzien", a nie raport tylko z jednego dnia.

Wymagania:
- jeden rekord = jeden worklog,
- zapis do JSON,
- snapshot przechowuje date uruchomienia, okno danych i metadane strefy czasowej,
- kolejne uruchomienia tworza kolejne pliki, nie nadpisuja historii.

Sciezka logiczna:
- `spaces/<space_key>/<space_slug>/raw/daily/YYYY/MM/YYYY-MM-DD.json`

## 6.2. Raport miesieczny JSON

`monthly` oraz `daily` musza materializowac raport miesieczny:
- dla jednego miesiaca,
- grupowany per ticket,
- z zachowaniem szczegolowych bookings.

Sciezka logiczna:
- `spaces/<space_key>/<space_slug>/derived/monthly/YYYY/YYYY-MM.json`

Semantyka:
- plik miesieczny jest widokiem pochodnym,
- kolejne przeliczenia tego samego miesiaca nadpisuja poprzedni plik.

## 6.3. Curated monthly dataset

Kazdy raport miesieczny musi miec rowniez plaski odpowiednik analityczny.

Wymagania:
- format `Parquet`,
- jeden rekord = jeden worklog,
- przeznaczenie: BigQuery i dalsza analityka,
- dane musza byc stabilne i deterministyczne.

Sciezka logiczna:
- `curated/worklogs/space=<space_slug>/year=YYYY/month=MM/worklogs.parquet`

## 7. Reguly pobierania danych

## 7.1. Model operacyjny

Glowny codzienny przebieg korzysta z `rolling_window(reference_date)`.

Regula domyslna:
- od pierwszego dnia poprzedniego miesiaca do `reference_date` wlacznie.

Przyklad:
- `2026-03-14` -> zakres `2026-02-01 .. 2026-03-14`

## 7.2. Regula specjalna na pierwszy dzien miesiaca

Pierwszego dnia miesiaca obowiazuje specjalny tryb:
- okno startuje od pierwszego dnia miesiaca sprzed dwoch miesiecy,
- okno konczy sie na ostatnim dniu poprzedniego miesiaca.

Przyklad:
- `2026-04-01` -> zakres `2026-02-01 .. 2026-03-31`

Znaczenie biznesowe:
- run na 1. dzien miesiaca domyka poprzedni miesiac,
- nie miesza jeszcze danych z nowego miesiaca do operacyjnego okna dwu-miesiecznego.

## 7.3. Backfill

Produkt musi obslugiwac rekalkulacje historyczna przez jawnie wskazany zakres dat.

Wymagania:
- zakres jest inkluzywny,
- system przelicza wszystkie miesiace dotkniete zakresem,
- wynik nie tworzy daily raw snapshot, tylko odswieza materializacje miesieczne.

## 8. Wymagania dla Google Sheets

## 8.1. Rola Google Sheets

Google Sheets jest warstwa publikacji i pracy operacyjnej.

Nie jest:
- magazynem kanonicznym,
- zrodlem prawdy,
- miejscem archiwizacji historii uruchomien.

## 8.2. Model publikacji

Aktualny model publikacji:
- jeden spreadsheet per `space` per rok,
- w spreadsheetcie sa zakladki miesieczne o nazwach `01`, `02`, ..., `12`,
- kazda zakladka zawiera surowe worklogi dla jednego miesiaca nalezacego do danego roku.

Nie ma obecnie:
- zakladki `monthly_summary`,
- zakladki `daily_summary`,
- zakladki `metadata`.

## 8.3. Rozdzial po latach

Jedno uruchomienie `sync sheets` moze aktualizowac wiecej niz jeden spreadsheet roczny.

Przyklad:
- zakres `2025-12-01 .. 2026-01-05`
- aktualizowane sa spreadsheety dla lat `2025` i `2026`

## 8.4. Tworzenie nowych spreadsheetow

Jesli dla danego `space` i roku nie ma skonfigurowanego spreadsheet ID:
- aplikacja moze utworzyc nowy spreadsheet,
- musi zalogowac URL i ID,
- ID powinno zostac potem dopisane do `config/spaces.yaml`.

## 9. Wymagania dla BigQuery

BigQuery jest wtornym celem publikacji dla danych kuratorowanych.

Wymagania:
- ladowanie odbywa sie z miesiecznych plikow Parquet,
- ladowanie jest per `space` i `month`,
- przed zaladowaniem system usuwa poprzedni slice dla danego `space` i miesiaca,
- system musi pilnowac braku duplikatow `worklog_id`,
- po zaladowaniu musza zostac odswiezone widoki raportowe.

## 10. Wymagania konfiguracji

Produkt musi umiec ladowac:
- kredencjale Jira z `.env`,
- backend storage,
- konfiguracje time zone,
- liste spaces z `config/spaces.yaml`,
- mapowanie `google_sheets_ids` per `space` i rok,
- opcjonalna konfiguracje BigQuery.

Walidacja konfiguracji musi wykrywac:
- brak wymaganych zmiennych srodowiskowych,
- pusty lub bledny `spaces.yaml`,
- zduplikowane `key` i `slug`,
- niepoprawne mapowanie arkuszy rocznych.

## 11. Wymagania niefunkcjonalne

System musi:
- dzialac deterministycznie dla tych samych danych wejsciowych,
- byc idempotentny dla `monthly`, `backfill`, `sync sheets` i `sync bigquery`,
- logowac start, koniec i wolumen danych,
- byc testowalny przez fake adaptery bez prawdziwej sieci,
- wspierac uruchomienie lokalne i z GitHub Actions.

## 12. Krytyczne decyzje produktowe

Przyjete decyzje:
- canonical storage pozostaje poza Google Sheets,
- operacyjny zakres raportowy obejmuje dwa miesiace z regula specjalna na 1. dzien miesiaca,
- raportowanie jest organizowane per `space`,
- JSON sluzy do czytelnych artefaktow raportowych,
- Parquet sluzy do analityki i BigQuery,
- Sheets i BigQuery sa niezaleznymi targetami publikacji,
- `sync sheets` jest osobnym krokiem, a nie ukryta czescia `daily`.

## 13. Kryteria akceptacji

Wersja produktu spelnia wymagania, jezeli:

1. `daily` dla wybranego `space` zapisuje snapshot raw i odswieza wszystkie miesiace objete oknem.
2. `monthly` generuje pojedynczy raport miesieczny i odpowiadajacy mu Parquet.
3. `backfill` przelicza wszystkie miesiace dotkniete historycznym zakresem.
4. `sync sheets` publikuje miesieczne zakladki roczne dla wszystkich lat obecnych w zakresie.
5. `sync bigquery` laduje miesieczne Parquety i odswieza widoki.
6. Dane sa rozdzielone per `space`, a nie mieszane miedzy projektami.
7. Storage lokalny i GCS sa zamienne z perspektywy use-case'ow.
8. Strefa czasowa jest jawna i decyduje o przynaleznosci worklogu do dnia, miesiaca i roku.
