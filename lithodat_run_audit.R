#!/usr/bin/env Rscript
# =====================================================================
# lithodat_run_audit.R
#
# Driver for the LithoDat deterministic QC audit on criticalmineralsexp.
# Runs the 9 checks defined in lithodat_qc_schema.sql, scoped to one
# region (country / division) or the whole database, against either
# analytical_results (the normalized table) or geochem_export_detail
# (the flattened export table — see notes in lithodat_qc_schema.sql
# section 6 for how identity, unit codes, and "package" are handled
# differently there; division scope is not available on that table).
#
# One-time setup (run once, or whenever lithodat_qc_schema.sql changes):
#   psql "$LITHODAT_DB_URL" -f lithodat_qc_schema.sql
#
# Usage:
#   Rscript lithodat_run_audit.R --target analytical_results   --scope-type country  --scope-value Greenland
#   Rscript lithodat_run_audit.R --target analytical_results   --scope-type division --scope-value Tasmania
#   Rscript lithodat_run_audit.R --target geochem_export_detail --scope-type country --scope-value Greenland
#   Rscript lithodat_run_audit.R --scope-type global   # target defaults to analytical_results
#   Rscript lithodat_run_audit.R --scope-type country --scope-value Finland \
#       --datasource "Geological Survey of Finland" --sample-type-id 31   # Finland Rock only
#
# Or source it and call run_lithodat_audit() interactively.
#
# Connection is read from environment variables, loaded from a .env file
# (working directory, then this script's own directory) if present, so
# credentials never live in the script itself:
#   LITHODAT_DB_HOST, LITHODAT_DB_PORT, LITHODAT_DB_NAME,
#   LITHODAT_DB_USER, LITHODAT_DB_PASSWORD
# =====================================================================

suppressPackageStartupMessages({
  library(DBI)
  library(RPostgres)
})

#' Load LITHODAT_DB_* (and anything else) from a .env file into the process
#' environment, mirroring the Python loaders' load_dotenv() - checks the
#' working directory first, then this script's own directory. Only sets a
#' variable if it isn't already set (real env vars win), and never prints
#' values.
.load_dotenv <- function() {
  candidates <- c(file.path(getwd(), ".env"))
  script_path <- tryCatch(sys.frame(1)$ofile, error = function(e) NULL)
  if (!is.null(script_path)) {
    candidates <- c(candidates, file.path(dirname(normalizePath(script_path)), ".env"))
  }
  for (env_file in candidates) {
    if (!file.exists(env_file)) next
    lines <- readLines(env_file, warn = FALSE)
    for (line in lines) {
      line <- trimws(line)
      if (line == "" || startsWith(line, "#") || !grepl("=", line, fixed = TRUE)) next
      parts <- strsplit(line, "=", fixed = TRUE)[[1]]
      key <- trimws(parts[1])
      value <- trimws(paste(parts[-1], collapse = "="))
      value <- gsub('^["\']|["\']$', "", value)
      if (nzchar(value) && identical(Sys.getenv(key), "")) {
        do.call(Sys.setenv, setNames(list(value), key))
      }
    }
    break
  }
}
.load_dotenv()

#' DBI's params=list(...) binding (as used here with RPostgres) requires
#' every element to have length exactly 1 - a raw R NULL has length 0 and
#' fails with "Parameter N does not have length 1" (confirmed: this broke
#' the plain --scope-type global case, where scope_value is NULL). Coerce
#' NULL to NA so optional text params bind as real SQL NULLs instead.
.na_if_null <- function(x) if (is.null(x)) NA_character_ else x

#' Best-effort current-user name for the audit_runs.run_by column.
#' Sys.getenv("USER") is empty on Windows (which sets USERNAME instead) -
#' check both before falling back to a generic label.
.default_run_by <- function() {
  for (var in c("USER", "USERNAME")) {
    val <- Sys.getenv(var)
    if (nzchar(val)) return(val)
  }
  "r_script"
}

lithodat_connect <- function() {
  dbConnect(
    RPostgres::Postgres(),
    host     = Sys.getenv("LITHODAT_DB_HOST", "localhost"),
    port     = as.integer(Sys.getenv("LITHODAT_DB_PORT", "5432")),
    dbname   = Sys.getenv("LITHODAT_DB_NAME", "criticialmineralsexp"),
    user     = Sys.getenv("LITHODAT_DB_USER"),
    password = Sys.getenv("LITHODAT_DB_PASSWORD")
  )
}

