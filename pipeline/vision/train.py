"""Train the land cover U-Net, resumable.

Port of musa6950/train_unet.py (the recipe of the published v2 model):
- ImageNet ResNet-34 U-Net, first conv changed to 4 bands (or plain U-Net)
- random 384 px crops, 1 in 3 centered on a building pixel
- flips, 90 degree turns, brightness and contrast jitter per band
- class-weighted cross entropy (1 / sqrt(class share)) + 0.5 x Dice
- AdamW, warmup then cosine decay over --epochs, early stop on val mIoU
- validation = every labeled pixel of the 24 val boxes

What is new:
- each run has its own folder, models/<run>/, never overwritten
- last.pt every epoch (and on pause) holds model, optimizer, scheduler,
  RNG states and the position inside the epoch, so --resume continues
  exactly where it stopped
- --max-minutes pauses cleanly (result.json state "paused", exit 0)
- --stop-epoch ends the run after a fixed number of epochs of the
  --epochs schedule. Runs compared with each other use the same
  schedule and the same stop epoch, so they get the same compute even
  when other jobs slow the GPU down
- --classes 5 adds the hard surface class

    python -m pipeline.vision.train --run r34_c5_s0 --classes 5 --seed 0 --epochs 16 --stop-epoch 14
    python -m pipeline.vision.train --run r34_c5_s0 --resume --max-minutes 60
"""
from __future__ import annotations

import argparse
import csv
import json
import resource
import signal
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np
import torch
import torch.nn.functional as F

from pipeline.vision import data as vdata
from pipeline.vision.labels import classes_for
from pipeline.vision.metrics import confusion, scores
from pipeline.vision.model import add_ndvi, make_model, predict_array, to_input

Boxes = list[tuple[np.ndarray, np.ndarray]]


@dataclass
class Config:
    run: str
    classes: int = 4
    kind: str = "smp"
    encoder: str = "resnet34"
    pretrained: bool = True
    ndvi: bool = False
    crop: int = 384
    batch: int = 12
    steps: int = 400               # steps per epoch
    epochs: int = 16               # planned epochs, sets the LR schedule
    stop_epoch: int = 0            # end the run after this epoch (0 = run the whole schedule)
    patience: int = 5
    lr: float = 5e-4
    warmup: int = 300              # warmup steps (capped at 10 % of all steps)
    dice: float = 0.5              # weight of the Dice loss, 0 = cross entropy only
    bld_frac: float = 1 / 3        # share of crops centered on a building pixel
    jitter: float = 0.1
    seed: int = 0
    init_from: str = ""            # start from these weights (e.g. a longer run at a lower LR)
    data: str = "chesapeake"       # or "city:philadelphia", "city:pittsburgh" (5 classes)
    val_win: int = 512
    val_margin: int = 64
    extra: dict = field(default_factory=dict)

    @property
    def last_epoch(self) -> int:
        return self.stop_epoch or self.epochs


# ---------------------------------------------------------------- data and batches
def load_real_data(cfg: Config) -> dict[str, Boxes]:
    if cfg.data.startswith("city:"):
        return load_city_data(cfg.data.split(":", 1)[1])
    return load_chesapeake(cfg)


def load_city_data(city: str) -> dict[str, Boxes]:
    """City boxes (600 m) with their 5-class labels, in memory."""
    from pipeline.vision.city import city_boxes, load_city_box

    return {r: [load_city_box(city, b) for b in city_boxes(city, r)] for r in ["train", "val"]}


def load_chesapeake(cfg: Config) -> dict[str, Boxes]:
    """Train and val boxes in memory (about 3 GB).

    The cache sits on a USB hard disk. Random 384 px crops from memory maps there
    cost thousands of small seeks per batch and tripled the epoch time, so the
    boxes are read once, in order, and kept in RAM.
    """
    boxes = vdata.split_boxes()
    out: dict[str, Boxes] = {}
    for r in ["train", "val"]:
        out[r] = [tuple(np.array(a) for a in vdata.load_box_mm(g, cfg.classes)) for g in boxes[boxes.role == r].GEOID]
    return out


def band_stats(train: Boxes, ndvi: bool) -> tuple[np.ndarray, np.ndarray]:
    """Per-band mean and std from every 7th pixel of the training boxes."""
    sample = np.concatenate([np.asarray(img[:, ::7, ::7]).reshape(img.shape[0], -1) for img, _ in train], 1).astype(np.float32)
    if ndvi:
        sample = add_ndvi(torch.from_numpy(sample)[None, :, None, :])[0, :, 0].numpy()
    return sample.mean(1).astype(np.float32), sample.std(1).astype(np.float32)


