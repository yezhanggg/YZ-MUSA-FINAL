"""U-Net models and whole-image prediction.

Port of musa6950/unet.py, with the class count as a parameter so the same
code serves the 4-class and the 5-class model. Checkpoints written by the
course code load unchanged (load_model reads both formats).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F


class Block(nn.Module):
    def __init__(self, cin: int, cout: int):
        super().__init__()
        self.net = nn.Sequential(
            nn.Conv2d(cin, cout, 3, padding=1, bias=False), nn.BatchNorm2d(cout), nn.ReLU(inplace=True),
            nn.Conv2d(cout, cout, 3, padding=1, bias=False), nn.BatchNorm2d(cout), nn.ReLU(inplace=True))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


class UNet(nn.Module):
    """Plain U-Net: 4 levels down, 4 up, skip connections. Input size must be a multiple of 16."""

    def __init__(self, in_ch: int = 4, n_classes: int = 4, base: int = 32):
        super().__init__()
        ch = [base, base * 2, base * 4, base * 8, base * 16]
        self.downs = nn.ModuleList()
        c = in_ch
        for k in ch[:-1]:
            self.downs.append(Block(c, k))
            c = k
        self.pool = nn.MaxPool2d(2)
        self.bottom = Block(ch[-2], ch[-1])
        self.ups, self.dec = nn.ModuleList(), nn.ModuleList()
        for k in reversed(ch[:-1]):
            self.ups.append(nn.ConvTranspose2d(k * 2, k, 2, stride=2))
            self.dec.append(Block(k * 2, k))
        self.head = nn.Conv2d(base, n_classes, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        skips = []
        for d in self.downs:
            x = d(x)
            skips.append(x)
            x = self.pool(x)
        x = self.bottom(x)
        for up, dec, s in zip(self.ups, self.dec, reversed(skips)):
            x = dec(torch.cat([up(x), s], 1))
        return self.head(x)


def adapt_first_conv(conv: nn.Conv2d, in_ch: int) -> nn.Conv2d:
    """ImageNet RGB conv -> in_ch bands.

    R, G, B keep their weights. NIR starts as the mean of the RGB weights.
    A 5th channel (NDVI) starts at 0. Weights are scaled by 3/4 so the
    output size stays about the same with one more band.
    """
    w = conv.weight.data
    new = torch.zeros(w.shape[0], in_ch, *w.shape[2:])
    new[:, :3] = w
    if in_ch > 3:
        new[:, 3] = w.mean(1)
    new[:, :4] *= 3 / 4
    out = nn.Conv2d(in_ch, conv.out_channels, conv.kernel_size, conv.stride, conv.padding, bias=conv.bias is not None)
    out.weight.data = new
    if conv.bias is not None:
        out.bias.data = conv.bias.data.clone()
    return out


def make_model(kind: str = "smp", in_ch: int = 4, n_classes: int = 4, encoder: str = "resnet34",
               pretrained: bool = True, base: int = 32) -> nn.Module:
    if kind == "plain":
        return UNet(in_ch, n_classes, base)
    import segmentation_models_pytorch as smp

    m = smp.Unet(encoder_name=encoder, encoder_weights="imagenet" if pretrained else None,
                 in_channels=3, classes=n_classes)
    # swap the first 3-band conv of the encoder for one that takes 4 or 5 bands
    name, conv = next((n, c) for n, c in m.encoder.named_modules() if isinstance(c, nn.Conv2d) and c.in_channels == 3)
    parent = m.encoder.get_submodule(name.rsplit(".", 1)[0]) if "." in name else m.encoder
    new = adapt_first_conv(conv, in_ch)
    if type(conv) is not nn.Conv2d:          # keep the padding of timm same-padding convs
        conv.weight = nn.Parameter(new.weight.data)
        conv.in_channels = in_ch
    else:
        setattr(parent, name.rsplit(".", 1)[-1], new)
    return m


def add_ndvi(x: torch.Tensor) -> torch.Tensor:
    """(B, 4, H, W) raw 0-255 -> (B, 5, H, W) with NDVI = (NIR - R) / (NIR + R)."""
    r, nir = x[:, 0:1], x[:, 3:4]
    return torch.cat([x, (nir - r) / (nir + r + 1e-6)], 1)


def to_input(raw, mean, std, ndvi: bool = False) -> torch.Tensor:
    """raw (B, 4, H, W) uint8 -> normalized float tensor (B, 4 or 5, H, W)."""
    x = torch.as_tensor(raw).float()
    if ndvi:
        x = add_ndvi(x)
    m = torch.as_tensor(mean, dtype=torch.float32, device=x.device).view(1, -1, 1, 1)
    s = torch.as_tensor(std, dtype=torch.float32, device=x.device).view(1, -1, 1, 1)
    return (x - m) / s


def checkpoint_n_classes(ck: dict) -> int:
    """Class count of a checkpoint. Course checkpoints have no field, they are all 4-class."""
    if "n_classes" in ck:
        return int(ck["n_classes"])
    head = [v for k, v in ck["state"].items() if k.endswith("weight") and ("segmentation_head" in k or k.startswith("head"))]
    return int(head[-1].shape[0]) if head else 4


def load_model(path: str | Path, device: str) -> tuple[nn.Module, dict]:
    """Load a checkpoint from train.py or the course code. Returns (model, meta)."""
    ck = torch.load(path, map_location="cpu", weights_only=False)
    kind = ck.get("kind", "plain")
    n = checkpoint_n_classes(ck)
    model = make_model(kind, in_ch=5 if ck.get("ndvi") else 4, n_classes=n, encoder=ck.get("encoder", "resnet34"),
                       pretrained=False, base=ck.get("base", 32))
    model.load_state_dict(ck["state"])
    model.to(device).eval()
    meta = {k: v for k, v in ck.items() if k != "state"}
    meta.update(mean=np.asarray(ck["mean"], np.float32), std=np.asarray(ck["std"], np.float32),
                ndvi=bool(ck.get("ndvi", False)), kind=kind, n_classes=n, class_bias=ck.get("class_bias"))
    return model, meta


# 8 views: 4 turns x (no flip, flip). Each is undone on the output.
D4 = [(k, f) for f in (False, True) for k in range(4)]


@torch.no_grad()
def predict_proba(model: nn.Module, x: torch.Tensor, tta: bool = False, bias=None) -> torch.Tensor:
    """x normalized (B, C, H, W) -> class probabilities (B, n, H, W).

    tta averages the 8 flips and turns. bias = per-class log offsets picked on validation.
    """
    model.eval()
    if not tta:
        out = F.softmax(model(x), 1)
    else:
        out = 0
        for k, f in D4:
            v = torch.flip(x, [3]) if f else x
            v = torch.rot90(v, k, [2, 3])
            p = torch.rot90(F.softmax(model(v), 1), -k, [2, 3])
            out = out + (torch.flip(p, [3]) if f else p)
        out = out / len(D4)
    if bias is not None:
        out = out * torch.exp(torch.as_tensor(bias, dtype=out.dtype, device=out.device)).view(1, -1, 1, 1)
        out = out / out.sum(1, keepdim=True)
    return out


@torch.no_grad()
def predict_array(model: nn.Module, img: np.ndarray, mean, std, device: str, n_classes: int = 4, win: int = 512,
                  margin: int = 64, batch: int = 4, ndvi: bool = False, tta: bool = False, proba: bool = False,
                  bias=None) -> np.ndarray:
    """Classify a whole (4, H, W) uint8 image.

    Windows of win + 2 * margin pixels, only the center win x win is kept
    (less edge effect). Returns uint8 (H, W), or float16 (n, H, W) if proba.
    """
    model.eval()
    _, H, W = img.shape
    full = win + 2 * margin
    nh, nw = -(-H // win), -(-W // win)
    pad = torch.from_numpy(np.pad(img, ((0, 0), (margin, nh * win - H + margin), (margin, nw * win - W + margin)),
                                  mode="reflect"))
    out = np.zeros((n_classes, nh * win, nw * win), np.float16) if proba else np.zeros((nh * win, nw * win), np.uint8)
    spots = [(i, j) for i in range(nh) for j in range(nw)]
    for k in range(0, len(spots), batch):
        part = spots[k:k + batch]
        raw = torch.stack([pad[:, i * win:i * win + full, j * win:j * win + full] for i, j in part]).to(device)
        p = predict_proba(model, to_input(raw, mean, std, ndvi), tta, bias)[:, :, margin:margin + win, margin:margin + win]
        p = p.cpu().numpy()
        for (i, j), pj in zip(part, p):
            if proba:
                out[:, i * win:(i + 1) * win, j * win:(j + 1) * win] = pj
            else:
                out[i * win:(i + 1) * win, j * win:(j + 1) * win] = pj.argmax(0)
    return out[..., :H, :W]
