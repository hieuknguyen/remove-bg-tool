"""Qt Quick frontend. Backend work stays outside the UI thread."""

import importlib
from pathlib import Path
import sys
import threading
import time

from PySide6.QtCore import QObject, Property, QTimer, QUrl, Signal, Slot, QSize, Qt
from PySide6.QtGui import QDesktopServices, QFont, QImage, QImageReader, QSurfaceFormat
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickImageProvider
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication, QMessageBox

HERE = Path(__file__).resolve().parent


def human_time(seconds):
    seconds = int(max(0, seconds))
    if seconds < 60:
        return f"{seconds} giây"
    if seconds < 3600:
        return f"{seconds // 60} phút {seconds % 60} giây"
    return f"{seconds // 3600} giờ {(seconds % 3600) // 60} phút"


class PreviewProvider(QQuickImageProvider):
    """Qt decodes thumbnails off the main thread; never uploads full-size photos."""

    def __init__(self):
        super().__init__(QQuickImageProvider.ImageType.Image)
        self.paths = {}
        self.lock = threading.Lock()

    def set_paths(self, source, result):
        with self.lock:
            self.paths = {"original": source, "result": result}

    def requestImage(self, image_id, size, requested_size):
        kind = image_id.split("/")[0]
        with self.lock:
            path = self.paths.get(kind)
        image = QImage()
        if path and Path(path).is_file():
            reader = QImageReader(str(path))
            reader.setAutoTransform(True)
            original = reader.size()
            target = QSize(1600, 1200)
            if original.isValid() and (original.width() > target.width() or original.height() > target.height()):
                reader.setScaledSize(original.scaled(target, Qt.AspectRatioMode.KeepAspectRatio))
            image = reader.read()
        if size is not None:
            size.setWidth(image.width())
            size.setHeight(image.height())
        return image


class WorkerSignals(QObject):
    log = Signal(str)
    device = Signal(str)
    progress = Signal(int, int, str)
    prepared = Signal(object)
    completed = Signal(object)
    failed = Signal(str)


