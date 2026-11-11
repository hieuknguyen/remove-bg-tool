"""
Xóa nền ảnh hàng loạt (batch) bằng AI - chất lượng cao dùng model BiRefNet.
Tương đương remove.bg nhưng chạy offline, miễn phí, không giới hạn.

Cách dùng:
    # Xóa nền tất cả ảnh trong thư mục 'input', lưu ra 'output'
    python remove_bg.py

    # Chỉ định thư mục vào / ra
    python remove_bg.py -i "D:\\anh_goc" -o "D:\\anh_da_xoa_nen"

    # Đổi model (u2net nhanh hơn, birefnet-general chất lượng cao nhất)
    python remove_bg.py -m u2net

    # Thêm nền màu trắng thay vì trong suốt
    python remove_bg.py --bg 255,255,255

    # Còn sót bóng đổ / phản chiếu dính vào đáy vật thể -> cắt thẳng phần dưới
    python remove_bg.py --auto --cut-below 96.5

    # Vật thể TỐI MÀU có tia sáng bay lên trên: vớt chi tiết bay ở phía trên,
    # phần thân và chân giao hẳn cho AI -> đáy sạch, tia sáng vẫn còn
    python remove_bg.py --keep-bright --bright-above auto --crop

    # Cắt sát chủ thể nhưng chừa lề 6% -> cả loạt ảnh khung đều nhau
    python remove_bg.py --auto --crop

    # Cắt sát + khung vuông + mọi ảnh ra đúng 2000x2000
    python remove_bg.py --auto --crop --square --size 2000x2000

Lần chạy đầu tiên sẽ tự tải model về (~ vài trăm MB), các lần sau chạy ngay.
"""

import argparse
import gc
import sys
import time
from pathlib import Path

# Ép console in được tiếng Việt (tránh lỗi cp1258 trên Windows)
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np
from PIL import Image, ImageFilter, ImageOps
from gpu_runtime import (activate_runtime, runtime_info, cuda_algorithm_for,
                         remember_cuda_algorithm)

# Executable entry points prepare GPU dependencies before ONNX loads its DLLs.
_bootstrap = argparse.ArgumentParser(add_help=False)
_bootstrap.add_argument("--device", choices=("auto", "gpu", "cpu"), default="auto")
_requested, _ = _bootstrap.parse_known_args() if __name__ == "__main__" else (argparse.Namespace(device="auto"), [])
activate_runtime(install=__name__ == "__main__" and _requested.device != "cpu"
                 and not any(flag in sys.argv for flag in ("-h", "--help")))
import onnxruntime as ort
from rembg import new_session, remove

# Các định dạng ảnh đầu vào được hỗ trợ
SUPPORTED = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif"}


GPU_PROVIDERS = ("CUDAExecutionProvider", "DmlExecutionProvider",
                 "ROCMExecutionProvider", "CoreMLExecutionProvider")


def device_label(provider=None):
    info = runtime_info()
    if provider == "CUDAExecutionProvider":
        name = info["name"].replace("GeForce ", "").replace(" with Max-Q Design", "")
        return f"GPU · {name}"
    if provider in GPU_PROVIDERS:
        return {"DmlExecutionProvider": "GPU · DirectML", "ROCMExecutionProvider": "GPU · AMD ROCm",
                "CoreMLExecutionProvider": "GPU · Apple CoreML"}[provider]
    if provider == "CPUExecutionProvider":
        return "CPU · Đang xử lý"
    if any(provider in ort.get_available_providers() for provider in GPU_PROVIDERS):
        return "Tự động · Ưu tiên GPU"
    return "CPU · Xử lý trên thiết bị"


