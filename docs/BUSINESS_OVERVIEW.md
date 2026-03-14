# BUSINESS_OVERVIEW - opis biznesowy narzedzia

## 1. Czym jest to narzedzie

`jirareport` to narzedzie operacyjno-raportowe do pozyskiwania, porzadkowania i publikowania danych o czasie pracy zabukowanym w Jira.

Biznesowo narzedzie robi trzy rzeczy:
- odzyskuje wiarygodny obraz worklogow z Jira,
- materializuje ten obraz do trwalych artefaktow raportowych,
- dostarcza dane do odbiorcow operacyjnych i analitycznych.

Nie jest to narzedzie do planowania pracy ani do zarzadzania taskami. Jego rola zaczyna sie w momencie, w ktorym worklog istnieje w Jira i trzeba go pokazac lub przetworzyc raportowo.

## 2. Jaki problem rozwiazuje

W organizacji istnieje potrzeba odpowiedzi na pytania:
- ile godzin zostalo zabukowanych w danym miesiacu,
- przez kogo,
- na jakich ticketach,
- w ktorych spaces,
- jak zmienial sie obraz miesiaca w czasie,
- jakie dane przekazac do dalszej analityki.

Najwiekszy problem biznesowy polega na tym, ze worklogi sa opozniane i korygowane:
- pracownik moze wpisac godziny za wczoraj,
- moze wpisac godziny za poczatek miesiaca kilka dni pozniej,
- moze poprawic stary wpis,
- moze zamknac poprzedni miesiac dopiero w nowym miesiacu.

To oznacza, ze prosty raport "dopisuj tylko nowy dzien" jest niepoprawny. Narzedzie rozwiazuje ten problem przez codzienna rekalkulacje odpowiedniego okna danych.

## 3. Glowna wartosc biznesowa

Najwazniejsze wartosci biznesowe:
- wiarygodnosc raportu mimo opoznionych bukowan,
- rozdzielenie warstwy danych od warstwy prezentacji,
- mozliwosc pracy operacyjnej w Google Sheets,
- przygotowanie danych do hurtowni i analityki,
- obsluga wielu spaces bez mieszania danych.

## 4. Aktorzy biznesowi

Glowne role:
- manager / team lead: chce zobaczyc godziny per miesiac, osoba, ticket,
- PM / owner space: chce rozumiec obciazenie i postep w swoim obszarze,
- osoba operacyjna: chce zweryfikowac konkretne worklogi i ich daty,
- analityk / data team: chce miec uporzadkowany dataset do BigQuery,
- developer / maintainer: chce niezawodnie uruchamiac i rozwijac proces,
- automation / GitHub Actions: wykonuje cykliczne przebiegi bez udzialu czlowieka.

## 5. Glowny use-case

Glowny use-case:
- codzienne odswiezenie raportow worklogow dla wszystkich aktywnych spaces.

Przeplyw biznesowy:
1. Scheduler uruchamia proces.
2. Narzedzie pobiera worklogi z operacyjnego okna czasowego.
3. Zapisuje surowy snapshot na potrzeby audytu i historii uruchomienia.
4. Przelicza miesiace objete oknem.
5. Odswieza materializacje miesieczne.
6. Opcjonalnie publikuje dane do Google Sheets.
7. Opcjonalnie publikuje dane do BigQuery.

Rezultat biznesowy:
- zespol ma aktualny obraz godzin z uwzglednieniem opoznionych i skorygowanych wpisow.

## 6. Pozostale use-case'y biznesowe

## 6.1. Rekalkulacja jednego miesiaca

Scenariusz:
- trzeba odtworzyc lub sprawdzic jeden konkretny miesiac.

Przyklady:
- domkniecie miesiaca po poznych korektach,
- kontrola danych po incydencie,
- lokalna analiza developera.

Rezultat:
- odswiezony raport miesieczny JSON i Parquet dla jednego miesiaca.

## 6.2. Backfill historyczny

Scenariusz:
- trzeba odtworzyc duzy zakres danych historycznych.

Przyklady:
- pierwsze zasilenie nowego storage,
- migracja,
- naprawa po blednej konfiguracji lub awarii.

