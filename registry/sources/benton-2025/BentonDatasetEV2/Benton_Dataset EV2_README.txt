
Dataset EV2. Antennal lobe atlas resources.
This README file contains legends for files in Dataset EV2, followed by brief instructions on viewing these in 3D Slicer.

Dataset EV2 AL-Coronal.mov
Movie generated from a series of coronal slices through the antennal lobe, moving from anterior to posterior. The orientation and glomerular colouring are identical to Figure 5.

Dataset EV2 AL-Transverse.mov
Movie generated from a series of transverse slices through the antennal lobe, moving from dorsal to ventral. Glomeruli are coloured as in Figure 5.

DatasetEV2.seg.vtm file and associated folder
These files contain segmentations of the antennal lobe created with the open-source software 3D Slicer (Fedorov et al., 2012) from the glomerular mesh models generated previously from the female adult fly brain (FAFB) connectome (Bates et al., 2020). 

DatasetEV2-label.nrrd
Volume file generated from a binary labelmap created from DatasetEV2.seg.vtm. It can be viewed in 3D Slicer or with limited capabilities in ImageJ.

DatasetEV2-label_ColorTable.ctbl
Colour lookup file, which can be associated with DatasetEV2-label.nrrd to implement the glomerular colour scheme used in Figure 5.


The antennal lobe can be viewed in two different modes with the DatasetEV2.seg.vtm segmentation file and DatasetEV2-label.nrrd files in 3D Slicer. It is best to close one file (or make it invisible using the Data module) before opening the other. 

1) When the DatasetEV2.seg.vtm segmentation file is opened and viewed in the Segmentation module, the antennal lobe can be viewed in 3D with each glomerulus represented as an individual segmentation. Each glomerulus is labeled with its name, associated receptor(s) and sensillum, and is coloured as in Figure 5. The antennal lobe can be rotated for viewing from different angles; interactive colouring and visibility control of individual glomeruli are supported.

2) The 3D antennal lobe volume can be visualised and slices taken through the volume (anterior-to-posterior, lateral-to-medial or dorsal-to-ventral axes) using the ROI feature in the Volume Rendering module. Open the DatasetEV2-label.nrrd volume file and the colour lookup file DatasetEV2-label_ColorTable.ctbl. In the Volumes module, under Display, set the Lookup Table to be the DatasetEV2-label_ColorTable.ctbl file so the colours from DatasetEV2-label_ColorTable.ctbl are associated with the glomeruli in the DatasetEV2-label.nrrd volume, and colouring is as in Figure 5. Next, go to the Volume Rendering module and make both the Volume and Display ROI visible. Drag the ROI frames in either the red, green and yellow 2D views or the 3D view in the purple window to slice through the antennal lobe, controlling which regions are viewable.