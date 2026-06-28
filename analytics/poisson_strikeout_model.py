"""
Poisson Regression Model for MLB Strikeout Prediction

Builds a PoissonRegressor to predict strikeout counts (lambda parameter),
calculates P(Over|line) using scipy.stats.poisson, computes edge%,
and backtests on June 15-27 with filters for |edge%| > 8% and confidence > 70%.

Compares to current archetype MSE model.

Uses pa_events table from baseball.duckdb for fast data access.

Usage:
    python poisson_strikeout_model.py [--db data/baseball.duckdb] [--output results.json]
"""

import sys
from pathlib import Path
import argparse
import json
from datetime import datetime

import pandas as pd
import numpy as np
import duckdb
from scipy.stats import poisson
from sklearn.linear_model import PoissonRegressor
from sklearn.preprocessing import StandardScaler
import warnings
warnings.filterwarnings('ignore')

# Add backend to path for archetype model comparison
sys.path.insert(0, str(Path(__file__).parent.parent / 'backend'))
try:
    from app.models.archetype_predictor import ArchetypePredictor
    HAS_ARCHETYPE = True
except ImportError:
    HAS_ARCHETYPE = False


class PoissonStrikeoutModel:
    """Poisson regression model for strikeout prediction."""

    def __init__(self, db_path: str = 'data/baseball.duckdb'):
        self.db_path = db_path
        self.con = duckdb.connect(db_path, read_only=True)
        self.model = None
        self.scaler = StandardScaler()
        self.feature_names = None

    def load_june_data(self, start_date: str = '2026-06-01', end_date: str = '2026-06-30'):
        """
        Load June Statcast data from pa_events: pitcher + conditions aggregated to game level.

        Returns:
            DataFrame with columns: game_date, game_pk, pitcher_id, pitcher_name,
                                   home_team, away_team, batters_faced, strikeouts
        """
        print(f"\n[1] Loading June {start_date} to {end_date} pitcher-game data...")

        # Get all pitcher appearances in June with strikeout counts
        query = f"""
        SELECT
            game_date,
            game_pk,
            pitcher,
            home_team,
            away_team,
            COUNT(DISTINCT at_bat_number) as batters_faced,
            SUM(CASE WHEN events LIKE '%strikeout%' THEN 1 ELSE 0 END) as strikeouts
        FROM pa_events
        WHERE game_date >= '{start_date}'
            AND game_date <= '{end_date}'
            AND pitcher IS NOT NULL
        GROUP BY game_date, game_pk, pitcher, home_team, away_team
        HAVING COUNT(DISTINCT at_bat_number) >= 3
        ORDER BY game_date, game_pk, pitcher
        """

        df_raw = self.con.execute(query).fetchdf()

        print(f"  Loaded {len(df_raw)} pitcher-game records")
        print(f"  Date range: {df_raw['game_date'].min()} to {df_raw['game_date'].max()}")
        print(f"  Unique pitchers: {df_raw['pitcher'].nunique()}")
        print(f"  Unique games: {df_raw['game_pk'].nunique()}")

        # Get pitcher names
        pitcher_names = self.con.execute("""
            SELECT DISTINCT player_id, name
            FROM pitchers
            WHERE season = 2026
        """).fetchdf()

        df_raw = df_raw.merge(
            pitcher_names,
            left_on='pitcher',
            right_on='player_id',
            how='left'
        )

        df_raw['pitcher_name'] = df_raw['name'].fillna('Unknown')
        df_raw['pitcher_id'] = df_raw['pitcher'].astype(int)

        # Determine opponent team
        def get_opponent(row):
            if row['pitcher_team'] == row['home_team']:
                return row['away_team']
            else:
                return row['home_team']

        # First, need to figure out which team the pitcher belongs to
        # Use the fact that pitcher is on one of the two teams
        pitcher_teams = self.con.execute("""
            SELECT DISTINCT pitcher, home_team
            FROM pa_events
            WHERE game_date >= '2026-06-01' AND game_date <= '2026-06-30'
                AND pitcher IS NOT NULL
        """).fetchdf()

        pitcher_team_map = {}
        for _, row in pitcher_teams.iterrows():
            pid = int(row['pitcher'])
            if pid not in pitcher_team_map:
                pitcher_team_map[pid] = row['home_team']

        df_raw['pitcher_team'] = df_raw['pitcher_id'].map(pitcher_team_map)

        # If not home team, must be away team
        def get_pitcher_team(row):
            if row['pitcher_team'] == row['home_team']:
                return row['home_team']
            else:
                return row['away_team']

        df_raw['pitcher_actual_team'] = df_raw.apply(get_pitcher_team, axis=1)

        # Get opponent
        df_raw['opponent_team'] = df_raw.apply(
            lambda row: row['away_team'] if row['pitcher_actual_team'] == row['home_team'] else row['home_team'],
            axis=1
        )

        # Select relevant columns
        df = df_raw[[
            'game_date', 'game_pk', 'pitcher_id', 'pitcher_name',
            'pitcher_actual_team', 'opponent_team', 'batters_faced',
            'strikeouts'
        ]].copy()

        df.columns = [
            'game_date', 'game_pk', 'pitcher_id', 'pitcher_name',
            'pitcher_team', 'opponent_team', 'batters_faced', 'strikeouts'
        ]

        return df

    def build_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Build feature matrix for Poisson regression.

        Features:
        - Pitcher K rate (rolling, from earlier games)
        - Opponent team (dummy)
        - Game number in season (proxy for fatigue/schedule effects)
        """
        print(f"\n[2] Building feature matrix...")

        df = df.copy()
        df['game_date'] = pd.to_datetime(df['game_date'])
        df = df.sort_values('game_date').reset_index(drop=True)

        # One-hot encode opponent team
        opponent_dummies = pd.get_dummies(df['opponent_team'], prefix='opp', drop_first=False)
        df = pd.concat([df, opponent_dummies], axis=1)

        # Pitcher rolling K rate (from previous games only)
        df['pitcher_k_rate'] = 0.0
        df['pitcher_game_count'] = 0

        for i in range(len(df)):
            pitcher_id = df.loc[i, 'pitcher_id']
            # Look at all previous appearances by this pitcher
            prev_mask = (df['pitcher_id'] == pitcher_id) & (df.index < i)

            if prev_mask.sum() > 0:
                prev_games = df.loc[prev_mask]
                k_rate = prev_games['strikeouts'].sum() / prev_games['batters_faced'].sum()
                df.loc[i, 'pitcher_k_rate'] = k_rate
                df.loc[i, 'pitcher_game_count'] = prev_mask.sum()

        # Standardize pitcher K rate
        df['pitcher_kr_z'] = (df['pitcher_k_rate'] - df['pitcher_k_rate'].mean()) / (df['pitcher_k_rate'].std() + 1e-6)
        df['pitcher_kr_z'].fillna(0, inplace=True)

        # Game number in season (normalized)
        df['game_seq'] = range(len(df))
        df['game_seq_z'] = (df['game_seq'] - df['game_seq'].mean()) / (df['game_seq'].std() + 1e-6)

        print(f"  Features shape: {df.shape}")
        print(f"  Feature columns: {[c for c in df.columns if c.startswith('opp_') or c.endswith('_z')]}")

        return df

    def train(self, df_train: pd.DataFrame):
        """Train Poisson regression model on training data."""
        print(f"\n[3] Training Poisson regression model...")

        feature_cols = [col for col in df_train.columns
                       if col.startswith('opp_') or col.endswith('_z')]

        X = df_train[feature_cols].fillna(0)
        y = df_train['strikeouts'].astype(int)

        self.feature_names = feature_cols

        # Scale features
        X_scaled = self.scaler.fit_transform(X)

        # Train Poisson regressor
        self.model = PoissonRegressor(alpha=0.01, max_iter=1000, solver='lbfgs')
        self.model.fit(X_scaled, y)

        # Training metrics
        y_pred = self.model.predict(X_scaled)
        mse = ((y - y_pred) ** 2).mean()
        mae = (np.abs(y - y_pred)).mean()

        print(f"  Training MSE: {mse:.4f}")
        print(f"  Training MAE: {mae:.4f}")
        print(f"  Model coefficients: {len(self.model.coef_)}")

        return self.model

    def predict_lambda(self, df_test: pd.DataFrame) -> np.ndarray:
        """Predict lambda (expected strikeouts) for test data."""
        feature_cols = [col for col in df_test.columns
                       if col.startswith('opp_') or col.endswith('_z')]

        X = df_test[feature_cols].fillna(0)
        X_scaled = self.scaler.transform(X)

        lambda_pred = self.model.predict(X_scaled)
        return lambda_pred

    def calculate_edge(self, lambda_pred: np.ndarray, line: float = 5.5) -> dict:
        """
        Calculate P(Over|line) using Poisson CDF and edge% vs book implied prob.

        Args:
            lambda_pred: Predicted lambda (expected strikeouts) for each observation
            line: Strikeout line (default 5.5)

        Returns:
            dict with 'model_prob', 'book_prob', 'edge_pct', 'confidence'
        """
        # P(K > line) = 1 - P(K <= line) for Poisson
        model_probs = []

        for lam in lambda_pred:
            # P(strikeouts > 5.5) = P(strikeouts >= 6) = 1 - P(strikeouts <= 5)
            prob_over = 1 - poisson.cdf(int(np.floor(line)), lam)
            model_probs.append(prob_over)

        model_probs = np.array(model_probs)

        # Book implied probability for -110 odds
        book_prob = 110 / 210  # ~0.524

        # Edge% = (Model Prob - Book Prob) * 100
        edge_pct = (model_probs - book_prob) * 100

        # Confidence = distance from 50% (how extreme is the bet?)
        confidence = np.abs(model_probs - 0.5) * 100

        return {
            'model_prob': model_probs,
            'book_prob': book_prob,
            'edge_pct': edge_pct,
            'confidence': confidence
        }

    def backtest(self, df_test: pd.DataFrame, start_date: str = '2026-06-15',
                 end_date: str = '2026-06-27', edge_threshold: float = 8.0,
                 confidence_threshold: float = 70.0, line: float = 5.5) -> dict:
        """
        Backtest model on test period with gatekeeper filters.

        Filters:
        - |edge%| > edge_threshold
        - confidence > confidence_threshold

        Returns backtest metrics: win_rate, roi, num_plays, breakdown
        """
        print(f"\n[5] Backtesting on {start_date} to {end_date}...")

        # Filter to test period
        df_test = df_test.copy()
        df_test['game_date'] = pd.to_datetime(df_test['game_date'])
        start = pd.to_datetime(start_date)
        end = pd.to_datetime(end_date)

        df_period = df_test[(df_test['game_date'] >= start) & (df_test['game_date'] <= end)].copy()

        print(f"  Test period records: {len(df_period)}")

        if df_period.empty:
            return {
                'win_rate': None,
                'roi': None,
                'num_plays': 0,
                'error': 'No data in test period'
            }

        # Get predictions
        lambda_pred = self.predict_lambda(df_period)
        edge_data = self.calculate_edge(lambda_pred, line=line)

        df_period['lambda'] = lambda_pred
        df_period['model_prob'] = edge_data['model_prob']
        df_period['edge_pct'] = edge_data['edge_pct']
        df_period['confidence'] = edge_data['confidence']

        # Apply gatekeeper filters
        df_bets = df_period[
            (np.abs(df_period['edge_pct']) > edge_threshold) &
            (df_period['confidence'] > confidence_threshold)
        ].copy()

        print(f"  Plays after filters (|edge%| > {edge_threshold}, confidence > {confidence_threshold}): {len(df_bets)}")

        if len(df_bets) == 0:
            return {
                'win_rate': None,
                'roi': None,
                'num_plays': 0,
                'reason': f'No plays passed filters: |edge%|>{edge_threshold}, confidence>{confidence_threshold}'
            }

        # Calculate win/loss (Over 5.5 line)
        df_bets['actual_over'] = df_bets['strikeouts'] > line
        df_bets['predicted_over'] = df_bets['model_prob'] > 0.5
        df_bets['correct'] = df_bets['actual_over'] == df_bets['predicted_over']

        # Metrics
        wins = df_bets['correct'].sum()
        losses = len(df_bets) - wins
        win_rate = (wins / len(df_bets)) * 100

        # ROI calculation (assume -110 odds)
        total_profit = (wins * 100) - (losses * 110)
        total_wagered = len(df_bets) * 110
        roi = (total_profit / total_wagered) * 100 if total_wagered > 0 else 0

        results = {
            'win_rate': win_rate,
            'roi': roi,
            'num_plays': len(df_bets),
            'wins': wins,
            'losses': losses,
            'total_wagered': total_wagered,
            'total_profit': total_profit,
            'avg_edge_pct': df_bets['edge_pct'].mean(),
            'plays': df_bets[['game_date', 'pitcher_id', 'pitcher_name', 'opponent_team',
                              'strikeouts', 'lambda', 'model_prob', 'edge_pct', 'correct']].to_dict('records')
        }

        return results

    def get_sample_predictions(self, df_test: pd.DataFrame, n: int = 10,
                               line: float = 5.5) -> list:
        """
        Return sample predictions showing: lambda → P(Over) → edge%.
        """
        df_sample = df_test.sample(min(n, len(df_test)), random_state=42).copy()

        lambda_pred = self.predict_lambda(df_sample)
        edge_data = self.calculate_edge(lambda_pred, line=line)

        df_sample['lambda'] = lambda_pred
        df_sample['model_prob'] = edge_data['model_prob']
        df_sample['edge_pct'] = edge_data['edge_pct']
        df_sample['confidence'] = edge_data['confidence']

        samples = []
        for _, row in df_sample.iterrows():
            samples.append({
                'pitcher_id': int(row['pitcher_id']),
                'pitcher_name': row['pitcher_name'],
                'opponent': row['opponent_team'],
                'game_date': str(row['game_date'].date()),
                'batters_faced': int(row['batters_faced']),
                'lambda': round(float(row['lambda']), 3),
                'p_over_5_5': round(float(row['model_prob']), 3),
                'edge_pct': round(float(row['edge_pct']), 2),
                'actual_strikeouts': int(row['strikeouts']),
                'actual_over': row['strikeouts'] > line
            })

        return samples


def compare_with_archetype(df_test: pd.DataFrame, poisson_model: PoissonStrikeoutModel,
                           line: float = 5.5) -> dict:
    """
    Compare Poisson model with archetype model on test period.
    """
    print(f"\n[6] Comparing with Archetype Model...")

    if not HAS_ARCHETYPE:
        return {'error': 'Archetype model not available'}

    try:
        archetype = ArchetypePredictor()
    except Exception as e:
        return {'error': f'Could not load archetype: {str(e)}'}

    # Use provided test period
    df_cmp = df_test.copy()

    if df_cmp.empty:
        return {'error': 'No test data provided'}

    # Poisson predictions
    poisson_lambda = poisson_model.predict_lambda(df_cmp)
    poisson_edge = poisson_model.calculate_edge(poisson_lambda, line=line)

    df_cmp['poisson_lambda'] = poisson_lambda
    df_cmp['poisson_prob'] = poisson_edge['model_prob']
    df_cmp['poisson_edge'] = poisson_edge['edge_pct']

    # Archetype predictions (use average opponent)
    archetype_preds = []
    archetype_mse_list = []

    for _, row in df_cmp.iterrows():
        try:
            # Use average opponent ID (simplified approach)
            pred = archetype.predict(int(row['pitcher_id']), 545361)
            k_rate = pred['k_rate']
            expected_ks = k_rate * row['batters_faced']

            archetype_preds.append(expected_ks)
            archetype_mse_list.append((expected_ks - row['strikeouts']) ** 2)
        except:
            archetype_preds.append(np.nan)
            archetype_mse_list.append(np.nan)

    # Calculate MSE and MAE for both models
    poisson_mse = ((poisson_lambda - df_cmp['strikeouts'].values) ** 2).mean()
    archetype_mse = np.nanmean(archetype_mse_list)

    poisson_mae = np.abs(poisson_lambda - df_cmp['strikeouts'].values).mean()
    archetype_mae = np.nanmean(np.abs(np.array(archetype_preds) - df_cmp['strikeouts'].values))

    comparison = {
        'poisson_mse': float(poisson_mse),
        'poisson_mae': float(poisson_mae),
        'archetype_mse': float(archetype_mse) if not np.isnan(archetype_mse) else None,
        'archetype_mae': float(archetype_mae) if not np.isnan(archetype_mae) else None,
        'poisson_better': poisson_mse < archetype_mse if not np.isnan(archetype_mse) else True,
        'improvement_pct': float(((archetype_mse - poisson_mse) / archetype_mse * 100)) if (archetype_mse > 0 and not np.isnan(archetype_mse)) else None
    }

    return comparison


def main():
    parser = argparse.ArgumentParser(description='Poisson regression model for strikeout prediction')
    parser.add_argument('--db', default='data/baseball.duckdb', help='Path to DuckDB database')
    parser.add_argument('--output', default='poisson_results.json', help='Output results file')
    parser.add_argument('--samples', type=int, default=10, help='Number of sample predictions')
    args = parser.parse_args()

    print("=" * 100)
    print("POISSON REGRESSION MODEL FOR MLB STRIKEOUT PREDICTION")
    print("=" * 100)

    # Initialize model
    model = PoissonStrikeoutModel(db_path=args.db)

    # Load all June data
    df_full = model.load_june_data()

    if df_full.empty:
        print("\nERROR: Could not load data. Exiting.")
        return

    # Build features
    df_features = model.build_features(df_full)

    # Split train/test (Note: database only has through June 14)
    # Use June 1-10 train, June 11-14 test
    df_train = df_features[df_features['game_date'] < '2026-06-11'].copy()
    df_test = df_features[df_features['game_date'] >= '2026-06-11'].copy()

    print(f"\n  Training set: {len(df_train)} records (June 1-10)")
    print(f"  Test set: {len(df_test)} records (June 11-14)")

    if len(df_train) == 0:
        print("  ERROR: No training data!")
        return

    # Train model
    model.train(df_train)

    # Backtest on test period
    backtest_results = model.backtest(df_test, start_date='2026-06-11', end_date='2026-06-14', line=5.5)

    print("\n" + "=" * 100)
    print("BACKTEST RESULTS (June 11-14)")
    print("=" * 100)

    if 'error' in backtest_results or 'reason' in backtest_results:
        error_msg = backtest_results.get('error') or backtest_results.get('reason')
        print(f"\n  {error_msg}")
    else:
        print(f"\n  Plays Released: {backtest_results['num_plays']}")
        print(f"  Win Rate: {backtest_results['win_rate']:.1f}%")
        print(f"  ROI: {backtest_results['roi']:+.1f}%")
        print(f"  Wins/Losses: {backtest_results['wins']}/{backtest_results['losses']}")
        print(f"  Total Wagered: ${backtest_results['total_wagered']}")
        print(f"  Total Profit: ${backtest_results['total_profit']:+d}")
        print(f"  Avg Edge: {backtest_results['avg_edge_pct']:.2f}%")

    # Sample predictions
    print("\n" + "=" * 100)
    print("SAMPLE PREDICTIONS: LAMBDA -> P(OVER 5.5) -> EDGE%")
    print("=" * 100)

    sample_preds = model.get_sample_predictions(df_test, n=args.samples)
    for i, pred in enumerate(sample_preds, 1):
        print(f"\n  [{i}] {pred['pitcher_name']} ({pred['pitcher_id']}) vs {pred['opponent']}")
        print(f"      Date: {pred['game_date']}")
        print(f"      Lambda (expected Ks): {pred['lambda']}")
        print(f"      P(Over 5.5): {pred['p_over_5_5']:.3f}")
        print(f"      Edge%: {pred['edge_pct']:+.2f}%")
        print(f"      Actual: {pred['actual_strikeouts']} Ks {'(Over)' if pred['actual_over'] else '(Under)'}")

    # Compare with archetype (on same test period)
    print("\n" + "=" * 100)
    print("MODEL COMPARISON: POISSON vs ARCHETYPE (June 11-14)")
    print("=" * 100)

    # Adjust test df for comparison
    comparison_df = df_test[(df_test['game_date'] >= '2026-06-11') & (df_test['game_date'] <= '2026-06-14')].copy()
    comparison = compare_with_archetype(comparison_df, model)

    if 'error' not in comparison:
        print(f"\n  Poisson MSE:    {comparison['poisson_mse']:.4f}")
        if comparison['archetype_mse'] is not None:
            print(f"  Archetype MSE:  {comparison['archetype_mse']:.4f}")
            print(f"  Winner: {'Poisson' if comparison['poisson_better'] else 'Archetype'}")
            if comparison['improvement_pct'] is not None:
                print(f"  Improvement: {comparison['improvement_pct']:+.1f}%")
        else:
            print(f"  Archetype MSE:  Unable to calculate")
        print(f"\n  Poisson MAE:    {comparison['poisson_mae']:.4f}")
        if comparison['archetype_mae'] is not None:
            print(f"  Archetype MAE:  {comparison['archetype_mae']:.4f}")
    else:
        print(f"\n  {comparison['error']}")

    # Prepare output
    output = {
        'timestamp': datetime.now().isoformat(),
        'data_summary': {
            'training_records': int(len(df_train)),
            'test_records': int(len(df_test)),
            'unique_pitchers': int(df_features['pitcher_id'].nunique()),
            'unique_games': int(df_features['game_pk'].nunique()),
            'date_range': {
                'start': str(df_features['game_date'].min().date()),
                'end': str(df_features['game_date'].max().date())
            }
        },
        'backtest_results': backtest_results,
        'sample_predictions': sample_preds,
        'model_comparison': comparison,
        'gatekeeper_filters': {
            'edge_threshold_pct': 8.0,
            'confidence_threshold': 70.0,
            'strikeout_line': 5.5
        }
    }

    # Save results
    output_path = Path('analytics') / args.output
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\n\nResults saved to {output_path}")
    print("=" * 100)
    print("COMPLETE")
    print("=" * 100)


if __name__ == '__main__':
    main()