Rezultat:
- wszystkie miesiace dotkniete zakresem zostaja przeliczone od nowa.

## 6.3. Publikacja do Google Sheets

Scenariusz:
- odbiorcy biznesowi chca pracowac na danych w arkuszu.

Rezultat:
- dane sa dostepne w znanym interfejsie,
- mozna filtrowac po miesiacu, autorze, ticketach i datach,
- arkusz jest aktualnym widokiem operacyjnym, ale nie zrodlem prawdy.

## 6.4. Publikacja do BigQuery

Scenariusz:
- dane maja trafic do warstwy analitycznej.

Rezultat:
- miesieczne worklogi sa ladowane do tabeli faktowej,
- widoki raportowe sa odswiezane,
- dane sa gotowe do downstream analytics.

## 6.5. Audyt pojedynczego worklogu

Scenariusz rzadszy, ale praktyczny:
- trzeba potwierdzic, czy konkretny worklog byl widoczny w danym uruchomieniu.

Rezultat:
- mozna sprawdzic raw snapshot JSON dla konkretnej daty uruchomienia,
- mozna porownac go z derived monthly i z arkuszem.

## 6.6. Diagnostyka granic miesiecy i lat

Scenariusz:
- worklog znajduje sie blisko polnocy, konca miesiaca albo konca roku.

Rezultat:
- system przypisuje go wedlug lokalnej strefy raportowej,
- mozna uruchomic jawny zakres i zweryfikowac zachowanie.

## 6.7. Obsluga nowego space

Scenariusz:
- do raportowania dochodzi nowy obszar biznesowy.

Rezultat:
- po dodaniu wpisu do `config/spaces.yaml` narzedzie zaczyna generowac dla niego komplet artefaktow,
- space moze miec osobne spreadsheety roczne.

## 6.8. Automatyczne utworzenie spreadsheetu rocznego

Scenariusz rzadki:
- pojawia sie nowy rok albo nowy space i nie ma jeszcze spreadsheet ID.

Rezultat:
- aplikacja tworzy spreadsheet,
- loguje URL,
- maintainer dopisuje ID do konfiguracji.

## 6.9. Idempotentny rerun po bledzie

Scenariusz:
- poprzedni run nie skonczyl sie poprawnie lub trzeba go powtorzyc.

Rezultat:
- raw snapshot dla danego dnia moze zostac wygenerowany ponownie,
- derived monthly i publikacje zewnetrzne sa nadpisywane, nie appendowane,
- system wraca do spojnego stanu.

## 7. Use-case'y wedlug czestotliwosci

Najczestsze:
- codzienny `daily`,
- regularny `sync sheets`.

Srednio czeste:
- `monthly`,
- `sync bigquery`.

Rzadsze:
- `backfill`,
- audyty historyczne,
- publikacje po jawnych zakresach.

Najrzadsze, ale istotne:
- obsluga pierwszego dnia miesiaca,
- sync przez granice roku,
- automatyczne utworzenie nowego spreadsheetu,
- diagnoza wpisow crossing midnight.

## 8. GLOWNE FLOW BIZNESOWE

## 8.1. Flow operacyjny dzienny

To najwazniejszy flow calego produktu.

1. System wybiera dzien referencyjny.
2. Wylicza okno obejmujace poprzedni miesiac i biezacy miesiac do dnia uruchomienia.
3. Jesli to pierwszy dzien miesiaca, zamiast tego domyka dwa poprzednie miesiace.
4. Pobiera worklogi z Jira dla wszystkich wybranych spaces.
5. Buduje snapshot raw.
6. Buduje miesieczne materializacje.
7. Udostepnia wynik dalej do pracy operacyjnej i analityki.

## 8.2. Flow publikacji do Sheets

1. System pobiera aktualny snapshot logiczny z Jira.
2. Rozdziela dane po latach.
3. Dla kazdego roku rozwiazuje odpowiedni spreadsheet.
4. Dla kazdego miesiaca przygotowuje zakladke raw.
5. Nadpisuje cala zawartosc zakladek.

