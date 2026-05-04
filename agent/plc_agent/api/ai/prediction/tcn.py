# mypy: ignore-errors
"""
NumpyTCN — Pure NumPy causal dilated Temporal Convolutional Network.

Architecture (default):
    Input: (batch, seq_len=24, n_features=14)
    CausalConv1D(14→8, k=3, d=1) + ReLU + residual
    CausalConv1D(8→8,  k=3, d=2) + ReLU + residual
    CausalConv1D(8→8,  k=3, d=4) + ReLU + residual
    Take last timestep → Dense(8→14)
    Output: (batch, 14)

Size: ~1100 params ≈ 8-10 KB saved (well within 10-50 KB budget).
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

logger = logging.getLogger("loggerfast.ai.prediction.tcn")


class NumpyTCN:
    """Pure NumPy causal dilated TCN for next-step prediction."""

    def __init__(
        self,
        n_features: int = 14,
        n_channels: int = 8,
        kernel_size: int = 3,
        n_layers: int = 3,
        dilations: list[int] | None = None,
    ):
        self.n_features = n_features
        self.n_channels = n_channels
        self.kernel_size = kernel_size
        self.n_layers = n_layers
        self.dilations = dilations or [2**i for i in range(n_layers)]
        self.threshold_97: float = 1.0

        # -- Conv layers: list of (W, b) --
        # W shape: (kernel_size, in_ch, out_ch)
        self.conv_W: list[np.ndarray] = []
        self.conv_b: list[np.ndarray] = []

        # 1x1 projection for residual when in_ch != out_ch
        self.proj_W: list[np.ndarray | None] = []
        self.proj_b: list[np.ndarray | None] = []

        for i in range(n_layers):
            in_ch = n_features if i == 0 else n_channels
            out_ch = n_channels
            # Xavier init
            scale = np.sqrt(2.0 / (kernel_size * in_ch))
            self.conv_W.append(np.random.randn(kernel_size, in_ch, out_ch) * scale)
            self.conv_b.append(np.zeros(out_ch))

            if in_ch != out_ch:
                proj_scale = np.sqrt(2.0 / in_ch)
                self.proj_W.append(np.random.randn(in_ch, out_ch) * proj_scale)
                self.proj_b.append(np.zeros(out_ch))
            else:
                self.proj_W.append(None)
                self.proj_b.append(None)

        # -- Output dense: n_channels → n_features --
        scale = np.sqrt(2.0 / n_channels)
        self.out_W = np.random.randn(n_channels, n_features) * scale
        self.out_b = np.zeros(n_features)

    def forward(self, x: np.ndarray) -> np.ndarray:
        """Forward pass. x: (batch, seq_len, n_features) → (batch, n_features)."""
        squeeze = x.ndim == 2
        if squeeze:
            x = x[np.newaxis]  # (1, seq_len, feat)

        h = x
        for i in range(self.n_layers):
            residual = h
            h = self._causal_conv1d(h, self.conv_W[i], self.conv_b[i], self.dilations[i])
            h = np.maximum(0, h)  # ReLU

            # Residual connection
            if self.proj_W[i] is not None:
                residual = residual @ self.proj_W[i] + self.proj_b[i]
            h = h + residual

        # Take last timestep → dense
        last = h[:, -1, :]  # (batch, n_channels)
        out = last @ self.out_W + self.out_b  # (batch, n_features)

        return out.squeeze(0) if squeeze else out

    def _causal_conv1d(
        self, x: np.ndarray, W: np.ndarray, b: np.ndarray, dilation: int,
    ) -> np.ndarray:
        """Causal dilated 1D convolution.

        x: (batch, seq_len, in_ch)
        W: (kernel_size, in_ch, out_ch)
        b: (out_ch,)
        Returns: (batch, seq_len, out_ch) — no future leakage.
        """
        batch, seq_len, in_ch = x.shape
        k = self.kernel_size
        out_ch = W.shape[2]

        # Left-pad to ensure causality
        pad = (k - 1) * dilation
        x_padded = np.pad(x, ((0, 0), (pad, 0), (0, 0)), mode="constant")

        # Build index array for dilated gather
        # For each output position t, gather t, t-d, t-2d from padded input
        t_idx = np.arange(seq_len) + pad  # output positions in padded space
        offsets = np.arange(k) * dilation  # [0, d, 2d]
        # gather_idx[t, k_pos] = t - k_pos * dilation
        gather_idx = t_idx[:, None] - offsets[None, :]  # (seq_len, kernel_size)

        # Gather: (batch, seq_len, kernel_size, in_ch)
        gathered = x_padded[:, gather_idx, :]

        # Reshape for matmul: (batch, seq_len, k*in_ch) @ (k*in_ch, out_ch)
        gathered_flat = gathered.reshape(batch, seq_len, k * in_ch)
        W_flat = W.reshape(k * in_ch, out_ch)

        return gathered_flat @ W_flat + b

    def compute_anomaly_score(
        self, x_seq: np.ndarray, x_actual: np.ndarray,
    ) -> tuple[float, np.ndarray]:
        """Given input sequence and actual next values, compute anomaly score.

        Args:
            x_seq: (1, seq_len, n_features) or (seq_len, n_features)
            x_actual: (n_features,) actual next reading

        Returns:
            (score, per_feature_errors) where score ∈ [0, 1].
        """
        predicted = self.forward(x_seq)
        if predicted.ndim > 1:
            predicted = predicted[0]
        errors = (predicted - x_actual) ** 2
        raw_score = float(np.mean(errors))
        score = min(1.0, raw_score / self.threshold_97) if self.threshold_97 > 0 else 0.0
        return score, errors

    def save(self, path: str | Path) -> None:
        """Save weights + config to .npz file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        save_dict = {
            "n_features": np.array([self.n_features]),
            "n_channels": np.array([self.n_channels]),
            "kernel_size": np.array([self.kernel_size]),
            "n_layers": np.array([self.n_layers]),
            "dilations": np.array(self.dilations),
            "threshold_97": np.array([self.threshold_97]),
            "out_W": self.out_W,
            "out_b": self.out_b,
        }
        for i in range(self.n_layers):
            save_dict[f"conv_W_{i}"] = self.conv_W[i]
            save_dict[f"conv_b_{i}"] = self.conv_b[i]
            if self.proj_W[i] is not None:
                save_dict[f"proj_W_{i}"] = self.proj_W[i]
                save_dict[f"proj_b_{i}"] = self.proj_b[i]
        np.savez_compressed(str(path), **save_dict)

    @classmethod
    def load(cls, path: str | Path) -> "NumpyTCN":
        """Load from .npz file."""
        data = np.load(str(path))
        n_features = int(data["n_features"][0])
        n_channels = int(data["n_channels"][0])
        kernel_size = int(data["kernel_size"][0])
        n_layers = int(data["n_layers"][0])
        dilations = data["dilations"].tolist()

        model = cls(
            n_features=n_features,
            n_channels=n_channels,
            kernel_size=kernel_size,
            n_layers=n_layers,
            dilations=dilations,
        )
        model.threshold_97 = float(data["threshold_97"][0])
        model.out_W = data["out_W"]
        model.out_b = data["out_b"]

        for i in range(n_layers):
            model.conv_W[i] = data[f"conv_W_{i}"]
            model.conv_b[i] = data[f"conv_b_{i}"]
            if f"proj_W_{i}" in data:
                model.proj_W[i] = data[f"proj_W_{i}"]
                model.proj_b[i] = data[f"proj_b_{i}"]
            else:
                model.proj_W[i] = None
                model.proj_b[i] = None

        return model
