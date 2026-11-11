"""U-Net models used by notebooks 03 (training + test) and 05 (pilot counties).

Two models:
- UNet: plain U-Net in torch, the first model (v1). Torch only
- make_model("smp", ...): U-Net with an ImageNet ResNet-34 encoder from
  segmentation-models-pytorch (v2, the final model). 4 bands in (R, G, B, NIR),
  plus NDVI as a 5th channel if asked

Use load_model() to get either one back from a saved checkpoint,
and predict_array() to classify a whole image.
"""
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

CLASSES = ["other", "building", "tree", "open"]


class Block(nn.Module):
    def __init__(self, cin, cout):
        super().__init__()
        self.net = nn.Sequential(
            nn.Conv2d(cin, cout, 3, padding=1, bias=False), nn.BatchNorm2d(cout), nn.ReLU(inplace=True),
            nn.Conv2d(cout, cout, 3, padding=1, bias=False), nn.BatchNorm2d(cout), nn.ReLU(inplace=True))

    def forward(self, x):
        return self.net(x)


class UNet(nn.Module):
    """4 levels down, 4 up, skip connections. Input size must be a multiple of 16."""

    def __init__(self, in_ch=4, n_classes=4, base=32):
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

    def forward(self, x):
        skips = []
        for d in self.downs:
            x = d(x)
            skips.append(x)
            x = self.pool(x)
        x = self.bottom(x)
        for up, dec, s in zip(self.ups, self.dec, reversed(skips)):
            x = dec(torch.cat([up(x), s], 1))
        return self.head(x)


def adapt_first_conv(conv, in_ch):
    """ImageNet RGB conv -> in_ch bands.

    R, G, B keep their weights. NIR starts as the mean of the RGB weights.
    A 5th channel (NDVI) starts at 0, so it is learned from scratch.
    Weights are scaled by 3 / 4 so the output size stays about the same.
    """
    w = conv.weight.data                     # (out, 3, k, k)
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


def make_model(kind="smp", in_ch=4, n_classes=4, encoder="resnet34", pretrained=True, base=32):
    if kind == "plain":
        return UNet(in_ch, n_classes, base)
    import segmentation_models_pytorch as smp
    m = smp.Unet(encoder_name=encoder, encoder_weights="imagenet" if pretrained else None,
                 in_channels=3, classes=n_classes)
    # swap the first 3-band conv of the encoder (conv1 in ResNet, conv_stem in EfficientNet)
    name, conv = next((n, c) for n, c in m.encoder.named_modules() if isinstance(c, nn.Conv2d) and c.in_channels == 3)
    parent = m.encoder.get_submodule(name.rsplit(".", 1)[0]) if "." in name else m.encoder
    new = adapt_first_conv(conv, in_ch)
    if type(conv) is not nn.Conv2d:          # keep padding behaviour of timm's same-padding convs
        conv.weight = nn.Parameter(new.weight.data)
        conv.in_channels = in_ch
    else:
        setattr(parent, name.rsplit(".", 1)[-1], new)
    return m


def add_ndvi(x):
    """x (B, 4, H, W) raw 0-255 float -> (B, 5, H, W) with NDVI = (NIR - R) / (NIR + R)."""
    r, nir = x[:, 0:1], x[:, 3:4]
    return torch.cat([x, (nir - r) / (nir + r + 1e-6)], 1)


def to_input(raw, mean, std, ndvi=False):
    """raw (B, 4, H, W) uint8 tensor or array -> normalized float tensor (B, 4 or 5, H, W)."""
    x = torch.as_tensor(raw).float()
    if ndvi:
        x = add_ndvi(x)
    m = torch.as_tensor(mean, dtype=torch.float32, device=x.device).view(1, -1, 1, 1)
    s = torch.as_tensor(std, dtype=torch.float32, device=x.device).view(1, -1, 1, 1)
    return (x - m) / s


def normalize(img, mean, std):
    """img (4, H, W) uint8 -> float32 tensor, per-band z-score (v1 helper, kept for old code)."""
    x = torch.from_numpy(img.astype(np.float32))
    return (x - torch.as_tensor(mean).view(-1, 1, 1)) / torch.as_tensor(std).view(-1, 1, 1)


def load_model(path, device):
    """Load a checkpoint saved by notebook 03 / train_unet.py. Returns (model, meta)."""
    ck = torch.load(path, map_location="cpu", weights_only=False)
    kind = ck.get("kind", "plain")
    in_ch = 5 if ck.get("ndvi") else 4
    model = make_model(kind, in_ch=in_ch, encoder=ck.get("encoder", "resnet34"), pretrained=False, base=ck.get("base", 32))
    model.load_state_dict(ck["state"])
    model.to(device).eval()
    meta = {k: v for k, v in ck.items() if k != "state"}
    meta.update(mean=np.asarray(ck["mean"], np.float32), std=np.asarray(ck["std"], np.float32),
                ndvi=bool(ck.get("ndvi", False)), kind=kind, class_bias=ck.get("class_bias"))
    return model, meta


# 8 views: 4 rotations x (no flip, flip). Each is undone on the output.
D4 = [(k, f) for f in (False, True) for k in range(4)]


@torch.no_grad()
def predict_proba(model, x, tta=False, bias=None):
    """x normalized (B, C, H, W) on device -> class probabilities (B, 4, H, W).

    tta=True averages the 8 flips / 90-degree rotations.
    bias = per-class log offsets (set on validation in notebook 03), or None.
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
def predict_array(model, img, mean, std, device, win=512, margin=64, batch=4, ndvi=False, tta=False, proba=False, bias=None):
    """Predict classes for a whole (4, H, W) uint8 image.

    Windows of win + 2*margin pixels, keep the center win x win (less edge effect).
    Returns uint8 (H, W), or float16 probabilities (4, H, W) if proba=True.
    """
    model.eval()
    _, H, W = img.shape
    full = win + 2 * margin
    nh, nw = -(-H // win), -(-W // win)
    pad = np.pad(img, ((0, 0), (margin, nh * win - H + margin), (margin, nw * win - W + margin)), mode="reflect")
    pad = torch.from_numpy(pad)
    out = np.zeros((4, nh * win, nw * win), np.float16) if proba else np.zeros((nh * win, nw * win), np.uint8)
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