Wartosc biznesowa:
- odbiorca widzi aktualny obraz danych bez potrzeby recznego importu.

## 8.3. Flow publikacji do BigQuery

1. System odczytuje miesieczne pliki Parquet.
2. Dla kazdego miesiaca wymienia slice w tabeli.
3. Odnawia widoki raportowe.

Wartosc biznesowa:
- dane sa gotowe do szerszej analityki i laczenia z innymi zbiorami.

## 8.4. Flow odtworzeniowy / naprawczy

1. Operator wskazuje miesiac albo zakres.
2. System pobiera dane historyczne.
3. Przelicza wszystkie potrzebne miesiace.
4. Opcjonalnie republikuje wynik do targetow zewnetrznych.

Wartosc biznesowa:
- mozna bezpiecznie odtworzyc stan po bledzie lub zmianie logiki.

## 9. Integracje biznesowe

## 9.1. Jira

Rola:
- system zrodlowy dla worklogow.

Dostarczane informacje:
- issue,
- summary,
- issue type,
- autor wpisu,
- czas rozpoczecia,
- czas trwania.

## 9.2. Local / GCS storage

Rola:
- trwale przechowywanie artefaktow raportowych.

Znaczenie biznesowe:
- historia uruchomien,
- audyt,
- niezaleznosc od Google Sheets,
- mozliwosc odtworzen i integracji downstream.

## 9.3. Google Sheets

Rola:
- warstwa prezentacji i operacyjnej pracy na danych.

Znaczenie biznesowe:
- latwy dostep dla nietechnicznych odbiorcow,
- filtrowanie i szybkie analizy bez SQL.

## 9.4. BigQuery

Rola:
- warstwa analityczna.

Znaczenie biznesowe:
- dalsze raportowanie,
- laczenie z innymi danymi,
- bardziej zaawansowane agregacje niz w arkuszu.

## 9.5. GitHub Actions

Rola:
- automatyczne uruchamianie procesu.

Znaczenie biznesowe:
- regularnosc,
- brak zaleznosci od recznego odpalania,
- powtarzalnosc procesu.

## 10. Artefakty biznesowe i ich znaczenie

## 10.1. Raw snapshot JSON

Znaczenie:
- audyt uruchomienia,
- odpowiedz na pytanie "co system widzial tego dnia",
- diagnostyka roznic miedzy uruchomieniami.

## 10.2. Derived monthly JSON

Znaczenie:
- czytelny raport miesieczny per ticket,
- materializacja do lokalnej inspekcji lub integracji.

## 10.3. Curated monthly Parquet

Znaczenie:
- stabilny dataset maszynowy do downstream analytics.

## 10.4. Spreadsheet roczny

Znaczenie:
- aktualny widok operacyjny dla odbiorcow biznesowych.

## 11. Najwazniejsze reguly biznesowe

1. Worklog nalezy do dnia, miesiaca i roku wedlug lokalnej strefy raportowej.
2. Google Sheets nie jest source of truth.
3. Raport miesieczny jest widokiem pochodnym, nie jedynym miejscem przechowywania danych.
4. Codzienny run ma korygowac opoznione i poprawione wpisy, a nie tylko dopisywac nowe.
5. Dane musza byc rozdzielone per `space`.
6. Publikacje zewnetrzne maja byc idempotentne.

## 12. Ryzyka biznesowe, ktore narzedzie ogranicza

Narzedzie zmniejsza ryzyko:
- blednych raportow wynikajacych z opoznionych wpisow,
- utraty danych przez trzymanie ich tylko w arkuszu,
- mieszania danych miedzy spaces,
- niekontrolowanego appendowania duplikatow do raportow,
- braku mozliwosci odtworzenia i audytu.

## 13. Czego narzedzie nie rozwiazuje

Narzedzie nie rozwiazuje:
- czy czas zostal zabukowany "prawidlowo biznesowo",
- czy worklog powinien zostac zatwierdzony,
- czy ticket byl wlasciwie skategoryzowany,
- jak przeliczyc godziny na koszty lub przychody.

To jest narzedzie raportowe nad danymi z Jira, nie system rozliczeniowy.
