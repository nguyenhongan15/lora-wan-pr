from __future__ import annotations
import os
import glob
import numpy as np
from pathlib import Path
from functools import lru_cache

# Thư mục chứa file HGT — tính từ backend/
DEM_DIR = Path(__file__).parent.parent.parent / "DEM"

SRTM1_SIZE = 3601   # 1 arc-second
SRTM3_SIZE = 1201   # 3 arc-second


class HGTTile:
    """Đại diện cho một tile HGT đơn."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        name = self.path.stem.lower()           # vd: n16e108
        self.lat0 = int(name[1:3])              # góc dưới-trái
        self.lng0 = int(name[4:7])
        if name[0] == "s": self.lat0 *= -1
        if name[3] == "w": self.lng0 *= -1

        raw = np.fromfile(str(self.path), dtype=">i2")
        size = SRTM1_SIZE if raw.size == SRTM1_SIZE ** 2 else SRTM3_SIZE
        self.size = size
        # shape: (rows, cols) — hàng đầu = lat cao nhất
        self.data = raw.reshape(size, size).astype(np.float32)
        self.data[self.data == -32768] = np.nan   # no-data → NaN
        self.res = 1.0 / (size - 1)               # degrees per pixel

    def contains(self, lat: float, lng: float) -> bool:
        return self.lat0 <= lat < self.lat0 + 1 and self.lng0 <= lng < self.lng0 + 1

    def get_elevation(self, lat: float, lng: float) -> float:
        """Bilinear interpolation để lấy độ cao tại (lat, lng)."""
        row_f = (self.lat0 + 1 - lat) / self.res
        col_f = (lng - self.lng0)       / self.res

        r0, c0 = int(row_f), int(col_f)
        r1 = min(r0 + 1, self.size - 1)
        c1 = min(c0 + 1, self.size - 1)
        dr, dc = row_f - r0, col_f - c0

        z00 = self.data[r0, c0]
        z01 = self.data[r0, c1]
        z10 = self.data[r1, c0]
        z11 = self.data[r1, c1]

        vals = [z00, z01, z10, z11]
        if all(np.isnan(v) for v in vals):
            return 0.0

        # Thay NaN bằng mean của các giá trị hợp lệ
        mean = np.nanmean(vals)
        z00 = mean if np.isnan(z00) else z00
        z01 = mean if np.isnan(z01) else z01
        z10 = mean if np.isnan(z10) else z10
        z11 = mean if np.isnan(z11) else z11

        return float(
            z00 * (1 - dr) * (1 - dc) +
            z01 * (1 - dr) * dc       +
            z10 * dr       * (1 - dc) +
            z11 * dr       * dc
        )

    def get_array_region(
        self,
        lat_min: float, lat_max: float,
        lng_min: float, lng_max: float,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Trả về (lats, lngs, elevations) cho một vùng con của tile.
        Dùng để tạo hillshade.
        """
        r_max = int((self.lat0 + 1 - lat_min) / self.res)
        r_min = int((self.lat0 + 1 - lat_max) / self.res)
        c_min = int((lng_min - self.lng0) / self.res)
        c_max = int((lng_max - self.lng0) / self.res)

        r_min = max(0, r_min); r_max = min(self.size - 1, r_max)
        c_min = max(0, c_min); c_max = min(self.size - 1, c_max)

        sub = self.data[r_min:r_max + 1, c_min:c_max + 1]
        lats = self.lat0 + 1 - np.arange(r_min, r_max + 1) * self.res
        lngs = self.lng0     + np.arange(c_min, c_max + 1) * self.res
        return lats, lngs, sub