def create_inference_session(model, device="auto", log=print, on_device=None, sess_opts=None,
                             cuda_algorithm=None, cpu_fallback=False):
    """Prefer an initialized GPU provider, and report any CPU fallback explicitly."""
    available = ort.get_available_providers()
    candidates = [] if device == "cpu" else [provider for provider in GPU_PROVIDERS if provider in available]
    info = runtime_info()
    if device != "cpu":
        for note in info.get("notes", []):
            log(note)
    for provider in candidates:
        try:
            options = sess_opts if sess_opts is not None else ort.SessionOptions()
            provider_options = {}
            if provider == "CUDAExecutionProvider":
                if cuda_algorithm is None:
                    cuda_algorithm = cuda_algorithm_for(model, ort.__version__)
                ort.preload_dlls(directory="")
                provider_options = {"device_id": info.get("device_id", 0),
                                    # Start with the remembered working algorithm, or
                                    # cuDNN fallback engines on a new GPU/model pair.
                                    "cudnn_conv_algo_search": cuda_algorithm,
                                    "cudnn_conv_use_max_workspace": "0",
                                    "arena_extend_strategy": "kSameAsRequested"}
                # Let CUDA allocate from available VRAM. A fixed 75% arena limit
                # rejected larger models even while the GPU still had free memory.
            elif provider == "DmlExecutionProvider":
                options.enable_mem_pattern = False
                options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
                provider_options = {"device_id": 0}
            elif provider == "CoreMLExecutionProvider":
                provider_options = {"MLComputeUnits": "CPUAndGPU"}
            if sess_opts is None:
                options.intra_op_num_threads = 2
                options.inter_op_num_threads = 1
            session = new_session(model, sess_opts=options,
                                  providers=[(provider, provider_options), "CPUExecutionProvider"])
            if provider not in session.inner_session.get_providers():
                del session
                log(f"Không khởi tạo được {provider}; đang thử bộ xử lý tiếp theo.")
                continue
            session.inner_session.disable_fallback()
            if provider == "CUDAExecutionProvider":
                session._cuda_algorithm = cuda_algorithm
                saved = [False]
                def remember(model=model, algorithm=cuda_algorithm, saved=saved):
                    if not saved[0]:
                        remember_cuda_algorithm(model, ort.__version__, algorithm)
                        saved[0] = True
                session._on_cuda_success = remember
            label = device_label(provider)
            log(f"Suy luận AI: {label} ({provider}).")
            if on_device is not None:
                on_device(label)
            return session, provider
        except Exception as error:
            log(f"GPU {provider} chưa dùng được: {error}")
    if device == "gpu":
        raise RuntimeError("Không có GPU tương thích đang hoạt động. Thử --device auto để cho phép dùng CPU.")
    if device == "auto":
        log("Chuyển sang CPU vì không có GPU sẵn sàng cho model này.")
    elif cpu_fallback:
        log("Suy luận AI: CPU (dự phòng sau lỗi GPU).")
    else:
        log("Suy luận AI: CPU (được chọn thủ công).")
    session = new_session(model, sess_opts=sess_opts, providers=["CPUExecutionProvider"])
    if on_device is not None:
        on_device("CPU · Dự phòng" if device == "auto" or cpu_fallback
                  else device_label("CPUExecutionProvider"))
    return session, "CPUExecutionProvider"


def is_memory_error(error):
    """Recognize allocator failures even when the message omits the GPU name."""
    message = str(error).lower()
    if "available memory of" in message and "smaller than requested" in message:
        return True
    return any(token in message for token in (
        "out of memory", "out_of_memory", "failed to allocate", "failure to allocate",
        "memory allocation failed", "not enough memory", "bad_alloc", "resource_exhausted",
        "cublas_status_alloc_failed", "cudnn_status_alloc_failed"))


def is_gpu_error(error):
    message = str(error).lower()
    return (type(error).__module__.startswith(("cupy", "cupyx")) or is_memory_error(error)
            or any(token in message for token in (
        "cuda", "cudnn", "cublas", "cusolver", "cusparse", "cupy", "nvrtc",
        "directml", "dml", "rocm", "hip", "coreml")))


def is_cuda_plan_error(error):
    message = str(error).lower()
    return any(token in message for token in ("heuristic_query_failed", "cudnn frontend",
                                              "cudnn_fe", "cudnn_status_not_supported"))


def gpu_error_summary(error):
    # ONNX errors can contain the entire graph. Keep the activity panel readable.
    return str(error).splitlines()[0][:300]


def create_image_processor(model, provider, device, log, on_device=None):
    """Choose a real CUDA pixel pipeline; never label CPU filters as GPU work."""
    if provider == "CUDAExecutionProvider":
        try:
            from gpu_images import CudaImages
            processor = CudaImages(model, runtime_info().get("device_id", 0))
            log("Tính toán ảnh: GPU (chuẩn bị ảnh, mặt nạ, giữ chi tiết, làm sạch viền, cắt và đổi kích thước).")
            log("CPU đọc file đầu vào, lưu PNG và điều khiển giao diện.")
            return processor
        except Exception as error:
            if device == "gpu":
                raise RuntimeError(f"Chưa kích hoạt được xử lý ảnh CUDA: {error}") from error
            log(f"Xử lý ảnh CUDA chưa sẵn sàng: {error}")
    elif provider in GPU_PROVIDERS and device == "gpu":
        raise RuntimeError("Xử lý ảnh hoàn toàn trên GPU hiện cần NVIDIA CUDA; GPU này chỉ chạy được model AI.")
    if provider in GPU_PROVIDERS:
        log("Suy luận AI dùng GPU; các phép tính chỉnh ảnh tạm dùng CPU.")
        if on_device is not None:
            on_device("GPU AI · CPU chỉnh ảnh")
    else:
        log("Tính toán ảnh: CPU.")
    return None


def subject_bottom(ai_alpha, min_frac=0.002):
    """Tìm hàng thấp nhất mà mặt nạ AI còn coi là chủ thể.

    Bỏ qua các hàng chỉ có lác đác vài pixel (nhiễu) bằng cách yêu cầu ít nhất
    'min_frac' phần chiều rộng ảnh là đục. Trả về None nếu mặt nạ rỗng.
    """
    rows = np.where((ai_alpha > 0.5).mean(axis=1) >= min_frac)[0]
    return int(rows.max()) if rows.size else None


