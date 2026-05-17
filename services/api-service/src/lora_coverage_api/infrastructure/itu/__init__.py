"""Infrastructure adapters cho Stage 1 ITU-R P.1812 + P.2108.

Hiện chỉ có `crc_covlib_backend.CrcCovlibBackend` (CRC Canada, MIT). Nếu phải
đổi lib (ITU reference C++, pycraf), thêm file mới ở đây và đổi wiring trong
`edge/deps.py` — `application/itu/` không cần biết.
"""
