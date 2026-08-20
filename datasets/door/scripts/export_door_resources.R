#!/usr/bin/env Rscript

suppressPackageStartupMessages(library(DoOR.data))

script_arg <- grep("^--file=", commandArgs(FALSE), value = TRUE)
script_path <- normalizePath(sub("^--file=", "", script_arg), mustWork = TRUE)
root <- normalizePath(file.path(dirname(script_path), ".."), mustWork = TRUE)
source_dir <- file.path(root, "data", "source")
dir.create(source_dir, recursive = TRUE, showWarnings = FALSE)

write_data <- function(object_name, file_name, gzip = FALSE) {
  data(list = object_name, package = "DoOR.data")
  value <- get(object_name)
  path <- file.path(source_dir, file_name)
  if (gzip) {
    write.csv(value, gzfile(path), row.names = TRUE, quote = TRUE)
  } else {
    write.csv(value, path, row.names = TRUE, quote = TRUE)
  }
}

write_data("door_response_matrix", "door_response_matrix.csv.gz", gzip = TRUE)
write_data(
  "door_response_matrix_non_normalized",
  "door_response_matrix_non_normalized.csv.gz",
  gzip = TRUE
)
write_data("door_mappings", "door_mappings.csv")
write_data("door_data_format", "door_data_format.csv")
write_data("door_dataset_info", "door_dataset_info.csv")
write_data("door_response_range", "door_response_range.csv")
write_data("door_glo_dist", "door_glo_dist.csv")

data(list = "door_AL_map", package = "DoOR.data")
write.csv(
  door_AL_map$glomeruli,
  file.path(source_dir, "door_al_map_glomeruli.csv"),
  row.names = FALSE,
  quote = TRUE
)
write.csv(
  door_AL_map$labels,
  file.path(source_dir, "door_al_map_labels.csv"),
  row.names = FALSE,
  quote = TRUE
)

writeLines(
  c(
    paste("DoOR.data", as.character(packageVersion("DoOR.data"))),
    paste("exported", format(Sys.time(), "%Y-%m-%dT%H:%M:%S%z"))
  ),
  file.path(source_dir, "door_export_versions.txt")
)