def decontaminate(rgb, alpha, key, min_alpha=0.12):
    """Khôi phục màu thật của chủ thể ở những pixel bán trong suốt.

    Pixel ở vùng mờ (viền, ánh sáng lóe) thực chất là màu chủ thể ĐÃ BỊ TRỘN với
    màu nền:   quan_sat = alpha * that + (1 - alpha) * nen
    Nếu cứ giữ nguyên màu quan sát rồi gắn alpha vào, đặt lên nền trắng sẽ thấy
    viền đen bẩn (vì màu quan sát đã ngấm màu nền đen). Đảo ngược công thức:
        that = nen + (quan_sat - nen) / alpha

    min_alpha: alpha quá nhỏ thì phép chia khuếch đại nhiễu -> kẹp lại ở mức này.
    """
    a = np.clip(alpha, min_alpha, 1.0)[..., None]
    keyc = np.asarray(key[:3], dtype=np.float32)
    true_rgb = keyc + (rgb - keyc) / a
    return np.clip(true_rgb, 0.0, 255.0)


def subject_shoulder(ai_alpha, frac=0.5):
    """Tìm hàng 'vai' của chủ thể: hàng đầu tiên từ trên xuống mà bề rộng đạt
    >= frac lần bề rộng lớn nhất.

    Dùng làm mốc cho --bright-above. KHÔNG dùng đỉnh cao nhất của vật thể, vì
    đỉnh thường là một chi tiết nhỏ nhô lên (khoen lon, núm, cọng...) - lấy mốc
    ở đó sẽ cắt mất quầng sáng bao quanh phần đầu vật thể, để lại một dải trống
    nằm ngang rất lộ.
    """
    w = (ai_alpha > 0.5).sum(axis=1)
    mx = int(w.max())
    if mx == 0:
        return None
    rows = np.where(w >= mx * frac)[0]
    return int(rows.min()) if rows.size else None


def keep_bright(original, ai_result, key=(0, 0, 0), low=25, high=70,
                no_below=True, feather=0.01, decontam=True, above=None):
    """Giữ lại các chi tiết sáng mà AI xóa nhầm (VD: trái tim/lấp lánh bay lơ lửng
    trên nền đen). Dùng cho ảnh nền TỐI/ĐƠN SẮC.

    Kết quả = HỢP của (mặt nạ AI) và (vùng khác màu nền), lấy màu từ ảnh gốc:
      - Mặt nạ AI giữ vật thể chính đặc, không thủng chữ tối trong nhãn.
      - Vùng khác màu nền vớt lại mọi chi tiết sáng rời rạc AI bỏ sót.

    key      : màu nền cần khử (mặc định đen 0,0,0)
    low      : khoảng cách màu <= low  -> coi là nền (trong suốt)
    high     : khoảng cách màu >= high -> coi là chủ thể (đục); giữa 2 mức mờ dần
    no_below : không cho mặt nạ màu vớt thêm gì BÊN DƯỚI đáy chủ thể. Phần nằm
               dưới chân vật thể gần như luôn là bóng đổ / phản chiếu trên sàn,
               không phải chi tiết cần giữ.
    feather  : độ cao dải chuyển tiếp ở chỗ cắt, tính theo tỉ lệ chiều cao ảnh,
               để mép cắt không thành một đường ngang cứng.
    above    : chỉ cho mặt nạ màu hoạt động PHÍA TRÊN hàng này (None = cả ảnh).
               Chia đôi ảnh: bên trên vớt chi tiết bay (tia sáng, lấp lánh,
               vật thể lơ lửng), bên dưới giao hẳn cho mặt nạ AI. Rất cần khi
               chính vật thể có màu gần giống màu nền - lúc đó mặt nạ màu áp
               lên thân vật thể sẽ khoét thủng lỗ chỗ.
    """
    rgb = np.asarray(original.convert("RGB"), dtype=np.float32)
    keyc = np.asarray(key[:3], dtype=np.float32)
    # Khoảng cách màu tới màu nền (0..441)
    dist = np.sqrt(((rgb - keyc) ** 2).sum(axis=2))
    luma_alpha = np.clip((dist - low) / max(high - low, 1), 0.0, 1.0)

    ai_alpha = np.asarray(ai_result.convert("RGBA").split()[3], dtype=np.float32) / 255.0

    if above is not None:
        # Tắt dần mặt nạ màu khi đi xuống dưới ranh giới -> dưới ranh giới chỉ
        # còn mặt nạ AI quyết định.
        h = ai_alpha.shape[0]
        fade = max(1, int(round(h * feather)))
        ramp = np.clip((above + fade - np.arange(h)) / fade, 0.0, 1.0)
        luma_alpha *= ramp[:, None]

    if no_below:
        bot = subject_bottom(ai_alpha)
        if bot is not None:
            # Nhân mặt nạ màu với một dải dọc: 1 ở trên đáy chủ thể, giảm dần
            # về 0 ngay bên dưới -> phản chiếu/bóng dưới chân bị loại, còn
            # lấp lánh phía trên vẫn giữ nguyên.
            h = ai_alpha.shape[0]
            fade = max(1, int(round(h * feather)))
            ramp = np.clip((bot + fade - np.arange(h)) / fade, 0.0, 1.0)
            luma_alpha *= ramp[:, None]

    combined = np.maximum(ai_alpha, luma_alpha)  # HỢP hai mặt nạ

    out_rgb = decontaminate(rgb, combined, key) if decontam else rgb
    out = np.dstack([out_rgb, combined * 255.0]).astype(np.uint8)
    return Image.fromarray(out, "RGBA")


