"""
ml/generate_hillshade.py — Admin task tạo shaded relief overlay PNG từ DEM tiles.

Mục đích:
  Hillshade là PNG bán-trong-suốt overlay lên Mapbox map, giúp người dùng
  thấy địa hình Đà Nẵng (đồi Sơn Trà, đèo Hải Vân, núi Bà Nà...) khi xem
  scatter / heatmap / simulator.

Tuân thủ:
  - 12-Factor F3 (config):  bbox / output qua CLI args, default Đà Nẵng
  - 12-Factor F11 (logs):   structured logging qua stdlib logging → stdout
  - 12-Factor F12 (admin):  chạy `python -m ml.generate_hillshade [...]`
  - SOLID SRP:              compute / render / write tách hàm riêng
  - API Contract:           bounds JSON keys camelCase (latMin, lngMax, ...)
  - Secure coding:          validate bbox + downsample, không trust input mù

Chạy:
  docker exec lora_api python -m ml.generate_hillshade
  docker exec lora_api python -m ml.generate_hillshade --lat-min 16 --lat-max 16.3

Output:
  backend/static/hillshade.png
  backend/static/hillshade_bounds.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# ── Defaults: AOI Đà Nẵng (admin level 2) + lighting/render params ──────────
DEFAULT_LAT_MIN    = 15.9
DEFAULT_LAT_MAX    = 16.3
DEFAULT_LNG_MIN    = 107.8
DEFAULT_LNG_MAX    = 108.4
DEFAULT_DOWNSAMPLE = 4       # ~120m/pixel sau downsample từ SRTM 1″
DEFAULT_AZIMUTH    = 315.0   # độ, hướng ánh sáng (Tây-Bắc — quy ước cartography)
DEFAULT_ALTITUDE   = 45.0    # độ, góc mặt trời
DEFAULT_ALPHA      = 140     # 0-255, alpha PNG để overlay không lấn map

DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent.parent / "static"


# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class HillshadeConfig:
    lat_min:    float
    lat_max:    float
    lng_min:    float
    lng_max:    float
    downsample: int
    azimuth:    float
    altitude:   float
    alpha:      int
    output_dir: Path

    def validate(self) -> None:
        """Fail fast trên config sai — dễ debug hơn lỗi runtime sâu trong DEM."""
        if self.lat_min >= self.lat_max:
            raise ValueError(f"lat_min ({self.lat_min}) phải < lat_max ({self.lat_max})")
        if self.lng_min >= self.lng_max:
            raise ValueError(f"lng_min ({self.lng_min}) phải < lng_max ({self.lng_max})")
        if not -90 <= self.lat_min and self.lat_max <= 90:
            raise ValueError("lat ngoài [-90, 90]")
        if not -180 <= self.lng_min and self.lng_max <= 180:
            raise ValueError("lng ngoài [-180, 180]")
        if self.downsample < 1:
            raise ValueError(f"downsample phải ≥ 1, got {self.downsample}")
        if not 0 <= self.alpha <= 255:
            raise ValueError(f"alpha phải 0-255, got {self.alpha}")
        if not 0 <= self.azimuth < 360:
            raise ValueError(f"azimuth phải [0, 360), got {self.azimuth}")
        if not 0 <= self.altitude <= 90:
            raise ValueError(f"altitude phải [0, 90], got {self.altitude}")


# ─────────────────────────────────────────────────────────────────────────────
# Pure functions — testable không phụ thuộc IO
# ─────────────────────────────────────────────────────────────────────────────

def compute_hillshade(
    z: np.ndarray,
    azimuth:  float = DEFAULT_AZIMUTH,
    altitude: float = DEFAULT_ALTITUDE,
) -> np.ndarray:
    """
    Shaded relief từ elevation grid theo công thức ESRI standard.

    Args:
        z: 2D array (rows, cols) elevation (m)
        azimuth: hướng ánh sáng (độ, 0=Bắc, 90=Đông)
        altitude: góc mặt trời (độ, 0=horizon, 90=overhead)

    Returns:
        Array shape giống z, giá trị ∈ [0, 1].
    """
    az_rad  = np.radians(360.0 - azimuth + 90.0)
    alt_rad = np.radians(altitude)

    dy, dx = np.gradient(z)
    slope  = np.arctan(np.sqrt(dx ** 2 + dy ** 2))
    aspect = np.arctan2(-dy, dx)

    hs = (
        np.sin(alt_rad) * np.cos(slope)
        + np.cos(alt_rad) * np.sin(slope) * np.cos(az_rad - aspect)
    )
    return np.clip(hs, 0.0, 1.0)


def render_rgba(hs: np.ndarray, alpha: int) -> Image.Image:
    """Hillshade [0,1] → RGBA PIL Image. RGB = grayscale, alpha = constant."""
    gray = (hs * 255).astype(np.uint8)
    rgba = np.stack([gray, gray, gray, np.full_like(gray, alpha)], axis=-1)
    return Image.fromarray(rgba, mode="RGBA")


def build_bounds(lats: np.ndarray, lngs: np.ndarray) -> dict[str, float]:
    """Bounds JSON cho frontend — camelCase per API Contract."""
    return {
        "latMin": float(lats.min()),
        "latMax": float(lats.max()),
        "lngMin": float(lngs.min()),
        "lngMax": float(lngs.max()),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Orchestrator + IO
# ─────────────────────────────────────────────────────────────────────────────

def generate(config: HillshadeConfig) -> tuple[Path, Path]:
    """
    Pipeline đầy đủ: load DEM → compute → render → write PNG + JSON.

    Idempotent: ghi đè file hiện có ở output_dir.

    Returns:
        (png_path, bounds_path)
    """
    config.validate()

    # Lazy import để module có thể được test mà không cần DEM tiles thật
    from ml.dem import get_dem

    logger.info(
        "hillshade.start",
        extra={"latMin": config.lat_min, "latMax": config.lat_max,
               "lngMin": config.lng_min, "lngMax": config.lng_max,
               "downsample": config.downsample},
    )

    dem = get_dem()
    if not dem.tiles:
        raise RuntimeError("Không có HGT tile nào được load (kiểm tra DEM_DIR)")

    lats, lngs, z = dem.get_region(
        config.lat_min, config.lat_max,
        config.lng_min, config.lng_max,
        downsample=config.downsample,
    )
    if z.size == 0:
        raise RuntimeError("DEM region rỗng — bbox không overlap tile nào?")

    logger.info(
        "hillshade.dem_loaded",
        extra={"shape": list(z.shape),
               "elevMinM": float(z.min()), "elevMaxM": float(z.max())},
    )

    hs  = compute_hillshade(z, config.azimuth, config.altitude)
    img = render_rgba(hs, config.alpha)

    config.output_dir.mkdir(parents=True, exist_ok=True)
    png_path    = config.output_dir / "hillshade.png"
    bounds_path = config.output_dir / "hillshade_bounds.json"

    img.save(png_path)
    bounds_path.write_text(
        json.dumps(build_bounds(lats, lngs), indent=2),
        encoding="utf-8",
    )

    logger.info(
        "hillshade.done",
        extra={"pngPath": str(png_path), "boundsPath": str(bounds_path),
               "sizePx": list(img.size)},
    )
    return png_path, bounds_path


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def parse_args(argv: list[str] | None = None) -> HillshadeConfig:
    p = argparse.ArgumentParser(
        prog="generate_hillshade",
        description="Tạo PNG shaded relief từ DEM tiles cho overlay Mapbox.",
    )
    p.add_argument("--lat-min",    type=float, default=DEFAULT_LAT_MIN)
    p.add_argument("--lat-max",    type=float, default=DEFAULT_LAT_MAX)
    p.add_argument("--lng-min",    type=float, default=DEFAULT_LNG_MIN)
    p.add_argument("--lng-max",    type=float, default=DEFAULT_LNG_MAX)
    p.add_argument("--downsample", type=int,   default=DEFAULT_DOWNSAMPLE)
    p.add_argument("--azimuth",    type=float, default=DEFAULT_AZIMUTH)
    p.add_argument("--altitude",   type=float, default=DEFAULT_ALTITUDE)
    p.add_argument("--alpha",      type=int,   default=DEFAULT_ALPHA)
    p.add_argument("--output-dir", type=Path,  default=DEFAULT_OUTPUT_DIR)

    args = p.parse_args(argv)
    return HillshadeConfig(
        lat_min    = args.lat_min,
        lat_max    = args.lat_max,
        lng_min    = args.lng_min,
        lng_max    = args.lng_max,
        downsample = args.downsample,
        azimuth    = args.azimuth,
        altitude   = args.altitude,
        alpha      = args.alpha,
        output_dir = args.output_dir,
    )


def main(argv: list[str] | None = None) -> int:
    # Khi chạy standalone (docker exec): tự setup logging cơ bản.
    # Khi import từ FastAPI app: handler đã được core/logging.py setup.
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )

    config = parse_args(argv)
    try:
        generate(config)
    except (RuntimeError, ValueError) as e:
        logger.error("hillshade.failed", extra={"error": str(e)})
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())