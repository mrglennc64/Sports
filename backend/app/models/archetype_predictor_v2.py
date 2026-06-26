"""
Pitcher-Batter Archetype Interaction Model V2 (FIXED)

FIX: Uses pitcher's actual K-rate as baseline, then applies batter archetype adjustment.
This preserves pitcher-specific skill instead of washing it out with cluster averages.

Diagnosis showed original model lost 38.6% accuracy by replacing pitcher rates with
archetype averages. This version keeps pitcher skill and tests if batter archetypes
add value ON TOP of that baseline.

Usage:
    from app.models.archetype_predictor_v2 import ArchetypePredictorV2

    predictor = ArchetypePredictorV2()
    result = predictor.predict(pitcher_id=657277, batter_id=660271)
"""

import pandas as pd
import duckdb
from pathlib import Path
from typing import Dict, Optional, Any
import logging

logger = logging.getLogger(__name__)


class ArchetypePredictorV2:
    """
    Predicts PA outcomes using pitcher baseline + batter archetype adjustment.

    Key difference from V1: Uses pitcher's actual K-rate, not archetype average.
    """

    def __init__(self, data_dir: str = 'data/exports', db_path: str = 'data/baseball.duckdb'):
        """
        Load archetype mappings, interaction matrix, and pitcher baselines.

        Args:
            data_dir: Directory containing archetype CSV files
            db_path: Path to DuckDB database with pitcher stats
        """
        data_path = Path(data_dir)

        # Load batter archetype mappings (still useful for matchup adjustments)
        try:
            batter_archetypes = pd.read_csv(data_path / 'batter_archetypes.csv')
            self.batter_map = dict(zip(
                batter_archetypes['player_id'],
                batter_archetypes['archetype']
            ))
            logger.info(f"Loaded {len(self.batter_map)} batter archetypes")
        except FileNotFoundError:
            logger.warning("batter_archetypes.csv not found")
            self.batter_map = {}

        # Load pitcher baselines from database (actual K-rates)
        try:
            con = duckdb.connect(db_path, read_only=True)
            pitcher_stats = con.execute("""
                SELECT
                    pitcher,
                    COUNT(*) as total_pa,
                    SUM(CASE WHEN events = 'strikeout' THEN 1 ELSE 0 END)::FLOAT / COUNT(*) as k_rate,
                    SUM(CASE WHEN events = 'walk' THEN 1 ELSE 0 END)::FLOAT / COUNT(*) as bb_rate
                FROM pa_events
                WHERE season = 2026
                GROUP BY pitcher
                HAVING COUNT(*) >= 50
            """).fetchdf()

            self.pitcher_baselines = dict(zip(
                pitcher_stats['pitcher'],
                pitcher_stats[['k_rate', 'bb_rate', 'total_pa']].to_dict('records')
            ))
            logger.info(f"Loaded {len(self.pitcher_baselines)} pitcher baselines from 2026 data")
            con.close()
        except Exception as e:
            logger.warning(f"Could not load pitcher baselines: {e}")
            self.pitcher_baselines = {}

        # Load batter archetype adjustments (how much each batter type affects K-rate)
        try:
            # Calculate adjustment factors: batter archetype effect vs league average
            self.matrix = pd.read_csv(data_path / 'archetype_interaction_matrix.csv')

            # Global K% across all matchups
            global_k_pct = self.matrix['k_pct'].mean()

            # For each batter archetype, calculate how much it deviates from average
            batter_effects = self.matrix.groupby('batter_archetype')['k_pct'].mean()
            self.batter_adjustments = {}

            for b_arch, k_pct in batter_effects.items():
                # Adjustment factor: ratio of batter-type K% to league average
                # e.g., if high-K batters strike out 35% vs 23% avg, factor = 1.52
                self.batter_adjustments[int(b_arch)] = k_pct / global_k_pct

            logger.info(f"Loaded batter adjustments for {len(self.batter_adjustments)} archetypes")

        except FileNotFoundError:
            logger.warning("archetype_interaction_matrix.csv not found")
            self.batter_adjustments = {}

        # Global fallback rates
        self.global_k_rate = 0.228  # 2026 MLB average
        self.global_bb_rate = 0.082

    def predict(
        self,
        pitcher_id: int,
        batter_id: int
    ) -> Dict[str, Any]:
        """
        Predict strikeout rate using pitcher baseline + batter archetype adjustment.

        Method:
        1. Get pitcher's actual K-rate (from 2026 data)
        2. If batter has archetype, apply adjustment factor
        3. Final K-rate = pitcher_k_rate × batter_adjustment_factor

        Args:
            pitcher_id: MLB player ID for pitcher
            batter_id: MLB player ID for batter

        Returns:
            Dictionary with predicted rates and metadata
        """
        # Get pitcher baseline (actual K-rate)
        if pitcher_id in self.pitcher_baselines:
            pitcher_k = self.pitcher_baselines[pitcher_id]['k_rate']
            pitcher_bb = self.pitcher_baselines[pitcher_id]['bb_rate']
            method = 'pitcher_baseline'
        else:
            # Fallback to global average if pitcher unknown
            pitcher_k = self.global_k_rate
            pitcher_bb = self.global_bb_rate
            method = 'global_fallback'

        # Apply batter archetype adjustment if available
        if batter_id in self.batter_map:
            b_arch = self.batter_map[batter_id]
            if b_arch in self.batter_adjustments:
                adjustment = self.batter_adjustments[b_arch]
                adjusted_k = pitcher_k * adjustment

                # Cap at reasonable bounds (5% to 50%)
                adjusted_k = max(0.05, min(0.50, adjusted_k))

                return {
                    'method': 'pitcher_baseline_with_batter_adjustment',
                    'k_rate': float(adjusted_k),
                    'bb_rate': float(pitcher_bb),
                    'pitcher_baseline_k': float(pitcher_k),
                    'batter_archetype': int(b_arch),
                    'batter_adjustment_factor': float(adjustment),
                    'pitcher_sample_size': int(self.pitcher_baselines.get(pitcher_id, {}).get('total_pa', 0))
                }

        # No batter adjustment available, return pitcher baseline
        return {
            'method': method,
            'k_rate': float(pitcher_k),
            'bb_rate': float(pitcher_bb),
            'pitcher_sample_size': int(self.pitcher_baselines.get(pitcher_id, {}).get('total_pa', 0)) if pitcher_id in self.pitcher_baselines else 0
        }

    def predict_expected_ks(
        self,
        pitcher_id: int,
        batter_id: int,
        expected_batters_faced: float = 25.0
    ) -> float:
        """
        Predict expected strikeouts for this matchup.

        Args:
            pitcher_id: Pitcher MLB ID
            batter_id: Batter MLB ID
            expected_batters_faced: How many batters pitcher will face

        Returns:
            Expected strikeout count
        """
        pred = self.predict(pitcher_id, batter_id)
        return pred['k_rate'] * expected_batters_faced


# Test the fixed model
if __name__ == '__main__':
    import logging
    logging.basicConfig(level=logging.INFO)

    predictor = ArchetypePredictorV2()

    # Test prediction
    example_pitcher = 682243  # Bryce Miller (11 K on June 25)
    example_batter = 660271

    result = predictor.predict(example_pitcher, example_batter)
    print(f"\nV2 Prediction for pitcher {example_pitcher} vs batter {example_batter}:")
    print(f"  Method: {result['method']}")
    print(f"  K Rate: {result['k_rate']:.1%}")
    if 'pitcher_baseline_k' in result:
        print(f"  Pitcher baseline: {result['pitcher_baseline_k']:.1%}")
        print(f"  Batter adjustment: {result.get('batter_adjustment_factor', 1.0):.3f}x")

    exp_k = predictor.predict_expected_ks(example_pitcher, example_batter, expected_batters_faced=22)
    print(f"  Expected Ks (22 BF): {exp_k:.2f}")
    print(f"  (Actual was 11 K)")
