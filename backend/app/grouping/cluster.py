"""Cluster pitchers / batters into behavioural GROUPS (never "archetypes").

Offline tooling. Takes the per-(player, season) feature tables built by
``app.grouping.features`` and partitions them into k data-driven GROUPS via
KMeans on z-scored features. ``k`` is chosen automatically by maximising the
mean silhouette over a candidate range, and every group gets a short, fully
data-derived descriptor (which features sit most above / below the league mean).

Pipeline (per role):
  1. impute NaN feature cells with the column median, then z-score (StandardScaler)
  2. select_k: KMeans for k in 4..14, score by mean silhouette, pick the best
  3. fit final KMeans at the chosen k -> integer ``group`` per row
  4. profile each group: raw-unit feature means, size, a human-readable descriptor
  5. persist parquet (labelled rows) + joblib bundle (scaler + kmeans + k + features)

The fitted bundle is saved so brand-new (player, season) rows can later be
assigned to a group without re-fitting (see ``assign``).

Pure / deterministic: KMeans uses random_state=42, n_init=10 everywhere.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

from app.grouping.features import FEATURE_COLUMNS
from app.grouping.retrosheet import DATA_DIR

RANDOM_STATE = 42
N_INIT = 10
K_RANGE = range(4, 15)  # 4..14 inclusive
# Cap the silhouette computation at this many rows for speed (sampled, seeded).
SILHOUETTE_SAMPLE = 4000
# How many std-devs from the mean a feature must sit to make the descriptor.
DESCRIPTOR_Z = 0.6
# Max features named in a descriptor (most extreme first).
DESCRIPTOR_MAX = 3

GROUPS_DIR = Path(DATA_DIR) / "groups"


@dataclass
class ModelBundle:
    """Everything needed to assign a new row to a group later."""

    scaler: StandardScaler
    kmeans: KMeans
    k: int
    feature_cols: list[str]
    medians: pd.Series  # column medians used to impute NaN before scaling
    silhouette_by_k: dict[int, float] = field(default_factory=dict)

    def transform(self, df: pd.DataFrame) -> np.ndarray:
        """Impute (with stored medians) + scale a frame's feature columns."""
        X = df[self.feature_cols].apply(pd.to_numeric, errors="coerce")
        X = X.fillna(self.medians)
        return self.scaler.transform(X.to_numpy())


def _impute_and_scale(df: pd.DataFrame, feature_cols: list[str]):
    """Median-impute NaN, then z-score. Returns (X_scaled, scaler, medians)."""
    raw = df[feature_cols].apply(pd.to_numeric, errors="coerce")
    medians = raw.median()
    filled = raw.fillna(medians)
    # If a whole column is NaN its median is NaN -> fall back to 0 (constant col).
    filled = filled.fillna(0.0)
    scaler = StandardScaler()
    X = scaler.fit_transform(filled.to_numpy())
    return X, scaler, medians


def _silhouette(X: np.ndarray, labels: np.ndarray) -> float:
    """Mean silhouette, sampled for speed on large X (seeded for determinism)."""
    n = X.shape[0]
    if n <= SILHOUETTE_SAMPLE:
        return float(silhouette_score(X, labels))
    return float(
        silhouette_score(
            X, labels, sample_size=SILHOUETTE_SAMPLE, random_state=RANDOM_STATE
        )
    )


def select_k(X: np.ndarray, krange=K_RANGE) -> tuple[int, dict[int, float]]:
    """Fit KMeans for each k in krange, score by mean silhouette, pick the best.

    Returns (best_k, {k: silhouette}). k values that can't be scored (e.g. a
    degenerate single-cluster solution) are skipped.
    """
    scores: dict[int, float] = {}
    for k in krange:
        if k < 2 or k >= X.shape[0]:
            continue
        km = KMeans(n_clusters=k, random_state=RANDOM_STATE, n_init=N_INIT)
        labels = km.fit_predict(X)
        if len(set(labels)) < 2:
            continue
        scores[k] = _silhouette(X, labels)
    if not scores:
        raise ValueError("select_k: no scorable k in range")
    best_k = max(scores, key=scores.get)
    return best_k, scores


