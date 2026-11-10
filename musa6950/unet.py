"""Plain U-Net used by notebooks 03 (training) and 05 (pilot counties).

No extra packages: torch only.
"""
import numpy as np
import torch
import torch.nn as nn

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


def normalize(img, mean, std):
    """img (4, H, W) uint8 -> float32 tensor, per-band z-score."""
    x = torch.from_numpy(img.astype(np.float32))
    return (x - torch.as_tensor(mean).view(-1, 1, 1)) / torch.as_tensor(std).view(-1, 1, 1)


@torch.no_grad()
def predict_array(model, img, mean, std, device, win=512, margin=64, batch=4):
    """Predict classes for a whole (4, H, W) image.

    Windows of win + 2*margin pixels, keep the center win x win (less edge effect).
    Returns uint8 (H, W).
    """
    model.eval()
    _, H, W = img.shape
    full = win + 2 * margin
    nh, nw = -(-H // win), -(-W // win)
    pad = np.pad(img, ((0, 0), (margin, nh * win - H + margin), (margin, nw * win - W + margin)), mode="reflect")
    x = normalize(pad, mean, std)
    out = np.zeros((nh * win, nw * win), np.uint8)
    spots = [(i, j) for i in range(nh) for j in range(nw)]
    for k in range(0, len(spots), batch):
        part = spots[k:k + batch]
        xb = torch.stack([x[:, i * win:i * win + full, j * win:j * win + full] for i, j in part]).to(device)
        p = model(xb).argmax(1).cpu().numpy().astype(np.uint8)
        for (i, j), pj in zip(part, p):
            out[i * win:(i + 1) * win, j * win:(j + 1) * win] = pj[margin:margin + win, margin:margin + win]
    return out[:H, :W]
