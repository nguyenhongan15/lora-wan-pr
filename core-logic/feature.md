# Core Features — Các tính năng cốt lõi

---

## 1. Nhóm tính năng quan sát & tra cứu (Dành cho Persona 5, 6)

- **Heatmap phủ sóng hiện tại:**
  - Hiển thị vùng sóng tốt/kém
  - Hỗ trợ bộ lọc theo SF và ngưỡng RSSI tối thiểu

- **Check my coverage (Tra cứu nhanh):**
  - Cho phép nhập địa chỉ hoặc dùng GPS
  - Trả về kết quả:
    - Có / Không
    - Mạnh / Yếu

- **Giao diện đơn giản (Mobile-first):**
  - Thiết kế tối ưu cho điện thoại
  - Ẩn các thông số kỹ thuật phức tạp

---

## 2. Nhóm tính năng quy hoạch & mô phỏng (Dành cho Persona 1, 2, 7)

- **Coverage simulator (Mô phỏng vùng phủ):**
  - Dự đoán vùng phủ khi đặt gateway giả định
  - Có thể cấu hình:
    - Độ cao anten
    - Công suất phát

- **Optimizer (Tối ưu hóa vị trí):**
  - Sử dụng thuật toán Greedy / Genetic
  - Đề xuất:
    - Số lượng gateway
    - Vị trí tối ưu

- **Trích xuất bảng dự toán (BoQ):**
  - Ước tính số lượng thiết bị

- **So sánh kịch bản (A/B Testing):**
  - So sánh các phương án:
    - Diện tích phủ
    - Chi phí
    - ROI

---

## 3. Nhóm tính năng chuyên sâu & phân tích (Dành cho Persona 2, 3, 4)

- **Báo cáo chuyên nghiệp:**
  - Xuất file:
    - PDF
    - Excel
    - GeoJSON
    - KML

- **Calibration Tool (Hiệu chỉnh ML):**
  - Upload dữ liệu đo thực tế (ground truth)
  - Tái huấn luyện mô hình ML

- **Dự báo quy hoạch đô thị:**
  - Dự đoán thay đổi vùng phủ khi có:
    - Tòa nhà mới
    - Vật cản mới

---

## 4. Nhóm tính năng hệ thống & quản lý (Dành cho Persona 1, 4)

- **RESTful API:**
  - Cung cấp API chuẩn
  - Có tài liệu chi tiết

- **Multi-tenancy:**
  - Tách dữ liệu theo từng khách hàng
  - Đảm bảo bảo mật

- **Gateway Health Dashboard:**
  - Giám sát trạng thái gateway
  - Đảm bảo uptime hệ thống

---

## 5. Tính năng xác thực & tin cậy (Dành cho Persona 1, 2, 7)

- **Thư viện Gateway & Sensor:**
  - Cho phép chọn đúng thông số thiết bị:
    - Công suất phát
    - Độ nhạy thu
    - Anten

- **GPS Verification:**
  - Đánh dấu điểm đo thực tế trên bản đồ
  - So sánh với mô phỏng

---

## 6. Tính năng tương tác vị trí (Dành cho Persona 5)

- **Quét QR Code thiết bị:**
  - Scan QR trên cảm biến
  - Hiển thị vùng phủ xung quanh
  - Hỗ trợ quyết định vị trí lắp đặt

---

## 7. Tính năng tích hợp kỹ thuật (Dành cho Persona 1, 4)

- **Webhooks:**
  - Gửi thông báo tự động khi:
    - Gateway offline
    - Nhiễu sóng tăng

- **Sandbox nghiên cứu:**
  - Cho phép tùy chỉnh:
    - Độ ẩm
    - Mật độ cây
  - Test mô hình ML

---

## 8. Tính năng quản lý dữ liệu (Dành cho Persona 2, 3)

- **Version Control:**
  - Lưu lịch sử thay đổi bản đồ phủ sóng

- **Phân quyền truy cập:**
  - Kiểm soát dữ liệu giữa các khách hàng
  - Quan trọng trong multi-tenancy