#!/usr/bin/env Rscript
# Run lithodat_refresh_geochem_exports('Resources Victoria') - rebuilds
# lithodat_datapoint_concentrations / lithodat_datapoint_export for the
# whole Resources Victoria datasource (all sample types) from
# analytical_results, so the 85,246-row detection-limit backfill flows
# through into Conc. Can take a long time (the function's own docs note
# 20+ min even scoped) - run in background, no client-side timeout here
# unlike the MCP query tool.

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

message(sprintf("Starting refresh at %s ...", Sys.time()))
t0 <- Sys.time()
res <- dbGetQuery(con, "SELECT lithodat_refresh_geochem_exports(p_datasource := 'Resources Victoria')")
t1 <- Sys.time()
message(sprintf("Done at %s (elapsed: %s)", t1, format(t1 - t0)))
print(res)