class Controller(QObject):
    optionsChanged = Signal()
    stateChanged = Signal()
    previewChanged = Signal()
    logsChanged = Signal()
    errorOccurred = Signal(str)

    def __init__(self, modes, models, previews):
        super().__init__()
        self._modes, self._models = modes, models
        self.previews = previews
        self.backend = None
        self._options = {"input": str(HERE / "input"), "output": str(HERE / "output"),
                         "mode": 0, "model": 0, "crop": True, "square": False,
                         "size_on": False, "pad": "6", "size": "2000x2000",
                         "bg": "trong", "color": "255,255,255", "overwrite": False}
        self._ready = self._busy = self._stopping = False
        self._status = "Đang chuẩn bị ứng dụng…"
        self._device = "Đang nhận diện thiết bị"
        self._progress = 0.0
        self._count = 0
        self._logs = ""
        self._preview_revision = 0
        self._preview_kind = "original"
        self._preview_name = "Chọn thư mục ảnh để bắt đầu"
        self._has_original = self._has_result = False
        self.stop_flag = threading.Event()
        self.worker = None
        self.preparation_worker = None
        self.last_input = self.last_output = None
        self.started_at = 0
        self.signals = WorkerSignals(self)
        self.signals.log.connect(self._on_log)
        self.signals.device.connect(self._on_device)
        self.signals.progress.connect(self._on_progress)
        self.signals.prepared.connect(self._on_prepared)
        self.signals.completed.connect(self._on_completed)
        self.signals.failed.connect(self._on_failed)
        self.count_timer = QTimer(self)
        self.count_timer.setSingleShot(True)
        self.count_timer.setInterval(350)
        self.count_timer.timeout.connect(self.refresh)

    @Property("QVariantMap", notify=optionsChanged)
    def options(self):
        return dict(self._options)

    @Property("QVariantList", constant=True)
    def modeItems(self):
        titles = ("Thủy tinh", "Chi tiết phía trên", "Chi tiết toàn ảnh",
                  "Tự động", "Làm sạch viền", "AI tiêu chuẩn")
        details = ("Ly, chai, vật thể trong suốt", "Giữ tia sáng, làm sạch đáy",
                   "Ảnh nền tối hoặc đơn sắc", "Nhận diện nền của ảnh",
                   "Tách nền và tinh chỉnh biên", "Xóa nền bằng model AI")
        return [{"title": title, "detail": detail} for title, detail in zip(titles, details)]

    @Property("QStringList", constant=True)
    def modelItems(self):
        return ["Tự chọn theo chế độ" if value is None else value for label, value in self._models]

    @Property(bool, notify=stateChanged)
    def ready(self):
        return self._ready

    @Property(bool, notify=stateChanged)
    def busy(self):
        return self._busy

    @Property(bool, notify=stateChanged)
    def stopping(self):
        return self._stopping

    @Property(str, notify=stateChanged)
    def status(self):
        return self._status

    @Property(str, notify=stateChanged)
    def device(self):
        return self._device

    @Property(float, notify=stateChanged)
    def progress(self):
        return self._progress

    @Property(int, notify=stateChanged)
    def count(self):
        return self._count

    @Property(str, notify=logsChanged)
    def logs(self):
        return self._logs

    @Property(str, notify=previewChanged)
    def previewSource(self):
        present = self._has_result if self._preview_kind == "result" else self._has_original
        return f"image://preview/{self._preview_kind}/{self._preview_revision}" if present else ""

    @Property(str, notify=previewChanged)
    def previewKind(self):
        return self._preview_kind

    @Property(str, notify=previewChanged)
    def previewName(self):
        return self._preview_name

    @Slot()
    def prepare(self):
        def initialize():
            try:
                from gpu_runtime import activate_runtime
                activate_runtime(install=True, gui=False, log=self.signals.log.emit,
                                 should_stop=self.stop_flag.is_set)
                if self.stop_flag.is_set():
                    return
                self.signals.prepared.emit(importlib.import_module("remove_bg"))
            except Exception as error:
                self.signals.failed.emit(str(error))
        self.preparation_worker = threading.Thread(target=initialize, daemon=True)
        self.preparation_worker.start()

    @Slot()
    def shutdown(self):
        self.stop_flag.set()
        # Give a pending installer time to terminate its child process cleanly.
        if self.preparation_worker is not None and self.preparation_worker.is_alive():
            self.preparation_worker.join(timeout=2)

    @Slot(object)
    def _on_prepared(self, module):
        self.backend = module
        self._ready = True
        self._status = "Sẵn sàng để xóa nền"
        self._device = module.device_label()
        self.refresh()
        self.stateChanged.emit()

    @Slot(str, "QVariant")
    def setOption(self, key, value):
        if self._busy or key not in self._options:
            return
        if key in ("mode", "model"):
            value = int(value)
            limit = len(self._modes if key == "mode" else self._models)
            if not 0 <= value < limit:
                return
        elif key in ("crop", "square", "size_on", "overwrite"):
            value = bool(value)
        else:
            value = str(value)
        if self._options[key] != value:
            self._options[key] = value
            self.optionsChanged.emit()
            if key in ("input", "output"):
                self.count_timer.start()

    @Slot(str, result=QUrl)
    def folderUrl(self, key):
        path = Path(self._options.get(key, str(HERE)))
        return QUrl.fromLocalFile(str(path if path.is_dir() else HERE))

    @Slot(str, QUrl)
    def setFolder(self, key, url):
        if url.isLocalFile():
            self.setOption(key, url.toLocalFile())

    @Slot(str)
    def selectPreview(self, kind):
        if kind in ("original", "result"):
            self._preview_kind = kind
            self.previewChanged.emit()

    def _set_preview(self, source=None, result=None):
        self._has_original = bool(source and Path(source).is_file())
        self._has_result = bool(result and Path(result).is_file())
        self.previews.set_paths(source, result)
        self._preview_name = Path(source).name if source else "Chọn thư mục ảnh để bắt đầu"
        self._preview_revision += 1
        self.previewChanged.emit()

    @Slot()
    def refresh(self):
        if self.backend is None or self._busy:
            return
        try:
            images = self.backend.list_images(self._options["input"])
            self._count = len(images)
            source = images[0] if images else None
            result = Path(self._options["output"]) / (source.stem + ".png") if source else None
            self._set_preview(source, result)
        except (OSError, ValueError):
            self._count = 0
            self._set_preview()
        self.stateChanged.emit()

    def _collect(self):
        state = self._options
        opts = dict(self._modes[state["mode"]][1])
        opts.update(input=state["input"], output=state["output"], overwrite=state["overwrite"])
        model = self._models[state["model"]][1]
        if model:
            opts["model"] = model
        if state["crop"]:
            try:
                padding = float(state["pad"])
            except ValueError:
                raise ValueError("Lề phải là một con số, ví dụ 6") from None
            opts.update(crop=True, pad=padding, square=state["square"])
        if state["size_on"]:
            opts["size"] = self.backend.parse_size(state["size"])
        if state["bg"] == "trang":
            opts["bg"] = (255, 255, 255, 255)
        elif state["bg"] == "khac":
            opts["bg"] = self.backend.parse_bg(state["color"])
        return self.backend.make_options(**opts)

    @Slot()
    def start(self):
        if not self._ready or self._busy:
            return
        try:
            opts = self._collect()
        except Exception as error:
            self.errorOccurred.emit(str(error))
            return
        self._busy, self._stopping = True, False
        self._progress = 0
        self._status = "Đang tải model…"
        self._logs = ""
        self.last_input, self.last_output = opts.input, opts.output
        self.started_at = time.monotonic()
        self.stop_flag.clear()
        self.logsChanged.emit()
        self.stateChanged.emit()

        def work():
            try:
                result = self.backend.run_batch(opts, log=self.signals.log.emit,
                    on_progress=self.signals.progress.emit, should_stop=self.stop_flag.is_set,
                    on_device=self.signals.device.emit)
                self.signals.completed.emit(result)
            except Exception as error:
                self.signals.failed.emit(str(error))
        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    @Slot()
    def stop(self):
        if self._busy:
            self.stop_flag.set()
            self._stopping = True
            self._status = "Đang dừng sau ảnh hiện tại…"
            self.stateChanged.emit()

    @Slot()
    def openOutput(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_output or self._options["output"])))

    @Slot(str)
    def _on_log(self, message):
        self._logs += message + "\n"
        self.logsChanged.emit()
        if not self._ready:
            self._status = message
            self.stateChanged.emit()

    @Slot(str)
    def _on_device(self, label):
        self._device = label
        self.stateChanged.emit()

    @Slot(int, int, str)
    def _on_progress(self, done, total, name):
        self._progress = done / max(1, total)
        elapsed = time.monotonic() - self.started_at
        eta = elapsed / max(1, done) * (total - done)
        self._status = f"{done}/{total} ảnh · còn khoảng {human_time(eta)}"
        self._set_preview(Path(self.last_input) / name,
                          Path(self.last_output) / (Path(name).stem + ".png"))
        self.stateChanged.emit()

    @Slot(object)
    def _on_completed(self, result):
        self._busy = self._stopping = False
        prefix = "Đã dừng" if result["stopped"] else "Xong"
        self._status = (f"{prefix}: {result['ok']} thành công, {result['skipped']} bỏ qua, "
                        f"{result['failed']} lỗi · {human_time(result['seconds'])}")
        if not result["stopped"]:
            self._progress = 1
        if result["ok"] and self._has_result:
            self.selectPreview("result")
        self.stateChanged.emit()

    @Slot(str)
    def _on_failed(self, message):
        self._busy = self._stopping = False
        self._status = "Có lỗi. Xem nhật ký để biết chi tiết."
        self._on_log("[LỖI] " + message)
        self.stateChanged.emit()
        self.errorOccurred.emit(message)


def run(modes, models):
    QQuickStyle.setStyle("Basic")
    surface = QSurfaceFormat()
    surface.setSamples(4)
    QSurfaceFormat.setDefaultFormat(surface)
    app = QApplication(sys.argv)
    app.setApplicationName("Xóa nền ảnh")
    app.setOrganizationName("Photo Studio")
    app.setFont(QFont("Segoe UI", 10))
    engine = QQmlApplicationEngine()
    previews = PreviewProvider()
    controller = Controller(modes, models, previews)
    engine.addImageProvider("preview", previews)
    engine.rootContext().setContextProperty("controller", controller)
    engine.load(QUrl.fromLocalFile(str(HERE / "ui" / "Main.qml")))
    if not engine.rootObjects():
        QMessageBox.critical(None, "Không mở được giao diện", "Không tải được ui/Main.qml.")
        return 1
    app.aboutToQuit.connect(controller.shutdown)
    QTimer.singleShot(0, controller.prepare)
    return app.exec()
