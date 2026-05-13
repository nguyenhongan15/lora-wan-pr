"""Tabular feature builder cho Stage 2 (LightGBM).

SKELETON. Features dự kiến (theo data-architecture.md):
  - distance_km
  - elevation_diff_m (gateway alt - target alt)
  - terrain_bin (categorical: urban/suburban/rural/mountain)
  - season_bin (rainy/dry — VN có 2 mùa)
  - gateway_age_days
  - hour_of_day, day_of_week
"""

from __future__ import annotations

__all__: list[str] = []
