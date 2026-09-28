"""
Combines the autoencoder's reconstruction error and the isolation forest's
anomaly score into a single 0-1 "confidence this is anomalous" value.

This is shared logic used both by training (to sanity-check thresholds
against the baseline) and by the scoring Azure Function at inference time.
"""

import numpy as np


def combine(reconstruction_error: np.ndarray, iso_score: np.ndarray, ae_error_p99: float) -> np.ndarray:
    """
    reconstruction_error: raw MSE from the autoencoder, per sample
    iso_score: isolation forest's decision_function output, per sample
               (note: sklearn's decision_function is HIGHER for normal,
               LOWER/negative for anomalous — inverted from intuition)
    ae_error_p99: the 99th percentile reconstruction error observed on
                  the training baseline, used to normalize AE error to 0-1

    Returns: array of combined confidence scores in [0, 1], where values
    near 1.0 indicate high confidence the sample is anomalous.
    """
    # normalize AE error: clip at p99*2 so a single extreme outlier doesn't
    # squash the whole scale, then scale to 0-1
    ae_norm = np.clip(reconstruction_error / (ae_error_p99 * 2), 0, 1)

    # isolation forest: decision_function is roughly in [-0.5, 0.5],
    # negative = anomalous. Flip and rescale to 0-1.
    iso_norm = np.clip((0.5 - iso_score) / 1.0, 0, 1)

    # equal-weighted average -- deliberately simple to start; revisit
    # once you have real block/no-block outcomes to validate against
    combined = 0.5 * ae_norm + 0.5 * iso_norm
    return combined
