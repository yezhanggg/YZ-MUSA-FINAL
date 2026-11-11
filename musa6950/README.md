# MUSA 6950: Room for a Backyard Home

Ye Zhang · MUSA 6950 AI for Urban Sustainability · Fall 2026 · Prof. Xiaojiang Li

This half asks: is there room on the lot, and how many trees would it cost?
The MUSA 5500 half (`../musa5500/`) asks about demand and payoff.

## Run it

```bash
conda activate geoai
python shared/get_boundaries.py       # if not done yet
python musa6950/get_data.py
```

Takes about 30-60 minutes the first time (about 2 GB of images).

Then work through the notebooks in order.

| Notebook | What it does | Saves |
|---|---|---|
| `notebooks/01_look_and_label.ipynb` | Check images + labels. Hand-label 200-300 lots (not done yet) | figures, `hand_labels.csv` (by hand) |
| `notebooks/02_random_forest.ipynb` | Pixel Random Forest baseline (Lab 6) | `6950_metrics_rf.json` |
| `notebooks/03_unet.ipynb` | U-Net: building, tree, open ground (Lab 9, A6). Loads the weights from `train_unet.py`, checks leakage, scores the test once | `6950_metrics_unet.json`, `data/models/unet.pt` |
| `notebooks/04_sheds.ipynb` | Garages and sheds. Outlines only, YOLO optional (Lab 8, A5). Picks the single-family lots | `sheds.csv`, `6950_lots_sf.gpkg` |
| `notebooks/05_room_rule.ipynb` | Does a 20 x 30 ft spot fit? With and without cutting trees. Largest footprint that fits. Map layers | `lots_pilot.csv`, `6950_lot_open.gpkg`, `6950_lot_spot.gpkg` |
| `notebooks/06_statewide.ipynb` | Scale to every tract. Fit curves by footprint size | `lots_tract.csv`, `fit_curves.csv` |

After notebooks 05 and 06, run `python app/build_data.py` to see the results in the tool.

## Files

- `get_data.py` downloads images, labels, building outlines, lot lines
- `notebooks/` the AI work, one step per notebook
- `unet.py` the U-Net models (v1 plain, v2 ResNet-34), used by notebooks 03 and 05
- `train_unet.py` trains the U-Net (run before notebook 03, about 1.5 hours on a Mac). Writes `data/models/unet_<tag>.pt`. Copy the final one to `data/models/unet.pt`
- `docs/` pages for the website: proposal, data, methods, results
- `requirements.txt` main packages. `requirements-yolo.txt` only for notebook 04

## Due

- Presentation: Tue Dec 1 (last day of class)
- Report: date and length not posted. Ask Prof. Li

## Starting code

- Random Forest: `ai-urban-sustainability/lab6-machine-learning/`
- U-Net: my Assignment 6 (`My Materials/Lab 09 + A6/`). 7 classes, spatial split, mIoU 0.397
- YOLO: my Assignment 5 (`My Materials/Lab 08 + A5/`). LabelMe to YOLO converter
- NAIP download: `ai-urban-sustainability/lab3-raster-data-manipulation/1. naip-downloader.ipynb`

## License note

YOLO (ultralytics) is AGPL-3.0. It is only used in notebook 04. The rest of the project does not import it, so the repo can stay Apache-2.0.

## AI use

The syllabus asks to keep AI use low for the model code. Claude Code helped set up the data download script, the website shell, and these docs.

The notebooks (01-06), `unet.py`, `train_unet.py`, and `docs/results.md` were written and run by Claude (Claude Code) at my request. That includes the v2 U-Net (pretrained encoder, longer training, ablations, test checks). The hand labels in notebook 01 are still mine to do.
