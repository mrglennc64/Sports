"""
Improved Poisson Regression Model for MLB Strikeout Prediction (STARTERS ONLY)

Uses only starting pitcher appearances (15+ batters faced) to avoid mixing
relief pitcher data that skews lambda predictions.

Builds PoissonRegressor with better starter-specific features,
calculates P(Over|line), computes edge%, and backtests with gatekeeper filters.

Usage:
    python poisson_strikeout_model_starters.py [--db data/baseball.duckdb]
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

sys.path.insert(0, str(Path(__file__).parent.parent / 'backend'))
try:
    from app.models.archetype_predictor import ArchetypePredictor
    HAS_ARCHETYPE = True
except ImportError:
    HAS_ARCHETYPE = False


class PoissonStarterModel:
    """Poisson regression for starting pitcher strikeout prediction."""

    def __init__(self, db_path: str = 'data/baseball.duckdb', min_batters: int = 15):
        self.db_path = db_path
        self.con = duckdb.connect(db_path, read_only=True)
        self.min_batters = min_batters  # Filter for starters
        self.model = None
        self.scaler = StandardScaler()
        self.feature_names = None

    def load_starter_data(self, start_date: str = '2026-06-01', end_date: str = '2026-06-30'):
        """Load only starting pitcher appearances (15+ BF)."""
        print(f"\n[1] Loading June {start_date} to {end_date} STARTER data...")
        print(f"    Filter: Batters Faced >= {self.min_batters}")

        # Get all pitcher appearances, filtered to starters
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
        HAVING COUNT(DISTINCT at_bat_number) >= {self.min_batters}
        ORDER BY game_date, game_pk, pitcher
        """

        df_raw = self.con.execute(query).fetchdf()

        print(f"  Loaded {len(df_raw)} starting pitcher appearances")
        print(f"  Date range: {df_raw['game_date'].min()} to {df_raw['game_date'].max()}")
        print(f"  Unique pitchers: {df_raw['pitcher'].nunique()}")
        print(f"  Unique games: {df_raw['game_pk'].nunique()}")

        # Get pitcher names
        pitcher_names = self.con.execute("""
            SELECT DISTINCT player_id, name
            FROM pitchers
            WHERE season = 2026
        """).fetchdf()

        df_raw = df_raw.merge(pitcher_names, left_on='pitcher', right_on='player_id', how='left')
        df_raw['pitcher_name'] = df_raw['name'].fillna('Unknown')
        df_raw['pitcher_id'] = df_raw['pitcher'].astype(int)

        # Determine pitcher team and opponent
        pitcher_teams = self.con.execute("""
            SELECT DISTINCT pitcher, home_team
            FROM pa_events
            WHERE game_date >= '2026-06-01' AND game_date <= '2026-06-30'
                AND pitcher IS NOT NULL
        """).fetchdf()

        pitcher_team_map = dict(zip(pitcher_teams['pitcher'], pitcher_teams['home_team']))

        def get_opponent(row):
            pitcher_team = pitcher_team_map.get(row['pitcher'])
            if pitcher_team == row['home_team']:
                return row['away_team']
            else:
                return row['home_team']

        df_raw['opponent_team'] = df_raw.apply(get_opponent, axis=1)

        # Select columns
        df = df_raw[[
            'game_date', 'game_pk', 'pitcher_id', 'pitcher_name',
            'opponent_team', 'batters_faced', 'strikeouts'
        ]].copy()

        df['batters_faced'] = df['batters_faced'].astype(int)
        df['strikeouts'] = df['strikeouts'].astype(int)

        return df

    def build_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Build features for Poisson regression."""
        print(f"\n[2] Building feature matrix...")

        df = df.copy()
        df['game_date'] = pd.to_datetime(df['game_date'])
        df = df.sort_values('game_date').reset_index(drop=True)

        # One-hot encode opponent team
        opponent_dummies = pd.get_dummies(df['opponent_team'], prefix='opp', drop_first=False)
        df = pd.concat([df, opponent_dummies], axis=1)

        # Rolling K rate (from previous starts only)
        df['pitcher_k_rate'] = 0.0
        for i in range(len(df)):
            pitcher_id = df.loc[i, 'pitcher_id']
            prev_mask = (df['pitcher_id'] == pitcher_id) & (df.index < i)
            if prev_mask.sum() > 0:
                prev_games = df.loc[prev_mask]
                k_rate = prev_games['strikeouts'].sum() / prev_games['batters_faced'].sum()
                df.loc[i, 'pitcher_k_rate'] = k_rate

        df['pitcher_kr_z'] = (df['pitcher_k_rate'] - df['pitcher_k_rate'].mean()) / (df['pitcher_k_rate'].std() + 1e-6)
        df['pitcher_kr_z'].fillna(0, inplace=True)

        # Game sequence
        df['game_seq_z'] = (np.arange(len(df)) - len(df)/2) / (len(df)/6 + 1e-6)

        feature_cols = [col for col in df.columns if col.startswith('opp_') or col.endswith('_z')]
        print(f"  Features: {len(feature_cols)} columns")

        return df

    def train(self, df_train: pd.DataFrame):
        """Train Poisson regressor."""
        print(f"\n[3] Training Poisson Regressor on starters...")

        feature_cols = [col for col in df_train.columns if col.startswith('opp_') or col.endswith('_z')]

        X = df_train[feature_cols].fillna(0)
        y = df_train['strikeouts'].astype(int)

        self.feature_names = feature_cols

        X_scaled = self.scaler.fit_transform(X)
        self.model = PoissonRegressor(alpha=0.01, max_iter=1000, solver='lbfgs')
        self.model.fit(X_scaled, y)

        y_pred = self.model.predict(X_scaled)
        mse = ((y - y_pred) ** 2).mean()
        mae = (np.abs(y - y_pred)).mean()

        print(f"  Training MSE: {mse:.4f}")
        print(f"  Training MAE: {mae:.4f}")
        print(f"  Mean strikeouts (actual): {y.mean():.2f}")
        print(f"  Mean strikeouts (predicted): {y_pred.mean():.2f}")

    def predict_lambda(self, df_test: pd.DataFrame) -> np.ndarray:
        """Predict lambda for test data."""
        feature_cols = [col for col in df_test.columns if col.startswith('opp_') or col.endswith('_z')]
        X = df_test[feature_cols].fillna(0)
        X_scaled = self.scaler.transform(X)
        return self.model.predict(X_scaled)

    def calculate_edge(self, lambda_pred: np.ndarray, line: float = 5.5) -> dict:
        """Calculate P(Over|line) and edge%."""
        model_probs = []
        for lam in lambda_pred:
            prob_over = 1 - poisson.cdf(int(np.floor(line)), lam)
            model_probs.append(prob_over)

        model_probs = np.array(model_probs)
        book_prob = 110 / 210  # -110 odds

        edge_pct = (model_probs - book_prob) * 100
        confidence = np.abs(model_probs - 0.5) * 100

        return {
            'model_prob': model_probs,
            'book_prob': book_prob,
            'edge_pct': edge_pct,
            'confidence': confidence
        }

    def backtest(self, df_test: pd.DataFrame, start_date: str = '2026-06-11',
                 end_date: str = '2026-06-14', edge_threshold: float = 5.0,
                 confidence_threshold: float = 60.0, line: float = 5.5) -> dict:
        """Backtest with relaxed gatekeeper (5% edge, 60% confidence for starters)."""
        print(f"\n[5] Backtesting {start_date} to {end_date}...")
        print(f"    Filters: |edge%| > {edge_threshold}, confidence > {confidence_threshold}%")

        df_test = df_test.copy()
        df_test['game_date'] = pd.to_datetime(df_test['game_date'])
        start = pd.to_datetime(start_date)
        end = pd.to_datetime(end_date)

        df_period = df_test[(df_test['game_date'] >= start) & (df_test['game_date'] <= end)].copy()

        if df_period.empty:
            return {'num_plays': 0, 'error': 'No test data'}

        lambda_pred = self.predict_lambda(df_period)
        edge_data = self.calculate_edge(lambda_pred, line=line)

        df_period['lambda'] = lambda_pred
        df_period['model_prob'] = edge_data['model_prob']
        df_period['edge_pct'] = edge_data['edge_pct']
        df_period['confidence'] = edge_data['confidence']

        # Apply gates
        df_bets = df_period[
            (np.abs(df_period['edge_pct']) > edge_threshold) &
            (df_period['confidence'] > confidence_threshold)
        ].copy()

        print(f"  Plays released: {len(df_bets)}")

        if len(df_bets) == 0:
            return {
                'num_plays': 0,
                'reason': f'No plays passed: |edge%|>{edge_threshold}, conf>{confidence_threshold}%'
            }

        # Backtest
        df_bets['actual_over'] = df_bets['strikeouts'] > line
        df_bets['predicted_over'] = df_bets['model_prob'] > 0.5
        df_bets['correct'] = df_bets['actual_over'] == df_bets['predicted_over']

        wins = df_bets['correct'].sum()
        losses = len(df_bets) - wins
        win_rate = (wins / len(df_bets)) * 100
        total_profit = (wins * 100) - (losses * 110)
        total_wagered = len(df_bets) * 110
        roi = (total_profit / total_wagered) * 100

        return {
            'num_plays': len(df_bets),
            'wins': wins,
            'losses': losses,
            'win_rate': win_rate,
            'roi': roi,
            'total_profit': total_profit,
            'avg_edge': df_bets['edge_pct'].mean(),
            'plays': df_bets[['pitcher_name', 'opponent_team', 'batters_faced',
                              'strikeouts', 'lambda', 'edge_pct', 'correct']].to_dict('records')
        }

    def get_samples(self, df_test: pd.DataFrame, n: int = 10) -> list:
        """Get sample predictions."""
        df_sample = df_test.sample(min(n, len(df_test)), random_state=42).copy()
        lambda_pred = self.predict_lambda(df_sample)
        edge_data = self.calculate_edge(lambda_pred)

        df_sample['lambda'] = lambda_pred
        df_sample['model_prob'] = edge_data['model_prob']
        df_sample['edge_pct'] = edge_data['edge_pct']

        samples = []
        for _, row in df_sample.iterrows():
            samples.append({
                'pitcher': row['pitcher_name'],
                'opponent': row['opponent_team'],
                'date': str(row['game_date'].date()),
                'bf': int(row['batters_faced']),
                'lambda': round(float(row['lambda']), 2),
                'p_over': round(float(row['model_prob']), 3),
                'edge_pct': round(float(row['edge_pct']), 1),
                'actual': int(row['strikeouts']),
                'actual_over': row['strikeouts'] > 5.5
            })
        return samples


def compare_models(df_test: pd.DataFrame, poisson_model: PoissonStarterModel) -> dict:
    """Compare Poisson vs Archetype on test set."""
    print(f"\n[6] Model Comparison (Poisson vs Archetype)...")

    if not HAS_ARCHETYPE:
        return {'error': 'Archetype not available'}

    try:
        archetype = ArchetypePredictor()
    except Exception as e:
        return {'error': str(e)}

    poisson_lambda = poisson_model.predict_lambda(df_test)
    poisson_mse = ((poisson_lambda - df_test['strikeouts'].values) ** 2).mean()
    poisson_mae = np.abs(poisson_lambda - df_test['strikeouts'].values).mean()

    # Archetype (simplified)
    archetype_preds = []
    for _, row in df_test.iterrows():
        try:
            pred = archetype.predict(int(row['pitcher_id']), 545361)
            k_rate = pred['k_rate']
            expected_ks = k_rate * row['batters_faced']
            archetype_preds.append((expected_ks - row['strikeouts']) ** 2)
        except:
            archetype_preds.append(np.nan)

    archetype_mse = np.nanmean(archetype_preds)

    return {
        'poisson_mse': round(float(poisson_mse), 4),
        'archetype_mse': round(float(archetype_mse), 4) if not np.isnan(archetype_mse) else None,
        'poisson_better': poisson_mse < archetype_mse if not np.isnan(archetype_mse) else True,
        'poisson_mae': round(float(poisson_mae), 4)
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', default='data/baseball.duckdb')
    parser.add_argument('--min-batters', type=int, default=15, help='Minimum batters for starter')
    parser.add_argument('--edge', type=float, default=5.0, help='Edge threshold percent')
    parser.add_argument('--confidence', type=float, default=60.0, help='Confidence threshold percent')
    args = parser.parse_args()

    print("=" * 100)
    print("POISSON REGRESSION MODEL - STARTING PITCHERS ONLY")
    print("=" * 100)

    model = PoissonStarterModel(db_path=args.db, min_batters=args.min_batters)

    # Load data
    df_full = model.load_starter_data()
    if df_full.empty:
        print("ERROR: No starter data loaded")
        return

    df_features = model.build_features(df_full)

    # Split
    df_train = df_features[df_features['game_date'] < '2026-06-11'].copy()
    df_test = df_features[df_features['game_date'] >= '2026-06-11'].copy()

    print(f"\n  Training: {len(df_train)} starts (June 1-10)")
    print(f"  Testing: {len(df_test)} starts (June 11-14)")

    if len(df_train) == 0:
        print("ERROR: No training data")
        return

    # Train
    model.train(df_train)

    # Backtest
    backtest = model.backtest(df_test, edge_threshold=args.edge, confidence_threshold=args.confidence)

    print("\n" + "=" * 100)
    print("BACKTEST RESULTS (June 11-14)")
    print("=" * 100)

    if 'error' in backtest or 'reason' in backtest:
        error = backtest.get('error') or backtest.get('reason')
        print(f"\n  {error}")
    else:
        print(f"\n  Plays Released: {backtest['num_plays']}")
        print(f"  Win Rate: {backtest['win_rate']:.1f}%")
        print(f"  ROI: {backtest['roi']:+.1f}%")
        print(f"  Wins/Losses: {backtest['wins']}/{backtest['losses']}")
        print(f"  Avg Edge: {backtest['avg_edge']:.2f}%")

    # Samples
    print("\n" + "=" * 100)
    print("SAMPLE PREDICTIONS: LAMBDA -> P(OVER 5.5) -> EDGE%")
    print("=" * 100)

    samples = model.get_samples(df_test)
    for i, s in enumerate(samples[:5], 1):
        print(f"\n  [{i}] {s['pitcher']} vs {s['opponent']} ({s['date']})")
        print(f"      Lambda: {s['lambda']:.2f} | P(Over): {s['p_over']:.3f} | Edge: {s['edge_pct']:+.1f}%")
        print(f"      Actual: {s['actual']} Ks {'(Over)' if s['actual_over'] else '(Under)'}")

    # Compare
    print("\n" + "=" * 100)
    print("MODEL COMPARISON")
    print("=" * 100)

    comparison = compare_models(df_test, model)
    if 'error' not in comparison:
        print(f"\n  Poisson MSE: {comparison['poisson_mse']}")
        if comparison['archetype_mse']:
            print(f"  Archetype MSE: {comparison['archetype_mse']}")
            print(f"  Winner: {'Poisson' if comparison['poisson_better'] else 'Archetype'}")
        print(f"  Poisson MAE: {comparison['poisson_mae']}")
    else:
        print(f"\n  {comparison['error']}")

    # Save output
    output = {
        'timestamp': datetime.now().isoformat(),
        'model': 'PoissonRegressor (Starters >= 15 BF)',
        'training_records': len(df_train),
        'test_records': len(df_test),
        'backtest': backtest,
        'sample_predictions': samples[:5],
        'comparison': comparison
    }

    output_path = Path('analytics') / 'poisson_starters_results.json'
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\nResults saved to {output_path}")
    print("=" * 100)


if __name__ == '__main__':
    main()
