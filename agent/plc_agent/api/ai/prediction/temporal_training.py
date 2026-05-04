# mypy: ignore-errors
"""
Training loop for the NumpyTCN — pure NumPy mini-batch SGD.

Mirrors validation/training.py: gradient clipping, early stopping,
threshold calibration. Backprop is standard conv gradient (no BPTT).
"""
from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger("loggerfast.ai.prediction.temporal_training")


def train_tcn(
    sequences: np.ndarray,
    targets: np.ndarray,
    *,
    n_features: int = 14,
    n_channels: int = 8,
    kernel_size: int = 3,
    n_layers: int = 3,
    epochs: int = 80,
    lr: float = 0.001,
    batch_size: int = 32,
    patience: int = 10,
) -> "NumpyTCN":
    """Train a NumpyTCN on temporal sequences.

    Args:
        sequences: (N, seq_len, n_features) input windows
        targets: (N, n_features) next-step values
        Other args: model hyperparameters and training config

    Returns:
        Trained NumpyTCN with threshold_97 calibrated.
    """
    from .tcn import NumpyTCN

    n_samples = sequences.shape[0]
    model = NumpyTCN(
        n_features=n_features,
        n_channels=n_channels,
        kernel_size=kernel_size,
        n_layers=n_layers,
    )

    best_loss = float("inf")
    no_improve = 0

    for epoch in range(epochs):
        perm = np.random.permutation(n_samples)
        epoch_loss = 0.0
        n_batches = 0

        for start in range(0, n_samples, batch_size):
            idx = perm[start : start + batch_size]
            x_batch = sequences[idx]  # (B, seq_len, feat)
            y_batch = targets[idx]    # (B, feat)
            B = x_batch.shape[0]

            # ── Forward pass with intermediates ──
            layer_inputs = []
            layer_pre_relu = []
            h = x_batch

            for i in range(model.n_layers):
                layer_inputs.append(h)
                conv_out = model._causal_conv1d(
                    h, model.conv_W[i], model.conv_b[i], model.dilations[i],
                )
                layer_pre_relu.append(conv_out)
                h_relu = np.maximum(0, conv_out)

                # Residual
                residual = layer_inputs[-1]
                if model.proj_W[i] is not None:
                    residual = residual @ model.proj_W[i] + model.proj_b[i]
                h = h_relu + residual

            # Take last timestep → dense
            last = h[:, -1, :]  # (B, n_channels)
            output = last @ model.out_W + model.out_b  # (B, n_features)

            # ── Loss: MSE ──
            diff = output - y_batch
            loss = float(np.mean(diff ** 2))
            epoch_loss += loss
            n_batches += 1

            # ── Backward pass ──
            d_output = 2.0 * diff / (B * n_features)  # (B, feat)

            # Dense layer grads
            d_out_W = last.T @ d_output / B          # (n_ch, feat)
            d_out_b = d_output.mean(axis=0)           # (feat,)
            d_last = d_output @ model.out_W.T         # (B, n_ch)

            # Expand d_last back to full sequence (only last timestep has gradient)
            d_h = np.zeros_like(h)
            d_h[:, -1, :] = d_last

            # Backprop through conv layers (reverse order)
            all_grads = [d_out_W, d_out_b]

            for i in reversed(range(model.n_layers)):
                # d_h is gradient of (h_relu + residual)
                # Split into relu branch and residual branch
                d_relu = d_h.copy()
                d_residual = d_h.copy()

                # Residual projection gradient
                if model.proj_W[i] is not None:
                    # d_residual goes through projection
                    inp = layer_inputs[i]  # (B, seq, in_ch)
                    # d_proj_W = sum over batch,seq of inp^T @ d_residual
                    d_proj_W = np.einsum("bsi,bso->io", inp, d_residual) / B
                    d_proj_b = d_residual.mean(axis=(0, 1))
                    d_inp_from_res = d_residual @ model.proj_W[i].T
                    all_grads.extend([d_proj_W, d_proj_b])
                else:
                    d_inp_from_res = d_residual

                # ReLU gradient
                relu_mask = (layer_pre_relu[i] > 0).astype(np.float64)
                d_conv_out = d_relu * relu_mask  # (B, seq, out_ch)

                # Causal conv gradient
                d_conv_W, d_conv_b, d_inp_from_conv = _causal_conv1d_backward(
                    layer_inputs[i], model.conv_W[i], d_conv_out,
                    model.kernel_size, model.dilations[i], B,
                )
                all_grads.extend([d_conv_W, d_conv_b])

                # Combine gradients flowing to previous layer
                d_h = d_inp_from_conv + d_inp_from_res

            # ── Gradient clipping (max global norm = 1.0) ──
            global_norm = np.sqrt(sum(float(np.sum(g ** 2)) for g in all_grads))
            if global_norm > 1.0:
                clip = 1.0 / global_norm
                all_grads = [g * clip for g in all_grads]

            # ── Weight update (SGD) ──
            gi = 0
            model.out_W -= lr * all_grads[gi]; gi += 1
            model.out_b -= lr * all_grads[gi]; gi += 1

            for i in reversed(range(model.n_layers)):
                if model.proj_W[i] is not None:
                    model.proj_W[i] -= lr * all_grads[gi]; gi += 1
                    model.proj_b[i] -= lr * all_grads[gi]; gi += 1
                model.conv_W[i] -= lr * all_grads[gi]; gi += 1
                model.conv_b[i] -= lr * all_grads[gi]; gi += 1

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
    # Per-sample prediction error on full training set
    all_pred = model.forward(sequences)
    per_sample = np.mean((all_pred - targets) ** 2, axis=1)
    model.threshold_97 = float(np.percentile(per_sample, 97))
    if model.threshold_97 < 1e-10:
        model.threshold_97 = 1e-3

    logger.info(
        "tcn_training_complete epochs=%d final_loss=%.6f threshold_97=%.6f",
        epoch + 1, avg_loss, model.threshold_97,
    )

    return model