#' Run the deterministic QC audit for one scope, against either target table
#'
#' @param target      "analytical_results" (default) or "geochem_export_detail"
#' @param scope_type  "global", "country", or "division". "division" is only
#'                     valid when target = "analytical_results" —
#'                     geochem_export_detail has no state/province column.
#' @param scope_value e.g. "Greenland" (country) or "Tasmania" (division);
#'                     NULL for scope_type = "global"
#' @param audit_label  optional free-text label stored on the run
#' @param datasource   optional further filter on locations.datasource
#'                      (analytical_results) / geochem_export_detail.datasource,
#'                      e.g. "GEUS - Geological Survey of Denmark and Greenland".
#'                      Only meaningful for target = "analytical_results" today.
#' @param sample_type_id optional further filter on samples.sample_type_id -
#'                      a single value or vector, e.g. 31 for GTK Finland
#'                      Rock (ROCK_SURFACE) vs. TILL/SEDIMENT under the same
#'                      country+datasource, or c(2,13,14,70,71,72) for all
#'                      SOIL-category types (Resources Victoria). Only
#'                      meaningful for target = "analytical_results" -
#'                      geochem_export_detail has no samples join.
#' @param con          optional existing DBI connection; a new one is
#'                      opened and closed automatically if omitted
#' @return a list with run_id, target, run_meta (1-row data.frame), and
#'         summary (rule-by-rule flag counts)
run_lithodat_audit <- function(target = c("analytical_results", "geochem_export_detail"),
                                scope_type = c("global", "country", "division"),
                                scope_value = NULL,
                                audit_label = NULL,
                                datasource = NULL,
                                sample_type_id = NULL,
                                con = NULL) {
  target <- match.arg(target)
  scope_type <- match.arg(scope_type)
  if (scope_type != "global" && is.null(scope_value)) {
    stop("scope_value is required when scope_type is '", scope_type, "'")
  }
  if (target == "geochem_export_detail" && scope_type == "division") {
    stop("scope_type = 'division' is not supported for geochem_export_detail ",
         "(no state/province column on that table) — use 'country' or 'global'")
  }
  if (target == "geochem_export_detail" && !is.null(sample_type_id)) {
    stop("sample_type_id is not supported for geochem_export_detail (no samples join on that table)")
  }

  close_con <- FALSE
  if (is.null(con)) {
    con <- lithodat_connect()
    close_con <- TRUE
  }
  if (close_con) on.exit(dbDisconnect(con), add = TRUE)

  message(sprintf("Running lithodat deterministic audit — target: %s, scope: %s%s%s%s",
                   target, scope_type,
                   if (!is.null(scope_value)) paste0(" = ", scope_value) else "",
                   if (!is.null(datasource)) paste0(", datasource = ", datasource) else "",
                   if (!is.null(sample_type_id)) paste0(", sample_type_id = ", paste(sample_type_id, collapse = ",")) else ""))

  # lithodat_run_deterministic_audit takes 6 args (scope_type, scope_value,
  # audit_label, run_by, datasource, sample_type_id integer[]); the
  # geochem_export_detail variant doesn't support either filter, so it's
  # called with 4. RPostgres's params=list(...) treats a multi-element
  # vector as several rows to bind, not a single array value (confirmed:
  # "Parameter 6 does not have length 1") - so the array is built as a
  # Postgres array-literal string ('{2,13,14}') and cast with ::integer[]
  # in the SQL instead of relying on vector auto-binding.
  run_id <- if (target == "analytical_results") {
    sample_type_id_literal <- if (is.null(sample_type_id)) NA_character_ else
      paste0("{", paste(as.integer(sample_type_id), collapse = ","), "}")
    dbGetQuery(
      con,
      "SELECT lithodat_run_deterministic_audit($1, $2, $3, $4, $5, $6::integer[]) AS run_id",
      params = list(scope_type, .na_if_null(scope_value), .na_if_null(audit_label), .default_run_by(),
                    .na_if_null(datasource), sample_type_id_literal)
    )$run_id
  } else {
    dbGetQuery(
      con,
      "SELECT lithodat_run_deterministic_audit_ged($1, $2, $3, $4) AS run_id",
      params = list(scope_type, .na_if_null(scope_value), .na_if_null(audit_label), .default_run_by())
    )$run_id
  }

  run_meta <- dbGetQuery(con, "SELECT * FROM lithodat_audit_runs WHERE run_id = $1", params = list(run_id))

  flags_table <- if (target == "analytical_results") "lithodat_audit_flags" else "lithodat_audit_flags_ged"

  summary <- dbGetQuery(con, sprintf("
    SELECT f.rule_code, f.tier, r.rule_name, count(*) AS n_flagged
    FROM %s f
    JOIN lithodat_flag_rules r ON r.rule_code = f.rule_code
    WHERE f.run_id = $1
    GROUP BY f.rule_code, f.tier, r.rule_name
    ORDER BY f.tier, n_flagged DESC
  ", flags_table), params = list(run_id))

  message(sprintf(
    "Run %d complete (%s): %s assessed, %s flagged (T1: %s, T2: %s)",
    run_id, target,
    format(run_meta$records_assessed, big.mark = ","),
    format(run_meta$records_flagged, big.mark = ","),
    format(run_meta$flags_t1, big.mark = ","),
    format(run_meta$flags_t2, big.mark = ",")
  ))

  list(run_id = run_id, target = target, run_meta = run_meta, summary = summary)
}

#' Pull a handful of example flags per rule for a run, for manual review
#' before trusting the run.
#'
#' @param target must match the target used for this run_id
#'   ("analytical_results" or "geochem_export_detail")
preview_flags <- function(run_id, target = c("analytical_results", "geochem_export_detail"),
                           n_per_rule = 5, con = NULL) {
  target <- match.arg(target)
  close_con <- FALSE
  if (is.null(con)) {
    con <- lithodat_connect()
    close_con <- TRUE
  }
  if (close_con) on.exit(dbDisconnect(con), add = TRUE)

  if (target == "analytical_results") {
    dbGetQuery(con, "
      SELECT f.rule_code, a.element_symbol, f.value, u.unitcode, f.flag_detail, f.sampleid
      FROM (
        SELECT *, row_number() OVER (PARTITION BY rule_code ORDER BY flag_id) AS rn
        FROM lithodat_audit_flags
        WHERE run_id = $1
      ) f
      JOIN analytes a ON a.analyte_id = f.analyte_id
      JOIN units u ON u.unitid = f.unitid
      WHERE f.rn <= $2
      ORDER BY f.rule_code, f.rn
    ", params = list(run_id, n_per_rule))
  } else {
    dbGetQuery(con, "
      SELECT f.rule_code, f.analyte_code, f.value, f.unit_code, f.flag_detail, f.datapoint_name
      FROM (
        SELECT *, row_number() OVER (PARTITION BY rule_code ORDER BY flag_id) AS rn
        FROM lithodat_audit_flags_ged
        WHERE run_id = $1
      ) f
      WHERE f.rn <= $2
      ORDER BY f.rule_code, f.rn
    ", params = list(run_id, n_per_rule))
  }
}

# ---------------------------------------------------------------------
# Command-line entry point
# ---------------------------------------------------------------------
.args_to_list <- function(args) {
  out <- list()
  i <- 1
  while (i <= length(args)) {
    key <- gsub("^--", "", args[i])
    key <- gsub("-", "_", key)
    val <- if (i < length(args) && !startsWith(args[i + 1], "--")) args[i + 1] else NA
    out[[key]] <- val
    i <- i + if (is.na(val)) 1 else 2
  }
  out
}

if (identical(environment(), globalenv()) && sys.nframe() == 0L && !interactive()) {
  cli_args <- .args_to_list(commandArgs(trailingOnly = TRUE))
  if (is.null(cli_args$scope_type)) {
    stop("Usage: Rscript lithodat_run_audit.R [--target analytical_results|geochem_export_detail] ",
         "--scope-type {global|country|division} [--scope-value <name>] [--audit-label <text>] ",
         "[--datasource <text>] [--sample-type-id <int>[,<int>...]]")
  }

  result <- run_lithodat_audit(
    target         = if (is.null(cli_args$target)) "analytical_results" else cli_args$target,
    scope_type     = cli_args$scope_type,
    scope_value    = cli_args$scope_value,
    audit_label    = cli_args$audit_label,
    datasource     = cli_args$datasource,
    sample_type_id = if (is.null(cli_args$sample_type_id)) NULL else
      as.integer(strsplit(cli_args$sample_type_id, ",")[[1]])
  )

  print(result$run_meta)
  cat("\nFlags by rule:\n")
  print(result$summary)

  cat("\nExample flags (first 5 per rule):\n")
  print(preview_flags(result$run_id, target = result$target))
}
