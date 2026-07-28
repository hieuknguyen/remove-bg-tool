"""
Giao diện đồ họa cho tool xóa nền ảnh.

Chạy:
    python giao-dien.py

Dùng tkinter (có sẵn trong Python, chạy được cả Windows lẫn macOS) nên không
cần cài thêm thư viện nào ngoài những thứ remove_bg.py đã cần.

Toàn bộ phần xử lý ảnh gọi thẳng remove_bg.run_batch() - không chép lại logic,
nên sửa thuật toán ở remove_bg.py là giao diện cũng đổi theo.
"""

import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import remove_bg

HERE = Path(__file__).resolve().parent

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


def human_time(seconds):
    """72 -> '1 phút 12 giây'; 5400 -> '1 giờ 30 phút'."""
    seconds = int(max(0, seconds))
    if seconds < 60:
        return f"{seconds} giây"
    if seconds < 3600:
        return f"{seconds // 60} phút {seconds % 60} giây"
    return f"{seconds // 3600} giờ {(seconds % 3600) // 60} phút"


def open_folder(path):
    """Mở thư mục bằng trình quản lý file của hệ điều hành."""
    path = str(path)
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", path], check=False)
        elif sys.platform.startswith("win"):
            subprocess.run(["explorer", path], check=False)
        else:
            subprocess.run(["xdg-open", path], check=False)
    except Exception:
        pass


