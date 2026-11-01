#!/usr/bin/env Rscript
# Extract GCDataPoint header rows for the "Resources Victoria: Soil Samples"
# LithoSurfer package (id 246454433) into the TSV load_gc_datapoints.py
# expects, from lithodat_datapoint_concentrations (not lithodat_datapoint_export
# directly - concentrations carries the same header fields per-row and lets
# us aggregate the "units" list ourselves in one pass).
#
# Grain: samplenumber + sourcemethodcode (verified: digestioncategory,
# digestionmethod, laboratorycode, sourcemethoddesc, sampleweightgm,
# analysisdate, sourceanalysisid, digestiontempcelsius, digestionnotes,
# analyticalSessionID, batchID, mountID are all 100% consistent within this
# grain - 0 inconsistent groups checked directly). sourceunit is the one
# field that legitimately varies within this grain (e.g. majors in % vs
# traces in ppm from the same analytical run) - aggregated here into a
# '/'-joined "units" column, exactly as load_gc_datapoints.py expects
# (single unit -> sourceUnit set directly; multiple -> left blank, "[units]"
# appended to the label instead).
#
# sampleName is samples.samplenumber - matching what was actually used to
# create Sample records for this package (NOT lithodat_datapoint_export's
# own "sampleName" column, which is locationid-based and doesn't match -
# recovered here via locationid parsed out of that column, joined back to
# samples; see the session's notes on lithodat_refresh_geochem_exports()
# for why the export tables carry the wrong sampleName).
#
# Usage: Rscript extract_victoria_gc_datapoints.R

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
  SELECT
    dc.datapointname_merged AS "datapointName",
    s.samplenumber AS "sampleName",
    max(dc.digestioncategory) AS digestioncategory,
    max(dc.digestionmethod) AS digestionmethod,
    dc.sourcemethodcode,
    max(dc.sourcemethoddesc) AS sourcemethoddesc,
    max(dc.laboratorycode) AS laboratorycode,
    max(dc.sampleweightgm) AS sampleweightgm,
    max(dc.analysisdate) AS analysisdate,
    max(dc.sourceanalysisid) AS sourceanalysisid,
    max(dc.digestiontempcelsius) AS digestiontempcelsius,
    max(dc.digestionnotes) AS digestionnotes,
    max(dc."analyticalSessionID") AS "analyticalSessionID",
    max(dc."batchID") AS "batchID",
    max(dc."mountID") AS "mountID",
    string_agg(DISTINCT dc.sourceunit, \'/\' ORDER BY dc.sourceunit) AS units
  FROM lithodat_datapoint_concentrations dc
  JOIN locations l ON l.locationid = split_part(dc."sampleName", \'//AA\', 1)::bigint
  JOIN samples s ON s.locationid = l.locationid
  WHERE dc.datasource = \'Resources Victoria\'
    AND dc.sample_type_id IN (2,13,14,70,71,72)
  GROUP BY dc.datapointname_merged, s.samplenumber, dc.sourcemethodcode
')
message(sprintf("GCDataPoint rows: %d", nrow(df)))
message(sprintf("Distinct datapointName: %d", length(unique(df$datapointName))))
write.table(df, "gcdp_victoria_soil.tsv", sep = "\t", row.names = FALSE, quote = FALSE, na = "")
message("Done.")
