"""Land cover training checks on tiny random tensors. CPU only, a few seconds. Needs torch (geoai env)."""
import json

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from pipeline.vision import labels  # noqa: E402
from pipeline.vision.metrics import confusion, edge_band, merge_classes, scores  # noqa: E402
from pipeline.vision.train import Config, RunExists, main, train  # noqa: E402


def tiny_data(cfg: Config) -> dict:
    """3 train boxes and 1 val box of 48 x 48 random pixels, with a few buildings."""
    rng = np.random.default_rng(123)

    def box():
        img = rng.integers(0, 255, (4, 48, 48), dtype=np.uint8)
        lab = rng.integers(0, cfg.classes, (48, 48)).astype(np.uint8)
        lab[:2] = 255                      # some no data
        return img, lab
    return {"train": [box() for _ in range(3)], "val": [box()]}


def tiny_config(run: str) -> Config:
    return Config(run=run, kind="plain", pretrained=False, crop=32, batch=2, steps=3, epochs=2, patience=10,
                  warmup=2, seed=7, val_win=32, val_margin=8, extra={"base": 4})


def run_tiny(cfg, path, **kw):
    import pipeline.vision.train as t

    # a 4-channel-wide U-Net keeps the test fast
    orig = t.make_model
    t.make_model = lambda kind, in_ch, n_classes, encoder, pretrained: orig(kind, in_ch, n_classes, encoder, pretrained, base=4)
    try:
        return train(cfg, path, device="cpu", data_fn=tiny_data, log=lambda m: None, **kw)
    finally:
        t.make_model = orig


def last_state(path):
    return torch.load(path / "last.pt", map_location="cpu", weights_only=False)


def test_resume_matches_uninterrupted_run(tmp_path):
    full = run_tiny(tiny_config("full"), tmp_path / "full")
    paused = run_tiny(tiny_config("split"), tmp_path / "split", pause_at_step=4)   # epoch 2, step 1
    assert paused["state"] == "paused"
    assert paused["epochs_done"] == 1 and paused["step_in_epoch"] == 1
    resumed = run_tiny(tiny_config("split"), tmp_path / "split", resume=True)
    assert full["state"] == resumed["state"] == "done"

    a, b = last_state(tmp_path / "full"), last_state(tmp_path / "split")
    for k in a["model"]:
        assert torch.equal(a["model"][k], b["model"][k]), k
    sa, sb = a["opt"]["state"], b["opt"]["state"]
    for k in sa:
        assert torch.equal(sa[k]["exp_avg"], sb[k]["exp_avg"])
    assert a["sched"]["last_epoch"] == b["sched"]["last_epoch"]
    assert a["rng"]["numpy"] == b["rng"]["numpy"]
    keep = ["epoch", "train_loss", "val_miou", "lr"]
    assert [{k: r[k] for k in keep} for r in a["progress"]["log"]] == [{k: r[k] for k in keep} for r in b["progress"]["log"]]
    assert a["progress"]["best"] == b["progress"]["best"]
    assert resumed["sessions"] == 2
    assert (tmp_path / "split" / "best.pt").exists() and (tmp_path / "split" / "log.csv").exists()


def test_pause_writes_paused_result(tmp_path):
    res = run_tiny(tiny_config("p"), tmp_path / "p", max_minutes=0)
    assert res["state"] == "paused"
    on_disk = json.loads((tmp_path / "p" / "result.json").read_text())
    assert on_disk["state"] == "paused" and on_disk["epochs_done"] == 0


def test_second_start_into_existing_run_is_refused(tmp_path, monkeypatch):
    run_tiny(tiny_config("x"), tmp_path / "x")
    with pytest.raises(RunExists):
        run_tiny(tiny_config("x"), tmp_path / "x")
    # the command line refuses with exit code 2 and leaves the folder alone
    monkeypatch.setenv("ADU_DATA_DIR", str(tmp_path))
    (tmp_path / "models" / "y").mkdir(parents=True)
    (tmp_path / "models" / "y" / "keep.txt").write_text("x")
    assert main(["--run", "y", "--device", "cpu"]) == 2
    assert (tmp_path / "models" / "y" / "keep.txt").read_text() == "x"


def test_resume_of_finished_run_does_nothing(tmp_path):
    run_tiny(tiny_config("f"), tmp_path / "f")
    before = last_state(tmp_path / "f")
    res = run_tiny(tiny_config("f"), tmp_path / "f", resume=True)
    assert res["state"] == "done" and res["epochs_done"] == 2
    after = last_state(tmp_path / "f")
    assert all(torch.equal(before["model"][k], after["model"][k]) for k in before["model"])


def test_class_map_covers_every_code():
    codes = set(labels.CHESAPEAKE_CODES)
    for n in (4, 5):
        m = labels.code_map(n)
        assert set(m) == codes
        assert all(v == 255 or 0 <= v < n for v in m.values())
        assert m[0] == 255
    m4, m5 = labels.code_map(4), labels.code_map(5)
    # 5 classes merged back equal 4 classes for every code
    assert all(labels.five_to_four(np.array([m5[c]]))[0] == m4[c] for c in codes)
    assert [c for c in codes if m5[c] == 4] == [20, 22, 31]
    assert m5[21] == 1 and m5[23] == 2 and m5[27] == 3 and m5[11] == 0
    lut = labels.lookup_table(5)
    assert lut[99] == 255                  # a code not in the list is never trained on


def test_metrics_hand_computed():
    y = np.array([[0, 0, 1], [1, 2, 255]], np.uint8)
    p = np.array([[0, 1, 1], [1, 2, 0]], np.uint8)
    cm = confusion(p, y, 3)
    assert cm.tolist() == [[1, 1, 0], [0, 2, 0], [0, 0, 1]]
    s = scores(cm, ["a", "b", "c"])
    # IoU a = 1 / (1 + 1), b = 2 / (2 + 1), c = 1 / 1
    assert s["iou"] == {"a": 0.5, "b": 0.6667, "c": 1.0}
    assert s["miou"] == round((0.5 + 2 / 3 + 1) / 3, 4)
    assert s["accuracy"] == 0.8
    merged = merge_classes(cm, [[0, 2], [1]])
    assert merged.tolist() == [[2, 1], [0, 2]]


def test_edge_band_marks_one_pixel_each_side():
    lab = np.zeros((5, 6), np.uint8)
    lab[:, 3:] = 1
    band = edge_band(lab)
    assert band[:, 2].all() and band[:, 3].all()
    assert not band[:, [0, 1, 4, 5]].any()


def test_city_class_map_and_area_split():
    from pipeline.vision.city import assign_roles, uvm_lookup

    lut = uvm_lookup((0, 15))
    # UVM 1 tree, 2 grass, 3 bare, 4 water, 5 buildings, 6 roads, 7 other paved
    assert lut[[1, 2, 3, 4, 5, 6, 7]].tolist() == [2, 3, 3, 0, 1, 4, 4]
    assert lut[0] == 255 and lut[15] == 255 and lut[9] == 255
    rng = np.random.default_rng(0)
    centers = np.c_[rng.uniform(-80.1, -79.9, 40), rng.uniform(40.35, 40.5, 40)]
    roles = assign_roles(centers, seed=1)
    assert set(roles) == {"train", "val", "test"}
    assert roles.count("test") >= 8 and roles.count("val") >= 6
