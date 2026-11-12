"""Train the land cover U-Net (MUSA 6950, step 3). Run from the repo root, geoai env.

    python musa6950/train_unet.py --tag r34 --minutes 40

Same data and split as notebook 03:
- train = 122 boxes, val = 24 boxes in 7 held-back train counties (seed 42)
- test (Cumberland, Centre) is never loaded here

What is new vs the first model (v1, plain U-Net, 10 epochs):
- ImageNet ResNet-34 encoder (segmentation-models-pytorch), first conv changed to 4 bands
- random 384 px crops from the whole boxes, 1 in 3 centered on a building pixel
- flips + 90 degree turns + brightness / contrast jitter per band
- cross entropy (weights 1 / sqrt(class share)) + Dice loss
- AdamW, warmup then cosine decay, early stop on validation mIoU
- validation = every labeled pixel of the 24 val boxes, same windows as the test

Saves data/models/unet_<tag>.pt and data/models/unet_<tag>_log.csv
"""

import argparse
import json
import sys
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import torch
import torch.nn.functional as F

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "shared"))
sys.path.insert(0, str(ROOT / "musa6950"))
from common import RAW  # noqa: E402
from unet import CLASSES, add_ndvi, make_model, predict_array, to_input  # noqa: E402

R6 = RAW / "6950"
MODELS = ROOT / "data" / "models"
VAL_COUNTIES = ["42001", "42009", "42011", "42021", "42099", "42109", "42117"]


def split_boxes():
    """Same split as notebook 03."""
    boxes = gpd.read_file(R6 / "sample_boxes.gpkg")
    have = boxes.GEOID.map(lambda g: (R6 / "naip" / f"{g}.tif").exists() and (R6 / "labels" / f"{g}.tif").exists())
    boxes = boxes[have].reset_index(drop=True)
    rng = np.random.default_rng(42)
    order = rng.permutation(boxes[boxes.split == "train"].county.unique())
    val, n, target = [], 0, int(0.15 * (boxes.split == "train").sum())
    for c in order:
        if n >= target:
            break
        val.append(c)
        n += (boxes.county == c).sum()
    assert sorted(val) == VAL_COUNTIES, val
    boxes["role"] = np.where(boxes.split == "test", "test", np.where(boxes.county.isin(val), "val", "train"))
    return boxes


def load(geoid):
    with rasterio.open(R6 / "naip" / f"{geoid}.tif") as s:
        img = s.read()
    with rasterio.open(R6 / "labels" / f"{geoid}.tif") as s:
        lab = s.read(1)
    return img, lab


CACHE = R6 / "npy_cache"  # plain .npy copies of the boxes, read as memory maps (low RAM). Safe to delete


def load_mm(geoid):
    """Same as load(), but from a memory-mapped .npy cache, so the boxes do not sit in RAM."""
    CACHE.mkdir(exist_ok=True)
    fi, fl = CACHE / f"{geoid}_img.npy", CACHE / f"{geoid}_lab.npy"
    if not fl.exists():
        img, lab = load(geoid)
        np.save(fi, img)
        np.save(fl, lab)
    return np.load(fi, mmap_mode="r"), np.load(fl, mmap_mode="r")


def confusion(pred, y):
    ok = y != 255
    return np.bincount(y[ok].astype(np.int64) * 4 + pred[ok], minlength=16).reshape(4, 4)


def scores(cm):
    tp = np.diag(cm).astype(float)
    iou = tp / (cm.sum(0) + cm.sum(1) - tp)
    return {
        "iou": dict(zip(CLASSES, iou.round(4).tolist(), strict=True)),
        "miou": round(float(iou.mean()), 4),
        "accuracy": round(float(tp.sum() / cm.sum()), 4),
    }


