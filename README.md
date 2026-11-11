# Xóa nền ảnh

Mở `giao-dien.bat` trên Windows hoặc `giao-dien.command` trên macOS.
Xử lý bằng dòng lệnh: `python remove_bg.py -m u2net --crop`.

## Giao diện

Giao diện desktop dùng **PySide6 / Qt Quick**, phong cách glassmorphism xanh–tím
pastel, panel kính mờ, nút chuyển màu và bố cục lấy cảm hứng từ ứng dụng mobile.
Qt Quick vẽ bằng scene graph, bo góc có khử răng cưa và tự xử lý tỉ lệ màn hình
DPI cao; hover, chuyển trạng thái và thanh tiến độ được cập nhật riêng.
Hiệu ứng kính lấy mẫu nền rồi làm mờ bằng shader, không dựng lại ảnh toàn cửa sổ
bằng Pillow mỗi lần rê chuột. Cửa sổ mặc định 16:9.
Vùng **Xem trước** chuyển giữa ảnh gốc và PNG kết quả; ảnh trong suốt hiển thị
trên nền ô caro. Chọn model ở tab **Chế độ xử lý**, chỉnh khung hình và nền ở
tab **Tùy chỉnh**. Mục **Nhật ký** ở thanh bên hiển thị đầy đủ thông tin xử lý.
Giao diện tự thích ứng khi chia cửa sổ **1/2 hoặc 1/4 màn hình** bằng Windows Snap:
thanh bên thu gọn thành nút **Ảnh / Log** trên đầu; cửa sổ hẹp chuyển các panel
thành một cột. Khi cửa sổ thấp, cuộn vùng nội dung để xem đủ thiết lập. Thanh
**Xóa nền / Dừng / Kết quả** luôn nằm ở cuối cửa sổ, kèm trạng thái và tiến độ.
Ở kích thước 1/4 màn hình, ẩn tiêu đề studio, vùng xem trước và thư mục ảnh;
panel thiết lập dùng toàn bộ vùng nội dung và cuộn riêng nếu cần. Các phần đã ẩn
tự hiện lại khi phóng lớn cửa sổ; thư mục đang chọn được giữ nguyên.
Sáu chế độ xử lý dùng nút gọn (ba cột khi đủ chiều ngang), model nằm ngay bên
dưới. Nút **Thư mục** trên đầu mở lựa chọn ảnh gốc và nơi lưu, không cần phóng
lớn cửa sổ. Rê chuột lên chế độ để xem mô tả đầy đủ.
Kích thước tối thiểu là 360 × 260 theo đơn vị hiển thị của Qt.
Ảnh xem trước được giải mã ở luồng riêng và giới hạn kích thước để tránh làm
chậm thao tác.
File mở ứng dụng tự cài Qt nếu môi trường cũ chưa có. Có thể cài riêng bằng
`python -m pip install -r requirements-ui.txt`. Giao diện chính không cần Tkinter.

## Tự động dùng GPU

Ứng dụng nhận diện phần cứng khi khởi động và mặc định dùng `--device auto`:

- NVIDIA tương thích CUDA 12.8+, kiến trúc Turing trở lên: CUDA.
- GPU hỗ trợ DirectX 12 trên Windows (AMD, Intel, NVIDIA): DirectML khi không có CUDA phù hợp.
- macOS: ưu tiên CoreML với GPU khi model và bộ chạy hỗ trợ.
- Linux: NVIDIA CUDA; ROCm được ưu tiên nếu runtime ROCm đã được cài sẵn.
- Không có GPU tương thích, thiếu driver hoặc GPU gặp lỗi: tự chuyển về CPU, ghi rõ trong nhật ký.

Lần đầu trên Windows/NVIDIA Linux, ứng dụng tự tải thư viện GPU vào `.gpu-runtime/`
trong project. Cần kết nối mạng; bộ chạy model CUDA tải khoảng 2 GB và bộ xử lý
ảnh CUDA tải thêm khoảng 800 MB trên Windows. Các lần sau tái sử dụng
thư viện đã cài. Thư viện GPU được tách khỏi bộ chạy CPU nên không ghi đè môi trường CPU.
Trong giao diện, nhãn ở góc trên và nhật ký cho biết bộ xử lý đang dùng sau khi tải model.

Trên NVIDIA CUDA, GPU chạy chuẩn bị ảnh đầu vào, suy luận model AI, tạo/đổi kích
thước mặt nạ, nhận diện nền đơn sắc, giữ chi tiết sáng, khử màu nền, làm sạch viền,
cắt khung, đổi kích thước, ghép nền và alpha matting nếu bật. Các model trong menu
giao diện đều có bộ xử lý ảnh CUDA. Ảnh chỉ đưa lên GPU một lần và tải kết quả
về khi lưu PNG. CPU quản lý file, giải mã ảnh đầu vào, mã hóa PNG, giao diện và
các quyết định điều khiển; không thể chuyển toàn bộ ứng dụng sang GPU.

DirectML/CoreML/ROCm hiện tăng tốc suy luận AI; các bước chỉnh ảnh vẫn dùng CPU.
Nếu bộ xử lý ảnh CUDA chưa cài được, ứng dụng ghi rõ GPU chỉ chạy AI và CPU chỉnh ảnh.
`--device gpu` yêu cầu cả model AI lẫn bộ xử lý ảnh CUDA, báo lỗi nếu chưa sẵn sàng.
`--device cpu` dùng toàn bộ luồng xử lý CPU cũ. Cách làm tròn/resample và cập nhật
alpha matting song song trên GPU có thể tạo khác biệt nhỏ ở viền so với CPU;
GPU không âm thầm đổi sang model khác hoặc giảm độ phân giải của model.

Máy ít VRAM có thể chuyển sang CPU khi chọn model quá lớn.
CUDA được phép dùng bộ nhớ GPU còn khả dụng, không bị giới hạn cố định ở 75% VRAM.
Nếu không cấp phát đủ bộ nhớ, ứng dụng giải phóng session GPU và thử lại cùng ảnh,
cùng model trên CPU; các ảnh còn lại của lượt đó tiếp tục dùng CPU.
Nếu cuDNN không tìm được thuật toán phù hợp, ứng dụng thử cấu hình CUDA khác
cho cùng model trước khi chuyển về CPU. Việc thử lại chỉ diễn ra một lần mỗi lượt xử lý.
Ứng dụng ưu tiên cấu hình cuDNN tương thích và nhớ cấu hình đã suy luận thành công
theo GPU, model và phiên bản thư viện trong `.gpu-runtime/profiles/`.
Phần chỉnh ảnh CuPy dùng các kernel CUDA gốc thay cho nhánh CUB có thể lỗi biên dịch
`__nv_fp8_e8m0`; các phép tính vẫn chạy trên GPU, không dùng FP8 hay chuyển về CPU.

Có thể chuẩn bị thư viện trước bằng `python gpu_runtime.py`.
Dùng `--device cpu` để chạy CPU hoặc `--device gpu` để yêu cầu GPU và báo lỗi nếu không khả dụng.

Ứng dụng nhận diện lại phần cứng khi mở trên máy khác. Không lưu cố định tên GPU
của máy hiện tại; hãy cài môi trường Python trên máy mới và mở ứng dụng như bình thường.
Driver GPU cần có sẵn trên máy; thư viện xử lý GPU được ứng dụng tự chuẩn bị.

## Cài lần đầu

```text
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Trên macOS/Linux, dùng `.venv/bin/python` thay cho `.venv\Scripts\python.exe`.
