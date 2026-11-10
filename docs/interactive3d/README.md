# Interactive 3D export

This viewer export contains camera-space hand joint annotations and predictions for four development examples. Units are meters, with OpenCV axes (+X right, +Y down, +Z forward). The coordinate frame changes with a moving camera; it is not a reconstructed world trajectory.

## Geometry and provenance

Each sequence JSON contains all source frames and timestamps, [left, right] hands, and 21 OpenPose-order joint coordinates. Missing joints are null. `source_valid` preserves the original method/GT mask; `valid` is the conservative display mask. `joint_valid` also requires finite coordinates. Detection flags and valid tracked boxes are distinct. HaWoR infill is explicitly labeled.

HGGT native geometry and its calibrated translation adapter are separate choices. The adapter changes translation only and fits HGGT's own projections, not GT. Predicted fingertip markers match the existing dataset-specific evaluation convention. Wrist-centered viewing should subtract each hand's own wrist without rotating or scaling it.

This export does not distribute MANO models, mesh topology, or predicted vertices. No GT mesh is exported: the cached DexYCB vertices have a separate reconstruction provenance, and HOT3D GT meshes were not present in this evaluation cache. The 21-joint skeleton is real 3D geometry, not a video or screen-space overlay.

## Dataset attribution and notices

DexYCB annotations derive from **DexYCB: A Benchmark for Capturing Hand Grasping of Objects**, Yu-Wei Chao, Wei Yang, Yu Xiang, Pavlo Molchanov, Ankur Handa, Jonathan Tremblay, Yashraj S. Narang, Karl Van Wyk, Umar Iqbal, Stan Birchfield, Jan Kautz, and Dieter Fox, CVPR 2021. Dataset terms: https://dex-ycb.github.io/ . The selected DexYCB annotation subset is distributed under [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) with its [legal code](https://creativecommons.org/licenses/by-nc/4.0/legalcode.en).

HOT3D-Aria annotations derive from the **HOT3D** dataset, Meta Reality Labs Research and contributors. Dataset agreement: https://huggingface.co/datasets/bop-benchmark/hot3d/blob/main/hot3d_dataset_license_agreement.pdf . The selected HOT3D-derived annotation subset is distributed under [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/) with its [legal code](https://creativecommons.org/licenses/by-nc-sa/4.0/legalcode.en). Copyright Meta Platforms Technologies, LLC and contributors. Data is provided as-is without warranties. No endorsement by either dataset's authors is implied. Project and citation: https://github.com/facebookresearch/hot3d .

Changes to GT: selected sequence/frame subset, HOT3D world-to-calibrated-RGB-camera transformation already present in the evaluation cache, [left, right] packaging, and JSON rounding to 0.000001 m. These evaluation GT arrays were not supplied to inference or used to align predictions; overlap with the pretrained models' training data is unverified. Dataset licenses apply to the relevant derivative annotation data; do not describe all exported data as unconditionally MIT-licensed. Redistribution remains noncommercial/research and subject to each source's terms.

Methods: HGGT https://github.com/lym29/HGGT and HaWoR https://github.com/ThunderVVV/HaWoR . These are third-party estimates, not ground truth. The four examples are development sequences and do not establish a complete benchmark ranking.

## Reproduce

Run `python scripts/export_interactive_3d.py --root PROJECT --gt-release reviewed_licenses.json` using the existing NumPy environment. The license JSON is keyed by dataset (`DexYCB`, `HOT3D-Aria`), each with `license_url`, `attribution`, and `permission_basis`. Without a reviewed entry, GT is not included in the public sequence output. The exporter validates frame IDs, timestamps, sides, shapes, finite display geometry and the translation-only property, and writes `validation.json` plus source SHA-256 values.
