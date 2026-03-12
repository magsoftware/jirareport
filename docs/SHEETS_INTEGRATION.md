# Google Sheets Integration Specification

## 1. Document Purpose

This document describes the technical design of publishing Jira worklog reports
from `jirareport` to Google Sheets.

It focuses on the agreed model:
- Google Cloud Storage remains the canonical data store,
- Google Sheets is a reporting and presentation layer,
- one spreadsheet is maintained per calendar year.

It covers the implemented integration and the constraints that shaped it.

## 2. High-Level Model

### 2.1. Source of Truth

The source of truth remains outside Google Sheets:
- `raw/daily/YYYY/MM/YYYY-MM-DD.json` in GCS,
- `derived/monthly/YYYY/YYYY-MM.json` in GCS.

Google Sheets is a materialized reporting view built from those datasets.

### 2.2. Spreadsheet Lifecycle

Google Sheets is not expected to keep a live connection to JSON files stored in
GCS.

Instead, each synchronization run:
1. reads or reuses report data prepared by the application,
2. flattens the data into tabular form,
3. updates the target spreadsheet tabs through the Google Sheets API.

After synchronization, the sheet is a static spreadsheet with current report
content.

### 2.3. Spreadsheet Granularity

The target model is:
- one spreadsheet per calendar year,
- a stable set of tabs inside each spreadsheet,
- daily synchronization that updates only the spreadsheet years affected by the
  report window.

Examples:
- `2026-03-11` daily run usually updates only spreadsheet `2026`,
- `2026-01-05` daily run may update both spreadsheets `2025` and `2026`
  because the rolling window crosses the year boundary.

## 3. Spreadsheet Naming

### 3.1. Naming Convention

The recommended spreadsheet title format is:

```text
Jira Worklog Analytics <YEAR>
```

Examples:
- `Jira Worklog Analytics 2026`
- `Jira Worklog Analytics 2027`

### 3.2. Year Resolution

The application should determine target spreadsheet years from the processed
data, not from the execution date alone.

Rule:
- every worklog row belongs to exactly one local calendar year derived from
  `started_at` in the configured reporting timezone,
- synchronization groups rows by year,
- one synchronization run may therefore write to one or more spreadsheets.

## 4. Spreadsheet Structure

Each yearly spreadsheet should contain the following tabs:

1. `raw_worklogs`
2. `monthly_summary`
3. `daily_summary`
4. `metadata`

Optional future tabs:
- `readme`
- `ticket_summary`
- `person_summary`

The current implementation manages only the four tabs above.

## 5. Tab Specifications

## 5.1. `raw_worklogs`

### Purpose

Contains flat operational data with one row per worklog entry.

This tab is the most detailed reporting tab and should be sufficient for:
- filtering,
- pivots,
- ad hoc analysis,
- manual verification against Jira.

### Row Granularity

One row equals one worklog.

### Columns

The tab should use the following columns in the exact order:

1. `snapshot_date`
2. `window_start`
3. `window_end`
4. `generated_at`
5. `timezone`
6. `month`
7. `issue_key`
8. `summary`
9. `author`
10. `author_account_id`
11. `worklog_id`
12. `started_at`
13. `ended_at`
14. `started_date`
15. `ended_date`
16. `crosses_midnight`
17. `duration_seconds`
18. `duration_hours`

### Notes

- `month` is the local reporting month in `YYYY-MM` format.
- `crosses_midnight` must be serialized as `TRUE` or `FALSE` in a Sheets-friendly
  way.
- `summary` should contain the current issue summary known at sync time.

## 5.2. `monthly_summary`

### Purpose

Contains monthly aggregates for management and operational reporting.

### Row Granularity

One row equals:
- one month,
- one issue,
- one author.

### Columns

The tab should use the following columns in the exact order:

1. `month`
2. `issue_key`
3. `summary`
4. `author`
5. `author_account_id`
6. `entries_count`
7. `total_seconds`
8. `total_hours`

### Aggregation Rules

- `entries_count` = number of worklog rows in the group
- `total_seconds` = sum of `duration_seconds`
- `total_hours` = `total_seconds / 3600`, rounded consistently by the
  application

## 5.3. `daily_summary`

### Purpose

Contains per-day aggregates derived from raw worklogs.

### Row Granularity

One row equals:
- one day,
- one issue,
- one author.

### Columns

The tab should use the following columns in the exact order:

1. `date`
2. `month`
3. `issue_key`
4. `summary`
5. `author`
6. `author_account_id`
7. `entries_count`
8. `total_seconds`
9. `total_hours`

### Aggregation Rules

- `date` is derived from `started_date`
- the grouping key is `(started_date, issue_key, author_account_id)`
- `summary` should come from the grouped worklog rows and is expected to be
  stable for a given issue

## 5.4. `metadata`

### Purpose

Contains synchronization metadata that makes the spreadsheet self-describing.

