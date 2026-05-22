# Báo cáo tiến độ dự án LoRa Coverage

**Ngày báo cáo:** 20/05/2026
**Phạm vi:** Dự đoán vùng phủ sóng mạng LoRaWAN tại Việt Nam (Đà Nẵng và Hải Phòng)

---

## 1. Dự án này làm gì?

Dự án này xây dựng một **trang web + dịch vụ backend** trả lời các câu hỏi đó. Người dùng nhập một điểm trên bản đồ, hệ thống trả về dự đoán chất lượng sóng và mức cấu hình thiết bị phù hợp.

Có hai cách dự đoán được dùng song song:

1. **Tính theo công thức vật lý** (đã hoàn thành) — dùng các mô hình toán học chuẩn quốc tế (ITU-R) để tính sóng truyền qua địa hình, nhà cửa.
2. **Tính theo dữ liệu thực đo + máy học** (đang làm) — dùng số liệu đo thực tế để học và sửa lỗi của công thức vật lý.

---

## 2. Tóm tắt tiến độ tổng thể

| Hạng mục | Mức độ hoàn thành | Ghi chú |
|---|---|---|
| Hệ thống tính toán theo công thức vật lý | **Xong 100%** | Đã dùng được, đã kiểm tra với số liệu thực |
| Cơ sở dữ liệu và backup | **Xong 100%** | PostgreSQL có sao lưu |
| Giao diện web cho người dùng | **Xong ~95%** | Bản đồ, tìm địa chỉ, dự đoán điểm, dự đoán hàng loạt, quản trị cột |
| Tài khoản người dùng (đăng ký, đăng nhập, quên mật khẩu) | **Xong backend 100%, frontend còn 1 phần nhỏ** | Email reset mật khẩu chạy được |
| Mô hình máy học sửa lỗi (Stage 2) | **Đang triển khai** | Có lập trình viên ML mới tiếp nhận; đang viết code |
| Pipeline tính bản đồ "vùng phủ tối ưu" | **Xong 100%** | Tự động tính mỗi cột phủ tới đâu |
| Hướng dẫn triển khai sản phẩm | **Xong 100%** | Có quy trình backup, rollback, monitoring |
| App điện thoại (mobile) | **Chưa làm** | Để dành cho phiên bản sau |
| Bộ thư viện SDK cho lập trình viên khác dùng | **Chưa làm** | Để dành cho phiên bản sau |

**Đánh giá chung:** Dự án đã có thể chạy thực tế (phục vụ người dùng) ở mức cơ bản. Phần đang chờ là **mô hình máy học** để dự đoán chính xác hơn, dự kiến lập trình viên ML sẽ hoàn thành trong thời gian tới.

---

## 3. Chi tiết từng phần

### 3.1. Trang web cho người dùng cuối (đã xong)

Trang web hiện có các tính năng sau, người dùng có thể vào dùng ngay:

- **Bản đồ tương tác** — kéo, zoom, xem vị trí các cột thu phát ở Đà Nẵng và Hải Phòng.
- **Dự đoán một điểm** — gõ địa chỉ hoặc click trên bản đồ, hệ thống báo: cường độ sóng dự đoán, mức cấu hình tiết kiệm pin tối thiểu cần dùng.
- **Dự đoán hàng loạt** — upload danh sách điểm, lấy kết quả cho tất cả cùng lúc.
- **Bản đồ vùng phủ** — tô màu cả khu vực để thấy chỗ nào sóng tốt, chỗ nào yếu.
- **Bản đồ "heatmap" từ dữ liệu đo thực** — hiển thị các điểm đã đo trong thực địa.
- **Tìm địa chỉ** — gõ tên đường, số nhà → ra toạ độ (dùng các dịch vụ Goong, VietMap, Nominatim).
- **Đăng ký / đăng nhập / quên mật khẩu** — có gửi email reset.
- **Trang quản trị cột thu phát** — thêm, sửa, xoá gateway (dành cho admin).

**Công nghệ:** React 19, MapLibre (bản đồ), TailwindCSS (giao diện). Đây là các công nghệ web phổ thông, dễ tìm người bảo trì.

### 3.2. Dịch vụ backend (đã xong)