def cluster_players(
    df: pd.DataFrame,
    feature_cols: list[str] = FEATURE_COLUMNS,
    k: int | None = None,
    krange=K_RANGE,
) -> tuple[pd.DataFrame, ModelBundle]:
    """Cluster rows of ``df`` into groups. NaN cells are imputed, never dropped.

    If ``k`` is None it is chosen automatically via :func:`select_k` over
    ``krange``. Returns ``(labelled_df, bundle)`` where ``labelled_df`` is ``df``
    plus an integer ``group`` column and ``bundle`` holds the fitted scaler +
    kmeans + metadata.
    """
    X, scaler, medians = _impute_and_scale(df, feature_cols)

    silhouette_by_k: dict[int, float] = {}
    if k is None:
        k, silhouette_by_k = select_k(X, krange)

    kmeans = KMeans(n_clusters=k, random_state=RANDOM_STATE, n_init=N_INIT)
    labels = kmeans.fit_predict(X)

    labelled = df.copy()
    labelled["group"] = labels.astype(int)

    bundle = ModelBundle(
        scaler=scaler,
        kmeans=kmeans,
        k=k,
        feature_cols=list(feature_cols),
        medians=medians,
        silhouette_by_k=silhouette_by_k,
    )
    return labelled, bundle


def assign(df: pd.DataFrame, bundle: ModelBundle) -> np.ndarray:
    """Assign new rows to existing groups using a fitted bundle (no re-fit)."""
    return bundle.kmeans.predict(bundle.transform(df)).astype(int)


def _descriptor(deltas: pd.Series) -> str:
    """Build a short label from the features furthest from the league mean.

    ``deltas`` is a per-feature z-score of this group's mean vs the overall mean.
    Names the most extreme features as high-/low-<feature>, most extreme first.
    """
    ranked = deltas.reindex(deltas.abs().sort_values(ascending=False).index)
    parts: list[str] = []
    for feat, z in ranked.items():
        if abs(z) < DESCRIPTOR_Z or len(parts) >= DESCRIPTOR_MAX:
            continue
        short = feat.replace("_rate", "").replace("_", "-")
        parts.append(f"{'high' if z > 0 else 'low'}-{short}")
    return ", ".join(parts) if parts else "league-average"


def profile_groups(
    labelled_df: pd.DataFrame, feature_cols: list[str] = FEATURE_COLUMNS
) -> pd.DataFrame:
    """Per-group raw-unit feature means, size, and a data-derived descriptor.

    Returns one row per group sorted by group id, with columns:
    [group, size, <feature means...>, descriptor].
    """
    raw = labelled_df[feature_cols].apply(pd.to_numeric, errors="coerce")
    overall_mean = raw.mean()
    overall_std = raw.std(ddof=0).replace(0, np.nan)

    rows = []
    for g, idx in labelled_df.groupby("group").groups.items():
        sub = raw.loc[idx]
        means = sub.mean()
        deltas = ((means - overall_mean) / overall_std).fillna(0.0)
        row = {"group": int(g), "size": int(len(idx))}
        row.update(means.to_dict())
        row["descriptor"] = _descriptor(deltas)
        rows.append(row)

    cols = ["group", "size", *feature_cols, "descriptor"]
    return pd.DataFrame(rows).sort_values("group").reset_index(drop=True)[cols]


def _features_path(role: str, data_dir: Path) -> Path:
    name = "pitchers" if role == "pitcher" else "batters"
    return Path(data_dir) / "features" / f"{name}.parquet"


def run_clustering(
    role: str,
    data_dir: Path = DATA_DIR,
    out_dir: Path = GROUPS_DIR,
    k: int | None = None,
) -> dict:
    """Load a role's feature parquet, cluster, profile, and persist outputs.

    ``role`` is "pitcher" or "batter". Writes ``<role>_groups.parquet`` and
    ``<role>_model.joblib`` under ``out_dir``. Returns a summary dict.
    """
    import joblib

    if role not in ("pitcher", "batter"):
        raise ValueError(f"role must be 'pitcher' or 'batter', got {role!r}")

    df = pd.read_parquet(_features_path(role, data_dir))
    labelled, bundle = cluster_players(df, FEATURE_COLUMNS, k=k)
    profile = profile_groups(labelled, FEATURE_COLUMNS)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    keep = ["player_id", "season", "pa", "group", *FEATURE_COLUMNS]
    keep = [c for c in keep if c in labelled.columns]
    groups_path = out_dir / f"{role}_groups.parquet"
    labelled[keep].to_parquet(groups_path, index=False)

    model_path = out_dir / f"{role}_model.joblib"
    joblib.dump(bundle, model_path)

    return {
        "role": role,
        "k": bundle.k,
        "silhouette_by_k": bundle.silhouette_by_k,
        "profile": profile,
        "groups_path": str(groups_path),
        "model_path": str(model_path),
        "n_rows": len(labelled),
    }


if __name__ == "__main__":  # pragma: no cover - manual run convenience
    for _role in ("pitcher", "batter"):
        res = run_clustering(_role)
        print(f"\n=== {_role} === k={res['k']}  rows={res['n_rows']}")
        print("silhouette by k:", {k: round(v, 4) for k, v in res["silhouette_by_k"].items()})
        print(res["profile"].to_string(index=False))
        print("wrote:", res["groups_path"], "|", res["model_path"])
