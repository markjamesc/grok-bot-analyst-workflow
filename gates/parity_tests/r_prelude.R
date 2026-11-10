# Parity prelude: sourced first by each patched copy of an R gate test script.
# - Every call to workflow_gate.R or procedure_gate.R through system2() is also run by the Python port on the same
#   project state (Python first, project restored, then R), and the two results are compared.
# - Every outermost call of a methodology contract function is also run by the Python port with the same
#   (type-tagged) arguments, and the results are compared.
# Results are appended to $PARITY_LOG (JSON lines). The R test itself runs unchanged and must still pass.
.parity <- new.env()
.parity$py <- Sys.getenv("PARITY_PYTHON", "python3")
.parity$pkg <- Sys.getenv("PARITY_PKG_ROOT")
.parity$depth <- 0L
.parity$unq <- function(a) gsub("'\\''", "'", sub("^'(.*)'$", "\\1", a), fixed = TRUE)
.parity$ser <- function(x) {
  if (is.null(x)) return(list(t = "NULL"))
  if (is.data.frame(x)) return(list(t = "df", names = as.list(names(x)), cols = unname(lapply(x, .parity$ser)), nrow = nrow(x)))
  if (is.list(x)) {
    nm <- names(x)
    return(list(t = "list", named = !is.null(nm), names = if (is.null(nm)) list() else as.list(nm), v = unname(lapply(x, .parity$ser))))
  }
  if (is.function(x) || is.environment(x)) return(list(t = "unsupported", class = class(x)[[1]]))
  na <- as.list(which(is.na(x)))
  if (is.character(x)) { v <- x; v[is.na(v)] <- ""; return(list(t = "chr", v = as.list(v), na = na)) }
  if (is.logical(x)) { v <- x; v[is.na(v)] <- FALSE; return(list(t = "lgl", v = as.list(v), na = na)) }
  if (is.integer(x)) { v <- x; v[is.na(v)] <- 0L; return(list(t = "int", v = as.list(v), na = na)) }
  if (is.double(x)) { v <- sprintf("%.17g", x); return(list(t = "dbl", v = as.list(v), na = as.list(which(is.na(x) & !is.nan(x))))) }
  list(t = "unsupported", class = class(x)[[1]])
}
.parity$py_call <- function(args) {
  out <- base::system2(.parity$py, c("-m", "gates.parity_tests.runner", args), stdout = TRUE, stderr = TRUE,
    env = paste0("PYTHONPATH=", shQuote(.parity$pkg)))
  invisible(out)
}
.parity$fn_compare <- function(name, args, result, error) {
  f <- tempfile("parity-fn-", fileext = ".json")
  payload <- list(fn = name, args = .parity$ser(args), result = .parity$ser(result), error = if (is.null(error)) NULL else error)
  jsonlite::write_json(payload, f, auto_unbox = TRUE, null = "null", digits = NA)
  .parity$py_call(c("fn", shQuote(f)))
  unlink(f)
}
.parity$wrap_env <- function(env) {
  targets <- c("m_design", "m_execution", "m_ai", "m_finish", "m_change", "m_operations", "m_checkpoint_contract",
    "m_operational_design", "m_validation", "m_source", "m_inventory", "m_review_subjects", "m_compare", "m_ref_ok",
    "m_historical", "m_refs_ok", "m_equal_ids", "m_missing_rule", "validate_stage_receipt")
  for (nm in intersect(targets, ls(env, all.names = TRUE))) {
    f <- get(nm, envir = env)
    if (!is.function(f) || isTRUE(attr(f, "parity_wrapped"))) next
    g <- local({ fn <- f; name <- nm; function(...) {
      args <- list(...)
      outer <- .parity$depth == 0L
      .parity$depth <- .parity$depth + 1L
      on.exit(.parity$depth <- .parity$depth - 1L, add = TRUE)
      res <- tryCatch(fn(...), error = function(e) e)
      if (outer) .parity$fn_compare(name, args, if (inherits(res, "error")) NULL else res, if (inherits(res, "error")) conditionMessage(res) else NULL)
      if (inherits(res, "error")) stop(res)
      res
    } })
    attr(g, "parity_wrapped") <- TRUE
    assign(nm, g, envir = env)
  }
}
source <- function(file, ...) {
  r <- base::source(file, ...)
  .parity$wrap_env(globalenv())
  invisible(r)
}
sys.source <- function(file, envir = baseenv(), ...) {
  base::sys.source(file, envir = envir, ...)
  .parity$wrap_env(envir)
  invisible(NULL)
}
system2 <- function(command, args = character(), stdout = "", stderr = "", ...) {
  a <- vapply(as.character(args), .parity$unq, character(1), USE.NAMES = FALSE)
  kind <- if (length(a) && grepl("workflow-gate/workflow_gate\\.R$", a[[1]])) "workflow" else
    if (length(a) && grepl("procedure-gate/procedure_gate\\.R$", a[[1]])) "procedure" else ""
  if (!nzchar(kind)) return(base::system2(command, args, stdout = stdout, stderr = stderr, ...))
  fw <- normalizePath(file.path(dirname(a[[1]]), ".."))
  rest <- a[-1]
  root <- if (kind == "workflow") rest[[1]] else if (length(rest) >= 2) rest[[2]] else ""
  tag <- tempfile("parity-gate-")
  # 1. Python on the current state (it may write); 2. restore; 3. R on the same state; 4. compare.
  snap <- paste0(tag, "-snap")
  if (nzchar(root) && dir.exists(root)) base::system2("cp", c("-a", shQuote(root), shQuote(snap)))
  attempts_before <- list.files(file.path(root, "artifacts", "workflow-attempts"), full.names = TRUE)
  .parity$py_call(c("gate-py", kind, shQuote(fw), shQuote(paste0(tag, "-py.json")), vapply(rest, shQuote, "")))
  if (nzchar(root) && dir.exists(snap)) { unlink(root, recursive = TRUE); base::system2("cp", c("-a", shQuote(snap), shQuote(root))); unlink(snap, recursive = TRUE) }
  errf <- paste0(tag, "-err.txt")
  out <- base::system2(command, args, stdout = TRUE, stderr = errf, ...)
  status <- attr(out, "status"); if (is.null(status)) status <- 0L
  err <- if (file.exists(errf)) readLines(errf, warn = FALSE) else character()
  new_attempt <- setdiff(list.files(file.path(root, "artifacts", "workflow-attempts"), full.names = TRUE), attempts_before)
  rinfo <- list(kind = kind, args = as.list(rest), status = status, stdout = paste(out, collapse = "\n"), stderr = paste(err, collapse = "\n"),
    report = if (kind == "workflow" && length(new_attempt) == 1) new_attempt[[1]] else NULL)
  jsonlite::write_json(rinfo, paste0(tag, "-r.json"), auto_unbox = TRUE, null = "null")
  .parity$py_call(c("gate-compare", shQuote(paste0(tag, "-py.json")), shQuote(paste0(tag, "-r.json"))))
  combined <- c(out, err)
  if (isTRUE(stdout)) { attr(combined, "status") <- if (status != 0L) status else NULL; return(combined) }
  if (is.character(stdout) && nzchar(stdout)) { writeLines(combined, stdout); return(invisible(status)) }
  if (identical(stdout, "")) { if (length(out)) writeLines(out); return(invisible(status)) }
  invisible(status)
}
