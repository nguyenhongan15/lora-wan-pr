"""Backend Protocol — phép tính path-loss vật lý cho 1 link TX→RX.

Lý do Protocol tách rời: implementation hiện tại bám crc-covlib (ITU-R P.1812
+ P.2108). Nếu phải đổi lib (port ITU reference, pycraf, sionna...) thì chỉ
file `infrastructure/itu/*_backend.py` đổi; application layer không biết.

GeoPoint + LinkGeometry là abstraction "khác layer, khác abstraction" (Ousterhout
Ch 7): backend KHÔNG thấy domain Target/Gateway — chỉ thấy hình học link. Việc
dịch Target→GeoPoint là việc của Stage1ItuModel.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class GeoPoint:
    latitude: float
    longitude: float


@dataclass(frozen=True, slots=True)
class LinkGeometry:
    """Tất cả tham số hình học mà backend cần để tính basic transmission loss.

    Bundle thành 1 dataclass thay vì 5 args lẻ vì các field này luôn đi cùng
    nhau và validate cùng nhau (cùng frequency, cùng kịch bản). Bundle còn cho
    phép cache key đơn giản nếu cần.

    Antenna heights: AGL (above ground level), KHÔNG phải MSL. Backend tự cộng
    terrain elevation tại tx/rx (DEM lookup).
    """

    tx: GeoPoint
    rx: GeoPoint
    tx_antenna_height_m: float
    rx_antenna_height_m: float
    freq_mhz: float


class Stage1PhysicsBackend(Protocol):
    """Computes basic transmission loss (dB) cho 1 cặp TX→RX.

    "Basic transmission loss" theo ITU-R nomenclature = PL (dB) trước khi trừ
    antenna gains — tức là số dB sẽ trừ vào (P_tx + G_tx + G_rx) để ra Pr.

    What:
      - basic_transmission_loss_db: 1 số PL ngoài trời (P.1812 + P.2108).
      - building_entry_loss_db: 1 số BEL nội suy theo ITU-R P.2109 dùng khi
        terminal nằm trong nhà; trả 0 cho outdoor.
    Hidden: lib choice, percent_time/percent_location config, polarization,
        radio-climatic zone, surface profile method, building type lookup.
    Failure mode: backend tự raise nếu DEM không cover bbox của link. Caller
        (Stage1ItuModel) không bắt — bubble lên orchestrator (HTTP 5xx). Sai
        sót cấu hình DEM = bug ops, không phải user error.
    """

    @property
    def model_version(self) -> str: ...

    def basic_transmission_loss_db(self, link: LinkGeometry) -> float: ...

    def building_entry_loss_db(self, freq_mhz: float, probability_percent: float) -> float:
        """BEL (dB) cho 1 terminal trong nhà, building type = traditional.

        `probability_percent` là persentile của distribution P.2109 (50% = median
        "indoor", 90% = sâu trong nhà). Outdoor caller không gọi method này.
        """
        ...
