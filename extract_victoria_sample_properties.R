#!/usr/bin/env Rscript
# Extract SampleProperty facts for the "Resources Victoria: Soil Samples"
# LithoSurfer package (id 246454433) from the two lithodat_sample_properties*
# views, into TSVs load_sample_properties2.py expects (sampleName, propname,
# propvalue - long format, one row per fact).
#
# lithodat_sample_properties  - location-level properties (locationName,
#   adminName, sourceURL, ProjectedX/Y, ProjectedSRID), scoped here to
#   countryname='Australia', datasource='Resources Victoria',
#   sample_type_id IN (2,13,14,70,71,72) - the 6 SOIL-category types.
# lithodat_sample_properties2 - sample-level + stratigraphy/lithology
#   properties (fieldid, sampletypelocal, sample_weight_kg, lithology_*,
#   etc.), already scoped to Resources Victoria soil in the view itself -
#   extracted here as-is, no additional WHERE needed.
#
# Both views build "sampleName" from samples.samplenumber (matching how
# Sample records were actually named for this package - see
# load_victoria_soil_samples.py), and both cover 133,980 samples - 1,770
# more than the 132,210 actually loaded (those have no active analytical
# result and were excluded from the Sample load). The loader will skip and
# warn on those, which is expected, not an error.
#
# Usage: Rscript extract_victoria_sample_properties.R

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

v1 <- dbGetQuery(con, "
  SELECT \"sampleName\", propname, propvalue
  FROM lithodat_sample_properties
  WHERE countryname = 'Australia'
    AND datasource = 'Resources Victoria'
    AND sample_type_id IN (2, 13, 14, 70, 71, 72)
")
message(sprintf("lithodat_sample_properties rows: %d", nrow(v1)))
write.table(v1, "victoria_sampleprop_v1.tsv", sep = "\t", row.names = FALSE, quote = FALSE, na = "")

v2 <- dbGetQuery(con, '
  SELECT "sampleName", propname, propvalue
  FROM lithodat_sample_properties2
')
message(sprintf("lithodat_sample_properties2 rows: %d", nrow(v2)))
write.table(v2, "victoria_sampleprop_v2.tsv", sep = "\t", row.names = FALSE, quote = FALSE, na = "")

message("Done.")
