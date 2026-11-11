"""Detect the host GPU and prepare an isolated ONNX runtime before importing rembg.

GPU wheels live beside the project, not over the CPU installation. This keeps
CPU fallback available and avoids replacing DLLs used by an already open app.
"""

import csv
import ctypes
import hashlib
from functools import lru_cache
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time


HERE = Path(__file__).resolve().parent
RUNTIME_DIR = HERE / ".gpu-runtime"
_state = {"backend": "cpu", "name": "CPU", "notes": []}
_dll_directories = []
_dll_paths = set()

for stream in (sys.stdout, sys.stderr):
    if stream is not None and hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")


def _command(args, timeout=10):
    kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=timeout, **kwargs)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Không đọc được thông tin GPU")
    return result.stdout.strip()


def _cuda_version():
    try:
        driver = ctypes.WinDLL("nvcuda.dll") if os.name == "nt" else ctypes.CDLL("libcuda.so.1")
        version = ctypes.c_int()
        if driver.cuDriverGetVersion(ctypes.byref(version)) == 0:
            return version.value
    except (OSError, AttributeError):
        pass
    return 0


@lru_cache(maxsize=1)
def detect_hardware():
    """Prefer a compatible NVIDIA device; otherwise use Windows DirectML / CoreML."""
    try:
        rows = _command(["nvidia-smi", "--query-gpu=index,name,compute_cap,memory.total,uuid",
                         "--format=csv,noheader,nounits"])
        devices = []
        for row in csv.reader(rows.splitlines()):
            index, name, capability, memory, uuid = (part.strip() for part in row)
            devices.append({"device_id": int(index), "name": name,
                            "capability": float(capability), "memory_mb": int(float(memory)),
                            "uuid": uuid})
        visible = os.getenv("CUDA_VISIBLE_DEVICES")
        if visible is not None:
            mapped = []
            for selector in visible.split(","):
                selector = selector.strip()
                match = next((device for device in devices
                              if selector == str(device["device_id"])
                              or (selector.startswith("GPU-") and device["uuid"].startswith(selector))), None)
                if match is None:
                    break  # CUDA only exposes the valid prefix of the visibility list.
                mapped.append({**match, "device_id": len(mapped)})
            devices = mapped
        devices.sort(key=lambda device: device["memory_mb"], reverse=True)
        for device in devices:
            if device["capability"] >= 7.5 and _cuda_version() >= 12080:
                return {**device, "backend": "cuda12"}
        if devices and sys.platform == "win32":
            return {"backend": "directml", "name": devices[0]["name"], "device_id": 0}
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
        pass

    if sys.platform == "win32":
        try:
            script = "Get-CimInstance Win32_VideoController | Select-Object Name,PNPDeviceID | ConvertTo-Json -Compress"
            controllers = json.loads(_command(["powershell.exe", "-NoProfile", "-NonInteractive",
                                               "-Command", script]))
            if isinstance(controllers, dict):
                controllers = [controllers]
            for device in controllers or []:
                name = device.get("Name", "")
                pnp = (device.get("PNPDeviceID") or "").upper()
                # Exclude remote/virtual adapters and Microsoft's software renderer.
                if any(vendor in pnp for vendor in ("VEN_10DE", "VEN_1002", "VEN_8086")):
                    return {"backend": "directml", "name": name, "device_id": 0}
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
            pass
    elif sys.platform == "darwin":
        return {"backend": "coreml", "name": "Apple GPU / CoreML", "device_id": 0}
    return {"backend": "cpu", "name": "CPU", "device_id": 0}


def runtime_target(backend):
    return RUNTIME_DIR / f"{backend}-{sys.implementation.cache_tag}-{platform.machine().lower()}"


def _ready(target):
    module = "cupy" if target.name.startswith("images-cuda12-") else "onnxruntime"
    return (target / "ready.json").is_file() and (target / module / "__init__.py").is_file()


def _install(backend, gui=False, log=print, should_stop=None):
    """Only publish a complete runtime; a failed download leaves CPU intact."""
    if should_stop is not None and should_stop():
        raise RuntimeError("Đã dừng chuẩn bị thư viện GPU")
    RUNTIME_DIR.mkdir(exist_ok=True)
    target = runtime_target(backend)
    requirement = HERE / {"cuda12": "requirements-gpu-cuda.txt",
                          "directml": "requirements-gpu-directml.txt",
                          "images-cuda12": "requirements-gpu-images.txt"}[backend]
    log(f"Đang chuẩn bị GPU ({backend}). Thư viện chỉ được tải ở lần đầu…")
    splash = None
    cancelled = [False]
    if gui:
        try:
            import tkinter as tk
            from tkinter import ttk
            splash = tk.Tk()
            splash.title("Chuẩn bị GPU")
            splash.geometry("480x185")
            splash.resizable(False, False)
            ttk.Label(splash, text="Đang chuẩn bị bộ xử lý GPU", font=("Segoe UI", 14, "bold")).pack(pady=(22, 8))
            ttk.Label(splash, text="Lần đầu cần tải thư viện GPU. Các lần sau sẽ mở ngay.",
                      font=("Segoe UI", 10)).pack()
            progress = ttk.Progressbar(splash, mode="indeterminate", length=420)
            progress.pack(pady=15)
            progress.start(12)
            ttk.Button(splash, text="Bỏ qua, dùng CPU", command=lambda: cancelled.__setitem__(0, True)).pack()
            splash.protocol("WM_DELETE_WINDOW", lambda: cancelled.__setitem__(0, True))
            splash.update()
        except Exception:
            if splash is not None:
                splash.destroy()
            splash = None
    kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    try:
        with tempfile.TemporaryDirectory(prefix="install-", dir=RUNTIME_DIR) as staging:
            command = [sys.executable, "-m", "pip", "install", "--no-cache-dir", "--no-deps",
                       "--only-binary=:all:", "--retries", "1", "--index-url", "https://pypi.org/simple",
                       "--target", staging, "-r", str(requirement)]
            with (RUNTIME_DIR / "setup.log").open("w", encoding="utf-8") as output:
                process = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT, **kwargs)
                try:
                    while process.poll() is None:
                        if splash is not None:
                            splash.update()
                        if cancelled[0] or (should_stop is not None and should_stop()):
                            process.terminate()
                            raise RuntimeError("Đã bỏ qua cài thư viện GPU")
                        time.sleep(0.10)
                    if process.returncode:
                        raise RuntimeError(f"Không cài được runtime GPU; chi tiết: {RUNTIME_DIR / 'setup.log'}")
                finally:
                    if process.poll() is None:
                        process.terminate()
                    process.wait()
            (Path(staging) / "ready.json").write_text(json.dumps({"backend": backend,
                "python": sys.implementation.cache_tag}), encoding="utf-8")
            if _ready(target):
                # Another app may have completed installation while this one downloaded.
                # Leave its runtime in place: Windows can have its DLLs open already.
                return
            if target.exists():
                # Retain an incomplete previous install for diagnosis; never delete an arbitrary path.
                target.rename(target.with_name(target.name + f"-old-{time.time_ns()}"))
            Path(staging).rename(target)
        log("Thư viện GPU đã sẵn sàng.")
    finally:
        if splash is not None:
            splash.destroy()


