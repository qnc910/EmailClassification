## Hướng dẫn cài đặt và Chạy ứng dụng

### 1. Yêu cầu hệ thống trước khi cài đặt:
*   **Docker** & **Docker Compose** đã được cài đặt và kích hoạt (khuyên dùng Docker Desktop trên Windows/macOS).
*   Đảm bảo các cổng kết nối sau trên máy chủ (Host) chưa bị chiếm dụng: `5173` (Frontend), `8000` (Backend), `5433` (PostgreSQL), `3025` (SMTP), `3143` (IMAP), `8081` (Greenmail Dashboard).

### Các bước khởi chạy hệ thống:

**Bước 1: Khởi động các Container dịch vụ**
Mở Terminal/PowerShell tại thư mục gốc của dự án và chạy lệnh:
```bash
docker-compose up --build -d
```
*Lưu ý: Quá trình xây dựng ban đầu có thể mất từ 3-5 phút do cần tải và cấu hình các môi trường Spark, Java, và các thư viện Python/NodeJS.*

**Bước 2: Khởi tạo tài khoản quản trị (Admin Account)**
Sau khi các dịch vụ đã hoạt động ổn định, khởi tạo tài khoản Admin bằng cách thực thi tập lệnh có sẵn bên trong container Backend:
```bash
docker exec -it backend python create_admin.py
```
*Tài khoản Admin mặc định sẽ được tạo là:*
*   **Email**: `admin@gmail.com`
*   **Mật khẩu**: `admin`

---

## 2. Các địa chỉ truy cập Demo

Sau khi chạy thành công, bạn có thể truy cập hệ thống qua các địa chỉ sau:
1.  **Giao diện người dùng (Frontend)**: [http://localhost:5173](http://localhost:5173)
2.  **Tài liệu API của Backend (FastAPI)**: [http://localhost:8000/docs](http://localhost:8000/docs) (Swagger UI để kiểm tra và tương tác trực tiếp với các API).
3.  **Trang quản lý Email ảo (Greenmail Admin)**: [http://localhost:8081](http://localhost:8081) (Xem trạng thái các hòm thư ảo của hệ thống).

---

## 3. Hướng dẫn thực nghiệm & Huấn luyện mô hình (Experiment Guide)

Hệ thống sử dụng mô hình **Naive Bayes** thuộc thư viện Spark MLlib kết hợp với kỹ thuật trích xuất đặc trưng văn bản **TF-IDF**.

### Quy trình huấn luyện mô hình (`spark/train_model.py`):
1.  **Trích xuất dữ liệu**: Lấy tối đa 50,000 dòng dữ liệu email từ cơ sở dữ liệu PostgreSQL.
2.  **Tiền xử lý văn bản**:
    *   Ghép tiêu đề (`subject`) và nội dung (`body`) thành một văn bản thống nhất.
    *   Tách từ (**Tokenizer**).
    *   Loại bỏ từ dừng (**StopWordsRemover**) để làm sạch dữ liệu nhiễu.
3.  **Biến đổi đặc trưng**:
    *   **HashingTF**: Chuyển đổi văn bản thành tần suất xuất hiện của các từ (Term Frequency) với kích thước vector cố định là 10,000 đặc trưng.
    *   **IDF**: Tính toán trọng số tầm quan trọng của từ trong toàn bộ tập văn bản (Inverse Document Frequency).
4.  **Huấn luyện (Model Fitting)**: Khớp dữ liệu vào mô hình **Naive Bayes** phân loại nhị phân (Spam vs Ham).
5.  **Đánh giá mô hình**:
    *   Chia dữ liệu theo tỷ lệ 80% huấn luyện (Train) và 20% kiểm thử (Test).
    *   Đo lường độ chính xác (**Accuracy**) và điểm số **F1-Score** để đảm bảo tính tối ưu của mô hình trước khi lưu trữ đè lên đường dẫn `/opt/bitnami/spark/models/spam_classification_model`.

### Cơ chế Tự động Huấn luyện lại (Auto-retraining):
*   Khi người dùng hoặc admin tải lên tệp tin dữ liệu mẫu dạng CSV (ví dụ dữ liệu Enron Spam) thông qua giao diện Web, **Spark Batch** (`batch_processor.py`) sẽ lập tức phát hiện và xử lý luồng dữ liệu mới.
*   Nếu số lượng mẫu mới trong tệp CSV lớn hơn hoặc bằng **500 mẫu**, hệ thống sẽ tự động gọi luồng huấn luyện lại mô hình từ cơ sở dữ liệu để cập nhật kiến thức mới thu được từ tệp tải lên, tự động cập nhật lại tệp mô hình trên ổ đĩa.
*   Bạn có thể theo dõi tiến trình thực nghiệm và độ chính xác của mô hình thông qua nhật ký hoạt động (Logs) của container Spark:
    ```bash
    docker logs -f spark-batch
    ```

---