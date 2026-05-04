# mypy: ignore-errors
"""
Training loop — pure NumPy mini-batch SGD for the anomaly autoencoder.

No PyTorch, TensorFlow, or scikit-learn. The network is tiny
(39→16→8→16→39 = 1,872 weights) so manual backprop is straightforward.
Training 10k samples for 100 epochs takes <5s on CPU.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from .anomaly import NumpyAutoencoder

logger = logging.getLogger("loggerfast.ai.validation.training")


def train_autoencoder(
    data: np.ndarray,
    mask: np.ndarray,
    *,
    input_dim: int = 39,
    hidden1: int = 16,
    bottleneck: int = 8,
    epochs: int = 100,
    lr: float = 0.001,
    batch_size: int = 64,
    patience: int = 10,
) -> "NumpyAutoencoder":
    """Train a NumpyAutoencoder on synthetic data using mini-batch SGD.

    Args:
        data: (n_samples, input_dim) normalized [0, 1]
        mask: (input_dim,) binary mask — 1 for populated slots
        input_dim: input/output dimension (default 39)
        hidden1: first hidden layer width
        bottleneck: bottleneck layer width
        epochs: max training epochs
        lr: learning rate
        batch_size: mini-batch size
        patience: early stopping patience (epochs without improvement)

    Returns:
        Trained NumpyAutoencoder with threshold_97 calibrated.
    """
    from .anomaly import NumpyAutoencoder

    n_samples = data.shape[0]
    model = NumpyAutoencoder(input_dim=input_dim, hidden1=hidden1, bottleneck=bottleneck)

    mask_row = mask.reshape(1, -1)  # (1, dim) for broadcasting
    mask_sum = mask.sum()
    if mask_sum == 0:
        mask_sum = 1.0  # avoid div-by-zero

    best_loss = float("inf")
    no_improve = 0

    for epoch in range(epochs):
        # Shuffle
        perm = np.random.permutation(n_samples)
        epoch_loss = 0.0
        n_batches = 0

        for start in range(0, n_samples, batch_size):
            idx = perm[start:start + batch_size]
            x = data[idx]  # (B, dim)
            B = x.shape[0]

            # ── Forward pass (store intermediates for backprop) ──
            # Layer 1: input → hidden1 (ReLU)
            z1 = x @ model.W1 + model.b1             # (B, h1)
            a1 = np.maximum(0, z1)                     # ReLU

            # Layer 2: hidden1 → bottleneck (ReLU)
            z2 = a1 @ model.W2 + model.b2             # (B, bn)
            a2 = np.maximum(0, z2)                     # ReLU

            # Layer 3: bottleneck → hidden1 (ReLU)
            z3 = a2 @ model.W3 + model.b3             # (B, h1)
            a3 = np.maximum(0, z3)                     # ReLU

            # Layer 4: hidden1 → output (Sigmoid)
            z4 = a3 @ model.W4 + model.b4             # (B, dim)
            output = _sigmoid(z4)                       # (B, dim)

            # ── Masked MSE loss ──
            diff = (output - x) * mask_row             # zero out masked slots
            loss = np.sum(diff ** 2) / (B * mask_sum)
            epoch_loss += loss
            n_batches += 1

            # ── Backward pass ──
            # dL/d_output = 2 * diff / (B * mask_sum)
            d_out = 2 * diff / (B * mask_sum)

            # Layer 4 (sigmoid)
            d_z4 = d_out * output * (1 - output)      # sigmoid derivative
            dW4 = a3.T @ d_z4 / B
            db4 = d_z4.mean(axis=0)
            d_a3 = d_z4 @ model.W4.T

            # Layer 3 (ReLU)
            d_z3 = d_a3 * (z3 > 0).astype(np.float64)
            dW3 = a2.T @ d_z3 / B
            db3 = d_z3.mean(axis=0)
            d_a2 = d_z3 @ model.W3.T

            # Layer 2 (ReLU)
            d_z2 = d_a2 * (z2 > 0).astype(np.float64)
            dW2 = a1.T @ d_z2 / B
            db2 = d_z2.mean(axis=0)
            d_a1 = d_z2 @ model.W2.T

            # Layer 1 (ReLU)
            d_z1 = d_a1 * (z1 > 0).astype(np.float64)
            dW1 = x.T @ d_z1 / B
            db1 = d_z1.mean(axis=0)

            # ── Gradient clipping (max global norm = 1.0) ──
            all_grads = [dW1, db1, dW2, db2, dW3, db3, dW4, db4]
            global_norm = np.sqrt(sum(np.sum(g ** 2) for g in all_grads))
            if global_norm > 1.0:
                clip_coef = 1.0 / global_norm
                dW1, db1 = dW1 * clip_coef, db1 * clip_coef
                dW2, db2 = dW2 * clip_coef, db2 * clip_coef
                dW3, db3 = dW3 * clip_coef, db3 * clip_coef
                dW4, db4 = dW4 * clip_coef, db4 * clip_coef

            # ── Weight update (SGD) ──
            model.W1 -= lr * dW1
            model.b1 -= lr * db1
            model.W2 -= lr * dW2
            model.b2 -= lr * db2
            model.W3 -= lr * dW3
            model.b3 -= lr * db3
            model.W4 -= lr * dW4
            model.b4 -= lr * db4

        avg_loss = epoch_loss / max(n_batches, 1)

        if epoch % 20 == 0 or epoch == epochs - 1:
            logger.debug("epoch=%d loss=%.6f", epoch, avg_loss)

        # Early stopping
        if avg_loss < best_loss - 1e-7:
            best_loss = avg_loss
            no_improve = 0
        else:
            no_improve += 1
            if no_improve >= patience:
                logger.info("early_stop epoch=%d loss=%.6f", epoch, avg_loss)
                break

    # ── Calibrate anomaly threshold ──
    # Compute per-sample reconstruction error on full training set
    output_full = model.forward(data)
    per_sample = np.sum(((output_full - data) * mask_row) ** 2, axis=1) / mask_sum
    model.threshold_97 = float(np.percentile(per_sample, 97))
    if model.threshold_97 < 1e-10:
        model.threshold_97 = 1e-3  # safety floor

    logger.info(
        "training_complete epochs=%d final_loss=%.6f threshold_97=%.6f",
        epoch + 1, avg_loss, model.threshold_97,
    )

    return model


def _sigmoid(x: np.ndarray) -> np.ndarray:
    """Numerically stable sigmoid."""
    return np.where(
        x >= 0,
        1 / (1 + np.exp(-x)),
        np.exp(x) / (1 + np.exp(x)),
    )
