"""Train the detector on the first pass labels.

Resumable: if the run folder has weights/last.pt and the run is not marked done, it
continues from there with a new time cap. All outputs go to the external drive.

Run with the geoai env:
    python train.py --smoke                 # small CPU check on a quarter of the train chips
    python train.py --run real --device mps --minutes 90
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import config

BASE_MODELS = {"n": "yolo11n.pt", "s": "yolo11s.pt"}
RUNS = config.MODELS / "runs"


def base_weights(size: str) -> Path:
    from ultralytics.utils.downloads import attempt_download_asset

    path = config.MODELS / "base" / BASE_MODELS[size]
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        here = os.getcwd()
        os.chdir(path.parent)
        try:
            attempt_download_asset(path.name)
        finally:
            os.chdir(here)
    return path


def state_file(run: str) -> Path:
    return RUNS / run / "run_state.json"


def read_state(run: str) -> dict:
    f = state_file(run)
    return json.loads(f.read_text()) if f.exists() else {}


def write_state(run: str, **kw) -> None:
    s = read_state(run)
    s.update(kw)
    state_file(run).parent.mkdir(parents=True, exist_ok=True)
    state_file(run).write_text(json.dumps(s, indent=1))


def time_cap(minutes: float, info: dict):
    """Callback that ends training before the next epoch would pass the cap.

    Ultralytics' own `time` setting stretches the epoch count to fill the time, so the cap
    is done here: the run stops at the epoch limit or the time cap, whichever comes first.
    """
    start = time.time()

    def on_fit_epoch_end(trainer) -> None:
        done = trainer.epoch + 1 - info.setdefault("first_epoch", trainer.epoch)
        used = time.time() - start
        per_epoch = used / max(done, 1)
        info["epochs_done"] = min(trainer.epoch + 1, trainer.epochs)
        if not trainer.stop and used + per_epoch > minutes * 60:
            trainer.stop = True
            info["capped"] = True
            print(f"time cap: stop after epoch {trainer.epoch + 1} ({used / 60:.1f} min used)", flush=True)

    return on_fit_epoch_end


def train(a: argparse.Namespace) -> int:
    from ultralytics import YOLO

    if a.device == "cpu":
        import torch

        torch.set_num_threads(a.threads)
    last = RUNS / a.run / "weights" / "last.pt"
    if read_state(a.run).get("state") == "done":
        print(f"{a.run}: already done")
        return 0
    t0 = time.time()
    info: dict = {}
    write_state(a.run, state="running", device=a.device, started=time.strftime("%Y-%m-%d %H:%M"))
    if last.exists():
        print(f"{a.run}: resume from {last}, cap {a.minutes} min", flush=True)
        model = YOLO(str(last))
        model.add_callback("on_fit_epoch_end", time_cap(a.minutes, info))
        model.train(resume=True, device=a.device, workers=a.workers)
    else:
        weights = base_weights(a.size)
        print(f"{a.run}: start from {weights.name}, cap {a.minutes} min, {a.epochs} epochs", flush=True)
        model = YOLO(str(weights))
        model.add_callback("on_fit_epoch_end", time_cap(a.minutes, info))
        model.train(data=str(config.WORK / "data.yaml"), epochs=a.epochs, patience=a.patience,
                    imgsz=config.CHIP_PX, batch=a.batch, device=a.device, workers=a.workers, seed=config.SEED,
                    fraction=a.fraction, project=str(RUNS), name=a.run, exist_ok=True, plots=True,
                    flipud=0.5, fliplr=0.5, degrees=0.0, mosaic=1.0, close_mosaic=5, cache=a.cache, verbose=True)
    best = RUNS / a.run / "weights" / "best.pt"
    write_state(a.run, state="done" if best.exists() else "failed", minutes=round((time.time() - t0) / 60, 1),
                epochs_done=info.get("epochs_done"), time_capped=bool(info.get("capped")),
                best=str(best), finished=time.strftime("%Y-%m-%d %H:%M"))
    print(f"{a.run}: finished in {(time.time() - t0) / 60:.1f} min", flush=True)
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", default="real")
    ap.add_argument("--smoke", action="store_true", help="CPU, nano model, 3 epochs, a quarter of the train chips")
    ap.add_argument("--device", default="mps")
    ap.add_argument("--size", choices=BASE_MODELS, default="s", help="model size: n (nano) or s (small)")
    ap.add_argument("--epochs", type=int, default=50)
    ap.add_argument("--minutes", type=float, default=90)
    ap.add_argument("--patience", type=int, default=10)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--fraction", type=float, default=1.0)
    ap.add_argument("--cache", default="ram", help="ram, disk or none. The drive is slow, so ram helps")
    ap.add_argument("--threads", type=int, default=4, help="CPU threads when training on CPU")
    a = ap.parse_args()
    a.cache = False if a.cache == "none" else a.cache
    if a.smoke:
        a.run = "smoke_cpu" if a.run == "real" else a.run
        a.device, a.size, a.epochs, a.fraction, a.batch, a.workers = "cpu", "n", 3, 0.25, 8, 2
        a.minutes = min(a.minutes, 30)
    raise SystemExit(train(a))


if __name__ == "__main__":
    main()
