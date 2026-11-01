#!/usr/bin/env Rscript
# Extract samplenumber -> material name for Resources Victoria soil samples
# that have exactly one distinct mindat_rocks-classified material, excluding
# the semantically-meaningless "Unclassified rock" catch-all. The 157
# genuinely multi-material samples and 3 materials with no exact
# LithoSurfer match (Sand, Diorite, Colluvium - resolved separately) are
# excluded here too; those stay materialId=null on the Sample record,
# consistent with what the multi-valued lithology_original SampleProperty
# facts already capture.
#
# Usage: Rscript extract_victoria_material_map.R

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

df <- dbGetQuery(con, "
  WITH per_sample AS (
    SELECT s.samplenumber, count(DISTINCT mr.name) AS n_distinct_material, max(mr.name) AS material
    FROM samples s
    JOIN locations l ON s.locationid = l.locationid
    JOIN countries c ON c.countryid = l.countryid
    LEFT JOIN lithology_observations lo ON lo.sampleid = s.sampleid AND lo.locationid = s.locationid
    LEFT JOIN mindat_rocks mr ON lo.mindat_id = mr.id
    WHERE c.countryname = 'Australia' AND l.datasource = 'Resources Victoria'
      AND s.sample_type_id IN (2,13,14,70,71,72) AND l.isactive = TRUE
    GROUP BY s.samplenumber
  )
  SELECT samplenumber AS \"sampleName\", material
  FROM per_sample
  WHERE n_distinct_material = 1
    AND material NOT IN ('Unclassified rock', 'Sand', 'Diorite', 'Colluvium')
")
message(sprintf("Rows: %d", nrow(df)))
write.table(df, "victoria_material_by_sample.tsv", sep = "\t", row.names = FALSE, quote = FALSE, na = "")
message("Done.")
