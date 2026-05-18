# training/ — Huấn luyện model
  - data.py — Lấy dữ liệu từ Postgres về.
  - splitter.py / spatial_cv.py — Chia data theo lưới không gian (tránh học vẹt).
  - stage1_recal.py — Hiệu chỉnh lại công thức vật lý trước khi học sai số.
  - objective.py — Định nghĩa "điểm số" để Optuna thử nhiều cấu hình tìm tốt nhất.
  - bounds.py — Ghi nhớ giới hạn feature để phát hiện "điểm lạ" sau này.
  - drift.py — Đo dữ liệu mới có lệch xa data cũ không (PSI).
  - guardrail.py — Chốt chặn vật lý: không cho kết quả phi thực tế.
  - registry_writer.py — Lưu model mới vào database, đánh dấu "đang dùng".
  - retrain.py / orchestrator.py — "Nhạc trưởng" điều phối toàn bộ quy trình huấn luyện.