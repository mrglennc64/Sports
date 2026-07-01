"""Offline weight-fitting support (never imported by the live API).

Step 1 of the weight-optimizer work: reconstruct ProjectionInputs for historical
starts from Retrosheet (leak-free), run the REAL ensemble project(), and record
each of the 10 component estimates + actual Ks — the dataset any weight fit needs.

Headline finding (see docs/WEIGHT_FITTING.md): the 10 components are near-perfectly
COLLINEAR. Eight of them are literally the same number (matchup_estimate × a factor
that is 1.0 when its data is neutral); the other two (recent_form, lineup) correlate
0.89-0.98 with it. The weight-optimization problem is therefore ~2-3 effective
dimensions with a degenerate solution space — which bounds how much any optimizer
can gain and makes regularization toward the priors mandatory, not optional.
"""
