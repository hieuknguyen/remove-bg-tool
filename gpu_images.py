"""CUDA image processing. Only decoded input and the final PNG cross to the CPU.

Small scalar results (crop bounds, solver convergence) return to the host for
control flow. Pixel buffers stay on CUDA, including the ONNX input and mask.
"""

import math
import os

import numpy as np
import onnxruntime as ort
from PIL import Image


MODEL_FORMATS = {
    "u2net": (320, False, (0.485, 0.456, 0.406), (0.229, 0.224, 0.225)),
    "u2netp": (320, False, (0.485, 0.456, 0.406), (0.229, 0.224, 0.225)),
    "isnet-general-use": (1024, False, (0.5, 0.5, 0.5), (1.0, 1.0, 1.0)),
}
for _model in ("birefnet-general", "birefnet-massive", "birefnet-general-lite",
               "birefnet-portrait", "birefnet-dis", "birefnet-hrsod", "birefnet-cod"):
    MODEL_FORMATS[_model] = (1024, True, (0.485, 0.456, 0.406), (0.229, 0.224, 0.225))


# Separable Lanczos-3 with antialiasing when reducing size. One thread per
# output component avoids building a large CPU or GPU interpolation matrix.
_RESIZE_SOURCE = r'''
__device__ float sinc3(float x) {
    x = fabsf(x);
    if (x < 1.e-6f) return 1.f;
    if (x >= 3.f) return 0.f;
    const float pi = 3.14159265358979323846f;
    return sinf(pi*x)/(pi*x) * sinf(pi*x/3.f)/(pi*x/3.f);
}
extern "C" __global__ void resize_axis(const float* src, float* dst,
    int ih, int iw, int oh, int ow, int channels, int axis) {
    long long i = (long long)blockDim.x * blockIdx.x + threadIdx.x;
    long long n = (long long)oh * ow * channels;
    if (i >= n) return;
    int c = i % channels;
    int x = (i / channels) % ow;
    int y = i / ((long long)ow * channels);
    int oldsize = axis == 1 ? iw : ih;
    int newsize = axis == 1 ? ow : oh;
    float ratio = (float)oldsize / newsize;
    float scale = fmaxf(1.f, ratio);
    float center = ((axis == 1 ? x : y) + .5f) * ratio - .5f;
    int first = max(0, (int)ceilf(center - 3.f*scale));
    int last = min(oldsize - 1, (int)floorf(center + 3.f*scale));
    float value = 0.f, weight = 0.f;
    for (int p = first; p <= last; ++p) {
        float k = sinc3((p - center) / scale);
        long long j = axis == 1 ? ((long long)y*iw+p)*channels+c
                               : ((long long)p*iw+x)*channels+c;
        value += src[j] * k;
        weight += k;
    }
    dst[i] = fabsf(weight) > 1.e-10f ? value / weight : 0.f;
}
'''


# The lower rows contain only a short vector of integer widths. Rank them
# directly on CUDA instead of invoking Thrust/CCCL's generic sort headers.
_MEDIAN_SOURCE = r'''
extern "C" __global__ void width_median(const long long* values,
                                      double* middle, int n) {
    int i = blockDim.x * blockIdx.x + threadIdx.x;
    if (i >= n) return;
    long long value = values[i];
    int rank = 0;
    for (int j = 0; j < n; ++j)
        rank += values[j] < value || (values[j] == value && j < i);
    if (rank == (n - 1) / 2) middle[0] = (double)value;
    if (rank == n / 2) middle[1] = (double)value;
}
'''


