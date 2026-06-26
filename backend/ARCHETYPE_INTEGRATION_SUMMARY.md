# Archetype Predictor Integration - Summary

## What Was Done

Successfully integrated the archetype predictor (`backend/app/models/archetype_predictor.py`) into the ensemble pipeline as an optional component.

## Files Modified

1. **app/model/projection.py**
   - Added `get_archetype_predictor()` singleton loader
   - Added archetype_interaction component in `project()` function
   - Component weight controlled by `cfg.archetype_weight`
   - Gracefully handles missing data (falls back silently)

2. **app/model/weights.py**
   - Added `archetype_weight: float = Field(0.0, ge=0, le=1)` to `ModelConfig`
   - Default 0.0 = disabled (no effect on existing projections)
   - Documentation explains behavior

## New Files Created

3. **tests/test_archetype_integration.py**
   - 5 tests verifying integration works correctly
   - Tests archetype enabled/disabled states
   - Tests fallback when pitcher_id missing
   - Tests weight sensitivity

4. **docs/archetype_integration.md**
   - Complete usage documentation
   - Configuration examples
   - Data requirements
   - Performance notes

5. **examples/archetype_demo.py**
   - Working demonstration script
   - Shows baseline vs. archetype-enabled projections
   - Weight sensitivity analysis
   - Component breakdown visualization

## How It Works

### Minimal Changes Design

The integration follows the existing pattern for optional components (umpire, weather, etc.):

1. **Flag-gated**: Only runs when `archetype_weight > 0`
2. **Graceful degradation**: Silently skips if data unavailable
3. **No breaking changes**: All existing tests pass (230/230)
4. **Module-level singleton**: Archetype predictor loads once, reused across predictions

### Current Implementation (V1)

```python
from app.model.weights import ModelConfig

# Enable archetype with 8% weight
cfg = ModelConfig(archetype_weight=0.08)
result = project(inputs, cfg)
```

The archetype component:
- Uses pitcher's archetype average K% as baseline signal
- Multiplies by expected batters faced
- Blends with ensemble via weight parameter
- Method tagged in detail string (archetype/pitcher_marginal/global_fallback)

### Data Files Required

Place in `data/exports/`:
- `pitcher_archetypes.csv` - pitcher_id → archetype mapping
- `batter_archetypes.csv` - player_id → archetype mapping  
- `archetype_interaction_matrix.csv` - (pitcher_arch, batter_arch) → rates

If missing, component silently skips (no error).

## Test Results

All 230 tests pass including:
- 16 existing projection tests
- 5 new archetype integration tests
- Full ensemble pipeline tests
- End-to-end API tests

```bash
cd backend
python -m pytest tests/ -v
# ===== 230 passed in 19.98s =====
```

## Usage Examples

### 1. Simple projection with archetype

```python
from app.model import project, ModelConfig

cfg = ModelConfig(archetype_weight=0.05)
result = project(inputs, cfg)

# Check if archetype was used
for c in result.components:
    if c.name == "archetype_interaction":
        print(f"Archetype: {c.estimate_ks:.2f} Ks ({c.detail})")
```

### 2. Via ensemble pipeline

```python
from app.ensemble_pipeline import predict_pitcher_ensemble
from app.model.weights import ModelConfig

result = await predict_pitcher_ensemble(
    pitcher="Gerrit Cole",
    line=6.5,
    date="2026-06-25",
    cfg=ModelConfig(archetype_weight=0.08)
)

print(result['components'].get('archetype_interaction', 'Not used'))
```

### 3. Run demo script

```bash
cd backend
export PYTHONPATH=.
python examples/archetype_demo.py
```

Shows:
- Baseline projection (archetype disabled)
- Projection with archetype (5% weight)
- Weight sensitivity analysis (0% to 15%)
- Full component breakdown

## Performance

- Singleton loader: archetype predictor loads once per process
- Lookup: O(1) dictionary access
- Overhead when disabled (default): ~0 (short-circuit)
- Overhead when enabled: < 1ms per projection

## Future Enhancements

**When LineupStrength includes batter IDs:**

The current implementation uses pitcher archetype average. The intended enhancement:

1. Get batter IDs from lineup
2. For each batter: `predictor.predict(pitcher_id, batter_id)`
3. Weight by expected PAs per lineup slot
4. Aggregate to total expected Ks

This will provide true pitcher-archetype × batter-archetype interaction predictions.

## Deployment Checklist

- [x] Integration code complete
- [x] All tests passing
- [x] Documentation written
- [x] Demo script working
- [ ] Export archetype CSV files to `data/exports/`
- [ ] Tune optimal `archetype_weight` via backtest
- [ ] Add to production config when signal validated

## Key Design Decisions

1. **Weight separate from sum-to-1 components**: Follows `type_matchup_weight` pattern - final projection blended rather than adding to component weights

2. **Module-level singleton**: Prevents reloading CSV files on every prediction

3. **Graceful fallback**: Missing data → component not added (vs. error/crash)

4. **Pitcher-only V1**: Simpler initial integration; batter-level coming in V2

5. **Flag-gated with default off**: Zero impact on existing projections unless explicitly enabled
