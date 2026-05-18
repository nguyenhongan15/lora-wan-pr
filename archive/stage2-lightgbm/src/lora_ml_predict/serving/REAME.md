# serving/ — Khi có người gọi API hỏi
  - server.py — Cổng API FastAPI nhận yêu cầu (POST /residual).
  - ood.py — Kiểm tra điểm hỏi có "lạ" so với data đã học không (cảnh báo nếu ngoài vùng).