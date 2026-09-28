"""
Trains the two-model ensemble on the 2-week baseline:
  1. Autoencoder (Keras) — learns to reconstruct "normal" traffic patterns;
     high reconstruction error == anomalous.
  2. Isolation Forest (scikit-learn) — tree-based outlier detector, catches
     anomalies the autoencoder's reconstruction-error metric might miss
     (they have different failure modes, which is the point of combining them).

Both models score every sample; scores are combined into a single 0-1
confidence value used for the 0.85 auto-block threshold (see combine_scores.py).

Requires:
    pip install scikit-learn tensorflow pandas joblib

Usage:
    python train_model.py --features baseline_features.parquet
"""

import argparse
import json

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
from tensorflow import keras
from tensorflow.keras import layers

from feature_engineering import build_features, load_raw


def build_autoencoder(input_dim: int) -> keras.Model:
    inputs = keras.Input(shape=(input_dim,))
    x = layers.Dense(16, activation="relu")(inputs)
    x = layers.Dense(8, activation="relu")(x)
    bottleneck = layers.Dense(4, activation="relu", name="bottleneck")(x)
    x = layers.Dense(8, activation="relu")(bottleneck)
    x = layers.Dense(16, activation="relu")(x)
    outputs = layers.Dense(input_dim, activation="linear")(x)

    model = keras.Model(inputs, outputs)
    model.compile(optimizer="adam", loss="mse")
    return model


def train(features_path: str, model_dir: str = "models") -> None:
    import os

    os.makedirs(model_dir, exist_ok=True)

    if features_path.endswith(".parquet"):
        feats = pd.read_parquet(features_path)
    else:
        raw = load_raw(features_path)
        feats, _ = build_features(raw)

    feature_cols = [c for c in feats.columns if c not in ("SrcAddr", "window")]
    X = feats[feature_cols].values.astype("float32")

    print(f"Training on {X.shape[0]:,} samples, {X.shape[1]} features")

    # --- scale ---
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # --- autoencoder ---
    ae = build_autoencoder(X_scaled.shape[1])
    history = ae.fit(
        X_scaled,
        X_scaled,
        epochs=50,
        batch_size=64,
        validation_split=0.1,
        shuffle=True,
        callbacks=[keras.callbacks.EarlyStopping(patience=5, restore_best_weights=True)],
        verbose=2,
    )

    reconstructions = ae.predict(X_scaled, verbose=0)
    reconstruction_errors = np.mean(np.square(X_scaled - reconstructions), axis=1)

    # threshold for "normal" reconstruction error, used later for scaling
    # anomaly scores into a 0-1 range (see combine_scores.py)
    ae_error_p99 = float(np.percentile(reconstruction_errors, 99))

    # --- isolation forest ---
    iso = IsolationForest(
        n_estimators=200,
        contamination=0.02,  # assume ~2% of baseline traffic is noisy/edge-case, not necessarily malicious
        random_state=42,
    )
    iso.fit(X_scaled)

    # --- save everything needed for scoring ---
    ae.save(f"{model_dir}/autoencoder.keras")
    joblib.dump(scaler, f"{model_dir}/scaler.joblib")
    joblib.dump(iso, f"{model_dir}/isolation_forest.joblib")

    metadata = {
        "feature_cols": feature_cols,
        "ae_error_p99": ae_error_p99,
        "trained_on_samples": int(X.shape[0]),
        "trained_on_hosts": int(feats["SrcAddr"].nunique()),
    }
    with open(f"{model_dir}/metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)

    print(f"Saved models to {model_dir}/")
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--features", type=str, default="baseline_features.parquet")
    parser.add_argument("--model-dir", type=str, default="models")
    args = parser.parse_args()
    train(args.features, args.model_dir)
