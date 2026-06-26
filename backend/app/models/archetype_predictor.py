"""
Pitcher-Batter Archetype Interaction Model

Predicts strikeout rates based on pitcher archetype × batter archetype interaction patterns.

Usage:
    from app.models.archetype_predictor import ArchetypePredictor

    predictor = ArchetypePredictor()
    result = predictor.predict(pitcher_id=657277, batter_id=660271)
    # Returns: {'k_rate': 0.245, 'bb_rate': 0.082, 'method': 'archetype', ...}
"""

import pandas as pd
from pathlib import Path
from typing import Dict, Optional, Any
import logging

logger = logging.getLogger(__name__)


class ArchetypePredictor:
    """
    Predicts PA outcomes using pitcher-batter archetype interaction patterns.

    Attributes:
        pitcher_map: Dict mapping pitcher_id -> archetype
        batter_map: Dict mapping batter_id -> archetype
        matrix: DataFrame with interaction rates per (pitcher_archetype, batter_archetype)
    """

    def __init__(self, data_dir: str = 'data/exports'):
        """
        Load archetype mappings and interaction matrix.

        Args:
            data_dir: Directory containing archetype CSV files
        """
        data_path = Path(data_dir)

        # Load archetype mappings from database-exported tables
        try:
            pitcher_archetypes = pd.read_csv(data_path / 'pitcher_archetypes.csv')
            self.pitcher_map = dict(zip(
                pitcher_archetypes['player_id'],
                pitcher_archetypes['archetype']
            ))
            logger.info(f"Loaded {len(self.pitcher_map)} pitcher archetypes")
        except FileNotFoundError:
            logger.warning("pitcher_archetypes.csv not found, using empty map")
            self.pitcher_map = {}

        try:
            batter_archetypes = pd.read_csv(data_path / 'batter_archetypes.csv')
            self.batter_map = dict(zip(
                batter_archetypes['player_id'],
                batter_archetypes['archetype']
            ))
            logger.info(f"Loaded {len(self.batter_map)} batter archetypes")
        except FileNotFoundError:
            logger.warning("batter_archetypes.csv not found, using empty map")
            self.batter_map = {}

        # Load interaction matrix
        try:
            self.matrix = pd.read_csv(data_path / 'archetype_interaction_matrix.csv')
            self.lookup = self.matrix.set_index(['pitcher_archetype', 'batter_archetype'])
            logger.info(f"Loaded interaction matrix with {len(self.matrix)} cells")
        except FileNotFoundError:
            logger.warning("archetype_interaction_matrix.csv not found, using empty matrix")
            self.matrix = pd.DataFrame()
            self.lookup = pd.DataFrame()

        # Compute global averages for fallback
        if not self.matrix.empty:
            self.global_k_rate = self.matrix['k_pct'].mean() / 100.0  # Convert % to rate
            self.global_bb_rate = self.matrix['bb_pct'].mean() / 100.0
            self.global_obp = self.matrix['obp'].mean() / 100.0 if 'obp' in self.matrix.columns else None
        else:
            self.global_k_rate = 0.22  # MLB average ~22%
            self.global_bb_rate = 0.08  # MLB average ~8%
            self.global_obp = 0.32

    def predict(
        self,
        pitcher_id: int,
        batter_id: int
    ) -> Dict[str, Any]:
        """
        Predict strikeout rate and other outcomes for this matchup.

        Args:
            pitcher_id: MLB player ID for pitcher
            batter_id: MLB player ID for batter

        Returns:
            Dictionary with:
                - method: 'archetype' | 'pitcher_marginal' | 'batter_marginal' | 'global_fallback'
                - k_rate: Predicted strikeout rate (0-1)
                - bb_rate: Predicted walk rate (0-1)
                - obp: Predicted on-base percentage (0-1, if available)
                - pitcher_archetype: Cluster ID (if found)
                - batter_archetype: Cluster ID (if found)
                - sample_size: Number of PAs this cell is based on (if archetype match)
        """
        # Check if both players have archetypes
        if pitcher_id not in self.pitcher_map:
            return self._fallback(reason='pitcher_unknown', batter_id=batter_id)

        if batter_id not in self.batter_map:
            return self._fallback(reason='batter_unknown', pitcher_id=pitcher_id)

        p_arch = self.pitcher_map[pitcher_id]
        b_arch = self.batter_map[batter_id]

        # Try exact archetype match
        key = (p_arch, b_arch)
        if key in self.lookup.index:
            row = self.lookup.loc[key]
            return {
                'method': 'archetype',
                'pitcher_archetype': int(p_arch),
                'batter_archetype': int(b_arch),
                'k_rate': float(row['k_pct']) / 100.0,  # Convert % to rate
                'bb_rate': float(row['bb_pct']) / 100.0,
                'obp': float(row['obp']) / 100.0 if 'obp' in row else None,
                'sample_size': int(row['total_pa']) if 'total_pa' in row else None
            }

        # Fallback: use pitcher archetype marginal (average vs all batter archetypes)
        pitcher_marginal = self.matrix[self.matrix['pitcher_archetype'] == p_arch]
        if not pitcher_marginal.empty:
            return {
                'method': 'pitcher_marginal',
                'pitcher_archetype': int(p_arch),
                'batter_archetype': int(b_arch),
                'k_rate': float(pitcher_marginal['k_pct'].mean()) / 100.0,
                'bb_rate': float(pitcher_marginal['bb_pct'].mean()) / 100.0,
                'obp': None
            }

        # Final fallback: global average
        return self._fallback(reason='no_interaction_data', pitcher_id=pitcher_id, batter_id=batter_id)

    def _fallback(self, reason: str, **context) -> Dict[str, Any]:
        """Return global average when archetype lookup fails."""
        logger.debug(f"Using global fallback: {reason}, context={context}")
        return {
            'method': 'global_fallback',
            'reason': reason,
            'k_rate': self.global_k_rate,
            'bb_rate': self.global_bb_rate,
            'obp': self.global_obp
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

    def get_archetype_profile(self, archetype_type: str, archetype_id: int) -> Optional[Dict]:
        """
        Get summary stats for an archetype cluster.

        Args:
            archetype_type: 'pitcher' or 'batter'
            archetype_id: Cluster ID

        Returns:
            Dict with mean stats for this archetype, or None if not found
        """
        if archetype_type == 'pitcher':
            subset = self.matrix[self.matrix['pitcher_archetype'] == archetype_id]
        elif archetype_type == 'batter':
            subset = self.matrix[self.matrix['batter_archetype'] == archetype_id]
        else:
            raise ValueError(f"archetype_type must be 'pitcher' or 'batter', got {archetype_type}")

        if subset.empty:
            return None

        return {
            'archetype_id': archetype_id,
            'n_matchups': len(subset),
            'avg_k_rate': float(subset['k_pct'].mean()) / 100.0,
            'avg_bb_rate': float(subset['bb_pct'].mean()) / 100.0,
            'total_pa': int(subset['total_pa'].sum()) if 'total_pa' in subset.columns else None
        }


# Example usage
if __name__ == '__main__':
    import logging
    logging.basicConfig(level=logging.INFO)

    predictor = ArchetypePredictor()

    # Test prediction
    example_pitcher = 657277  # Top pitcher from audit
    example_batter = 660271   # Example batter

    result = predictor.predict(example_pitcher, example_batter)
    print(f"\nPrediction for pitcher {example_pitcher} vs batter {example_batter}:")
    print(f"  Method: {result['method']}")
    print(f"  K Rate: {result['k_rate']:.1%}")
    print(f"  BB Rate: {result['bb_rate']:.1%}")

    if 'pitcher_archetype' in result:
        print(f"  Pitcher Archetype: {result['pitcher_archetype']}")
        profile = predictor.get_archetype_profile('pitcher', result['pitcher_archetype'])
        if profile:
            print(f"    Archetype avg K%: {profile['avg_k_rate']:.1%}")

    # Test expected strikeouts
    exp_k = predictor.predict_expected_ks(example_pitcher, example_batter, expected_batters_faced=27)
    print(f"\n  Expected Ks (27 BF): {exp_k:.2f}")
