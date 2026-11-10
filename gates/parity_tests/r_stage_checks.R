#!/usr/bin/env Rscript
# R side of the stage-check parity test: runs, with the R repo's own Procedure Gate functions, the checks the Python
# gates G1/G2/G3/G4d/G5 port in stage_gates.r_stage_checks (validate_stage_receipt + m_operations + evidence closure),
# with the same arguments the Python gates use (no run state), and prints [{check, result}] as JSON.
# usage: Rscript r_stage_checks.R <r-repo> <project-root> <step-id> <receipt-rel>
suppressPackageStartupMessages(library(jsonlite))
a <- commandArgs(trailingOnly = TRUE)
repo_root <- normalizePath(a[[1]], mustWork = TRUE)
root <- normalizePath(a[[2]], mustWork = TRUE)
step_id <- a[[3]]
rel <- a[[4]]
gate_script <- file.path(repo_root, "procedure-gate", "procedure_gate.R")
gate <- new.env()
sys.source(gate_script, envir = gate)
gate$procedure_script_path <- function() gate_script
gate$load_methodology()
receipt <- gate$read_artifact_safe(file.path(root, rel))
checks <- list(list(check = "Required receipt exists and parses", result = if (is.list(receipt)) "PASS" else "FAIL"))
res <- tryCatch({
  x <- c(gate$validate_stage_receipt(step_id, receipt, root), gate$m_operations(root, NULL, step_id, receipt = rel))
  closure <- gate$step_closure(root, step_id, receipt)
  c(x, list(list(check = "Stage evidence closure", result = if (!is.null(closure)) "PASS" else "FAIL")))
}, error = function(e) list(list(check = "stage checks ran", result = "FAIL")))
checks <- c(checks, res)
out <- lapply(checks, function(c) list(check = as.character(c$check), result = if (identical(c$result, "PASS")) "PASS" else "FAIL"))
cat(toJSON(out, auto_unbox = TRUE))