class App:
    def __init__(self, root):
        self.root = root
        root.title("Xóa nền ảnh")
        root.minsize(700, 620)

        # Hàng đợi để luồng xử lý gửi tin về luồng giao diện. Bắt buộc phải làm
        # thế này: tkinter KHÔNG an toàn khi gọi từ luồng khác.
        self.q = queue.Queue()
        self.stop_flag = threading.Event()
        self.worker = None
        self.last_output = None
        self.t0 = time.time()

        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(120, self._pump)

    # ------------------------------------------------------------------ giao diện
    def _build(self):
        pad = dict(padx=10, pady=4)
        main = ttk.Frame(self.root, padding=12)
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=1)

        # --- Thư mục ---
        box = ttk.LabelFrame(main, text="Thư mục", padding=8)
        box.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        box.columnconfigure(1, weight=1)

        self.in_var = tk.StringVar(value=str(HERE / "input"))
        self.out_var = tk.StringVar(value=str(HERE / "output"))
        for r, (label, var) in enumerate([("Ảnh gốc:", self.in_var),
                                          ("Lưu ra:", self.out_var)]):
            ttk.Label(box, text=label).grid(row=r, column=0, sticky="w", padx=(0, 6), pady=3)
            ttk.Entry(box, textvariable=var).grid(row=r, column=1, sticky="ew", pady=3)
            ttk.Button(box, text="Chọn...", width=9,
                       command=lambda v=var: self._pick(v)).grid(row=r, column=2, padx=(6, 0))

        self.count_lbl = ttk.Label(box, text="", foreground="#555")
        self.count_lbl.grid(row=2, column=1, sticky="w", pady=(4, 0))
        ttk.Button(box, text="Đếm ảnh", width=9,
                   command=self._count).grid(row=2, column=2, padx=(6, 0), pady=(4, 0))

        # --- Chế độ ---
        box = ttk.LabelFrame(main, text="Chế độ xóa nền", padding=8)
        box.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        self.mode_var = tk.IntVar(value=0)
        for i, (label, _) in enumerate(MODES):
            ttk.Radiobutton(box, text=label, variable=self.mode_var,
                            value=i).grid(row=i, column=0, sticky="w", pady=1)

        row = ttk.Frame(box)
        row.grid(row=len(MODES), column=0, sticky="ew", pady=(8, 0))
        ttk.Label(row, text="Model AI:").pack(side="left")
        self.model_var = tk.StringVar(value=MODELS[0][0])
        ttk.Combobox(row, textvariable=self.model_var, state="readonly", width=58,
                     values=[m[0] for m in MODELS]).pack(side="left", padx=(6, 0))

        # --- Cắt khung ---
        box = ttk.LabelFrame(main, text="Cắt khung", padding=8)
        box.grid(row=2, column=0, sticky="ew", pady=(0, 8))

        self.crop_var = tk.BooleanVar(value=True)
        self.square_var = tk.BooleanVar(value=False)
        self.size_on_var = tk.BooleanVar(value=False)
        self.pad_var = tk.StringVar(value="6")
        self.size_var = tk.StringVar(value="2000x2000")

        row = ttk.Frame(box)
        row.grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(row, text="Cắt sát chủ thể, chừa lề",
                        variable=self.crop_var).pack(side="left")
        ttk.Entry(row, textvariable=self.pad_var, width=5).pack(side="left", padx=(6, 3))
        ttk.Label(row, text="% cạnh lớn của chủ thể").pack(side="left")

        ttk.Checkbutton(box, text="Ép khung vuông",
                        variable=self.square_var).grid(row=1, column=0, sticky="w", pady=(3, 0))

        row = ttk.Frame(box)
        row.grid(row=2, column=0, sticky="w", pady=(3, 0))
        ttk.Checkbutton(row, text="Mọi ảnh cùng kích thước:",
                        variable=self.size_on_var).pack(side="left")
        ttk.Entry(row, textvariable=self.size_var, width=12).pack(side="left", padx=(6, 0))

        # --- Nền + tùy chọn khác ---
        box = ttk.LabelFrame(main, text="Nền kết quả", padding=8)
        box.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        self.bg_var = tk.StringVar(value="trong")
        self.bg_custom = tk.StringVar(value="255,255,255")
        row = ttk.Frame(box)
        row.pack(anchor="w")
        ttk.Radiobutton(row, text="Trong suốt", variable=self.bg_var,
                        value="trong").pack(side="left")
        ttk.Radiobutton(row, text="Trắng", variable=self.bg_var,
                        value="trang").pack(side="left", padx=(12, 0))
        ttk.Radiobutton(row, text="Màu khác:", variable=self.bg_var,
                        value="khac").pack(side="left", padx=(12, 0))
        ttk.Entry(row, textvariable=self.bg_custom, width=12).pack(side="left", padx=(6, 0))

        self.overwrite_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(box, text="Làm lại cả ảnh đã có kết quả "
                                  "(bỏ trống thì bị ngắt giữa chừng có thể chạy tiếp)",
                        variable=self.overwrite_var).pack(anchor="w", pady=(6, 0))

        # --- Nút bấm ---
        row = ttk.Frame(main)
        row.grid(row=4, column=0, sticky="ew", pady=(0, 6))
        self.start_btn = ttk.Button(row, text="Bắt đầu", command=self.start)
        self.start_btn.pack(side="left")
        self.stop_btn = ttk.Button(row, text="Dừng", command=self.stop, state="disabled")
        self.stop_btn.pack(side="left", padx=(8, 0))
        ttk.Button(row, text="Mở thư mục kết quả",
                   command=self.open_out).pack(side="right")

        # --- Tiến độ ---
        self.prog = ttk.Progressbar(main, mode="determinate")
        self.prog.grid(row=5, column=0, sticky="ew")
        self.status = ttk.Label(main, text="Sẵn sàng.")
        self.status.grid(row=6, column=0, sticky="w", pady=(3, 6))

        # --- Nhật ký ---
        box = ttk.LabelFrame(main, text="Nhật ký", padding=6)
        box.grid(row=7, column=0, sticky="nsew")
        main.rowconfigure(7, weight=1)
        box.rowconfigure(0, weight=1)
        box.columnconfigure(0, weight=1)
        self.logbox = tk.Text(box, height=10, wrap="none")
        self.logbox.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(box, orient="vertical", command=self.logbox.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.logbox.configure(yscrollcommand=sb.set, state="disabled")

        self._count()

    def _pick(self, var):
        d = filedialog.askdirectory(initialdir=var.get() or str(HERE))
        if d:
            var.set(d)
            self._count()

    def _count(self):
        try:
            n = len(remove_bg.list_images(self.in_var.get()))
            self.count_lbl.config(text=f"{n} ảnh trong thư mục này")
        except Exception:
            self.count_lbl.config(text="Thư mục không tồn tại")

    def log(self, text):
        self.logbox.configure(state="normal")
        self.logbox.insert("end", text + "\n")
        self.logbox.see("end")
        self.logbox.configure(state="disabled")

    # ------------------------------------------------------------------ chạy
    def _collect_options(self):
        """Gom lựa chọn trên giao diện thành bộ tùy chọn cho run_batch."""
        kw = dict(MODES[self.mode_var.get()][1])
        kw["input"] = self.in_var.get()
        kw["output"] = self.out_var.get()
        kw["overwrite"] = self.overwrite_var.get()

        # Chon model tay thi de len tren model cua che do
        chosen = dict(MODELS).get(self.model_var.get())
        if chosen is not None:
            kw["model"] = chosen

        if self.crop_var.get():
            kw["crop"] = True
            try:
                kw["pad"] = float(self.pad_var.get())
            except ValueError:
                raise ValueError("Lề phải là một con số, ví dụ 6")
            kw["square"] = self.square_var.get()

        if self.size_on_var.get():
            kw["size"] = remove_bg.parse_size(self.size_var.get())

        if self.bg_var.get() == "trang":
            kw["bg"] = (255, 255, 255, 255)
        elif self.bg_var.get() == "khac":
            kw["bg"] = remove_bg.parse_bg(self.bg_custom.get())

        return remove_bg.make_options(**kw)

    def start(self):
        if self.worker is not None and self.worker.is_alive():
            return
        try:
            opts = self._collect_options()
        except Exception as e:
            messagebox.showerror("Tùy chọn chưa đúng", str(e))
            return

        self.stop_flag.clear()
        self.logbox.configure(state="normal")
        self.logbox.delete("1.0", "end")
        self.logbox.configure(state="disabled")
        self.prog.configure(value=0, maximum=100)
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.status.config(text="Đang tải model...")
        self.last_output = opts.output
        self.t0 = time.time()

        def work():
            try:
                res = remove_bg.run_batch(
                    opts,
                    log=lambda m: self.q.put(("log", m)),
                    on_progress=lambda d, t, n: self.q.put(("prog", d, t, n)),
                    should_stop=self.stop_flag.is_set,
                )
                self.q.put(("done", res))
            except Exception as e:
                self.q.put(("error", str(e)))

        # daemon=True: đóng cửa sổ là tiến trình thoát được ngay
        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def stop(self):
        self.stop_flag.set()
        self.stop_btn.config(state="disabled")
        self.status.config(text="Đang dừng sau khi xong ảnh hiện tại...")

    def open_out(self):
        open_folder(self.last_output or self.out_var.get())

    def _pump(self):
        """Lấy tin từ luồng xử lý và cập nhật giao diện. Chạy trên luồng chính."""
        try:
            while True:
                msg = self.q.get_nowait()
                kind = msg[0]

                if kind == "log":
                    self.log(msg[1])

                elif kind == "prog":
                    done, total, _name = msg[1], msg[2], msg[3]
                    self.prog.configure(maximum=total, value=done)
                    # Ước tính thời gian còn lại theo tốc độ trung bình thực tế
                    elapsed = time.time() - self.t0
                    eta = (elapsed / done) * (total - done) if done else 0
                    self.status.config(
                        text=f"{done}/{total} ảnh · còn khoảng {human_time(eta)}")

                elif kind in ("done", "error"):
                    self.start_btn.config(state="normal")
                    self.stop_btn.config(state="disabled")
                    if kind == "error":
                        self.status.config(text="Có lỗi.")
                        self.log(f"[LỖI] {msg[1]}")
                        messagebox.showerror("Lỗi", msg[1])
                    else:
                        r = msg[1]
                        self.status.config(
                            text=f"Xong: {r['ok']} thành công, {r['skipped']} bỏ qua, "
                                 f"{r['failed']} lỗi · {human_time(r['seconds'])}")
                        if not r["stopped"]:
                            self.prog.configure(value=self.prog["maximum"])
        except queue.Empty:
            pass
        self.root.after(120, self._pump)

    def on_close(self):
        if self.worker is not None and self.worker.is_alive():
            if not messagebox.askokcancel("Đang xử lý",
                                          "Đang chạy dở. Đóng cửa sổ để dừng?"):
                return
            self.stop_flag.set()
        self.root.destroy()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