def _causal_conv1d_backward(
    x_input: np.ndarray,
    W: np.ndarray,
    d_output: np.ndarray,
    kernel_size: int,
    dilation: int,
    batch_size: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Backward pass for causal dilated 1D convolution.

    Args:
        x_input: (B, seq_len, in_ch) — input to the conv layer
        W: (kernel_size, in_ch, out_ch) — conv weights
        d_output: (B, seq_len, out_ch) — upstream gradient

    Returns:
        (dW, db, d_input) gradients.
    """
    B, seq_len, in_ch = x_input.shape
    k = kernel_size
    out_ch = W.shape[2]

    # Left-pad input (same as forward)
    pad = (k - 1) * dilation
    x_padded = np.pad(x_input, ((0, 0), (pad, 0), (0, 0)), mode="constant")

    # Build gather indices (same as forward)
    t_idx = np.arange(seq_len) + pad
    offsets = np.arange(k) * dilation
    gather_idx = t_idx[:, None] - offsets[None, :]  # (seq_len, k)

    # Gathered input: (B, seq_len, k, in_ch)
    gathered = x_padded[:, gather_idx, :]
    gathered_flat = gathered.reshape(B, seq_len, k * in_ch)

    W_flat = W.reshape(k * in_ch, out_ch)

    # dW: gathered^T @ d_output, averaged over batch
    # gathered_flat: (B, seq, k*in_ch), d_output: (B, seq, out_ch)
    dW_flat = np.einsum("bsi,bso->io", gathered_flat, d_output) / batch_size
    dW = dW_flat.reshape(k, in_ch, out_ch)

    # db: mean of d_output over batch and seq
    db = d_output.mean(axis=(0, 1))

    # d_input: scatter d_output @ W^T back to input positions
    d_gathered_flat = d_output @ W_flat.T  # (B, seq, k*in_ch)
    d_gathered = d_gathered_flat.reshape(B, seq_len, k, in_ch)

    # Scatter back to padded input positions
    d_x_padded = np.zeros_like(x_padded)
    for ki in range(k):
        # gather_idx[:, ki] gives the padded positions for kernel tap ki
        positions = gather_idx[:, ki]  # (seq_len,)
        # Accumulate gradient
        np.add.at(d_x_padded, (slice(None), positions, slice(None)), d_gathered[:, :, ki, :])

    # Remove padding to get d_input
    d_input = d_x_padded[:, pad:, :] if pad > 0 else d_x_padded

    return dW, db, d_input