def dice_loss(logits, y, n=4):
    """Multiclass soft Dice, 255 ignored, mean over classes."""
    ok = (y != 255).unsqueeze(1).float()
    p = F.softmax(logits, 1) * ok
    t = F.one_hot(y.clamp(max=n - 1), n).permute(0, 3, 1, 2).float() * ok
    inter = (p * t).sum((0, 2, 3))
    den = p.sum((0, 2, 3)) + t.sum((0, 2, 3))
    return 1 - ((2 * inter + 1) / (den + 1)).mean()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--kind", default="smp", choices=["smp", "plain"])
    ap.add_argument("--encoder", default="resnet34")
    ap.add_argument("--no-pretrained", action="store_true")
    ap.add_argument("--ndvi", action="store_true")
    ap.add_argument("--crop", type=int, default=384)
    ap.add_argument("--batch", type=int, default=12)
    ap.add_argument("--steps", type=int, default=400, help="steps per epoch")
    ap.add_argument("--epochs", type=int, default=12, help="planned epochs (sets the LR schedule)")
    ap.add_argument("--minutes", type=float, default=60, help="time cap")
    ap.add_argument("--patience", type=int, default=4)
    ap.add_argument("--lr", type=float, default=5e-4)
    ap.add_argument("--dice", type=float, default=0.5, help="weight of the Dice loss (0 = cross entropy only)")
    ap.add_argument("--bld-frac", type=float, default=1 / 3, help="share of crops centered on a building pixel")
    ap.add_argument("--jitter", type=float, default=0.1)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()

    torch.manual_seed(a.seed)
    rng = np.random.default_rng(a.seed)
    device = "mps" if torch.backends.mps.is_available() else "cuda" if torch.cuda.is_available() else "cpu"
    boxes = split_boxes()
    t0 = time.time()
    data = {r: [load_mm(g) for g in boxes[boxes.role == r].GEOID] for r in ["train", "val"]}
    print(f"loaded {len(data['train'])} train, {len(data['val'])} val boxes in {time.time() - t0:.0f} s", flush=True)

    # band stats + class weights from train only
    sample = np.concatenate([img[:, ::7, ::7].reshape(4, -1) for img, _ in data["train"]], 1).astype(np.float32)
    if a.ndvi:
        sample = add_ndvi(torch.from_numpy(sample)[None, :, None, :])[0, :, 0].numpy()
    mean, std = sample.mean(1).astype(np.float32), sample.std(1).astype(np.float32)
    freq = sum(np.bincount(np.asarray(lab).ravel(), minlength=256)[:4] for _, lab in data["train"]).astype(float)
    freq /= freq.sum()
    w = 1 / np.sqrt(freq)
    cw = (w / w.mean()).astype(np.float32)
    print("mean", mean.round(2), "std", std.round(2), "class weights", cw.round(2), flush=True)
    bld_px = [np.flatnonzero(np.asarray(lab).ravel() == 1)[::20].astype(np.int32).copy() for _, lab in data["train"]]

    C = a.crop

    def batch():
        xs, ys = [], []
        for _ in range(a.batch):
            k = rng.integers(len(data["train"]))
            img, lab = data["train"][k]
            H, W = lab.shape
            if rng.random() < a.bld_frac and len(bld_px[k]):
                r, c = divmod(int(rng.choice(bld_px[k])), W)
                r0 = int(np.clip(r - C // 2 + rng.integers(-C // 4, C // 4 + 1), 0, H - C))
                c0 = int(np.clip(c - C // 2 + rng.integers(-C // 4, C // 4 + 1), 0, W - C))
            else:
                r0, c0 = rng.integers(0, H - C + 1), rng.integers(0, W - C + 1)
            xs.append(img[:, r0 : r0 + C, c0 : c0 + C])
            ys.append(lab[r0 : r0 + C, c0 : c0 + C])
        x = to_input(torch.from_numpy(np.stack(xs)).to(device), mean, std, a.ndvi)
        y = torch.from_numpy(np.stack(ys)).long().to(device)
        # same random flip / turn on image and label, one per crop
        for i in range(len(x)):
            k = int(rng.integers(4))
            xi, yi = torch.rot90(x[i], k, [1, 2]), torch.rot90(y[i], k, [0, 1])
            if rng.random() < 0.5:
                xi, yi = torch.flip(xi, [2]), torch.flip(yi, [1])
            x[i], y[i] = xi, yi
        if a.jitter:  # brightness / contrast per crop and band, in z-score units
            nb = x.shape[1]
            g = (
                torch.from_numpy(
                    rng.normal(0, a.jitter, (len(x), 1, 1, 1)) + rng.normal(0, a.jitter / 2, (len(x), nb, 1, 1))
                )
                .float()
                .to(device)
            )
            b = (
                torch.from_numpy(
                    rng.normal(0, a.jitter, (len(x), 1, 1, 1)) + rng.normal(0, a.jitter / 2, (len(x), nb, 1, 1))
                )
                .float()
                .to(device)
            )
            x = x * (1 + g) + b
        return x, y

    model = make_model(a.kind, in_ch=5 if a.ndvi else 4, encoder=a.encoder, pretrained=not a.no_pretrained).to(device)
    print(device, f"{sum(p.numel() for p in model.parameters()):,} parameters", flush=True)
    opt = torch.optim.AdamW(model.parameters(), lr=a.lr, weight_decay=1e-4)
    total = a.epochs * a.steps
    warm = min(300, total // 10)
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt,
        lambda s: (
            (s + 1) / warm
            if s < warm
            else 0.5 * (1 + np.cos(np.pi * min(1, (s - warm) / max(1, total - warm)))) * 0.99 + 0.01
        ),
    )
    cw_t = torch.as_tensor(cw).to(device)

    log, best, bad, t0 = [], -1, 0, time.time()
    dest = MODELS / f"unet_{a.tag}.pt"
    for ep in range(1, a.epochs + 1):
        model.train()
        tot = 0.0
        for _ in range(a.steps):
            x, y = batch()
            out = model(x)
            loss = F.cross_entropy(out, y, weight=cw_t, ignore_index=255)
            if a.dice:
                loss = loss + a.dice * dice_loss(out, y)
            opt.zero_grad()
            loss.backward()
            opt.step()
            sched.step()
            tot += loss.item()
            if (_ + 1) % 100 == 0:
                print(
                    f"  step {_ + 1}/{a.steps} loss {tot / (_ + 1):.3f} ({(time.time() - t0) / 60:.1f} min)", flush=True
                )
        cm = np.zeros((4, 4), np.int64)
        for img, lab in data["val"]:
            cm += confusion(predict_array(model, np.asarray(img), mean, std, device, ndvi=a.ndvi), np.asarray(lab))
        s = scores(cm)
        mins = (time.time() - t0) / 60
        log.append(
            {
                "epoch": ep,
                "train_loss": tot / a.steps,
                "val_miou": s["miou"],
                "val_acc": s["accuracy"],
                **{f"val_iou_{k}": v for k, v in s["iou"].items()},
                "lr": sched.get_last_lr()[0],
                "minutes": mins,
            }
        )
        pd.DataFrame(log).to_csv(MODELS / f"unet_{a.tag}_log.csv", index=False)
        flag = ""
        if s["miou"] > best:
            best, bad, flag = s["miou"], 0, " *"
            torch.save(
                {
                    "state": model.state_dict(),
                    "kind": a.kind,
                    "encoder": a.encoder,
                    "ndvi": a.ndvi,
                    "mean": mean,
                    "std": std,
                    "epoch": ep,
                    "val_miou": best,
                    "val_counties": VAL_COUNTIES,
                    "class_weights": cw.tolist(),
                    "args": vars(a),
                    "val_confusion": cm.tolist(),
                },
                dest,
            )
        else:
            bad += 1
        print(
            f"epoch {ep}: loss {tot / a.steps:.3f} val mIoU {s['miou']:.4f} {s['iou']} ({mins:.1f} min){flag}",
            flush=True,
        )
        if bad >= a.patience:
            print("early stop")
            break
        if mins > a.minutes:
            print("time cap reached")
            break
    with open(MODELS / f"unet_{a.tag}_summary.json", "w") as fh:
        json.dump(
            {
                "tag": a.tag,
                "best_val_miou": best,
                "minutes": round((time.time() - t0) / 60, 1),
                "epochs": len(log),
                "args": vars(a),
            },
            fh,
            indent=1,
        )
    print("best val mIoU", best)


if __name__ == "__main__":
    main()