- **Kiến trúc sạch, có kỷ luật** — code được chia thành 5 tầng (giao diện → ứng dụng → nghiệp vụ → cơ sở dữ liệu → vật lý). Có công cụ tự động kiểm tra để không ai "đi tắt" giữa các tầng.
- **API có tài liệu chuẩn** (file OpenAPI) — bên thứ ba có thể tích hợp dễ dàng.
- **Báo lỗi rõ ràng** — khi có lỗi, người dùng nhận thông báo dễ hiểu thay vì "Error 500".
- **Có cơ chế chống spam** — giới hạn số lần gọi API trong một khoảng thời gian (rate limit).
- **Có cơ chế chống đăng nhập sai liên tục** — khoá tài khoản tạm thời nếu đăng nhập sai quá nhiều lần.

**Các API chính đã chạy được:**
- Dự đoán vùng phủ tại một điểm
- Danh sách cột thu phát
- Đăng ký / đăng nhập / refresh phiên đăng nhập / đổi mật khẩu / quên mật khẩu
- Nhận dữ liệu đo thực tế từ thiết bị (qua ChirpStack — hệ thống quản lý mạng LoRa phổ biến)

### 3.3. Mô hình dự đoán sóng theo vật lý (đã xong)

Đây là phần lõi tính toán. Ban đầu dự án dùng công thức đơn giản (log-distance), nhưng chính xác kém. Tháng 5/2026 đã **chuyển sang dùng tiêu chuẩn quốc tế ITU-R P.1812 + P.2108** — đây là chuẩn của Liên minh Viễn thông Quốc tế dùng cho dự đoán sóng vô tuyến.

Mô hình tính được:
- Sóng đi qua đồi núi, đồi thấp.
- Sóng bị toà nhà che chắn (dùng dữ liệu OpenStreetMap về chiều cao nhà).
- Sai số đo thực tế: trước khi tính nhà cửa **lệch khoảng 11.65 dB** (dự đoán sóng mạnh hơn thực tế), sau khi tính nhà cửa **sai số gần như bằng 0** trung bình.

### 3.4. Mô hình máy học sửa lỗi (đang triển khai)

Mô hình vật lý đã tốt, nhưng vẫn có sai số ngẫu nhiên do nhiều yếu tố nhỏ (cây cối, vật liệu nhà, hướng anten...). Mô hình máy học sẽ học từ dữ liệu đo thực tế để "đoán" thêm phần sai số đó.

**Trạng thái:**
- Lập trình viên ML mới đang tiếp nhận và xây dịch vụ chính thức (`ml-service`). Tuần qua đã làm xong:
  - Khung dịch vụ HTTP để backend gọi vào.
  - Bảo mật bằng token.
  - Cơ chế "an toàn khi hỏng": nếu mô hình ML chưa sẵn sàng, backend vẫn trả kết quả từ mô hình vật lý (không bị treo).

**Còn phải làm:**
- Train mô hình ML chính thức trên dữ liệu Đà Nẵng đầy đủ.
- Tích hợp vào hệ thống Docker để chạy tự động.
- Kiểm tra end-to-end (chạy thử toàn bộ luồng).

### 3.5. Bản đồ "vùng phủ tối ưu" (đã xong)

Mỗi cột thu phát có nhiều mức cấu hình "tiết kiệm pin" khác nhau (gọi là Spreading Factor — SF7 đến SF12). Càng cao càng đi xa nhưng càng tốn pin và càng chậm.

Hệ thống tự động tính trước cho mỗi điểm trong thành phố: **mức SF thấp nhất** mà điểm đó vẫn liên lạc được. Kết quả lưu thành bản đồ raster, trang web hiển thị bằng các vùng màu.

Tính năng này giúp người triển khai biết: "Nếu tôi đặt thiết bị ở phường X, tôi nên cấu hình mức SF nào để vừa tiết kiệm pin vừa đảm bảo kết nối."

### 3.6. Cơ sở dữ liệu (đã xong)

- Dùng **PostgreSQL 17** kèm hai phần mở rộng:
  - **PostGIS** — xử lý dữ liệu không gian (toạ độ, vùng, khoảng cách).
  - **TimescaleDB** — xử lý dữ liệu theo thời gian (số liệu đo từ thiết bị).
- Đã có **9 phiên bản schema** (migration), nâng cấp tự động khi deploy.
- Đã có **dữ liệu mẫu**: 11 cột ở Đà Nẵng + 2 cột ở Hải Phòng.
- Có **script sao lưu tự động** trước khi triển khai phiên bản mới.

### 3.7. Pipeline dữ liệu (đã xong)

Các script tự động dùng để chuẩn bị dữ liệu, gồm:

