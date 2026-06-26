# Archetype Predictor Integration

## Overview

The archetype predictor has been integrated into the ensemble pipeline as an optional component. It provides pitcher archetype-based strikeout rate predictions that can be blended with the existing ensemble components.

## Integration Points

### 1. Model Configuration

Add `archetype_weight` to your `ModelConfig` to enable archetype predictions:

```python
from app.model.weights import ModelConfig

# Default: archetype disabled (weight = 0.0)
cfg = ModelConfig()

# Enable with 5% weight
cfg = ModelConfig(archetype_weight=0.05)

# Enable with 10% weight
cfg = ModelConfig(archetype_weight=0.10)
```

### 2. Projection Component

When enabled and data is available, the archetype predictor adds an `archetype_interaction` component to the projection breakdown:

```python
from app.model import project, ModelConfig

cfg = ModelConfig(archetype_weight=0.05)
result = project(inputs, cfg)

# Check components
for component in result.components:
    if component.name == "archetype_interaction":
        print(f"Archetype estimate: {component.estimate_ks:.2f} Ks")
        print(f"Weight: {component.weight}")
        print(f"Detail: {component.detail}")
```

### 3. Data Requirements

The archetype predictor requires:

- Pitcher archetype mapping: `data/exports/pitcher_archetypes.csv`
- Batter archetype mapping: `data/exports/batter_archetypes.csv`
- Interaction matrix: `data/exports/archetype_interaction_matrix.csv`

If these files are not present, the archetype component is silently skipped (graceful degradation).

### 4. Current Limitations

**Version 1** (current implementation):
- Uses pitcher archetype average K% as a baseline signal
- Does not yet compute per-batter archetype matchups
- Requires only `pitcher_id` on `ProjectionInputs`

**Future Enhancement**:
- When `LineupStrength` includes batter IDs, the component will compute archetype interaction predictions for each pitcher-batter pair and aggregate across the lineup
- This will provide true archetype × archetype interaction modeling

## Example Usage

### Simple API Call

```python
from app.ensemble_pipeline import predict_pitcher_ensemble
from app.model.weights import ModelConfig

# Enable archetype predictions
cfg = ModelConfig(archetype_weight=0.08)

result = await predict_pitcher_ensemble(
    pitcher="Gerrit Cole",
    line=6.5,
    date="2026-06-25",
    over_odds=-115,
    under_odds=-105,
    settings=settings.model_copy(update={'archetype_weight': 0.08})
)

# Check if archetype was used
components = result.get('components', {})
if 'archetype_interaction' in components:
    print(f"Archetype K estimate: {components['archetype_interaction']:.2f}")
```

### Testing Different Weights

```python
from app.model import project, ModelConfig

# Compare projections with different archetype weights
for weight in [0.0, 0.05, 0.10, 0.15]:
    cfg = ModelConfig(archetype_weight=weight)
    result = project(inputs, cfg)
    print(f"Weight {weight:.0%}: {result.projected_ks:.2f} Ks")
```

## Performance Notes

- The archetype predictor is loaded once as a module-level singleton
- Prediction lookups are O(1) dictionary lookups
- Negligible performance impact when disabled (weight = 0)
- When enabled, adds < 1ms per projection

## Fallback Behavior

The archetype component gracefully handles missing data:

1. If archetype CSV files are not found → component not added
2. If `pitcher_id` is `None` → component not added
3. If prediction fails (exception) → component not added
4. If archetype lookup fails → uses global fallback K rate

The ensemble continues to work normally in all cases.
