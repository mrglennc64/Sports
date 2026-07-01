"""Tests for group clustering (pure / synthetic, no file I/O)."""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import adjusted_rand_score

from app.grouping.cluster import (
    cluster_players,
    profile_groups,
    select_k,
)

FEATS = ["f0", "f1", "f2", "f3"]


def _blobs(n_per=80, seed=0):
    """Three well-separated 4-D gaussian blobs. Returns (df, true_labels)."""
    rng = np.random.default_rng(seed)
    centers = np.array([
        [0.0, 0.0, 0.0, 0.0],
        [12.0, 12.0, 0.0, 0.0],
        [0.0, 0.0, 12.0, 12.0],
    ])
    rows, truth = [], []
    for ci, c in enumerate(centers):
        pts = c + rng.normal(scale=0.4, size=(n_per, 4))
        rows.append(pts)
        truth += [ci] * n_per
    X = np.vstack(rows)
    df = pd.DataFrame(X, columns=FEATS)
    df["player_id"] = [f"p{i:04d}" for i in range(len(df))]
    df["season"] = 2020
    df["pa"] = 100
    return df, np.array(truth)


def test_select_k_picks_three_on_three_blobs():
    df, _ = _blobs()
    X = df[FEATS].to_numpy()
    # z-score so it matches the real pipeline's scaled space
    X = (X - X.mean(0)) / X.std(0)
    best_k, scores = select_k(X, range(2, 9))
    assert best_k == 3
    assert set(scores) == set(range(2, 9))


def test_cluster_recovers_blobs():
    df, truth = _blobs()
    labelled, bundle = cluster_players(df, FEATS, k=None, krange=range(2, 9))
    assert bundle.k == 3
    ari = adjusted_rand_score(truth, labelled["group"].to_numpy())
    assert ari > 0.95
    assert labelled["group"].dtype.kind in "iu"


def test_determinism_fixed_seed():
    df, _ = _blobs()
    a, _ = cluster_players(df, FEATS, k=3)
    b, _ = cluster_players(df, FEATS, k=3)
    assert np.array_equal(a["group"].to_numpy(), b["group"].to_numpy())


def test_nan_rows_imputed_not_dropped():
    df, _ = _blobs()
    n_before = len(df)
    # Punch NaNs into a feature for a handful of rows.
    df.loc[[0, 5, 10, 200], "f2"] = np.nan
    labelled, bundle = cluster_players(df, FEATS, k=3)
    # No rows dropped: every input row got a group.
    assert len(labelled) == n_before
    assert labelled["group"].notna().all()
    # The NaN rows were imputed with the column median (stored on the bundle).
    assert bundle.medians["f2"] == df["f2"].median()


def test_profile_groups_shape_and_descriptor():
    df, _ = _blobs()
    labelled, _ = cluster_players(df, FEATS, k=3)
    prof = profile_groups(labelled, FEATS)
    assert len(prof) == 3
    assert set(["group", "size", "descriptor"]).issubset(prof.columns)
    assert prof["size"].sum() == len(df)
    # Every group should have a non-empty descriptor string.
    assert prof["descriptor"].str.len().gt(0).all()
