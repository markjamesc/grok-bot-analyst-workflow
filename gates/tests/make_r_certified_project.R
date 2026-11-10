#!/usr/bin/env Rscript
# Build an R-CERTIFIED five-stage project by driving the R repo's own Procedure Gate CLI (start, begin/complete for
# every stage, finalize) with the R repo's own test writers (procedure-gate/tests/test_procedure_gate.R up to the
# first project, plus methodology/tests/fixtures.R). Extra top-level receipt fields are added before each `complete`
# (the R test runner rewrites the operations ledger inside `complete`, so ledger hashes stay current).
# Optional extras$deliverables {path: text}: Stage 5 deliverable text written after the R Stage 5 writer; the R finish
# fixture (t_finish) is then re-run so its claim ledger hashes the final deliverable bytes.
# usage: Rscript make_r_certified_project.R <r-repo> <out-dir> [extras.json]
suppressPackageStartupMessages(library(jsonlite))
a <- commandArgs(trailingOnly = TRUE)
repo_root <- normalizePath(a[[1]], mustWork = TRUE)
out <- a[[2]]
extras <- if (length(a) >= 3 && nzchar(a[[3]]) && file.exists(a[[3]])) fromJSON(a[[3]], simplifyVector = FALSE) else list()
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
must <- function(r, what) if (!identical(r$status, 0L)) stop(what, " failed:\n", paste(r$output, collapse = "\n"))
must(run_gate("start", project_root, "GROK-GATES-CERT"), "start")
steps <- list(c("start", "stage1_decision.json"), c("framing", "stage2_framing.json"), c("design", "stage3_locked_design.json"),
  c("execution", "stage4_validation_status.json"), c("finish", "stage5_interpretation_status.json"))
writers <- list(write_stage1, write_stage2, write_stage3, write_stage4, write_stage5)
for (i in seq_along(steps)) {
  must(run_gate("begin", project_root, steps[[i]][[1]]), paste("begin", steps[[i]][[1]]))
  writers[[i]](project_root)
  if (steps[[i]][[1]] == "finish" && length(extras$deliverables)) {
    for (d in names(extras$deliverables)) writeLines(extras$deliverables[[d]], file.path(project_root, d))
    t_finish(project_root)
  }
  add_extras(steps[[i]][[2]])
  must(run_gate("complete", project_root, steps[[i]][[1]]), paste("complete", steps[[i]][[1]]))
}
must(run_gate("finalize", project_root), "finalize")
cat("OK", project_root, "\n")