def detect_solid_bg(img, tol=32):
    """Đoán xem ảnh có nền ĐƠN SẮC (đồng màu) không, dựa trên viền quanh ảnh.

    Trả về (True, màu_nền) nếu viền đồng màu -> nên bật keep_bright.
    Trả về (False, None) nếu nền lộn xộn -> để AI xử lý bình thường.
    """
    arr = np.asarray(img.convert("RGB"), dtype=np.float32)
    h, w = arr.shape[:2]
    b = max(2, min(h, w) // 40)  # độ dày viền lấy mẫu
    border = np.concatenate([
        arr[:b].reshape(-1, 3), arr[-b:].reshape(-1, 3),
        arr[:, :b].reshape(-1, 3), arr[:, -b:].reshape(-1, 3),
    ])
    mean = border.mean(axis=0)
    # Độ lệch màu trung bình của viền so với màu trung bình -> đo độ "đồng màu"
    spread = np.sqrt(((border - mean) ** 2).sum(axis=1)).mean()
    if spread < tol:
        return True, tuple(int(x) for x in mean)
    return False, None


def trim_base(img, max_trim=0.06, width_ratio=0.35, threshold=8):
    """Cắt nốt mẩu bóng/phản chiếu còn dính vào chân vật thể.

    Phần sót lại ở chân thường là vài cục nhỏ nhô ra dưới đế - nó DÍNH LIỀN vào
    chủ thể nên lọc mảng rời không xử lý được, nhưng lại có dấu hiệu rất rõ: bề
    rộng của mặt nạ sụt đột ngột so với thân ngay phía trên.

    Quét trong khoảng max_trim (tỉ lệ chiều cao chủ thể) tính từ đáy lên; hàng
    đầu tiên có bề rộng < width_ratio so với thân -> cắt từ đó xuống.

    Không tìm thấy chỗ sụt thì không cắt gì, nên ảnh vốn đã sạch vẫn an toàn.
    """
    img = img.convert("RGBA")
    a = np.asarray(img.split()[3])
    rows = np.where((a > threshold).any(axis=1))[0]
    if rows.size == 0:
        return img

    top, bot = int(rows.min()), int(rows.max())
    sh = bot - top
    zone = int(sh * max_trim)
    if zone < 4 or sh < 40:
        return img

    widths = (a > threshold).sum(axis=1)
    zone_start = bot - zone
    # Bề rộng "thân" tham chiếu: lấy trung vị ngay phía trên vùng quét
    body = np.median(widths[max(top, zone_start - zone):zone_start])
    if body <= 0:
        return img

    drop = np.where(widths[zone_start:bot + 1] < body * width_ratio)[0]
    if drop.size == 0:
        return img  # chân đã sạch, không cắt

    cut = zone_start + int(drop.min())
    arr = a.astype(np.float32) / 255.0
    # Dải chuyển tiếp nằm NGAY TRÊN điểm cắt: alpha = 0 kể từ hàng 'cut' trở
    # xuống (mẩu thừa biến mất hẳn), mờ dần lên trên để mép không bị cứng.
    fade = max(1, int(round(sh * 0.004)))
    ramp = np.clip((cut - np.arange(a.shape[0])) / fade, 0.0, 1.0)
    arr *= ramp[:, None]

    r, g, b, _ = img.split()
    return Image.merge("RGBA", (r, g, b,
                                Image.fromarray((arr * 255.0).astype(np.uint8), "L")))


def cut_below(img, pct):
    """Xóa hẳn mọi thứ nằm dưới 'pct' phần trăm chiều cao ảnh (0-100).

    Dùng khi phần bóng/phản chiếu còn sót nằm lẫn trong vùng AI vẫn coi là chủ
    thể, nên --no-below tự động không cắt tới. Có dải chuyển tiếp mềm để mép cắt
    không lộ thành đường ngang.
    """
    img = img.convert("RGBA")
    r, g, b, a = img.split()
    arr = np.asarray(a, dtype=np.float32) / 255.0
    h = arr.shape[0]
    edge = h * pct / 100.0
    fade = max(1, int(round(h * 0.01)))
    ramp = np.clip((edge + fade - np.arange(h)) / fade, 0.0, 1.0)
    arr *= ramp[:, None]
    a = Image.fromarray((arr * 255.0).astype(np.uint8), "L")
    return Image.merge("RGBA", (r, g, b, a))


def clean_edges(img, threshold=0, erode=0, defringe=False):
    """Làm sạch viền: cắt lớp nền nửa trong suốt còn dính ở mép + khử màu viền.

    - threshold: pixel có độ đục < ngưỡng này -> xóa hẳn (loại halo mờ). 0 = tắt.
    - erode: co mặt nạ vào trong 'erode' pixel để cắt vành nền còn sót. 0 = tắt.
    - defringe: kéo màu chủ thể ra mép để mép không còn ám màu nền cũ.
    """
    img = img.convert("RGBA")
    r, g, b, a = img.split()

    if threshold > 0:
        # Pixel quá mờ (chủ yếu là nền sót) -> trong suốt hẳn
        a = a.point(lambda p: 0 if p < threshold else p)

    if erode > 0:
        # MinFilter thu nhỏ vùng sáng của kênh alpha -> co mặt nạ vào trong,
        # cắt bỏ vành pixel nền còn dính quanh mép chủ thể.
        size = erode * 2 + 1
        a = a.filter(ImageFilter.MinFilter(size))

    if defringe:
        # Khử ám màu: làm nhòe nhẹ RGB rồi chỉ dùng ở vùng viền, để màu chủ thể
        # "tràn" ra thay cho màu nền cũ bám ở mép.
        rgb = Image.merge("RGB", (r, g, b))
        blurred = rgb.filter(ImageFilter.GaussianBlur(2))
        # Vùng viền = nơi alpha nằm giữa (không đặc, không rỗng)
        edge = a.point(lambda p: 255 if 5 < p < 250 else 0)
        rgb = Image.composite(blurred, rgb, edge)
        r, g, b = rgb.split()

    return Image.merge("RGBA", (r, g, b, a))


def autocrop(img, pad_pct=6.0, threshold=8, square=False):
    """Cắt sát chủ thể theo kênh alpha, nhưng vẫn chừa lại một khoảng lề.

    Lề = pad_pct %% của CẠNH LỚN NHẤT của chủ thể, áp dụng đều cho cả 4 phía.
    Nhờ lấy theo kích thước chủ thể (không phải kích thước ảnh gốc), mọi ảnh
    trong loạt đều có tỉ lệ chủ thể/lề như nhau -> nhìn đồng đều dù ảnh gốc to
    nhỏ khác nhau.

    threshold : alpha > ngưỡng này mới tính là chủ thể (bỏ qua halo mờ còn sót)
    square    : mở rộng khung ra hình vuông, chủ thể canh giữa
    """
    img = img.convert("RGBA")
    a = np.asarray(img.split()[3])
    ys, xs = np.nonzero(a > threshold)
    if xs.size == 0:
        return img  # ảnh trong suốt hoàn toàn -> không cắt gì

    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1

    pad = int(round(max(x1 - x0, y1 - y0) * pad_pct / 100.0))
    x0, y0, x1, y1 = x0 - pad, y0 - pad, x1 + pad, y1 + pad

    if square:
        w, h = x1 - x0, y1 - y0
        if w < h:
            d = h - w
            x0, x1 = x0 - d // 2, x1 + (d - d // 2)
        elif h < w:
            d = w - h
            y0, y1 = y0 - d // 2, y1 + (d - d // 2)

    # Khung có thể vượt ra ngoài ảnh gốc; PIL tự chèn pixel trong suốt -> đúng ý
    return img.crop((x0, y0, x1, y1))


def fit_canvas(img, size):
    """Scale ảnh vừa khung W x H rồi canh giữa trên nền trong suốt.

    Dùng khi muốn MỌI ảnh xuất ra đúng cùng một kích thước pixel.

    Lưu ý: phải scale cả HAI chiều (phóng to lẫn thu nhỏ), không dùng thumbnail()
    vì thumbnail chỉ thu nhỏ - ảnh nhỏ hơn khung sẽ nằm lọt thỏm ở giữa và khung
    hình không còn đồng đều với các ảnh khác.
    """
    w, h = size
    im = img.convert("RGBA")
    scale = min(w / im.width, h / im.height)
    nw, nh = max(1, round(im.width * scale)), max(1, round(im.height * scale))
    im = im.resize((nw, nh), Image.LANCZOS)  # giữ nguyên tỉ lệ, không méo
    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    canvas.paste(im, ((w - nw) // 2, (h - nh) // 2))
    return canvas


def parse_size(value: str):
    """Chuyển '2000x2000' -> (2000, 2000)."""
    try:
        w, h = (int(x) for x in value.lower().split("x"))
    except ValueError:
        raise argparse.ArgumentTypeError("Kích thước phải có dạng RỘNGxCAO, vd 2000x2000")
    if w <= 0 or h <= 0:
        raise argparse.ArgumentTypeError("Kích thước phải lớn hơn 0")
    return w, h


def parse_bg(value: str):
    """Chuyển '255,255,255' -> (255, 255, 255, 255). Trả None nếu để nền trong suốt."""
    if not value:
        return None
    parts = [int(x) for x in value.split(",")]
    if len(parts) == 3:
        parts.append(255)  # thêm alpha = đục hoàn toàn
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("Màu nền phải có dạng R,G,B hoặc R,G,B,A")
    return tuple(parts)


def build_parser():
    """Khai báo toàn bộ tùy chọn. Tách riêng để giao diện đồ họa lấy được đúng
    bộ giá trị mặc định mà không phải chép lại (xem make_options)."""
    ap = argparse.ArgumentParser(description="Xóa nền ảnh hàng loạt bằng AI")
    ap.add_argument("-i", "--input", default="input",
                    help="Thư mục chứa ảnh gốc (mặc định: input)")
    ap.add_argument("-o", "--output", default="output",
                    help="Thư mục lưu kết quả (mặc định: output)")
    ap.add_argument("-m", "--model", default="birefnet-general",
                    help="Model AI. birefnet-general = chất lượng cao nhất (mặc định); "
                         "u2net = nhanh; u2netp = nhẹ; isnet-general-use = tốt cho vật thể")
    ap.add_argument("--device", choices=("auto", "gpu", "cpu"), default="auto",
                    help="auto: ưu tiên GPU và dự phòng CPU (mặc định); gpu: bắt buộc GPU; cpu: chỉ dùng CPU")
    ap.add_argument("--bg", type=parse_bg, default=None,
                    help="Màu nền thay thế dạng R,G,B (vd 255,255,255 = trắng). "
                         "Bỏ trống = nền trong suốt.")
    ap.add_argument("--matting", action="store_true",
                    help="Bật alpha matting - viền tóc/lông mịn hơn nhưng chậm hơn")
    ap.add_argument("--clean", action="store_true",
                    help="Làm sạch viền tự động (khuyến nghị): cắt nền sót ở mép + khử ám màu. "
                         "Tương đương --threshold 30 --erode 1 --defringe")
    ap.add_argument("--threshold", type=int, default=0, metavar="N",
                    help="Xóa hẳn pixel có độ đục < N (0-255). Loại lớp halo mờ. VD: 30")
    ap.add_argument("--erode", type=int, default=0, metavar="N",
                    help="Co mặt nạ vào trong N pixel để cắt vành nền còn dính. VD: 1 hoặc 2")
    ap.add_argument("--defringe", action="store_true",
                    help="Khử ám màu nền cũ bám ở mép chủ thể")
    ap.add_argument("--auto", action="store_true",
                    help="TỰ ĐỘNG: nếu ảnh có nền đơn sắc (đen/trắng...) thì tự bật giữ chi tiết "
                         "sáng rời rạc. Khuyến nghị dùng mặc định cho ảnh sản phẩm.")
    ap.add_argument("--keep-bright", dest="keep_bright", action="store_true",
                    help="Giữ chi tiết sáng rời rạc mà AI xóa nhầm (trái tim/lấp lánh bay...). "
                         "DÀNH CHO ẢNH NỀN TỐI/ĐƠN SẮC. Kết hợp mặt nạ AI + khử màu nền.")
    ap.add_argument("--key-color", dest="key_color", type=parse_bg, default=(0, 0, 0),
                    help="Màu nền cần khử khi dùng --keep-bright (mặc định đen: 0,0,0)")
    ap.add_argument("--bright-low", dest="bright_low", type=int, default=90, metavar="N",
                    help="--keep-bright: khoảng cách màu <= N coi là nền. Tăng nếu nền còn sót.")
    ap.add_argument("--bright-high", dest="bright_high", type=int, default=220, metavar="N",
                    help="--keep-bright: khoảng cách màu >= N coi là chủ thể (đục hoàn toàn). "
                         "Đặt quá thấp thì quầng sáng mờ quanh vật thể bị gán đục và giữ nguyên "
                         "màu tối -> viền đen bẩn. Giảm nếu mất chi tiết.")
    ap.add_argument("--bright-above", dest="bright_above", default=None, metavar="PCT|auto",
                    help="Chia đôi ảnh: chỉ vớt chi tiết bay ở PHÍA TRÊN mốc này, phía dưới "
                         "giao hẳn cho AI. Nhập %% chiều cao ảnh (vd 25), hoặc 'auto' để lấy "
                         "ngang VAI vật thể (chỗ vật thể đạt 50%% bề rộng lớn nhất). Dùng khi "
                         "vật thể có màu gần giống màu nền. Mốc đặt quá cao sẽ để lại một dải "
                         "trống nằm ngang ngay trên đầu vật thể -> hạ %% xuống.")
    ap.add_argument("--no-decontam", dest="no_decontam", action="store_true",
                    help="Tắt khôi phục màu ở vùng bán trong suốt. Mặc định BẬT - nếu tắt, "
                         "viền và ánh sáng lóe sẽ còn ám đen khi đặt lên nền sáng.")
    ap.add_argument("--keep-below", dest="keep_below", action="store_true",
                    help="Giữ lại cả bóng đổ / phản chiếu dưới chân vật thể. Mặc định phần "
                         "nằm dưới đáy chủ thể bị xóa vì hầu như luôn là phản chiếu trên sàn.")
    ap.add_argument("--no-trim-base", dest="no_trim_base", action="store_true",
                    help="Tắt cắt tự động mẩu bóng còn dính ở chân vật thể. Mặc định --auto "
                         "có bật. Nên tắt nếu vật thể vốn thon nhọn dần về phía đáy.")
    ap.add_argument("--cut-below", dest="cut_below", type=float, default=None, metavar="PCT",
                    help="Xóa hẳn mọi thứ nằm dưới PCT%% chiều cao ảnh (vd 95). Dùng khi phản "
                         "chiếu còn sót dính vào đáy vật thể nên tự động không cắt hết.")
    ap.add_argument("--crop", action="store_true",
                    help="Cắt sát chủ thể sau khi xóa nền, vẫn chừa lề đều 4 phía "
                         "(xem --pad). Mọi ảnh sẽ có tỉ lệ chủ thể/lề như nhau.")
    ap.add_argument("--pad", type=float, default=6.0, metavar="PCT",
                    help="--crop: lề chừa lại, tính theo %% cạnh lớn nhất của chủ thể "
                         "(mặc định 6). Đặt 0 để cắt sát tuyệt đối.")
    ap.add_argument("--square", action="store_true",
                    help="--crop: mở rộng khung thành hình vuông, chủ thể canh giữa")
    ap.add_argument("--size", type=parse_size, default=None, metavar="RỘNGxCAO",
                    help="Ép mọi ảnh ra đúng cùng kích thước, vd 2000x2000. Chủ thể được "
                         "thu vừa khung và canh giữa, không méo tỉ lệ.")
    ap.add_argument("--overwrite", action="store_true",
                    help="Xử lý lại cả ảnh đã có kết quả")
    return ap


def make_options(**kw):
    """Tạo bộ tùy chọn đầy đủ cho run_batch, chỉ cần ghi đè vài mục cần đổi.

    Giá trị mặc định lấy thẳng từ argparse nên không bao giờ lệch với dòng lệnh.
    """
    opts = build_parser().parse_args([])
    for k, v in kw.items():
        if not hasattr(opts, k):
            raise TypeError(f"Không có tùy chọn tên '{k}'")
        setattr(opts, k, v)
    return opts


def list_images(in_dir):
    """Danh sách ảnh hợp lệ trong thư mục, sắp xếp theo tên."""
    return sorted(p for p in Path(in_dir).iterdir()
                  if p.is_file() and p.suffix.lower() in SUPPORTED)


def apply_pipeline(original, result, opts, log=lambda _: None):
    """Các bước xử lý sau khi AI đã tách xong nền, theo đúng thứ tự bắt buộc."""
    # Quyết định có vớt chi tiết sáng không, và dùng màu nền nào
    do_bright = opts.keep_bright
    key_color = opts.key_color
    if opts.auto and not opts.keep_bright:
        solid, bg_color = detect_solid_bg(original)
        if solid:
            do_bright = True
            key_color = bg_color
            log(f"      (auto: phát hiện nền đơn sắc {bg_color} -> giữ chi tiết sáng)")

    # Vớt lại chi tiết sáng AI bỏ sót (ảnh nền tối) - làm TRƯỚC khi làm sạch viền
    if do_bright:
        above = None
        if opts.bright_above is not None:
            ai_a = np.asarray(result.convert("RGBA").split()[3], dtype=np.float32) / 255.0
            if str(opts.bright_above).lower() == "auto":
                above = subject_shoulder(ai_a)
            else:
                above = int(ai_a.shape[0] * float(opts.bright_above) / 100.0)
            log(f"      (vớt chi tiết bay giới hạn phía trên hàng {above})")
        result = keep_bright(original, result, key_color,
                             opts.bright_low, opts.bright_high,
                             no_below=not opts.keep_below,
                             decontam=not opts.no_decontam,
                             above=above)
    # Cắt nốt mẩu bóng còn dính ở chân vật thể
    if (opts.auto or opts.keep_bright) and not opts.no_trim_base:
        result = trim_base(result)
    # Cắt thủ công phần đáy (phản chiếu còn sót) nếu người dùng chỉ định
    if opts.cut_below is not None:
        result = cut_below(result, opts.cut_below)
    # Làm sạch viền nếu người dùng bật
    if opts.threshold or opts.erode or opts.defringe:
        result = clean_edges(result, opts.threshold, opts.erode, opts.defringe)
    # Cắt sát chủ thể (chừa lề) - phải làm sau khi alpha đã sạch
    if opts.crop:
        result = autocrop(result, opts.pad, square=opts.square)
    # Ép về cùng một kích thước cho cả loạt
    if opts.size is not None:
        result = fit_canvas(result, opts.size)
    # Đổ nền màu ở bước cuối, khi mọi xử lý dựa trên alpha đã xong
    if opts.bg is not None:
        flat = Image.new("RGBA", result.size, tuple(opts.bg))
        result = Image.alpha_composite(flat, result.convert("RGBA"))
    return result


def run_batch(opts, log=print, on_progress=None, should_stop=None, on_device=None):
    """Xử lý cả thư mục. Dùng chung cho dòng lệnh và giao diện đồ họa.

    log         : hàm nhận một dòng chữ để hiển thị
    on_progress : hàm nhận (đã_xong, tổng_số, tên_ảnh) sau mỗi ảnh
    should_stop : hàm trả True khi người dùng bấm dừng -> ngưng giữa chừng
    on_device   : hàm nhận tên bộ xử lý thực tế (GPU hoặc CPU)

    Trả về dict {ok, skipped, failed, stopped, seconds, output}.
    """
    # --clean = preset gộp các bước làm sạch viền thường dùng
    if opts.clean:
        if opts.threshold == 0:
            opts.threshold = 30
        if opts.erode == 0:
            opts.erode = 1
        opts.defringe = True

    in_dir, out_dir = Path(opts.input), Path(opts.output)
    if not in_dir.is_dir():
        raise NotADirectoryError(f"Không tìm thấy thư mục đầu vào: {in_dir.resolve()}")

    images = list_images(in_dir)
    if not images:
        raise FileNotFoundError(
            f"Không có ảnh nào trong {in_dir.resolve()}\n"
            f"Định dạng hỗ trợ: {', '.join(sorted(SUPPORTED))}")

    out_dir.mkdir(parents=True, exist_ok=True)

    log(f"Model: {opts.model}")
    log(f"Tìm thấy {len(images)} ảnh trong '{in_dir}'. Đang tải model (lần đầu có thể lâu)...")

    # Tạo session 1 lần rồi tái sử dụng cho mọi ảnh -> nhanh hơn nhiều
    session, provider = create_inference_session(opts.model, opts.device, log, on_device)
    image_processor = create_image_processor(opts.model, provider, opts.device, log, on_device)
    cuda_algorithm = getattr(session, "_cuda_algorithm", "DEFAULT")
    attempted_cuda_algorithms = {cuda_algorithm}

    kwargs = {}
    if opts.matting:
        kwargs.update(
            alpha_matting=True,
            alpha_matting_foreground_threshold=240,
            alpha_matting_background_threshold=20,
            alpha_matting_erode_size=11,
        )
    # Nền màu được đổ ở BƯỚC CUỐI (không nhờ rembg làm qua bgcolor), để các bước
    # làm sạch viền / cắt sát chủ thể phía trước vẫn còn kênh alpha mà dùng.

    ok = skipped = failed = 0
    stopped = False
    t0 = time.time()

    for idx, src in enumerate(images, 1):
        if should_stop is not None and should_stop():
            log("Đã dừng theo yêu cầu.")
            stopped = True
            break

        dst = out_dir / (src.stem + ".png")  # kết quả luôn là PNG (giữ độ trong suốt)
        if dst.exists() and not opts.overwrite:
            log(f"[{idx}/{len(images)}] Bỏ qua (đã có): {src.name}")
            skipped += 1
        else:
            try:
                with Image.open(src) as im:
                    original = im.convert("RGBA")
                    while True:
                        try:
                            if image_processor is not None:
                                result = image_processor.process(original, session, opts, log)
                            else:
                                original = ImageOps.exif_transpose(original)
                                result = remove(original, session=session, **kwargs)
                                remember = getattr(session, "_on_cuda_success", None)
                                if remember is not None:
                                    remember()
                                result = apply_pipeline(original, result, opts, log)
                            break
                        except Exception as error:
                            memory_error = is_memory_error(error)
                            retry_cuda = (provider == "CUDAExecutionProvider"
                                          and len(attempted_cuda_algorithms) < 2
                                          and not memory_error
                                          and is_cuda_plan_error(error))
                            if not retry_cuda and not (provider in GPU_PROVIDERS
                                    and opts.device == "auto" and is_gpu_error(error)):
                                raise
                            if memory_error:
                                log("GPU không đủ bộ nhớ để chạy model này.")
                            else:
                                log(f"GPU gặp lỗi: {gpu_error_summary(error)}")
                        # Release the failed session after leaving the exception handler:
                        # its traceback can otherwise retain all GPU allocations.
                        session = None
                        gc.collect()
                        if image_processor is not None:
                            image_processor.release_cache()
                        if retry_cuda:
                            cuda_algorithm = ("DEFAULT" if cuda_algorithm == "EXHAUSTIVE"
                                              else "EXHAUSTIVE")
                            attempted_cuda_algorithms.add(cuda_algorithm)
                            log("Đang thử cấu hình CUDA tương thích hơn cho model này…")
                            session, provider = create_inference_session(
                                opts.model, opts.device, log, on_device,
                                cuda_algorithm=cuda_algorithm)
                        else:
                            log("Thử lại ảnh này trên CPU; các ảnh còn lại sẽ tiếp tục trên CPU.")
                            session, provider = create_inference_session(
                                opts.model, "cpu", log, on_device, cpu_fallback=True)
                        image_processor = create_image_processor(
                            opts.model, provider, opts.device, log, on_device)
                    if image_processor is not None:
                        image_processor.release_cache()
                result.save(dst)
                log(f"[{idx}/{len(images)}] OK  {src.name}  ->  {dst.name}")
                ok += 1
            except Exception as e:
                if session is None:
                    # Never let rembg silently create an uncontrolled default session.
                    raise RuntimeError(f"Không khởi tạo lại được bộ xử lý: {e}") from e
                log(f"[{idx}/{len(images)}] LỖI {src.name}: {e}")
                failed += 1

        if on_progress is not None:
            on_progress(idx, len(images), src.name)

    dt = time.time() - t0
    log("-" * 50)
    log(f"Xong: {ok} thành công, {skipped} bỏ qua, {failed} lỗi  ({dt:.1f}s)")
    log(f"Kết quả nằm ở: {out_dir.resolve()}")
    return {"ok": ok, "skipped": skipped, "failed": failed,
            "stopped": stopped, "seconds": dt, "output": out_dir.resolve()}


def main():
    opts = build_parser().parse_args()
    try:
        run_batch(opts)
    except NotADirectoryError as e:
        print(f"[LỖI] {e}")
        print("      Hãy tạo thư mục đó và bỏ ảnh vào, hoặc dùng -i để chỉ định thư mục khác.")
        sys.exit(1)
    except FileNotFoundError as e:
        print(f"[!] {e}")
        sys.exit(0)
    except RuntimeError as e:
        print(f"[LỖI] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
