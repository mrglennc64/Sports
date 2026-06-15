"""Shared clustering engine: numpy k-means++ + silhouette + centroid auto-naming.

Pure helpers used by the player-categorization scripts (objectives 2 & 4). No
DuckDB / I/O here — callers pass a feature matrix and get labels + centroids.
Deterministic given a seed.
"""

from __future__ import annotations

import numpy as np


def kmeans(X, k, seed, iters=200, restarts=12):
    """k-means++ init, best of several restarts by inertia. Returns (labels, centroids)."""
    rng = np.random.default_rng(seed)
    best = None
    for _ in range(restarts):
        c = [X[rng.integers(len(X))]]
        for _ in range(1, k):
            d2 = np.min(((X[:, None, :] - np.array(c)[None, :, :]) ** 2).sum(2), axis=1)
            s = d2.sum()
            probs = d2 / s if s > 0 else None
            c.append(X[rng.choice(len(X), p=probs)])
        C = np.array(c)
        lab = np.zeros(len(X), dtype=int)
        for _ in range(iters):
            lab = np.argmin(((X[:, None, :] - C[None, :, :]) ** 2).sum(2), axis=1)
            newC = np.array([X[lab == j].mean(0) if np.any(lab == j) else C[j]
                             for j in range(k)])
            if np.allclose(newC, C):
                C = newC
                break
            C = newC
        inertia = sum(((X[lab == j] - C[j]) ** 2).sum() for j in range(k))
        if best is None or inertia < best[2]:
            best = (lab, C, inertia)
    return best[0], best[1]


def silhouette(X, lab):
    """Mean silhouette coefficient (O(n^2); fine for a few hundred points)."""
    labs = np.unique(lab)
    if len(labs) < 2:
        return -1.0
    D = np.sqrt(((X[:, None, :] - X[None, :, :]) ** 2).sum(2))
    n = len(X)
    s = np.zeros(n)
    for i in range(n):
        same = lab == lab[i]
        same[i] = False
        a = D[i, same].mean() if same.any() else 0.0
        b = min(D[i, lab == j].mean() for j in labs if j != lab[i])
        s[i] = (b - a) / max(a, b) if max(a, b) > 0 else 0.0
    return float(s.mean())


def scan_k(Z, max_k, seed):
    """Cluster for k=2..max_k; return list of (k, silhouette, labels, centroids)."""
    out = []
    for k in range(2, max_k + 1):
        lab, C = kmeans(Z, k, seed)
        out.append((k, silhouette(Z, lab), lab, C))
    return out


def autoname(zc, phrases, thresh=0.55, top=2):
    """Name an archetype from its standardized centroid ``zc``.

    ``phrases[i] = (high_phrase, low_phrase)`` for feature i. Picks the ``top``
    features with the largest |z| above ``thresh`` and joins their directional
    phrases; falls back to 'balanced / average'.
    """
    order = sorted(range(len(zc)), key=lambda i: -abs(zc[i]))
    parts = []
    for i in order[:top]:
        if abs(zc[i]) < thresh:
            continue
        parts.append(phrases[i][0] if zc[i] > 0 else phrases[i][1])
    return " / ".join(parts) if parts else "balanced / average"