def activate_runtime(install=False, gui=False, log=print, should_stop=None):
    """Must run before onnxruntime/rembg is imported; never swap a loaded DLL."""
    global _state
    hardware = detect_hardware()
    backend = hardware["backend"]
    notes = []
    images_ready = False
    if backend in ("cuda12", "directml"):
        target = runtime_target(backend)
        if not _ready(target) and install and "onnxruntime" not in sys.modules:
            try:
                _install(backend, gui, log, should_stop)
            except Exception as error:
                notes.append(f"GPU chưa sẵn sàng: {error}. Tạm dùng CPU.")
                log(notes[-1])
        if _ready(target):
            if "onnxruntime" not in sys.modules or str(target) in str(sys.modules["onnxruntime"].__file__):
                if str(target) not in sys.path:
                    sys.path.insert(0, str(target))
                roots = [target]
                if backend == "cuda12":
                    images = runtime_target("images-cuda12")
                    if not _ready(images) and install:
                        try:
                            _install("images-cuda12", gui, log, should_stop)
                        except Exception as error:
                            notes.append(f"Chưa chuẩn bị được xử lý ảnh CUDA: {error}")
                            log(notes[-1])
                    if _ready(images):
                        if str(images) not in sys.path:
                            sys.path.insert(0, str(images))
                        roots.append(images)
                        images_ready = True
                if os.name == "nt":
                    directories = [directory for root in roots for directory in root.glob("nvidia/*/bin")
                                   if str(directory) not in _dll_paths]
                    for directory in directories:
                        _dll_directories.append(os.add_dll_directory(str(directory)))
                        _dll_paths.add(str(directory))
                    # cuDNN dynamically loads its engine DLLs with the Windows loader.
                    # That loader also needs PATH, beyond Python's add_dll_directory.
                    if directories:
                        os.environ["PATH"] = os.pathsep.join(map(str, directories)) + os.pathsep + os.environ.get("PATH", "")
            else:
                notes.append("Runtime CPU đã được nạp; cần mở lại ứng dụng để kích hoạt GPU.")
                backend = "cpu"
        else:
            backend = "cpu"
            if not notes:
                notes = list(_state.get("notes", [])) or [
                    "Chưa có runtime GPU. Mở ứng dụng hoặc chạy gpu_runtime.py để tự chuẩn bị."]
    _state = {**hardware, "backend": backend, "notes": notes, "images_ready": images_ready}
    return dict(_state)


def runtime_info():
    return dict(_state)


def _cuda_profile_path(model, ort_version):
    info = runtime_info()
    # Keep settings separate for different hardware, models and runtime pins.
    manifest = (HERE / "requirements-gpu-cuda.txt").read_bytes()
    identity = json.dumps([info.get("uuid", info.get("name")),
                           info.get("capability"), _cuda_version(), model,
                           ort_version, hashlib.sha256(manifest).hexdigest()])
    key = hashlib.sha256(identity.encode()).hexdigest()
    return RUNTIME_DIR / "profiles" / (key + ".json")


def cuda_algorithm_for(model, ort_version):
    try:
        algorithm = json.loads(_cuda_profile_path(model, ort_version).read_text(
            encoding="utf-8"))["algorithm"]
        if algorithm in ("DEFAULT", "EXHAUSTIVE"):
            return algorithm
    except (OSError, ValueError, KeyError, TypeError):
        pass
    # Prefer the fallback engines first: the user's GTX 1650 log confirms
    # DEFAULT completes inference whereas EXHAUSTIVE fails at cuDNN Frontend.
    return "DEFAULT"


def remember_cuda_algorithm(model, ort_version, algorithm):
    if algorithm not in ("DEFAULT", "EXHAUSTIVE"):
        return
    temporary = None
    try:
        target = _cuda_profile_path(model, ort_version)
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".tmp",
                                         dir=target.parent, delete=False) as output:
            temporary = Path(output.name)
            json.dump({"model": model, "algorithm": algorithm}, output)
        temporary.replace(target)
    except OSError:
        # A read-only project must not invalidate a completed GPU inference.
        pass
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


if __name__ == "__main__":
    info = activate_runtime(install=True)
    print(f"Thiết bị: {info['name']} · runtime: {info['backend']}")
    if info["notes"]:
        sys.exit(1)