class DEMReader:
    """Quản lý nhiều tile HGT, tự chọn tile phù hợp theo tọa độ."""

    def __init__(self, dem_dir: str | Path = DEM_DIR):
        self.tiles: list[HGTTile] = []
        dem_dir = Path(dem_dir)
        for p in sorted(dem_dir.glob("*.hgt")):
            try:
                self.tiles.append(HGTTile(p))
                print(f"[DEM] Loaded {p.name}")
            except Exception as e:
                print(f"[DEM] Skip {p.name}: {e}")

    def get_elevation(self, lat: float, lng: float) -> float:
        """Trả về độ cao (m) tại tọa độ. Trả 0 nếu không có tile."""
        for tile in self.tiles:
            if tile.contains(lat, lng):
                return tile.get_elevation(lat, lng)
        return 0.0

    def get_elevations_batch(
        self, lats: list[float], lngs: list[float]
    ) -> np.ndarray:
        """Lấy độ cao cho nhiều điểm cùng lúc (vectorised per tile)."""
        result = np.zeros(len(lats), dtype=np.float32)
        for i, (la, lo) in enumerate(zip(lats, lngs)):
            result[i] = self.get_elevation(la, lo)
        return result

    def get_region(
        self,
        lat_min: float, lat_max: float,
        lng_min: float, lng_max: float,
        downsample: int = 1,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Lấy elevation grid cho vùng bbox, merge tất cả tile liên quan.
        downsample=3 → ~90m resolution (đủ nhanh cho hillshade).

        Cách hoạt động:
          1. Tạo sẵn output grid với kích thước xác định từ bbox
          2. Với mỗi tile overlap, tính chính xác vị trí row/col trong
             output grid rồi copy trực tiếp — không dùng searchsorted
             để tránh lệch index khi tile chung biên.
        """
        if not self.tiles:
            return np.array([]), np.array([]), np.array([[]])

        # Dùng resolution của tile đầu tiên làm chuẩn
        res = self.tiles[0].res * downsample   # degrees/pixel sau downsample

        # Tạo output grid (lat giảm dần từ max → min, lon tăng dần)
        out_lats = np.arange(lat_max, lat_min, -res)
        out_lngs = np.arange(lng_min, lng_max,  res)
        nrows, ncols = len(out_lats), len(out_lngs)

        if nrows == 0 or ncols == 0:
            return np.array([]), np.array([]), np.array([[]])

        grid = np.full((nrows, ncols), np.nan, dtype=np.float32)

        for tile in self.tiles:
            # Kiểm tra tile có overlap với bbox không
            if tile.lat0 >= lat_max or tile.lat0 + 1 <= lat_min:
                continue
            if tile.lng0 >= lng_max or tile.lng0 + 1 <= lng_min:
                continue

            # Vùng cắt: phần overlap giữa tile và bbox
            la_min = max(lat_min, float(tile.lat0))
            la_max = min(lat_max, float(tile.lat0 + 1))
            lo_min = max(lng_min, float(tile.lng0))
            lo_max = min(lng_max, float(tile.lng0 + 1))

            # Lấy sub-array từ tile
            tile_lats, tile_lngs, z = tile.get_array_region(
                la_min, la_max, lo_min, lo_max
            )
            if z.size == 0:
                continue

            # Tính row/col trong output grid tương ứng với tile_lats/tile_lngs
            # Dùng phép tính tuyến tính thay searchsorted → chính xác hơn
            r0 = int(round((lat_max - tile_lats[0])  / res))
            c0 = int(round((tile_lngs[0] - lng_min)  / res))

            # Kích thước sau downsample
            z_ds = z[::downsample, ::downsample]
            nr, nc = z_ds.shape

            # Clamp vào output grid
            r_end = min(r0 + nr, nrows)
            c_end = min(c0 + nc, ncols)
            r_src = r_end - r0
            c_src = c_end - c0
            r0c   = max(r0, 0)
            c0c   = max(c0, 0)

            # Xử lý trường hợp r0/c0 âm (tile vượt biên trái/trên)
            z_r0 = max(0, -r0)
            z_c0 = max(0, -c0)

            try:
                grid[r0c:r_end, c0c:c_end] = z_ds[z_r0:r_src, z_c0:c_src]
            except ValueError:
                # Kích thước không khớp do làm tròn — bỏ qua hàng/cột lẻ
                gr = r_end - r0c
                gc = c_end - c0c
                sz = z_ds[z_r0:z_r0+gr, z_c0:z_c0+gc]
                grid[r0c:r0c+sz.shape[0], c0c:c0c+sz.shape[1]] = sz

            print(f"[DEM] Merged tile {tile.path.name} → "
                  f"rows {r0c}:{r_end}, cols {c0c}:{c_end}")

        # Fill NaN bằng giá trị lân cận (nearest) thay vì global mean
        # để tránh vùng biển bị fill lên cao
        nan_mask = np.isnan(grid)
        if nan_mask.all():
            return np.array([]), np.array([]), np.array([[]])
        if nan_mask.any():
            from scipy.ndimage import distance_transform_edt
            _, idx = distance_transform_edt(nan_mask, return_indices=True)
            grid[nan_mask] = grid[idx[0][nan_mask], idx[1][nan_mask]]

        return out_lats, out_lngs, grid


# Singleton — load 1 lần khi import
_dem: DEMReader | None = None

def get_dem() -> DEMReader:
    global _dem
    if _dem is None:
        _dem = DEMReader()
    return _dem