### Row Granularity

One row per synchronization run for the given spreadsheet year.

The current implementation stores only the latest state overwritten on each run.

### Columns

The tab should use the following columns in the exact order:

1. `spreadsheet_year`
2. `last_run_at`
3. `source_snapshot_date`
4. `window_start`
5. `window_end`
6. `timezone`
7. `raw_rows_count`
8. `monthly_summary_rows_count`
9. `daily_summary_rows_count`

### Notes

- `spreadsheet_year` identifies the target yearly workbook
- `last_run_at` should use ISO 8601 without fractional seconds
- counts are limited to rows published to the current yearly spreadsheet

## 5.5. Summary Footer Rows

The `monthly_summary` and `daily_summary` tabs contain one additional footer
row:
- label: `VISIBLE_TOTALS`
- formulas based on `SUBTOTAL(109;...)` for spreadsheets using `pl_PL`
- formulas based on `SUBTOTAL(109,...)` for spreadsheets using locales with
  comma separators

This row is intentionally excluded from the sheet filter range so subtotal
values react to user filtering by author, month, date, or issue.

## 6. Data Mapping

## 6.1. Input Data Sources

The Google Sheets publisher should operate on application models or serialized
report payloads produced by existing use cases.

The expected source data is:
- daily snapshot payloads for raw rows,
- derived monthly payloads or application-level aggregates for summary tabs.

### Recommended Internal Flow

1. Generate or load report data.
2. Normalize report objects into flat row models.
3. Partition rows by calendar year.
4. Publish rows to yearly spreadsheets.

## 6.2. Mapping to `raw_worklogs`

Each worklog entry in the daily snapshot maps directly to one sheet row.

Field mapping:
- `snapshot_date` <- daily snapshot `snapshot_date`
- `window_start` <- daily snapshot `window_start`
- `window_end` <- daily snapshot `window_end`
- `generated_at` <- daily snapshot `generated_at`
- `timezone` <- daily snapshot `timezone`
- `month` <- worklog `month`
- `issue_key` <- worklog `issue_key`
- `summary` <- worklog `summary`
- `author` <- worklog `author`
- `author_account_id` <- worklog `author_account_id`
- `worklog_id` <- worklog `worklog_id`
- `started_at` <- worklog `started_at`
- `ended_at` <- worklog `ended_at`
- `started_date` <- worklog `started_date`
- `ended_date` <- worklog `ended_date`
- `crosses_midnight` <- worklog `crosses_midnight`
- `duration_seconds` <- worklog `duration_seconds`
- `duration_hours` <- worklog `duration_hours`

## 6.3. Mapping to `monthly_summary`

The `monthly_summary` tab is derived from raw worklog rows grouped by:
- `month`
- `issue_key`
- `author_account_id`

The displayed fields come from the group:
- `summary` <- the shared issue summary
- `author` <- the shared author display name
- `entries_count` <- row count
- `total_seconds` <- sum of durations
- `total_hours` <- sum of durations in hours

## 6.4. Mapping to `daily_summary`

The `daily_summary` tab is derived from raw worklog rows grouped by:
- `started_date`
- `issue_key`
- `author_account_id`

The displayed fields come from the group:
- `date` <- `started_date`
- `month` <- month derived from `started_date`
- `summary` <- the shared issue summary
- `author` <- the shared author display name
- `entries_count` <- row count
- `total_seconds` <- sum of durations
- `total_hours` <- sum of durations in hours

## 6.5. Year Partitioning

Rows must be partitioned by year before publication.

Partition key:
- year derived from `started_date`

Implications:
- a synchronization run may publish to multiple spreadsheets,
- each spreadsheet receives only rows belonging to its year,
- metadata counts must reflect only rows written to that specific spreadsheet.

## 7. Update Strategy

## 7.1. General Approach

The recommended synchronization model is `full refresh per tab`.

For each target spreadsheet year and for each managed tab:
1. prepare the full dataset for that tab,
2. clear the existing tab range,
3. write the new dataset from `A1`.

This approach is preferred over incremental append because Jira worklogs may be:
- added late,
- edited retroactively,
- corrected in previous days or months.

## 7.2. Idempotency

Synchronization must be idempotent.

Running the same synchronization twice for the same source data should produce
the same final spreadsheet contents.

## 7.3. Range Management

The first row of each tab must always be the header row.

The application should:
- write headers explicitly,
- write data starting from row 2,
- clear previous tab contents before writing the new payload.

## 7.4. Tab Creation

The publisher should create missing tabs automatically if they do not exist.

Required tabs for automatic creation:
- `raw_worklogs`
- `monthly_summary`
- `daily_summary`
- `metadata`

## 7.5. Sorting Rules

To keep output stable and human-readable, rows should be sorted before upload.

Recommended sorting:

`raw_worklogs`
- `started_at` ascending
- `issue_key` ascending
- `author` ascending