class CudaImages:
    def __init__(self, model, device_id=0):
        if model not in MODEL_FORMATS:
            raise ValueError(f"Chưa có bộ xử lý ảnh CUDA cho model {model}")
        # CuPy's optional CUB JIT path includes FP8 definitions even for integer
        # image reductions. Use native CUDA kernels to avoid the reported
        # __nv_fp8_e8m0 header incompatibility; calculations remain on the GPU.
        os.environ["CUPY_ACCELERATORS"] = ""
        import cupy as cp
        from cupy._core import _accelerator
        _accelerator.set_elementwise_accelerators([])
        _accelerator.set_reduction_accelerators([])
        _accelerator.set_routine_accelerators([])
        from cupyx.scipy import ndimage

        self.cp = cp
        self.nd = ndimage
        self.device_id = device_id
        self.device = cp.cuda.Device(device_id)
        self.device.use()  # The batch worker has its own current CUDA device.
        self.format = MODEL_FORMATS[model]
        self.resize_kernel = cp.RawKernel(_RESIZE_SOURCE, "resize_axis")
        self.median_kernel = cp.RawKernel(_MEDIAN_SOURCE, "width_median")

    def release_cache(self):
        self.device.use()
        self.cp.get_default_memory_pool().free_all_blocks()

    def resize(self, image, size, rgba=False):
        cp = self.cp
        width, height = size
        if width <= 0 or height <= 0:
            raise ValueError("Kích thước ảnh phải lớn hơn 0")
        if (image.shape[1], image.shape[0]) == size:
            return image.copy()
        source = cp.ascontiguousarray(image, dtype=cp.float32)
        grayscale = source.ndim == 2
        if grayscale:
            source = source[..., None]
        if rgba:
            source = source.copy()
            source[..., :3] *= source[..., 3:4] / 255.0
        old_h, old_w, channels = source.shape
        intermediate = cp.empty((old_h, width, channels), dtype=cp.float32)
        result = cp.empty((height, width, channels), dtype=cp.float32)
        for src, dst, axis in ((source, intermediate, 1), (intermediate, result, 0)):
            h, w = src.shape[:2]
            oh, ow = dst.shape[:2]
            self.resize_kernel(((dst.size + 255) // 256,), (256,),
                (src, dst, np.int32(h), np.int32(w), np.int32(oh), np.int32(ow),
                 np.int32(channels), np.int32(axis)))
        if rgba:
            result[..., :3] *= 255.0 / cp.maximum(result[..., 3:4], 1.e-6)
            result[..., :3] = cp.where(result[..., 3:4] > 0, result[..., :3], 0)
        return cp.clip(result[..., 0] if grayscale else result, 0, 255)

    def _decoded_image(self, original):
        cp = self.cp
        pixels = cp.asarray(np.asarray(original), dtype=cp.float32)
        orientation = original.getexif().get(274, 1)
        if orientation == 2:
            pixels = pixels[:, ::-1]
        elif orientation == 3:
            pixels = pixels[::-1, ::-1]
        elif orientation == 4:
            pixels = pixels[::-1]
        elif orientation == 5:
            pixels = pixels.transpose(1, 0, 2)
        elif orientation == 6:
            pixels = cp.rot90(pixels, -1)
        elif orientation == 7:
            pixels = pixels.transpose(1, 0, 2)[::-1, ::-1]
        elif orientation == 8:
            pixels = cp.rot90(pixels, 1)
        return cp.ascontiguousarray(pixels)

    def infer(self, original, session):
        cp = self.cp
        pixels = self._decoded_image(original)
        size, sigmoid, mean, std = self.format
        resized = cp.rint(self.resize(pixels[..., :3], (size, size)))
        resized /= cp.maximum(resized.max(), 1.e-6)
        resized -= cp.asarray(mean, dtype=cp.float32)
        resized /= cp.asarray(std, dtype=cp.float32)
        tensor = cp.ascontiguousarray(resized.transpose(2, 0, 1)[None])
        del resized
        self.release_cache()
        inner = session.inner_session
        binding = inner.io_binding()
        binding.bind_input(inner.get_inputs()[0].name, "cuda", self.device_id,
                           np.float32, tensor.shape, tensor.data.ptr)
        binding.bind_output(inner.get_outputs()[0].name, "cuda", self.device_id)
        # CuPy and ONNX use different CUDA streams. Explicit barriers make the
        # raw-pointer exchange safe without assuming either stream's defaults.
        cp.cuda.get_current_stream().synchronize()
        run_options = ort.RunOptions()
        run_options.add_run_config_entry("memory.enable_memory_arena_shrinkage", f"gpu:{self.device_id}")
        inner.run_with_iobinding(binding, run_options)
        binding.synchronize_outputs()
        remember = getattr(session, "_on_cuda_success", None)
        if remember is not None:
            remember()
        value = binding.get_outputs()[0]
        if value.device_name() != "cuda":
            raise RuntimeError("CUDA không trả mặt nạ trên GPU")
        types = {"tensor(float)": cp.float32, "tensor(float16)": cp.float16,
                 "tensor(double)": cp.float64}
        dtype = types.get(value.data_type())
        if dtype is None:
            raise RuntimeError(f"CUDA: định dạng mặt nạ không hỗ trợ: {value.data_type()}")
        memory = cp.cuda.UnownedMemory(value.data_ptr(), value.tensor_size_in_bytes(), value,
                                      device_id=self.device_id)
        output = cp.ndarray(tuple(value.shape()), dtype=dtype,
                            memptr=cp.cuda.MemoryPointer(memory, 0))
        pred = output[0, 0].astype(cp.float32)
        if sigmoid:
            pred = 1.0 / (1.0 + cp.exp(-cp.clip(pred, -80, 80)))
        lo, hi = pred.min(), pred.max()
        pred = cp.clip((pred - lo) / cp.maximum(hi - lo, 1.e-8), 0, 1)
        # Preserve rembg's 8-bit mask before scaling back to the original size.
        mask = (pred * 255).astype(cp.uint8).astype(cp.float32)
        mask = cp.rint(self.resize(mask, (pixels.shape[1], pixels.shape[0]))) / 255.0
        result = cp.rint(pixels * mask[..., None])
        cp.cuda.get_current_stream().synchronize()
        return pixels, result

    def solid_background(self, pixels, tolerance=32):
        cp = self.cp
        rgb = pixels[..., :3]
        h, w = rgb.shape[:2]
        b = max(2, min(h, w) // 40)
        border = cp.concatenate((rgb[:b].reshape(-1, 3), rgb[-b:].reshape(-1, 3),
                                 rgb[:, :b].reshape(-1, 3), rgb[:, -b:].reshape(-1, 3)))
        mean = border.mean(axis=0)
        spread = cp.sqrt(cp.square(border - mean).sum(axis=1)).mean()
        color = tuple(int(component.item()) for component in mean)
        return bool((spread < tolerance).item()), color

    def bottom(self, alpha):
        cp = self.cp
        rows = cp.flatnonzero((alpha > 0.5).mean(axis=1) >= 0.002)
        return int(rows[-1].item()) if rows.size else None

    def shoulder(self, alpha):
        cp = self.cp
        widths = (alpha > 0.5).sum(axis=1)
        widest = widths.max()
        if not bool((widest > 0).item()):
            return None
        return int(cp.flatnonzero(widths >= widest * 0.5)[0].item())

    def bright(self, original, result, opts, key, above):
        cp = self.cp
        rgb = original[..., :3]
        background = cp.asarray(key[:3], dtype=cp.float32)
        distance = cp.sqrt(cp.square(rgb - background).sum(axis=2))
        bright_alpha = cp.clip((distance - opts.bright_low) /
                              max(opts.bright_high - opts.bright_low, 1), 0, 1)
        alpha = result[..., 3] / 255.0
        h = alpha.shape[0]
        fade = max(1, round(h * 0.01))
        rows = cp.arange(h, dtype=cp.float32)
        if above is not None:
            bright_alpha *= cp.clip((above + fade - rows) / fade, 0, 1)[:, None]
        if not opts.keep_below:
            bottom = self.bottom(alpha)
            if bottom is not None:
                bright_alpha *= cp.clip((bottom + fade - rows) / fade, 0, 1)[:, None]
        alpha = cp.maximum(alpha, bright_alpha)
        if not opts.no_decontam:
            rgb = cp.clip(background + (rgb - background) /
                          cp.maximum(alpha[..., None], 0.12), 0, 255)
        return cp.concatenate((rgb, alpha[..., None] * 255), axis=2).astype(cp.uint8).astype(cp.float32)

    def trim_base(self, result):
        cp = self.cp
        alpha = result[..., 3]
        widths = (alpha > 8).sum(axis=1)
        rows = cp.flatnonzero(widths)
        if not rows.size:
            return result
        top, bottom = int(rows[0].item()), int(rows[-1].item())
        height = bottom - top
        zone = int(height * 0.06)
        if zone < 4 or height < 40:
            return result
        start = bottom - zone
        sample = cp.ascontiguousarray(widths[max(top, start - zone):start], dtype=cp.int64)
        middle = cp.empty(2, dtype=cp.float64)
        self.median_kernel(((sample.size + 127) // 128,), (128,),
                           (sample, middle, np.int32(sample.size)))
        body = middle.mean()
        if not bool((body > 0).item()):
            return result
        drop = cp.flatnonzero(widths[start:bottom + 1] < body * 0.35)
        if drop.size:
            cut = start + int(drop[0].item())
            fade = max(1, round(height * 0.004))
            ramp = cp.clip((cut - cp.arange(alpha.shape[0])) / fade, 0, 1)
            result[..., 3] = (alpha * ramp[:, None]).astype(cp.uint8)
        return result

    def clean(self, result, opts):
        cp = self.cp
        alpha = result[..., 3]
        if opts.threshold > 0:
            alpha = cp.where(alpha < opts.threshold, 0, alpha)
        if opts.erode > 0:
            alpha = self.nd.minimum_filter(alpha, size=opts.erode * 2 + 1, mode="nearest")
        result[..., 3] = alpha
        if opts.defringe:
            blurred = self.nd.gaussian_filter(result[..., :3], sigma=(2, 2, 0), mode="nearest")
            edge = ((alpha > 5) & (alpha < 250))[..., None]
            result[..., :3] = cp.where(edge, cp.rint(blurred), result[..., :3])
        return result

    def crop(self, result, pad_pct, square):
        cp = self.cp
        visible = result[..., 3] > 8
        rows = cp.flatnonzero(visible.any(axis=1))
        cols = cp.flatnonzero(visible.any(axis=0))
        if not rows.size or not cols.size:
            return result
        x0, x1 = int(cols[0].item()), int(cols[-1].item()) + 1
        y0, y1 = int(rows[0].item()), int(rows[-1].item()) + 1
        pad = round(max(x1 - x0, y1 - y0) * pad_pct / 100)
        x0, y0, x1, y1 = x0 - pad, y0 - pad, x1 + pad, y1 + pad
        if square:
            w, h = x1 - x0, y1 - y0
            if w < h:
                delta = h - w
                x0, x1 = x0 - delta // 2, x1 + delta - delta // 2
            elif h < w:
                delta = w - h
                y0, y1 = y0 - delta // 2, y1 + delta - delta // 2
        canvas = cp.zeros((y1 - y0, x1 - x0, 4), dtype=cp.float32)
        h, w = result.shape[:2]
        sx0, sy0, sx1, sy1 = max(x0, 0), max(y0, 0), min(x1, w), min(y1, h)
        if sx1 > sx0 and sy1 > sy0:
            canvas[sy0-y0:sy1-y0, sx0-x0:sx1-x0] = result[sy0:sy1, sx0:sx1]
        return canvas

    def fit(self, result, size):
        cp = self.cp
        w, h = size
        ih, iw = result.shape[:2]
        scale = min(w / iw, h / ih)
        nw, nh = max(1, round(iw * scale)), max(1, round(ih * scale))
        image = cp.rint(self.resize(result, (nw, nh), rgba=True))
        canvas = cp.zeros((h, w, 4), dtype=cp.float32)
        x, y = (w - nw) // 2, (h - nh) // 2
        canvas[y:y+nh, x:x+nw] = image
        return canvas

    def composite(self, result, background):
        cp = self.cp
        bg = cp.asarray(background, dtype=cp.float32)
        foreground_alpha = result[..., 3:4] / 255
        background_alpha = bg[3] / 255
        alpha = foreground_alpha + background_alpha * (1 - foreground_alpha)
        rgb = (result[..., :3] * foreground_alpha + bg[:3] * background_alpha *
               (1 - foreground_alpha)) / cp.maximum(alpha, 1.e-8)
        return cp.concatenate((cp.where(alpha > 0, rgb, 0), alpha * 255), axis=2)

    def _matting_alpha(self, rgb, mask):
        """Closed-form matting with a matrix-free CUDA Laplacian and CG.

        Solve only unknown trimap pixels. Known foreground/background are exact
        constraints, as in the CPU path; no approximate penalty or CPU solver.
        """
        cp = self.cp
        nd = self.nd
        h, w = mask.shape
        structure = cp.ones((11, 11), dtype=cp.bool_)
        foreground = nd.binary_erosion(mask > 240, structure=structure)
        background = nd.binary_erosion(mask < 20, structure=structure, border_value=1)
        if not bool(foreground.any().item()) or not bool(background.any().item()) or min(h, w) < 3:
            return None
        known = foreground | background
        indices = cp.flatnonzero(~known.ravel())
        fixed = foreground.astype(cp.float64)
        if not indices.size:
            return fixed.astype(cp.float32)
        image = rgb.astype(cp.float64) / 255
        mean = nd.uniform_filter(image, size=(3, 3, 1), mode="constant")
        # Symmetric covariance and its explicit 3x3 inverse avoid a large
        # collection of tiny cuSOLVER allocations.
        covariance = {}
        for i in range(3):
            for j in range(i, 3):
                covariance[i, j] = (nd.uniform_filter(image[..., i] * image[..., j],
                    size=3, mode="constant") - mean[..., i] * mean[..., j]
                    + (1.e-7 / 9 if i == j else 0))
        a, b, c = covariance[0, 0], covariance[0, 1], covariance[0, 2]
        d, e, f = covariance[1, 1], covariance[1, 2], covariance[2, 2]
        co00, co01, co02 = d*f-e*e, c*e-b*f, b*e-c*d
        co11, co12, co22 = a*f-c*c, b*c-a*e, a*d-b*b
        determinant = cp.maximum(a*co00 + b*co01 + c*co02, 1.e-30)
        inverse = cp.stack((co00, co01, co02, co01, co11, co12, co02, co12, co22), axis=-1)
        inverse = inverse.reshape(h, w, 3, 3) / determinant[..., None, None]
        del covariance, a, b, c, d, e, f, co00, co01, co02, co11, co12, co22, determinant
        centers = cp.zeros((h, w), dtype=cp.float64)
        centers[1:-1, 1:-1] = 1
        count = nd.uniform_filter(centers, size=3, mode="constant") * 9

        def laplacian(x):
            local_mean = nd.uniform_filter(x, size=3, mode="constant")
            correlation = nd.uniform_filter(image*x[..., None], size=(3, 3, 1), mode="constant")
            v = correlation - mean*local_mean[..., None]
            slope = (inverse*v[..., None, :]).sum(axis=-1)
            offset = local_mean - (slope*mean).sum(axis=2)
            slope *= centers[..., None]
            offset *= centers
            sum_slope = nd.uniform_filter(slope, size=(3, 3, 1), mode="constant") * 9
            sum_offset = nd.uniform_filter(offset, size=3, mode="constant") * 9
            return count*x - sum_offset - (image*sum_slope).sum(axis=2)

        def multiply(x):
            full = cp.zeros((h*w,), dtype=cp.float64)
            full[indices] = x
            return laplacian(full.reshape(h, w)).ravel()[indices]

        rhs = -laplacian(fixed).ravel()[indices]
        x = mask.ravel()[indices].astype(cp.float64) / 255
        residual = rhs - multiply(x)
        preconditioner = cp.maximum(count.ravel()[indices], 1.e-6)
        z = residual / preconditioner
        direction = z.copy()
        rz = (residual*z).sum()
        tolerance = max(float((rhs*rhs).sum().item()) * 1.e-12, 1.e-14)
        converged = False
        for _ in range(2000):
            if float((residual*residual).sum().item()) <= tolerance:
                converged = True
                break
            product = multiply(direction)
            denominator = (direction*product).sum()
            if float(denominator.item()) <= 0:
                break
            step = rz / denominator
            x += step*direction
            residual -= step*product
            z = residual / preconditioner
            next_rz = (residual*z).sum()
            direction = z + next_rz / cp.maximum(rz, 1.e-30)*direction
            rz = next_rz
        if not converged:
            raise RuntimeError("CUDA alpha matting chưa hội tụ; không xuất mặt nạ chưa hoàn chỉnh")
        fixed.ravel()[indices] = cp.clip(x, 0, 1)
        return fixed.astype(cp.float32)

    def _foreground(self, image, alpha):
        """Multilevel foreground/background estimation, parallel CUDA updates."""
        cp = self.cp
        h, w = alpha.shape
        image = image / 255
        fg_mask, bg_mask = alpha > 0.9, alpha < 0.1
        foreground = ((image*fg_mask[..., None]).sum(axis=(0, 1)) /
                      cp.maximum(fg_mask.sum(), 1)).reshape(1, 1, 3)
        background = ((image*bg_mask[..., None]).sum(axis=(0, 1)) /
                      cp.maximum(bg_mask.sum(), 1)).reshape(1, 1, 3)
        levels = max(1, math.ceil(math.log2(max(h, w))))

        def nearest(array, nh, nw):
            yy = cp.arange(nh)*array.shape[0] // nh
            xx = cp.arange(nw)*array.shape[1] // nw
            return array[yy[:, None], xx[None, :]]

        for level in range(levels + 1):
            nh, nw = max(1, round(h**(level/levels))), max(1, round(w**(level/levels)))
            rgb, a = nearest(image, nh, nw), nearest(alpha, nh, nw)
            foreground, background = nearest(foreground, nh, nw), nearest(background, nh, nw)
            padded = cp.pad(a, 1, mode="edge")
            neighbors = (padded[1:-1, :-2], padded[1:-1, 2:], padded[:-2, 1:-1], padded[2:, 1:-1])
            weights = [1.e-5 + cp.abs(a-neighbor) for neighbor in neighbors]
            smoothness = sum(weights)
            aa, ab, bb = a*a+smoothness, a*(1-a), (1-a)**2+smoothness
            determinant = cp.maximum(aa*bb-ab*ab, 1.e-12)[..., None]
            # Jacobi updates are simultaneous on GPU; use more sweeps than
            # the CPU's in-place updates to propagate the same local constraints.
            for _ in range(20 if max(nh, nw) <= 32 else 10):
                pf = cp.pad(foreground, ((1, 1), (1, 1), (0, 0)), mode="edge")
                pb = cp.pad(background, ((1, 1), (1, 1), (0, 0)), mode="edge")
                f_neighbors = (pf[1:-1, :-2], pf[1:-1, 2:], pf[:-2, 1:-1], pf[2:, 1:-1])
                b_neighbors = (pb[1:-1, :-2], pb[1:-1, 2:], pb[:-2, 1:-1], pb[2:, 1:-1])
                f_rhs = a[..., None]*rgb + sum(weight[..., None]*neighbor
                    for weight, neighbor in zip(weights, f_neighbors))
                b_rhs = (1-a[..., None])*rgb + sum(weight[..., None]*neighbor
                    for weight, neighbor in zip(weights, b_neighbors))
                foreground = cp.clip((bb[..., None]*f_rhs-ab[..., None]*b_rhs) / determinant, 0, 1)
                background = cp.clip((aa[..., None]*b_rhs-ab[..., None]*f_rhs) / determinant, 0, 1)
        return foreground * 255

    def matting(self, original, result, log):
        cp = self.cp
        # Recover the mask independently of existing input transparency.
        mask = cp.rint(result[..., 3]*255 / cp.maximum(original[..., 3], 1))
        alpha = self._matting_alpha(original[..., :3], mask)
        if alpha is None:
            log("      (alpha matting: chưa đủ vùng nền/chủ thể chắc chắn; giữ mặt nạ AI)")
            return result
        foreground = self._foreground(original[..., :3], alpha)
        return cp.concatenate((foreground, alpha[..., None]*255), axis=2).astype(cp.uint8).astype(cp.float32)

    def process(self, original, session, opts, log):
        self.device.use()
        cp = self.cp
        pixels, result = self.infer(original, session)
        self.release_cache()
        if opts.matting:
            result = self.matting(pixels, result, log)
        do_bright, key = opts.keep_bright, opts.key_color
        if opts.auto and not do_bright:
            solid, color = self.solid_background(pixels)
            if solid:
                do_bright, key = True, color
                log(f"      (auto: phát hiện nền đơn sắc {color} -> giữ chi tiết sáng)")
        if do_bright:
            above = None
            if opts.bright_above is not None:
                above = (self.shoulder(result[..., 3] / 255) if str(opts.bright_above).lower() == "auto"
                         else int(result.shape[0] * float(opts.bright_above) / 100))
                log(f"      (vớt chi tiết bay giới hạn phía trên hàng {above})")
            result = self.bright(pixels, result, opts, key, above)
        if (opts.auto or opts.keep_bright) and not opts.no_trim_base:
            result = self.trim_base(result)
        if opts.cut_below is not None:
            h = result.shape[0]
            fade = max(1, round(h * 0.01))
            ramp = cp.clip((h * opts.cut_below / 100 + fade - cp.arange(h)) / fade, 0, 1)
            result[..., 3] = (result[..., 3] * ramp[:, None]).astype(cp.uint8)
        if opts.threshold or opts.erode or opts.defringe:
            result = self.clean(result, opts)
        if opts.crop:
            result = self.crop(result, opts.pad, opts.square)
        if opts.size is not None:
            result = self.fit(result, opts.size)
        if opts.bg is not None:
            result = self.composite(result, tuple(opts.bg))
        host = cp.asnumpy(cp.clip(cp.rint(result), 0, 255).astype(cp.uint8))
        return Image.fromarray(host, "RGBA")
