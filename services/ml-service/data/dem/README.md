# DEM (Digital Elevation Model) data

SRTM 1 arc-second tiles (~30m resolution) cho khu vực Việt Nam — dùng cho path-loss prediction (terrain profile, line-of-sight, diffraction).

## Files

| File | Bbox | Khu vực |
|------|------|---------|
| `n15e107.hgt` | 15°N–16°N, 107°E–108°E | Quảng Nam – Quảng Ngãi |
| `n15e108.hgt` | 15°N–16°N, 108°E–109°E | Quảng Ngãi (ven biển) |
| `n16e107.hgt` | 16°N–17°N, 107°E–108°E | Thừa Thiên Huế |
| `n16e108.hgt` | 16°N–17°N, 108°E–109°E | Đà Nẵng |

Định dạng: SRTMHGT (binary, 1201×1201 int16 big-endian, mỗi sample 1 arc-second).

## Nguồn

NASA SRTM v3 — tải qua [USGS EarthExplorer](https://earthexplorer.usgs.gov/) hoặc [opentopography.org](https://opentopography.org/).
Public domain.

## Cách dùng

Đọc bằng `rasterio` hoặc `srtm.py`:

```python
import rasterio
with rasterio.open("services/ml-service/data/dem/n16e108.hgt") as src:
    elevation = src.read(1)
```

## Mở rộng

Khi cần phủ thêm tỉnh: download tile theo bbox và đặt cùng folder. Đặt tên theo convention SRTM (`n{lat}e{lng}.hgt`).
