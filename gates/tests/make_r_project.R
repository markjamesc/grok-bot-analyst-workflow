#!/usr/bin/env Rscript
# Build an R-referee-valid five-stage project with the R repo's own test helpers (procedure-gate/tests/test_procedure_gate.R
# lines up to the stage writers, and methodology/tests/fixtures.R), optionally adding extra top-level fields to each stage
# receipt BEFORE its operations ledger is written (so ledger hashes stay current).
# usage: Rscript make_r_project.R <r-repo> <out-dir> [extras.json] [last-stage 1..5]
suppressPackageStartupMessages(library(jsonlite))
a <- commandArgs(trailingOnly = TRUE)
repo_root <- normalizePath(a[[1]], mustWork = TRUE)
out <- a[[2]]
extras <- if (length(a) >= 3 && nzchar(a[[3]]) && file.exists(a[[3]])) fromJSON(a[[3]], simplifyVector = FALSE) else list()
last <- if (length(a) >= 4) as.integer(a[[4]]) else 5L
test <- readLines(file.path(repo_root, "procedure-gate/tests/test_procedure_gate.R"))
stop_at <- grep("^project_root <- tempfile", test)[[1]] - 1L
exprs <- parse(text = test[seq_len(stop_at)])
for (e in exprs) eval(e, globalenv())
dir.create(out, recursive = TRUE, showWarnings = FALSE)
project_root <- normalizePath(out)
add_extras <- function(name) {
  x <- extras[[name]]
  if (is.null(x)) return(invisible(NULL))
  p <- file.path(project_root, "artifacts", name)
  v <- m_read(p)
  for (k in names(x)) v[[k]] <- x[[k]]
  t_write(project_root, file.path("artifacts", name), v)
}
steps <- list(c("start", "stage1_decision.json"), c("framing", "stage2_framing.json"), c("design", "stage3_locked_design.json"),
  c("execution", "stage4_validation_status.json"), c("finish", "stage5_interpretation_status.json"))
writers <- list(write_stage1, write_stage2, write_stage3, write_stage4, write_stage5)
for (i in seq_len(last)) {
  writers[[i]](project_root)
  add_extras(steps[[i]][[2]])
  dir.create(file.path(project_root, "artifacts/procedure"), recursive = TRUE, showWarnings = FALSE)
  write_json(list(run_id = "GROK-GATES-TEST", current_step = steps[[i]][[1]]), file.path(project_root, "artifacts/procedure/run_state.json"), auto_unbox = TRUE)
  t_operations(project_root, steps[[i]][[1]])
}
cat("OK", project_root, "\n")
