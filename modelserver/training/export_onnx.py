# Owner: Jana
"""Export the trained `classifier_dl.pt` into `../artifacts/classifier.onnx`.

Pins `opset_version` and runs a numerical-equivalence check against the
training-time outputs so the bake-off table's macro-F1 is not invalidated
by silent export drift (research.md Decision 2 open risk "ONNX numerical drift").

Exits non-zero if max-abs-diff exceeds the epsilon — the operator must rerun
training or change the export settings before shipping.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import numpy as np
import onnxruntime as ort
import torch
import torch.nn.functional as F
from torch import nn

EPS = 1e-5
OPSET = 17


class TinyCNN(nn.Module):
    def __init__(self, in_dim: int, n_classes: int = 5) -> None:
        super().__init__()
        self.fc1 = nn.Linear(in_dim, 128)
        self.fc2 = nn.Linear(128, n_classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.fc2(F.relu(self.fc1(x)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pt", type=Path, default=Path("classifier_dl.pt"))
    parser.add_argument(
        "--out", type=Path, default=Path("../artifacts/classifier.onnx")
    )
    args = parser.parse_args(argv)

    checkpoint = torch.load(args.pt, map_location="cpu")
    in_dim = int(checkpoint["in_dim"])
    model = TinyCNN(in_dim)
    model.load_state_dict(checkpoint["state_dict"])
    model.eval()

    sample = torch.randn(1, in_dim)
    with torch.no_grad():
        torch_out = model(sample).numpy()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    torch.onnx.export(
        model,
        sample,
        args.out,
        input_names=["features"],
        output_names=["logits"],
        opset_version=OPSET,
        dynamic_axes={"features": {0: "batch"}, "logits": {0: "batch"}},
    )

    session = ort.InferenceSession(str(args.out), providers=["CPUExecutionProvider"])
    onnx_out = session.run(None, {"features": sample.numpy()})[0]
    diff = float(np.abs(torch_out - onnx_out).max())
    print({"max_abs_diff": diff, "epsilon": EPS, "opset": OPSET})
    if diff > EPS:
        print("ONNX export drifted beyond epsilon — refuse to ship", file=sys.stderr)
        return 1

    digest = hashlib.sha256(args.out.read_bytes()).hexdigest()
    print({"artifact": str(args.out), "sha256": digest, "size_bytes": args.out.stat().st_size})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
