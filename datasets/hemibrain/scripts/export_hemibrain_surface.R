#!/usr/bin/env Rscript

suppressPackageStartupMessages(library(hemibrainr))
suppressPackageStartupMessages(library(nat))

script_arg <- grep("^--file=", commandArgs(FALSE), value = TRUE)
script_path <- normalizePath(sub("^--file=", "", script_arg), mustWork = TRUE)
root <- normalizePath(file.path(dirname(script_path), ".."), mustWork = TRUE)
source_dir <- file.path(root, "data", "source")
dir.create(source_dir, recursive = TRUE, showWarnings = FALSE)

materials <- nat::materials(hemibrain_al_microns.surf)
materials$name <- row.names(materials)
row.names(materials) <- NULL
write.csv(
  materials[, c("id", "name", "col")],
  file.path(source_dir, "hemibrain_al_microns_materials.csv"),
  row.names = FALSE,
  quote = TRUE
)

vertices <- hemibrain_al_microns.surf$Vertices[, c("PointNo", "X", "Y", "Z")]
write.csv(
  vertices,
  gzfile(file.path(source_dir, "hemibrain_al_microns_vertices.csv.gz")),
  row.names = FALSE,
  quote = FALSE
)

face_chunks <- lapply(seq_along(hemibrain_al_microns.surf$Regions), function(index) {
  faces <- hemibrain_al_microns.surf$Regions[[index]]
  data.frame(
    id = materials$id[index],
    name = materials$name[index],
    v1 = faces$V1,
    v2 = faces$V2,
    v3 = faces$V3
  )
})
write.csv(
  do.call(rbind, face_chunks),
  gzfile(file.path(source_dir, "hemibrain_al_microns_faces.csv.gz")),
  row.names = FALSE,
  quote = TRUE
)

write.csv(
  hemibrain_glomeruli_summary,
  file.path(source_dir, "hemibrain_glomeruli_summary.csv"),
  row.names = FALSE,
  quote = TRUE
)
write.csv(
  odour_scenes,
  file.path(source_dir, "odour_scenes.csv"),
  row.names = FALSE,
  quote = TRUE
)

writeLines(
  c(
    paste("hemibrainr", as.character(packageVersion("hemibrainr"))),
    paste("nat", as.character(packageVersion("nat"))),
    paste("exported", format(Sys.time(), "%Y-%m-%dT%H:%M:%S%z"))
  ),
  file.path(source_dir, "natverse_export_versions.txt")
)
