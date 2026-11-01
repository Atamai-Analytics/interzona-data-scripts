#!/usr/bin/env Rscript
# Extract Sample rows for the combined "Resources Victoria: Soil Samples"
# LithoSurfer package (id 246454433) from samples/locations, into the TSV
# load_victoria_soil_samples.py expects.
#
# Scope: datasource='Resources Victoria', sample_type_id IN (2,14,70,72,13,71)
# (all 6 SOIL-category sample types), isactive=TRUE, AND has at least one
# active analytical_results row (matches what will actually carry
# measurements - 132,210 of 133,980 technically-active soil samples in
# scope have no active result at all and are excluded here; re-run without
# the EXISTS clause if the full 133,980 is wanted instead).
#
# samplenumber is used as the unique sample label (verified 100% unique -
# 133,980/133,980 distinct - across the full scope, no datapointname_merged-
# style reconciliation needed here unlike Finland Rock).
#
# method_code is derived from split_part(sampletypelocal, ' | ', 2) and
# mapped to one of LithoSurfer's 9 SampleMethod values in Python
# (load_victoria_soil_samples.py), per the mapping confirmed with the user:
#   UNK1/AUGE1/HAUG1/MAUG1 -> Unknown/Auger/Auger/Auger
#   SHOV1/BULK1/LAG1       -> Grab
#   MAG1/SEL1              -> Other
#
# Usage: Rscript extract_victoria_soil_samples.R

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

samples <- dbGetQuery(con, "
  SELECT s.samplenumber AS \"sampleName\",
         split_part(s.sampletypelocal, ' | ', 2) AS method_code,
         l.locationname AS \"locationName\",
         l.latitude, l.longitude,
         s.sampledate::text AS sampledate,
         s.comments AS \"sampleComment\"
  FROM samples s
  JOIN locations l ON l.locationid = s.locationid
  WHERE l.datasource = 'Resources Victoria'
    AND s.sample_type_id IN (2,14,70,72,13,71)
    AND s.isactive = TRUE
    AND EXISTS (
      SELECT 1 FROM analytical_results ar
      WHERE ar.sampleid = s.sampleid AND ar.isactive = TRUE
    )
")
message(sprintf("Sample rows: %d", nrow(samples)))
message(sprintf("Distinct sampleName: %d", length(unique(samples$sampleName))))
write.table(samples, "victoria_soil_samples.tsv", sep = "\t", row.names = FALSE, quote = FALSE, na = "")
message("Done.")
