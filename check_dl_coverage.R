#!/usr/bin/env Rscript
# Cross-check victoria_inferred_dl.tsv coverage against the actual
# Victoria Soil null-value BDL rows in lithodat_datapoint_concentrations.

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

need_dl <- dbGetQuery(con, "
  SELECT dc.result_id, s.samplenumber, dc.element_oxide, dc.sourceunit
  FROM lithodat_datapoint_concentrations dc
  JOIN locations l ON l.locationid = split_part(dc.\"sampleName\", '//AA', 1)::bigint
  JOIN samples s ON s.locationid = l.locationid
  WHERE dc.datasource = 'Resources Victoria'
    AND dc.sample_type_id IN (2,13,14,70,71,72)
    AND dc.analysis_group = 'Element'
    AND dc.\"Conc\" IS NULL
    AND dc.qualifier_code = '<'
")
message(sprintf("Rows needing an inferred DL: %d", nrow(need_dl)))

lookup <- read.delim("victoria_inferred_dl.tsv", stringsAsFactors = FALSE, colClasses = "character")
message(sprintf("Lookup rows available: %d", nrow(lookup)))

need_dl$key <- paste(need_dl$samplenumber, need_dl$element_oxide, need_dl$sourceunit, sep = "|")
lookup$key <- paste(lookup$samplenumber, lookup$element_symbol, lookup$unitCd, sep = "|")

# a (samplenumber, element, unit) key can map to >1 inferred value if the
# sample had multiple analytical batches for that element/unit - keep the
# first, note if any such duplicates exist
dup_keys <- sum(duplicated(lookup$key))
message(sprintf("Duplicate (samplenumber,element,unit) keys in lookup: %d", dup_keys))
lookup_dedup <- lookup[!duplicated(lookup$key), ]

need_dl$inferred_dl <- lookup_dedup$inferred_detection_limit[match(need_dl$key, lookup_dedup$key)]
need_dl$batch_sample_id <- lookup_dedup$batchSampleId[match(need_dl$key, lookup_dedup$key)]
need_dl$batch_seq_id <- lookup_dedup$batchSeqId[match(need_dl$key, lookup_dedup$key)]

n_matched <- sum(!is.na(need_dl$inferred_dl))
n_unmatched <- sum(is.na(need_dl$inferred_dl))
message(sprintf("Matched: %d / %d (%.1f%%)", n_matched, nrow(need_dl), 100*n_matched/nrow(need_dl)))
message(sprintf("Unmatched: %d", n_unmatched))

if (n_unmatched > 0) {
  unmatched <- need_dl[is.na(need_dl$inferred_dl), ]
  tab <- sort(table(unmatched$element_oxide), decreasing = TRUE)
  message("Top unmatched elements:")
  print(head(tab, 15))
}

out <- need_dl[!is.na(need_dl$inferred_dl), c("result_id", "samplenumber", "element_oxide", "sourceunit", "inferred_dl", "batch_sample_id", "batch_seq_id")]
out$report_number <- paste0("gsiteassay-batch:", out$batch_sample_id, "-", out$batch_seq_id)
write.table(out, "victoria_dl_final.tsv", sep = "\t", row.names = FALSE, quote = FALSE, na = "")
message(sprintf("Wrote victoria_dl_final.tsv (%d rows)", nrow(out)))
