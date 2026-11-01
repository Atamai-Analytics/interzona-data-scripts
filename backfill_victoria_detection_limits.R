#!/usr/bin/env Rscript
# Backfill analytical_results.value / lower_detection_limit / report_number
# for the 85,246 Resources Victoria Soil below-detection-limit element
# results that had qualifier_id=1 ('<') but no numeric value anywhere in
# the source - inferred from D:\CriticalMineralsDB\...\gsiteassay.txt as
# the minimum quantified value within the same
# (batchSampleId, batchSeqId, element, unit) analytical batch group.
# See infer_victoria_detection_limits.py / check_dl_coverage.R for the
# derivation; victoria_dl_final.tsv is the input here.
#
# qualifier_id is NOT touched - these rows are already correctly flagged
# '<', this only fills in the missing number.
#
# Usage: Rscript backfill_victoria_detection_limits.R

suppressPackageStartupMessages({
  library(DBI)
  library(RPostgres)
})

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

con <- dbConnect(
  RPostgres::Postgres(),
  host     = Sys.getenv("LITHODAT_DB_HOST", "localhost"),
  port     = as.integer(Sys.getenv("LITHODAT_DB_PORT", "5432")),
  dbname   = Sys.getenv("LITHODAT_DB_NAME", "criticialmineralsexp"),
  user     = Sys.getenv("LITHODAT_DB_USER"),
  password = Sys.getenv("LITHODAT_DB_PASSWORD")
)
on.exit(dbDisconnect(con), add = TRUE)

df <- read.delim("victoria_dl_final.tsv", stringsAsFactors = FALSE)
df$result_id <- as.integer(df$result_id)
df$inferred_dl <- as.numeric(df$inferred_dl)
message(sprintf("Loaded %d rows to backfill", nrow(df)))
stopifnot(!any(is.na(df$result_id)), !any(is.na(df$inferred_dl)))

# Write the target rows to a temp table first (RPostgres's params=list(...)
# can't bind a multi-thousand-element R vector as a single Postgres array
# parameter - confirmed: "malformed array literal" - so joins against this
# temp table are used for the checks below instead of ANY($1)).
dbWriteTable(con, "tmp_victoria_dl_backfill", df[, c("result_id", "inferred_dl", "report_number")],
             temporary = TRUE, overwrite = TRUE)

# Sanity check: confirm every target row is still an untouched
# qualifier_id=1 / null-value row before writing anything - guards against
# double-applying this backfill if the script is ever re-run after a
# partial or full previous run.
chk <- dbGetQuery(con, "
  SELECT count(*) AS n,
         count(*) FILTER (WHERE ar.value IS NULL AND ar.qualifier_id = 1) AS n_still_null_bdl
  FROM analytical_results ar
  JOIN tmp_victoria_dl_backfill t ON t.result_id = ar.result_id
")
message(sprintf("Pre-check: %.0f target rows found, %.0f still null-value BDL (expect equal to loaded count)",
                 chk$n, chk$n_still_null_bdl))
if (as.integer(chk$n_still_null_bdl) != nrow(df)) {
  stop("Pre-check mismatch - some target rows are no longer null-value BDL (already backfilled, or changed since derivation). Investigate before proceeding; refusing to run to avoid double-applying or overwriting different data.")
}

dbBegin(con)
tryCatch({
  res <- dbExecute(con, "
    UPDATE analytical_results ar
    SET value = t.inferred_dl,
        lower_detection_limit = t.inferred_dl,
        report_number = t.report_number,
        modified_by = 'lithodat_victoria_dl_backfill',
        modified_date = now()
    FROM tmp_victoria_dl_backfill t
    WHERE ar.result_id = t.result_id
  ")
  message(sprintf("Rows updated: %d", res))

  if (res != nrow(df)) {
    stop(sprintf("Row count mismatch: expected to update %d rows, actually updated %d - rolling back.",
                  nrow(df), res))
  }

  dbCommit(con)
  message("Committed.")
}, error = function(e) {
  dbRollback(con)
  stop(e)
})

# Post-check
post <- dbGetQuery(con, "
  SELECT count(*) AS n_confirmed
  FROM analytical_results ar
  JOIN tmp_victoria_dl_backfill t ON t.result_id = ar.result_id
  WHERE ar.report_number LIKE 'gsiteassay-batch:%'
")
message(sprintf("Post-check: %.0f rows confirmed with report_number set", post$n_confirmed))
