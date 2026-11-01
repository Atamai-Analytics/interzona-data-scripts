#!/usr/bin/env Rscript
# Extract Element and Oxide concentration rows for GTK Finland Rock
# (datasource='Geological Survey of Finland', countryname='Finland',
# sample_type_id=31) from lithodat_datapoint_concentrations into the two
# TSVs load_elemental_concentrations.py / load_oxide_concentrations.py
# expect, without routing 525K+ rows through the assistant's context.
#
# Unlike the GEUS/Greenland extraction this package needed no exclusions -
# Finland Rock's analysis_group is cleanly 'Element' or 'Oxide' for every
# row (no NULL/LOI-VOL rows, no FETO3/Sum entries in the Oxide set).
#
# Usage: Rscript extract_finland_rock_concentrations.R

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

scope_where <- "
  WHERE datasource = 'Geological Survey of Finland'
    AND countryname = 'Finland'
    AND sample_type_id = 31
"

elem <- dbGetQuery(con, sprintf('
  SELECT result_id, datapointname_merged AS "datapointName", aliquotname_merged AS "aliquotName",
         element_symbol, "Conc", qualifier_code
  FROM lithodat_datapoint_concentrations
  %s
    AND analysis_group = \'Element\'
', scope_where))
message(sprintf("Element rows: %d", nrow(elem)))
write.table(elem, "elem_finland_rock.tsv", sep = "\t", row.names = FALSE, quote = FALSE, na = "")

oxide <- dbGetQuery(con, sprintf('
  SELECT result_id, datapointname_merged AS "datapointName", aliquotname_merged AS "aliquotName",
         element_oxide, "Conc", qualifier_code
  FROM lithodat_datapoint_concentrations
  %s
    AND analysis_group = \'Oxide\'
', scope_where))
message(sprintf("Oxide rows: %d", nrow(oxide)))
write.table(oxide, "oxide_finland_rock.tsv", sep = "\t", row.names = FALSE, quote = FALSE, na = "")

message("Done.")
