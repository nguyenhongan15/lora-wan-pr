# scripts/
  - build_urbanization_grid.py — Chạy 1 lần (offline) để tạo bản đồ "độ đô thị hóa" từ dữ liệu OpenStreetMap (file PBF) → xuất ra file GeoTIFF. Đây là   nguyên liệu mà features/osm.py sẽ tra cứu sau này.                                                                                                 
  - train_stage2.py — Lệnh huấn luyện model Stage 2. Gõ python -m scripts.train_stage2 --promote để train xong và đưa model mới lên "đang dùng"       
  (promote). Có cờ --dry-run để chạy thử mà không lưu. Bên trong nó gọi training/orchestrator.py.                                                     
  - eval_stage2_holdout.py — Lệnh chấm điểm model: so sánh chỉ dùng công thức vật lý (Stage 1) với việc thêm cả model học máy (Stage 1+2) trên tập
  test riêng → xem ML có thực sự cải thiện không.