def class_weights(train: Boxes, n: int) -> np.ndarray:
    """1 / sqrt(class share), scaled to mean 1. Rare classes (buildings) count more."""
    freq = sum(np.bincount(np.asarray(lab).ravel(), minlength=256)[:n] for _, lab in train).astype(float)
    freq = np.maximum(freq / freq.sum(), 1e-6)
    w = 1 / np.sqrt(freq)
    return (w / w.mean()).astype(np.float32)


def building_pixels(train: Boxes) -> list[np.ndarray]:
    """Every 20th building pixel per box, for crops centered on buildings."""
    return [np.flatnonzero(np.asarray(lab).ravel() == 1)[::20].astype(np.int32).copy() for _, lab in train]


def make_batch(cfg: Config, train: Boxes, bld_px: list[np.ndarray], rng: np.random.Generator,
               mean: np.ndarray, std: np.ndarray, device: str) -> tuple[torch.Tensor, torch.Tensor]:
    """One batch of random crops with augmentation. Same draws in the same order as the course trainer."""
    C = cfg.crop
    xs, ys = [], []
    for _ in range(cfg.batch):
        k = rng.integers(len(train))
        img, lab = train[k]
        H, W = lab.shape
        if rng.random() < cfg.bld_frac and len(bld_px[k]):
            r, c = divmod(int(rng.choice(bld_px[k])), W)
            r0 = int(np.clip(r - C // 2 + rng.integers(-C // 4, C // 4 + 1), 0, H - C))
            c0 = int(np.clip(c - C // 2 + rng.integers(-C // 4, C // 4 + 1), 0, W - C))
        else:
            r0, c0 = rng.integers(0, H - C + 1), rng.integers(0, W - C + 1)
        xs.append(np.asarray(img[:, r0:r0 + C, c0:c0 + C]))
        ys.append(np.asarray(lab[r0:r0 + C, c0:c0 + C]))
    x = to_input(torch.from_numpy(np.stack(xs)).to(device), mean, std, cfg.ndvi)
    y = torch.from_numpy(np.stack(ys)).long().to(device)
    for i in range(len(x)):        # same flip and turn on image and label
        k = int(rng.integers(4))
        xi, yi = torch.rot90(x[i], k, [1, 2]), torch.rot90(y[i], k, [0, 1])
        if rng.random() < 0.5:
            xi, yi = torch.flip(xi, [2]), torch.flip(yi, [1])
        x[i], y[i] = xi, yi
    if cfg.jitter:                 # brightness and contrast per crop and band, in z-score units
        nb = x.shape[1]
        g = torch.from_numpy(rng.normal(0, cfg.jitter, (len(x), 1, 1, 1)) + rng.normal(0, cfg.jitter / 2, (len(x), nb, 1, 1))).float().to(device)
        b = torch.from_numpy(rng.normal(0, cfg.jitter, (len(x), 1, 1, 1)) + rng.normal(0, cfg.jitter / 2, (len(x), nb, 1, 1))).float().to(device)
        x = x * (1 + g) + b
    return x, y


def dice_loss(logits: torch.Tensor, y: torch.Tensor, n: int) -> torch.Tensor:
    """Multiclass soft Dice, 255 ignored, mean over classes."""
    ok = (y != 255).unsqueeze(1).float()
    p = F.softmax(logits, 1) * ok
    t = F.one_hot(y.clamp(max=n - 1), n).permute(0, 3, 1, 2).float() * ok
    inter = (p * t).sum((0, 2, 3))
    den = p.sum((0, 2, 3)) + t.sum((0, 2, 3))
    return 1 - ((2 * inter + 1) / (den + 1)).mean()


def lr_factor(total: int, warm: int) -> Callable[[int], float]:
    """Linear warmup, then cosine decay to 1 % of the base LR."""
    def f(s: int) -> float:
        if s < warm:
            return (s + 1) / warm
        return 0.5 * (1 + np.cos(np.pi * min(1, (s - warm) / max(1, total - warm)))) * 0.99 + 0.01
    return f


# ---------------------------------------------------------------- RNG and checkpoints
def rng_state(rng: np.random.Generator, device: str) -> dict:
    st = {"numpy": rng.bit_generator.state, "torch": torch.get_rng_state()}
    if device == "mps":
        st["mps"] = torch.mps.get_rng_state()
    return st


def set_rng_state(rng: np.random.Generator, st: dict, device: str) -> None:
    rng.bit_generator.state = st["numpy"]
    torch.set_rng_state(st["torch"])
    if device == "mps" and "mps" in st:
        torch.mps.set_rng_state(st["mps"])


def atomic_save(obj, path: Path) -> None:
    """Save next to the target, then rename. A kill during save never leaves a broken last.pt."""
    tmp = path.with_name(path.name + ".tmp")
    torch.save(obj, tmp)
    tmp.replace(path)


def memory_gb(device: str) -> dict:
    """Peak resident memory of the process and memory the GPU driver holds, in GB."""
    out = {"rss_peak_gb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e9, 2)}  # bytes on macOS
    if device == "mps":
        out["mps_driver_gb"] = round(torch.mps.driver_allocated_memory() / 1e9, 2)
    return out


# ---------------------------------------------------------------- the run
class RunExists(RuntimeError):
    pass


class Pause:
    """Set by SIGTERM or the time cap. The loop checks it after every step."""

    def __init__(self, max_minutes: float | None, t_start: float, at_step: int | None = None):
        self.deadline = t_start + max_minutes * 60 if max_minutes is not None else None
        self.at_step = at_step      # pause before this global step (lets tests pause at a known point)
        self.signal = False

    def due(self, global_step: int) -> bool:
        if self.at_step is not None and global_step >= self.at_step:
            return True
        return self.signal or (self.deadline is not None and time.time() >= self.deadline)


def prepare_run_dir(run_dir: Path, resume: bool) -> None:
    if resume:
        if not (run_dir / "last.pt").exists():
            raise FileNotFoundError(f"nothing to resume: {run_dir / 'last.pt'} missing")
        return
    if run_dir.exists():
        raise RunExists(f"{run_dir} exists. Use --resume to continue it, or pick a new --run name")
    run_dir.mkdir(parents=True)


def validate(model, val: Boxes, cfg: Config, mean, std, device: str) -> tuple[dict, np.ndarray]:
    n = cfg.classes
    cm = np.zeros((n, n), np.int64)
    for img, lab in val:
        pred = predict_array(model, np.asarray(img), mean, std, device, n_classes=n, win=cfg.val_win,
                             margin=cfg.val_margin, ndvi=cfg.ndvi)
        cm += confusion(pred, np.asarray(lab), n)
    return scores(cm, classes_for(n)), cm


def write_log(run_dir: Path, rows: list[dict]) -> None:
    if not rows:
        return
    keys = list(rows[0])
    with open(run_dir / "log.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def write_result(run_dir: Path, cfg: Config, st: dict, state: str, reason: str, device: str) -> dict:
    best_row = max(st["log"], key=lambda r: r["val_miou"]) if st["log"] else {}
    res = {"run": cfg.run, "state": state, "reason": reason, "config": asdict(cfg),
           "best_val_miou": st["best"] if st["best"] >= 0 else None, "best_epoch": best_row.get("epoch"),
           "best_val_iou": {c: best_row.get(f"val_iou_{c}") for c in classes_for(cfg.classes)} if best_row else None,
           "epochs_done": st["epoch"], "step_in_epoch": st["step"], "minutes": round(st["minutes"], 1),
           "sessions": st["sessions"], "device": device, "memory": memory_gb(device)}
    (run_dir / "result.json").write_text(json.dumps(res, indent=1, default=float))
    return res


def train(cfg: Config, run_dir: Path, resume: bool = False, max_minutes: float | None = None,
          device: str = "cpu", data_fn: Callable[[Config], dict[str, Boxes]] = load_real_data,
          log: Callable[[str], None] = print, pause_at_step: int | None = None) -> dict:
    """Train or continue one run. Returns the result.json content."""
    t_start = time.time()
    prepare_run_dir(run_dir, resume)
    if resume:
        cfg = Config(**json.loads((run_dir / "config.json").read_text()))
    else:
        (run_dir / "config.json").write_text(json.dumps(asdict(cfg), indent=1))

    pause = Pause(max_minutes, t_start, pause_at_step)
    old = signal.signal(signal.SIGTERM, lambda *_: setattr(pause, "signal", True))
    try:
        return _run(cfg, run_dir, resume, pause, device, data_fn, log)
    finally:
        signal.signal(signal.SIGTERM, old)


def _run(cfg: Config, run_dir: Path, resume: bool, pause: Pause, device: str,
         data_fn: Callable[[Config], dict[str, Boxes]], log: Callable[[str], None]) -> dict:
    n = cfg.classes
    torch.manual_seed(cfg.seed)
    rng = np.random.default_rng(cfg.seed)
    t0 = time.time()
    d = data_fn(cfg)
    log(f"loaded {len(d['train'])} train, {len(d['val'])} val boxes in {time.time() - t0:.0f} s")

    init = None
    if cfg.init_from:
        init = torch.load(Path(cfg.init_from).expanduser(), map_location="cpu", weights_only=False)
        mean, std = np.asarray(init["mean"], np.float32), np.asarray(init["std"], np.float32)
    else:
        mean, std = band_stats(d["train"], cfg.ndvi)
    if init is not None and len(init.get("class_weights", [])) == n:
        # keep the loss of the starting model. A small city set can have almost no
        # pixels of one class (water), and 1 / sqrt(share) would then swamp the rest
        cw = np.asarray(init["class_weights"], np.float32)
    else:
        cw = class_weights(d["train"], n)
    bld_px = building_pixels(d["train"])
    log(f"mean {mean.round(2)} std {std.round(2)} class weights {cw.round(3)}")

    model = make_model(cfg.kind, in_ch=5 if cfg.ndvi else 4, n_classes=n, encoder=cfg.encoder,
                       pretrained=cfg.pretrained and not cfg.init_from)
    if init is not None:
        model.load_state_dict(init["state"])
    model.to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=cfg.lr, weight_decay=1e-4)
    total = cfg.epochs * cfg.steps
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lr_factor(total, min(cfg.warmup, total // 10)))
    cw_t = torch.as_tensor(cw).to(device)

    st = {"epoch": 0, "step": 0, "loss_sum": 0.0, "best": -1.0, "bad": 0, "log": [], "minutes": 0.0, "sessions": 0}
    if resume:
        ck = torch.load(run_dir / "last.pt", map_location="cpu", weights_only=False)
        model.load_state_dict(ck["model"])
        opt.load_state_dict(ck["opt"])
        sched.load_state_dict(ck["sched"])
        st = ck["progress"]
        set_rng_state(rng, ck["rng"], device)
        if st.get("finished"):
            log(f"run already finished ({st['finished']})")
            return write_result(run_dir, cfg, st, "done", st["finished"], device)
        log(f"resumed at epoch {st['epoch'] + 1}, step {st['step']}, best val mIoU {st['best']}")
    st["sessions"] += 1
    log(f"{device} | {sum(p.numel() for p in model.parameters()):,} parameters | {cfg.classes} classes")

    def save_last() -> None:
        atomic_save({"model": model.state_dict(), "opt": opt.state_dict(), "sched": sched.state_dict(),
                     "progress": st, "rng": rng_state(rng, device), "config": asdict(cfg)}, run_dir / "last.pt")

    t_mark = time.time()

    def tick() -> None:            # running total of training minutes, across sessions
        nonlocal t_mark
        st["minutes"] += (time.time() - t_mark) / 60
        t_mark = time.time()

    while st["epoch"] < cfg.last_epoch:
        ep = st["epoch"] + 1
        model.train()
        while st["step"] < cfg.steps:
            if pause.due(st["epoch"] * cfg.steps + st["step"]):
                tick()
                save_last()
                log(f"paused at epoch {ep}, step {st['step']} ({st['minutes']:.1f} min)")
                return write_result(run_dir, cfg, st, "paused", "signal" if pause.signal else "max_minutes", device)
            x, y = make_batch(cfg, d["train"], bld_px, rng, mean, std, device)
            out = model(x)
            loss = F.cross_entropy(out, y, weight=cw_t, ignore_index=255)
            if cfg.dice:
                loss = loss + cfg.dice * dice_loss(out, y, n)
            opt.zero_grad()
            loss.backward()
            opt.step()
            sched.step()
            st["loss_sum"] += loss.item()
            st["step"] += 1
            if st["step"] % 100 == 0:
                tick()
                log(f"  step {st['step']}/{cfg.steps} loss {st['loss_sum'] / st['step']:.3f} ({st['minutes']:.1f} min)")

        s, cm = validate(model, d["val"], cfg, mean, std, device)
        tick()
        row = {"epoch": ep, "train_loss": st["loss_sum"] / cfg.steps, "val_miou": s["miou"], "val_acc": s["accuracy"],
               **{f"val_iou_{k}": v for k, v in s["iou"].items()}, "lr": sched.get_last_lr()[0],
               "minutes": st["minutes"], **memory_gb(device)}
        st["log"].append(row)
        st.update(epoch=ep, step=0, loss_sum=0.0)
        flag = ""
        if s["miou"] > st["best"]:
            st["best"], st["bad"], flag = s["miou"], 0, " *"
            atomic_save({"state": model.state_dict(), "kind": cfg.kind, "encoder": cfg.encoder, "ndvi": cfg.ndvi,
                         "n_classes": n, "classes": classes_for(n), "mean": mean, "std": std, "epoch": ep,
                         "val_miou": s["miou"], "val_counties": vdata.VAL_COUNTIES, "class_weights": cw.tolist(),
                         "args": asdict(cfg), "val_confusion": cm.tolist()}, run_dir / "best.pt")
        else:
            st["bad"] += 1
        if st["bad"] >= cfg.patience:
            st["finished"] = "early_stop"
        elif ep >= cfg.last_epoch:
            st["finished"] = "stop_epoch"
        save_last()
        write_log(run_dir, st["log"])
        log(f"epoch {ep}: loss {row['train_loss']:.3f} val mIoU {s['miou']:.4f} {s['iou']} "
            f"({st['minutes']:.1f} min, {memory_gb(device)}){flag}")
        if st.get("finished"):
            break
    st.setdefault("finished", "stop_epoch")
    save_last()
    log(f"done ({st['finished']}), best val mIoU {st['best']}")
    return write_result(run_dir, cfg, st, "done", st["finished"], device)


# ---------------------------------------------------------------- CLI
def parse(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Train the land cover U-Net (resumable)")
    ap.add_argument("--run", required=True, help="run name, folder models/<run>")
    ap.add_argument("--resume", action="store_true", help="continue the run from last.pt (recipe comes from its config.json)")
    ap.add_argument("--max-minutes", type=float, help="pause cleanly after this many minutes of wall clock")
    ap.add_argument("--device")
    ap.add_argument("--classes", type=int, default=4, choices=[4, 5])
    ap.add_argument("--kind", default="smp", choices=["smp", "plain"])
    ap.add_argument("--encoder", default="resnet34")
    ap.add_argument("--no-pretrained", action="store_true")
    ap.add_argument("--ndvi", action="store_true")
    ap.add_argument("--crop", type=int, default=384)
    ap.add_argument("--batch", type=int, default=12)
    ap.add_argument("--steps", type=int, default=400)
    ap.add_argument("--epochs", type=int, default=16, help="planned epochs, sets the LR schedule")
    ap.add_argument("--stop-epoch", type=int, default=0, help="end the run after this epoch (0 = all --epochs)")
    ap.add_argument("--patience", type=int, default=5)
    ap.add_argument("--lr", type=float, default=5e-4)
    ap.add_argument("--warmup", type=int, default=300)
    ap.add_argument("--dice", type=float, default=0.5)
    ap.add_argument("--bld-frac", type=float, default=1 / 3)
    ap.add_argument("--jitter", type=float, default=0.1)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--init-from", default="", help="start from the weights of this checkpoint")
    ap.add_argument("--data", default="chesapeake", help='"chesapeake" or "city:<name>"')
    return ap.parse_args(argv)


def config_from_args(a: argparse.Namespace) -> Config:
    return Config(run=a.run, classes=a.classes, kind=a.kind, encoder=a.encoder, pretrained=not a.no_pretrained,
                  ndvi=a.ndvi, crop=a.crop, batch=a.batch, steps=a.steps, epochs=a.epochs, stop_epoch=a.stop_epoch,
                  patience=a.patience, lr=a.lr, warmup=a.warmup, dice=a.dice, bld_frac=a.bld_frac, jitter=a.jitter,
                  seed=a.seed, init_from=a.init_from, data=a.data)


def main(argv: list[str] | None = None) -> int:
    a = parse(argv)
    device = a.device or ("mps" if torch.backends.mps.is_available() else "cuda" if torch.cuda.is_available() else "cpu")
    run_dir = vdata.models_dir() / a.run
    try:
        res = train(config_from_args(a), run_dir, a.resume, a.max_minutes, device,
                    log=lambda m: print(m, flush=True))
    except RunExists as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    print(json.dumps({k: res[k] for k in ["run", "state", "reason", "best_val_miou", "epochs_done", "minutes"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