- Tải và xử lý dữ liệu địa hình (DEM — bản đồ độ cao).
- Tạo "bản đồ bề mặt" (DSM) bằng cách cộng độ cao địa hình + độ cao nhà từ OpenStreetMap.
- Nhập dữ liệu đo thực tế từ thiết bị đã đi khảo sát ngoài thực địa.
- Tính trước bản đồ vùng phủ cho từng cột.
- Kiểm tra (validation) — so sánh dự đoán với số liệu thực để đo sai số.

### 3.8. Quy trình triển khai (đã xong)

Dự án đã có quy trình triển khai chuyên nghiệp:

- **Docker Compose** — một lệnh `docker compose up` chạy toàn bộ hệ thống.
- **Đánh dấu phiên bản theo Git** — mỗi lần build có ID riêng, dễ rollback nếu lỗi.
- **Checklist 9 điểm trước khi deploy** — bao gồm: backup database, kiểm tra log, kiểm tra SMTP, kiểm tra rate limit, smoke test...
- **Log rotation** — log tự động xoay, không đầy đĩa.
- **Tài liệu DEPLOY.md** — hướng dẫn từng bước cho người triển khai.

### 3.9. Kiểm thử (đã có cơ bản)

- **13 file test tự động** trong backend, chia 4 tầng (domain, application, integration, unit).
- Mỗi lần commit code, **GitHub Actions** chạy tự động: kiểm tra format, kiểm tra type, kiểm tra kiến trúc, build Docker, test frontend.
- Đảm bảo code mới không phá hỏng tính năng cũ.

---

## 4. Phần chưa làm (để dành phiên bản sau)

| Hạng mục | Lý do để lại |
|---|---|
| **App điện thoại** | Web đã dùng được trên mobile browser; app native không phải ưu tiên giai đoạn đầu |
| **Tile server** (phục vụ bản đồ tĩnh tốc độ cao) | Tải hiện tại nhẹ, dùng API trả về bản đồ vẫn ổn |
| **Worker service** (xử lý job nền) | Chưa có job lớn cần chạy nền |
| **SDK cho lập trình viên** (JavaScript, Go, Python) | Bên thứ ba có thể dùng API trực tiếp; SDK chỉ là phần "đường ngọt" |
| **Site tài liệu công khai** | Đang dùng README và file docs trong repo |
| **Hải Phòng — mô hình ML đầy đủ** | Hải Phòng chỉ có 2 cột + dữ liệu ít → chưa đủ huấn luyện ML; tạm validation only |

---

### Rủi ro / điểm cần theo dõi

1. **Phụ thuộc lập trình viên ML mới** — Stage 2 chưa xong, nếu chậm sẽ ảnh hưởng độ chính xác cuối cùng. Tuy nhiên hệ thống đã có fallback: nếu ML chưa sẵn sàng, vẫn dùng được mô hình vật lý.
2. **Hải Phòng dữ liệu ít** — phần ML cho Hải Phòng có thể không đạt độ chính xác như Đà Nẵng. Cần thông báo rõ với người dùng cuối.
4. **crc-covlib (thư viện tính ITU-R)** chỉ chạy trên Windows + Linux x86_64 — không chạy trên máy Mac M1/M2. Lập trình viên dùng Mac phải dev qua Docker.

---

## 5. Việc cần làm tiếp

**Ngắn hạn (1–2 tuần):**
1. Lập trình viên ML hoàn thiện và đóng gói mô hình Stage 2.
2. Thêm `ml-service` vào docker-compose, chạy thử end-to-end.

**Trung hạn (1–2 tháng):**
1. Test với người dùng thật, thu phản hồi UX.
2. Đo lại sai số sau khi có Stage 2, so sánh với mục tiêu (ví dụ ≤ 5 dB RMSE).
3. Sinh SDK từ file OpenAPI để bên thứ ba dễ tích hợp.

**Dài hạn:**
1. Mở rộng sang các tỉnh khác (sau khi xong AS923-2 cho Việt Nam).
2. App điện thoại nếu có nhu cầu thực địa khảo sát ngoài hiện trường.
3. Worker service nếu có job xử lý nặng (ví dụ tính trước cả nước).

---

## 7. Kết luận

Dự án đã đi qua giai đoạn khó nhất — **xây nền tảng, backend, frontend, mô hình vật lý đều đã chạy được**. Phần còn lại chủ yếu là **bổ sung mô hình máy học** để nâng độ chính xác, và **đánh bóng** (UX, tài liệu, SDK).

Theo đánh giá, hệ thống **có thể bắt đầu phục vụ người dùng pilot ngay bây giờ** ở mức "dự đoán theo vật lý", và **nâng lên dự đoán có ML** trong vài tuần tới khi Stage 2 xong.
