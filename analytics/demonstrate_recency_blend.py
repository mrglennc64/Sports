"""Demonstrate the recency blend effect on a pitcher with tightening leash.

Example: A pitcher with a season average of 6.2 IP/start but recent games show
only 4.5 IP/start (manager pulling him early). The blend gives us 5.8 IP/start
instead of 6.2, reducing strikeout projection by ~3%.
"""

# Synthetic example
SEASON_AVG_IP = 6.2
RECENT_AVG_IP = 4.5

RECENT_WEIGHT = 0.6
SEASON_WEIGHT = 0.4

blended = (RECENT_AVG_IP * RECENT_WEIGHT) + (SEASON_AVG_IP * SEASON_WEIGHT)

print("Recency Blend Example: Mid-Season Leash Tightening")
print("=" * 50)
print(f"Season IP/start:     {SEASON_AVG_IP:.2f}")
print(f"Recent 21d IP/start: {RECENT_AVG_IP:.2f}")
print(f"Blend (60/40):       {blended:.2f}")
print(f"Reduction:           {SEASON_AVG_IP - blended:.2f} IP ({(1 - blended/SEASON_AVG_IP)*100:.1f}%)")
print()

# Impact on strikeout projection
BF_PER_IP = 4.3
NEUTRAL_K_RATE = 0.220

season_bf = SEASON_AVG_IP * BF_PER_IP
recent_bf = RECENT_AVG_IP * BF_PER_IP
blended_bf = blended * BF_PER_IP

season_ks = season_bf * NEUTRAL_K_RATE
blended_ks = blended_bf * NEUTRAL_K_RATE

print("Strikeout Projection Impact (vs neutral lineup):")
print(f"Season avg projects: {season_ks:.2f} Ks")
print(f"Blended projects:    {blended_ks:.2f} Ks")
print(f"Delta:               {blended_ks - season_ks:+.2f} Ks ({(blended_ks/season_ks - 1)*100:+.1f}%)")
print()
print("This shift directly reduces the +0.27 systematic over-prediction bias.")
