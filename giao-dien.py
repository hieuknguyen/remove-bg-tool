"""Qt Quick interface for batch background removal.

Start with giao-dien.bat / giao-dien.command or python giao-dien.py.
The Qt frontend delegates image processing to the existing remove_bg backend.
"""

import sys


# Các chế độ xử lý, khớp với menu của xoa-nen.bat / xoa-nen.command.
# Mục ĐẦU TIÊN là mặc định khi mở giao diện.
#
# Lưu ý về ngưỡng bright_low/bright_high: hai loại ảnh cần thiết lập NGƯỢC NHAU.
#   - Đồ thủy tinh trong suốt trên nền tối: cần ngưỡng THẤP, vì kính trong đặt
#     trên nền đen thì trong ảnh gần như chính là màu đen; ngưỡng cao sẽ khoét
#     thủng cái ly/dĩa thành lỗ chỗ.
#   - Vật thể phát sáng, lấp lánh: cần ngưỡng CAO, nếu không quầng sáng mờ sẽ bị
#     coi là đục và giữ nguyên màu tối -> viền đen bẩn.
MODES = [
    ("Đồ thủy tinh / vật thể trong suốt  (dĩa, ly, chai trên nền tối)",
     dict(model="u2net")),
    ("Chi tiết bay ở trên + đáy sạch  (tia sáng, vật thể tối màu)",
     dict(keep_bright=True, bright_above="auto")),
    ("Giữ chi tiết bay trên toàn ảnh  (nền tối/đơn sắc)",
     dict(keep_bright=True)),
    ("Tự động - tự nhận biết nền đơn sắc",
     dict(auto=True)),
    ("Xóa nền + làm sạch viền",
     dict(clean=True)),
    ("Xóa nền thường  (chỉ dùng AI)",
     dict()),
]

# Model AI. Chon model quan trong hon chinh cac nguong mau, vi neu model da nhin
# ra vat the thi khong can den mat na mau nua.
MODELS = [
    ("(theo chế độ ở trên)", None),
    ("birefnet-general - tốt cho chi tiết bay (tim, tia nước, lấp lánh)", "birefnet-general"),
    ("u2net - nhìn ra đồ thủy tinh trong suốt, nhanh nhất", "u2net"),
    ("isnet-general-use - nhanh, nhưng hay để lại vệt xám", "isnet-general-use"),
    ("birefnet-massive - chất lượng cao, chậm gấp ~50 lần u2net", "birefnet-massive"),
]



def main():
    try:
        from qt_ui import run
    except ModuleNotFoundError as error:
        if error.name and error.name.startswith('PySide6'):
            message = ('Chưa cài thư viện Qt. Mở giao-dien.bat / giao-dien.command '
                       'để tự cài, hoặc chạy: python -m pip install -r requirements-ui.txt')
            if sys.platform == 'win32':
                import ctypes
                ctypes.windll.user32.MessageBoxW(None, message, 'Thiếu thư viện giao diện', 0x10)
            elif sys.stderr is not None:
                print(message, file=sys.stderr)
            return 1
        raise
    return run(MODES, MODELS)


if __name__ == '__main__':
    sys.exit(main())
