"""Distance-binned bias correction từ survey residual.

Stage 1 ITU-R P.1812 + P.2108 + LandCover vẫn có bias ổn định theo
distance band (gateway-specific) do: antenna pattern lệch omni, mast/feeder
loss chưa model, calibration drift của transmitter. Module này load file
JSON `bias_<gw_code>.json` (sinh từ scripts/validate_stage1_itu.py
--dump-bias-dir) và cộng additive offset vào PL trong predict / precompute.
"""

from .distance_binned import DistanceBinnedBias

__all__ = ["DistanceBinnedBias"]