`monthly_summary`
- `month` ascending
- `issue_key` ascending
- `author` ascending

`daily_summary`
- `date` ascending
- `issue_key` ascending
- `author` ascending

## 7.6. Year Boundary Behavior

If the rolling window crosses a year boundary:
- data must be split by year,
- both yearly spreadsheets must be updated in one run.

Example:
- reference date: `2026-01-05`
- rolling window: `2025-12-01 .. 2026-01-05`

Expected result:
- spreadsheet `2025` receives December 2025 rows from the current snapshot,
- spreadsheet `2026` receives January 2026 rows from the current snapshot.

## 8. Spreadsheet Discovery and Ownership

## 8.1. Recommended Ownership Model

The recommended operational model is:
- spreadsheets are created manually once,
- spreadsheets are owned by a human or a shared business account,
- the service account is granted `Editor` access.

This avoids lifecycle and ownership issues caused by automation-created files.

## 8.2. Spreadsheet Discovery

The current implementation resolves spreadsheets by configuration first and
creates missing yearly spreadsheets when necessary.

Current model:
- one configured spreadsheet ID per year when available
- if no yearly ID exists, the application creates a spreadsheet named
  `Jira Worklog Analytics <YEAR>` or `<GOOGLE_SHEETS_TITLE_PREFIX> <YEAR>`
- no Drive-based lookup by title during runtime

## 9. Configuration Requirements

## 9.1. Required Variables

The following configuration inputs are required for Google Sheets
integration:

- `GOOGLE_SHEETS_ENABLED`
- `GOOGLE_SHEETS_TITLE_PREFIX`
- `config/spaces.yaml`

At minimum, the application needs a way to resolve:
- whether Sheets publishing is enabled,
- which spreadsheet ID belongs to which space and year.

## 9.2. Recommended Variable Naming

Because the system is designed around yearly spreadsheets and multiple Jira
spaces, the implemented approach is:

```yaml
spaces:
  - key: LA004832
    name: Click Price
    slug: click-price
    google_sheets_ids:
      2026: <spreadsheet-id>

  - key: LA009644
    name: Data Fixer
    slug: data-fixer
    google_sheets_ids:
      2026: <spreadsheet-id>
```

This keeps resolution explicit and avoids runtime ambiguity between spaces.

## 9.3. Authentication

Local development:
- `GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account-key.json`

CI and GitHub Actions:
- Google Workload Identity Federation through
  `google-github-actions/auth`

## 9.4. Future Optional Variables

Optional future variables may include:
- `GOOGLE_SHEETS_CREATE_MISSING_TABS=true`
- `GOOGLE_SHEETS_RAW_TAB_NAME=raw_worklogs`
- `GOOGLE_SHEETS_MONTHLY_TAB_NAME=monthly_summary`
- `GOOGLE_SHEETS_DAILY_TAB_NAME=daily_summary`
- `GOOGLE_SHEETS_METADATA_TAB_NAME=metadata`

The current implementation keeps tab names fixed in code.

## 10. Implementation Recommendations

## 10.1. Architecture

The implementation should follow the existing project structure:
- domain ports for publisher abstractions,
- application service for synchronization use cases,
- infrastructure adapter for the Google Sheets API,
- CLI command for explicit publishing.

Recommended additions:
- `domain/ports.py` -> spreadsheet publishing protocol
- `application/services.py` -> sheet publishing use case
- `infrastructure/google/sheets_client.py` -> Sheets adapter
- `interfaces/cli/app.py` -> `sync sheets` command

## 10.2. Synchronization Command

The implemented CLI action is:

```text
jirareport sync sheets --date YYYY-MM-DD
```

This is preferred over bundling Sheets publishing directly into `daily` because:
- debugging is easier,
- failures are isolated,
- rollout can be staged.

A future enhancement may allow:
- `daily --publish-sheets`

## 10.3. Error Handling

The publisher should:
- fail loudly on authentication problems,
- fail loudly on missing spreadsheet configuration,
- retry transient Google API errors,
- log the year, tab name, and row counts for every upload.

## 11. Acceptance Criteria

The current implementation satisfies all of the following:

1. The system can publish raw worklogs to a yearly spreadsheet.
2. The system can publish `monthly_summary`.
3. The system can publish `daily_summary`.
4. The system can publish `metadata`.
5. Missing tabs are created automatically.
6. The same synchronization can be rerun without producing duplicate rows.
7. A synchronization run that crosses a year boundary updates all affected
   yearly spreadsheets.
8. The integration is covered by automated tests and preserves the project
   coverage gate.

## 12. Out of Scope for the First Version

The following items remain intentionally out of scope:
- rich spreadsheet formatting,
- charts and dashboards,
- formulas managed by the application,
- Drive-based spreadsheet search,
- user-managed append-only histories inside Sheets,
- cross-spreadsheet formulas,
- bidirectional sync from Sheets back to GCS or Jira.
