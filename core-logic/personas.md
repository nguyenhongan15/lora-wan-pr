# Personas khách hàng

## Persona 1: Công ty IoT triển khai dịch vụ (B2B - Startups/SMEs) (Ưu tiên: Cao)

- **Họ là ai:** Các Startup hoặc công ty quy mô vừa và nhỏ đang triển khai giải pháp Smart City, nông nghiệp thông minh hoặc theo dõi phương tiện (tracking).
- **Vấn đề:** Cần lập kế hoạch đặt một số lượng gateway bất kỳ để phủ sóng các khu vực cụ thể (ví dụ: Đà Nẵng) nhằm đáp ứng hợp đồng mới nhưng thiếu công cụ tính toán chính xác.
- **Họ cần:**
  - Xác định vị trí đặt gateway tối ưu theo từng quận
  - Số lượng cần thiết và ước tính chi phí đầu tư
  - Khả năng xuất dữ liệu vùng phủ dưới dạng GIS (GeoJSON, KML)
- **Giá trị từ Machine Learning (ML):** Cung cấp mô phỏng vùng phủ sóng real-time giúp phản hồi khách hàng nhanh hơn trong giai đoạn chào giá.

---

## Persona 2: Nhà khai thác mạng viễn thông (Telco / Network Operator) (Ưu tiên: Cao)

- **Họ là ai:** Các đơn vị lớn như VNPT, Viettel, FPT đang xây dựng hạ tầng mạng LoRa công cộng.
- **Vấn đề:** Quy hoạch mạng quy mô toàn thành phố, yêu cầu độ chính xác cao và tích hợp hệ thống phức tạp.
- **Họ cần:**
  - Công cụ mô phỏng và tối ưu vị trí gateway tự động
  - Tích hợp với hệ thống GIS hiện có
  - Quản lý hàng nghìn điểm kết nối
- **Giá trị từ ML:** Tối ưu vị trí gateway tự động dựa trên địa hình và vật cản, giảm số lượng thiết bị nhưng vẫn đảm bảo chất lượng sóng.

---

## Persona 3: Đơn vị xây dựng Smart City / Chính quyền (B2G) (Ưu tiên: Thấp)

- **Họ là ai:** Sở Thông tin & Truyền thông, Ban quản lý khu công nghệ cao.
- **Vấn đề:** Cần lập đề án phủ sóng IoT cho đô thị thông minh.
- **Họ cần:**
  - Báo cáo PDF chi tiết, có cơ sở khoa học
  - Hình ảnh trực quan để trình bày
  - Công cụ minh bạch để thẩm định năng lực
- **Giá trị từ ML:** Dự báo xu hướng phủ sóng theo quy hoạch đô thị.

---

## Persona 4: Nhà nghiên cứu & Sinh viên kỹ thuật (Academic) (Ưu tiên: Trung bình)

- **Họ là ai:** Sinh viên làm đồ án, phòng lab nghiên cứu LoRaWAN.
- **Vấn đề:** Thiếu dữ liệu thực tế và công cụ mô hình hóa.
- **Họ cần:**
  - API chuẩn (RESTful)
  - Documentation chi tiết
  - Giao diện thử nghiệm nhanh
- **Giá trị từ ML:** Môi trường học tập và đóng góp thuật toán cải tiến.

---

## Persona 5: Khách hàng cuối (Người dùng thiết bị) (Ưu tiên: Cao)

- **Họ là ai:** Nông dân, đội xe vận tải nhỏ.
- **Vấn đề:** Không hiểu kỹ thuật, chỉ cần biết có sóng hay không.
- **Họ cần:**
  - Giao diện bản đồ đơn giản trên điện thoại
  - Kết quả dạng:
    - Có / Không
    - Mạnh / Yếu
- **Giá trị từ ML:** Chuyển thông số kỹ thuật thành trải nghiệm dễ hiểu.

### Ví dụ thiết bị:
- **Nông nghiệp:** Cảm biến độ ẩm, nhiệt độ, pH, hệ thống tưới
- **Vận tải:** GPS tracker cho xe
- **Dân dụng:** Đồng hồ điện/nước, nút khẩn cấp

---

## Persona 6: Nhà cung cấp thiết bị phần cứng (Hardware Vendors) (Ưu tiên: Trung bình)

- **Họ là ai:** Nhà sản xuất hoặc phân phối thiết bị LoRa.
- **Vấn đề:** Cần chứng minh hiệu quả vùng phủ sóng để bán hàng.
- **Họ cần:**
  - Công cụ demo trực quan cho khách hàng
- **Giá trị từ ML:** Tạo heatmap thể hiện ưu điểm thiết bị.

---

## Persona 7: Nhà tích hợp hệ thống (System Integrators - SI) (Ưu tiên: Trung bình)

- **Họ là ai:** Công ty nhận thầu dự án công nghệ.
- **Vấn đề:** Cần khảo sát nhanh để báo giá, tránh tốn chi phí khảo sát thực địa.
- **Họ cần:**
  - Công cụ ước tính số lượng thiết bị
  - Dự toán ngân sách (BoQ)
- **Giá trị từ ML:** Giảm sai số báo giá, tránh lỗ dự án.