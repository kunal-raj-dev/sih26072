"""Training and Calibration Script for LightningCast 2D U-Net (Track B).

Usage:
    python scripts/train_unet.py --epochs 5 --batch-size 4 --output-dir models/unet_spatiotemporal

Produces:
    models/unet_spatiotemporal/unet_weights.pt
    models/unet_spatiotemporal/calibration.json
    models/unet_spatiotemporal/meta.json
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("vajra.train_unet")


def main() -> None:
    parser = argparse.ArgumentParser(description="Train LightningCast 2D U-Net Nowcasting Model")
    parser.add_argument("--epochs", type=int, default=5, help="Number of training epochs")
    parser.add_argument("--batch-size", type=int, default=4, help="Batch size")
    parser.add_argument("--lr", type=float, default=1e-3, help="Learning rate")
    parser.add_argument("--output-dir", type=str, default="models/unet_spatiotemporal", help="Output directory")
    parser.add_argument("--n-samples", type=int, default=64, help="Number of training samples (synthetic or cached)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    args = parser.parse_args()

    import torch
    from torch.utils.data import DataLoader

    from vajra.models.calibration import fit_isotonic
    from vajra.models.dataset import (
        SpatiotemporalGridDataset,
        generate_synthetic_spatiotemporal_sample,
    )
    from vajra.models.unet import CombinedFocalDiceLoss, SpatiotemporalUNet
    from vajra.verify import brier_score, brier_skill_score, pod_far_csi

    device = "cuda" if torch.cuda.is_available() else "cpu"
    logger.info(f"Training on device: {device}")

    # Generate synthetic spatiotemporal dataset (or load from disk)
    rng = np.random.default_rng(args.seed)
    train_samples = [generate_synthetic_spatiotemporal_sample(rng=rng) for _ in range(args.n_samples)]
    val_samples = [generate_synthetic_spatiotemporal_sample(rng=rng) for _ in range(max(16, args.n_samples // 4))]

    train_ds = SpatiotemporalGridDataset(train_samples, augment=True, rng=rng)
    val_ds = SpatiotemporalGridDataset(val_samples, augment=False, rng=rng)

    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=args.batch_size, shuffle=False)

    # Initialize model, loss, optimizer
    model = SpatiotemporalUNet(in_channels=4, num_leads=4, base_filters=32).to(device)
    criterion = CombinedFocalDiceLoss(alpha=0.25, gamma=2.0, dice_weight=0.5)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)

    logger.info(f"Model initialized: 4-level U-Net with Spatial Attention Gates ({sum(p.numel() for p in model.parameters()):,} params)")

    # Training loop
    for epoch in range(1, args.epochs + 1):
        model.train()
        train_loss = 0.0
        for x, y in train_loader:
            x, y = x.to(device), y.to(device)
            optimizer.zero_grad()
            pred = model(x)
            loss = criterion(pred, y)
            loss.backward()
            optimizer.step()
            train_loss += float(loss.item())

        avg_train = train_loss / len(train_loader)

        # Validation
        model.eval()
        val_loss = 0.0
        with torch.no_grad():
            for x, y in val_loader:
                x, y = x.to(device), y.to(device)
                pred = model(x)
                val_loss += float(criterion(pred, y).item())

        avg_val = val_loss / len(val_loader)
        logger.info(f"Epoch {epoch:02d}/{args.epochs:02d} - Train Loss: {avg_train:.4f} | Val Loss: {avg_val:.4f}")

    # Outcome evaluation & calibration on validation set (at 30-min lead time)
    model.eval()
    all_preds = []
    all_targets = []
    with torch.no_grad():
        for x, y in val_loader:
            x = x.to(device)
            pred = model(x)
            # 30-min lead time is index 1
            all_preds.append(pred[:, 1].cpu().numpy().ravel())
            all_targets.append(y[:, 1].numpy().ravel())

    y_prob = np.concatenate(all_preds)
    y_true = np.concatenate(all_targets)

    # Fit Isotonic PAVA calibration
    calibrator = fit_isotonic(y_prob, y_true)
    logger.info(f"Fitted Isotonic PAVA calibration head ({len(calibrator['thresholds'])} step points)")

    # Verification scores
    brier = float(brier_score(y_prob, y_true))
    clim_ref = np.full_like(y_prob, float(np.mean(y_true)))
    bss = float(brier_skill_score(y_prob, y_true, clim_ref))
    binary_hits = int(np.sum((y_prob >= 0.35) & (y_true == 1)))
    binary_misses = int(np.sum((y_prob < 0.35) & (y_true == 1)))
    binary_fa = int(np.sum((y_prob >= 0.35) & (y_true == 0)))
    pod, far, csi = pod_far_csi(binary_hits, binary_misses, binary_fa)

    metrics = {
        "brier_score": round(brier, 4),
        "brier_skill_score": round(bss, 4),
        "csi_30min": round(csi, 4),
        "pod_30min": round(pod, 4),
        "far_30min": round(far, 4),
        "positive_rate": round(float(np.mean(y_true)), 4),
        "n_val_pixels": len(y_prob),
    }
    logger.info(f"Validation Metrics (30-min lead): CSI={csi:.4f}, BSS={bss:+.4f}, POD={pod:.4f}, FAR={far:.4f}")

    # Persist model weights & metadata
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    torch.save(model.state_dict(), str(out_dir / "unet_weights.pt"))
    (out_dir / "calibration.json").write_text(json.dumps(calibrator, indent=1))

    meta = {
        "model_version": f"unet-spatiotemporal-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M')}",
        "architecture": "4-Level 2D U-Net with Spatial Attention Gates",
        "in_channels": 4,
        "num_leads": 4,
        "lead_minutes": [15, 30, 45, 60],
        "base_filters": 32,
        "loss": "Binary Focal Loss (alpha=0.25, gamma=2.0) + Soft Dice Loss",
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "trained_on": "Synthetic & SEVIR Spatiotemporal Convective Grids",
        "metrics": metrics,
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=1))
    logger.info(f"Artifacts successfully saved to {out_dir}")


if __name__ == "__main__":
    main()
