"""
Demonstration of archetype predictor integration into the ensemble pipeline.

This script shows how to enable archetype predictions and inspect the results.
"""

from app.model import (
    ExpectedWorkload,
    Handedness,
    LineupStrength,
    ModelConfig,
    OpponentKProfile,
    PitcherRecentForm,
    ProjectionInputs,
    project,
)


def demo_archetype_integration():
    """Compare projections with and without archetype integration."""

    # Create sample inputs for a pitcher
    inputs = ProjectionInputs(
        pitcher_name="Gerrit Cole",
        pitcher_id=543037,  # Gerrit Cole's MLB ID
        opponent=OpponentKProfile(
            k_pct_vs_rhp=0.23,
            k_pct_vs_lhp=0.21,
            k_pct_last_14=0.24,
            k_pct_last_30=0.23,
            k_pct_starting_lineup=0.25,
        ),
        pitcher_form=PitcherRecentForm(
            throws=Handedness.R,
            recent_start_ks=[9, 8, 11, 7, 10],
            k_per_9_last_30=10.5,
        ),
        workload=ExpectedWorkload(
            expected_innings=6.5,
            expected_pitch_count=100,
            manager_hook_pitch_count=105,
        ),
        lineup=LineupStrength(
            projected_lineup_k_pct=0.25,
            high_k_hitters_resting=0,
        ),
    )

    print("=" * 70)
    print("ARCHETYPE PREDICTOR INTEGRATION DEMO")
    print("=" * 70)
    print()

    # 1. Baseline projection (archetype disabled)
    print("1. BASELINE PROJECTION (archetype disabled)")
    print("-" * 70)
    cfg_baseline = ModelConfig(archetype_weight=0.0)
    result_baseline = project(inputs, cfg_baseline)

    print(f"Projected Ks: {result_baseline.projected_ks:.2f}")
    print(f"Expected BF:  {result_baseline.expected_batters_faced:.1f}")
    print(f"Components:   {len(result_baseline.components)}")
    print()

    # 2. Projection with archetype enabled (5% weight)
    print("2. WITH ARCHETYPE (5% weight)")
    print("-" * 70)
    cfg_archetype = ModelConfig(archetype_weight=0.05)
    result_archetype = project(inputs, cfg_archetype)

    print(f"Projected Ks: {result_archetype.projected_ks:.2f}")
    print(f"Expected BF:  {result_archetype.expected_batters_faced:.1f}")
    print(f"Components:   {len(result_archetype.components)}")

    # Check if archetype component was added
    archetype_comp = None
    for c in result_archetype.components:
        if c.name == "archetype_interaction":
            archetype_comp = c
            break

    if archetype_comp:
        print()
        print("Archetype Component:")
        print(f"  Estimate: {archetype_comp.estimate_ks:.2f} Ks")
        print(f"  Weight:   {archetype_comp.weight:.0%}")
        print(f"  Detail:   {archetype_comp.detail}")
    else:
        print()
        print("Note: Archetype component not added (data files may not be present)")
    print()

    # 3. Compare with different weights
    print("3. ARCHETYPE WEIGHT SENSITIVITY")
    print("-" * 70)
    print(f"{'Weight':>8} | {'Projected Ks':>12} | {'Delta from Baseline':>18}")
    print("-" * 70)

    for weight in [0.0, 0.03, 0.05, 0.08, 0.10, 0.15]:
        cfg = ModelConfig(archetype_weight=weight)
        result = project(inputs, cfg)
        delta = result.projected_ks - result_baseline.projected_ks
        delta_str = f"{delta:+.3f}" if weight > 0 else "baseline"
        print(f"{weight:>7.0%} | {result.projected_ks:>12.2f} | {delta_str:>18}")

    print()

    # 4. Component breakdown
    print("4. COMPONENT BREAKDOWN (with 8% archetype weight)")
    print("-" * 70)
    cfg_detail = ModelConfig(archetype_weight=0.08)
    result_detail = project(inputs, cfg_detail)

    print(f"{'Component':<25} | {'Weight':>7} | {'Estimate':>8} | {'Contribution':>12}")
    print("-" * 70)

    for component in result_detail.components:
        contribution = component.weight * component.estimate_ks
        print(f"{component.name:<25} | {component.weight:>6.0%} | "
              f"{component.estimate_ks:>8.2f} | {contribution:>12.2f}")

    print("-" * 70)
    print(f"{'TOTAL':<25} | {'':<7} | {'':<8} | {result_detail.projected_ks:>12.2f}")
    print()

    print("=" * 70)
    print("DEMO COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    demo_archetype_integration()
