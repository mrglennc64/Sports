"""Application settings, loaded from environment / .env.

Secrets (odds API keys) live only in .env, never in code. See .env.example.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Odds provider selection + keys
    # Options: "theoddsapi" (default, US books), "oddsapiio" (secondary, US books),
    # or EU-focused: "csv" (manual CSV import), "betano", "bet365", "unibet" (live scrapers)
    odds_provider: str = "theoddsapi"
    odds_api_key_theoddsapi: str = ""
    odds_api_key_io: str = ""
    # CSV importer path (used when odds_provider="csv")
    odds_csv_path: str = ""
    # the-odds-api region sets. The SLATE (single best book per pitcher) uses a
    # single region to conserve quota; the ARB/CLV quotes path pulls wide
    # (us,us2,eu => ~12 books incl. Pinnacle) so cross-book comparison + a sharp
    # reference line are available. Each region ~1x request cost, so wide quotes
    # are ~3x — fine on-demand (/v2/arb), too costly for a frequent cron on free tier.
    odds_regions_props: str = "us"
    odds_regions_quotes: str = "us,us2,eu"

    # Edge / staking
    min_edge: float = 0.03
    kelly_fraction: float = 0.25
    kelly_cap: float = 0.05
    # Correlated-exposure cap (app.model.risk): the per-bet kelly_cap can't see
    # that two legs are the SAME pitcher (two books, two lines, or a re-pulled
    # slate). This caps the AGGREGATE stake across all legs sharing a pitcher, so
    # one arm can't quietly carry multiples of kelly_cap (the 2026-06-28 stack).
    # Reduce-only; set a touch above kelly_cap so a lone bet is never reduced.
    kelly_group_cap: float = 0.08
    devig_method: str = "shin"  # "shin" | "proportional"
    # Calibration: shrink model probabilities toward 0.5 before measuring edge.
    # 1.0 = off; <1 pulls overconfident edges back toward the market. The backtest
    # showed the model is overconfident above ~5% edge, so this is the lever to
    # correct it once enough graded data justifies a value. Code default stays
    # off (tests pin unshrunk math); PRODUCTION sets PROB_SHRINKAGE in
    # /etc/mlb-edge.env. The weekly report prints the post-hoc optimal k so the
    # production value can be sanity-checked as the graded sample grows.
    prob_shrinkage: float = 1.0
    # Low-confidence gate (v1 had MIN_STARTS/MIN_INNINGS; the v2 path dropped
    # it — restored 2026-06-12): fewer than this many starts this season =>
    # low_confidence, which caps the verdict and blocks the bet flag.
    min_recent_starts: int = 5

    # Where daily predictions get logged (relative to repo root by default)
    predictions_log: str = "../data/predictions.csv"

    # Where the daily line snapshot (app.data.snapshot) accumulates the strikeout
    # prop lines that feed the historical backtest (app.data.history).
    lines_csv: str = "../data/lines.csv"

    # Timestamped line snapshots (app.data.line_capture) tagged open|close. The
    # close-tagged rows are the closing lines that /clv settles flagged bets against.
    line_history_log: str = "../data/line_history.csv"

    # Home-plate umpire K-tendency table (JSON). The MLB API gives the umpire
    # *assignment* but not their zone tendency, so this is a replaceable lookup
    # populated from a source like Umpire Scorecards. Missing file -> neutral.
    umpire_data_path: str = "../data/umpires.json"

    # Expected-Ks model: "multiplier" (season K/9 x factors) or "ensemble"
    # (the v2 framework: recent form + lineup + workload + umpire + ...).
    expected_ks_model: str = "ensemble"

    # Type-matchup synthesis (analytics/): path to the exported archetype priors.
    # The blend WEIGHT lives in ModelConfig.type_matchup_weight (default 0 = off);
    # this is just where the prior file is found. Missing file -> blend is a no-op.
    type_priors_path: str = "app/data/type_priors.json"


settings = Settings()
