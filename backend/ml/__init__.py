"""
ml/ — Machine Learning package cho LoRa coverage prediction.

Public API:
  from ml.dem         import get_dem, DEMReader
  from ml.features    import engineer_dataframe, FEATURE_NAMES
  from ml.trainer     import train, AlgorithmType
  from ml.predictor   import predict_grid
  from ml.model_store import save, load, exists, list_models, ModelBundle
  from ml.dem_predict_patch import enrich_with_dem
"""

from ml.dem              import get_dem, DEMReader          # noqa: F401
from ml.features         import engineer_dataframe, FEATURE_NAMES  # noqa: F401
from ml.trainer          import train, AlgorithmType        # noqa: F401
from ml.predictor        import predict_grid                # noqa: F401
from ml.model_store      import (                           # noqa: F401
    save, load, exists, list_models, ModelBundle,
)
from ml.dem_predict_patch import enrich_with_dem            # noqa: F401
