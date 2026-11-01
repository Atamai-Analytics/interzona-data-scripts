#!/usr/bin/env Rscript
# Extract Element concentration rows for the "Resources Victoria: Soil
# Samples" LithoSurfer package (id 246454433) into the TSV
# load_elemental_concentrations.py expects.
#
# Scope: analysis_group='Element', excluding:
#   - OsIr (112 rows): combined Os+Ir assay, no fixed stoichiometric split
#     possible, and Conc is null throughout anyway (no usable data)
#   - Hydrogen/pH (238 rows): not a real elemental concentration (soil pH
#     on a log scale, no valid ppm conversion) - already migrated to
#     SampleProperty (propname='soil_pH')
#
# Everything else is included as-is, real values and below-detection-limit
# rows alike - load_elemental_concentrations.py's existing qualifier_code
# handling already does the right thing in both cases:
#   qualifier_code=''  -> concentration=Conc
#   qualifier_code='<' -> concentration=null, detectionLimit=Conc (which is
#                         itself null for the 9,491 rows where no value was
#                         recoverable even after the batch-inference
#                         backfill - correctly produces a bare "< with no
#                         number" placeholder, confirmed the API accepts
#                         this pattern)
#
# sampleName/aliquotName come from datapointname_merged/aliquotname_merged
# (samplenumber + sourcemethodcode - see the session's notes on why the
# raw sampleName column in this table can't be used directly for Victoria).
#
# Usage: Rscript extract_victoria_elem.R

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

df <- dbGetQuery(con, '
  SELECT dc.result_id, dc.datapointname_merged AS "datapointName",
         dc.aliquotname_merged AS "aliquotName",
         dc.element_symbol, dc."Conc", dc.qualifier_code
  FROM lithodat_datapoint_concentrations dc
  WHERE dc.datasource = \'Resources Victoria\'
    AND dc.sample_type_id IN (2,13,14,70,71,72)
    AND dc.analysis_group = \'Element\'
    AND dc.element_oxide NOT IN (\'OsIr\', \'Hydrogen\')
')
message(sprintf("Element rows (pre units-suffix fix): %d", nrow(df)))

# The actual GCDataPoint/GCAliquot label includes a "[units]" suffix for
# multi-unit datapoints (load_gc_datapoints.py's own labeling rule) -
# Victoria has 23,085 such datapoints (unlike Finland Rock, which had
# none, so this was never needed there). Without this, aliquotName/
# datapointName here wouldn't match what's actually in LithoSurfer for any
# multi-unit datapoint. gcdp_victoria_soil.tsv already carries the correct
# per-datapoint "units" string (built the same way, from the same
# underlying data) - reuse it here instead of recomputing.
gcdp <- read.delim("gcdp_victoria_soil.tsv", stringsAsFactors = FALSE, colClasses = "character")
units_by_dp <- setNames(gcdp$units, gcdp$datapointName)

n_unmatched_base <- sum(!(df$datapointName %in% gcdp$datapointName))
message(sprintf("Base datapointName values with no match in gcdp_victoria_soil.tsv (should be 0): %d", n_unmatched_base))

multi_unit <- grepl("/", units_by_dp[df$datapointName], fixed = TRUE)
multi_unit[is.na(multi_unit)] <- FALSE
suffix <- ifelse(multi_unit, paste0(" [", units_by_dp[df$datapointName], "]"), "")
df$datapointName <- paste0(df$datapointName, suffix)
df$aliquotName <- paste0(df$aliquotName, suffix)
message(sprintf("Rows with multi-unit suffix applied: %d", sum(nzchar(suffix))))
message(sprintf("Distinct datapointName: %d", length(unique(df$datapointName))))
message(sprintf("Null Conc (bare BDL placeholders): %d", sum(is.na(df$Conc))))
write.table(df, "elem_victoria_soil.tsv", sep = "\t", row.names = FALSE, quote = FALSE, na = "")
message("Done.")
