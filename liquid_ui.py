"""Liquid glass surfaces and controls for the native Tk desktop application.

The backdrop is composited through each glass surface with Pillow. Text and
editable fields remain native Tk objects, so Vietnamese input stays reliable.
"""

from functools import lru_cache
import tkinter as tk

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps, ImageTk


INK = "#222749"
MUTED = "#53617f"
BLUE = "#4954dc"


@lru_cache(maxsize=128)
def rounded_mask(width, height, radius, inset=0):
    scale = 2
    mask = Image.new("L", (width * scale, height * scale))
    ImageDraw.Draw(mask).rounded_rectangle(
        (inset * scale, inset * scale,
         (width - inset) * scale - 1, (height - inset) * scale - 1),
        radius=max(0, radius - inset) * scale, fill=255)
    return mask.resize((width, height), Image.Resampling.LANCZOS)


def backdrop(width, height):
    """A continuous color field: every pane receives the colors behind it."""
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    x /= width
    y /= height
    pixels = np.empty((height, width, 3), dtype=np.float32)
    pixels[:] = (232, 237, 255)
    for cx, cy, sx, sy, color, strength in (
        (0.04, 0.38, 0.36, 0.42, (146, 192, 255), 0.72),
        (0.87, 0.08, 0.34, 0.38, (164, 167, 246), 0.66),
        (0.66, 0.92, 0.40, 0.46, (208, 160, 245), 0.74),
        (0.23, 0.04, 0.28, 0.23, (251, 252, 255), 0.76),
        (0.98, 0.64, 0.24, 0.36, (187, 218, 255), 0.64),
    ):
        amount = np.exp(-(((x - cx) / sx) ** 2 + ((y - cy) / sy) ** 2))
        amount = (amount * strength)[..., None]
        pixels = pixels * (1 - amount) + np.array(color) * amount
    # A broad curved band remains visible through the refracted panes.
    curve = 0.45 + 0.13 * np.sin(x * 5.5 - 0.8)
    amount = (np.exp(-((y - curve) / 0.055) ** 2) * 0.14)[..., None]
    pixels = pixels * (1 - amount) + np.array((111, 172, 232)) * amount
    scene = Image.fromarray(np.uint8(np.clip(pixels, 0, 255)), "RGB").convert("RGBA")
    # Broad translucent ribbons give the panels something visible to diffuse.
    ribbons = Image.new("RGBA", scene.size)
    draw = ImageDraw.Draw(ribbons)
    for offset, color in ((0, (255, 255, 255, 65)), (48, (143, 152, 255, 22))):
        points = [(int(t * width), int((0.58 - 0.29 * t + 0.11 * np.sin(t * 6)) * height + offset))
                  for t in np.linspace(-0.1, 1.1, 80)]
        draw.line(points, fill=color, width=max(24, height // 11), joint="curve")
    scene.alpha_composite(ribbons.filter(ImageFilter.GaussianBlur(8)))
    return scene


def glass(scene, box, radius=24, opacity=0.32, tint=(255, 255, 255), shadow=False):
    """Blur and refract the backdrop, then add a curved specular glass edge."""
    x, y, width, height = map(int, box)
    if width < 4 or height < 4:
        return
    mask = rounded_mask(width, height, radius)
    if shadow:
        shadow_layer = Image.new("RGBA", scene.size)
        shadow_alpha = Image.new("L", scene.size)
        shadow_alpha.paste(mask.point(lambda value: int(value * 0.15)), (x, y + 8))
        shadow_alpha = shadow_alpha.filter(ImageFilter.GaussianBlur(14))
        shadow_layer.paste((42, 57, 100, 255), (0, 0, scene.width, scene.height))
        shadow_layer.putalpha(shadow_alpha)
        scene.alpha_composite(shadow_layer)
    region = scene.crop((x - 3, y - 3, x + width + 3, y + height + 3))
    region = region.resize((width, height), Image.Resampling.BICUBIC)
    region = region.filter(ImageFilter.GaussianBlur(12))
    # Milky highlights vary down the surface instead of using a solid fill.
    rows = np.linspace(opacity + 0.17, opacity, height).clip(0, 0.86)
    alpha = np.repeat(np.uint8(rows[:, None] * 255), width, axis=1)
    film = Image.new("RGBA", (width, height), (*tint, 255))
    film.putalpha(Image.fromarray(alpha, "L"))
    region = Image.alpha_composite(region, film)
    scene.paste(region, (x, y), mask)
    if radius >= 18:
        # A narrow lens rim bends the underlying colors around the glass edge.
        lens = scene.crop((x - 8, y - 8, x + width + 8, y + height + 8))
        lens = lens.resize((width, height), Image.Resampling.BICUBIC)
        lens = Image.blend(region, lens, 0.45)
        rim = ImageChops.subtract(mask, rounded_mask(width, height, radius, 4))
        scene.paste(lens, (x, y), rim)
    edge = ImageChops.subtract(mask, rounded_mask(width, height, radius, 1))
    edge_rows = np.linspace(230, 85, height).astype(np.uint8)
    edge_alpha = Image.fromarray(np.repeat(edge_rows[:, None], width, axis=1), "L")
    scene.paste((255, 255, 255, 255), (x, y), ImageChops.multiply(edge, edge_alpha))


def primary_pill(scene, box, hovered=False, disabled=False):
    x, y, width, height = map(int, box)
    top = np.array((70, 108, 243) if hovered else (64, 92, 227))
    bottom = np.array((130, 74, 216))
    if disabled:
        top, bottom = np.array((156, 174, 209)), np.array((143, 160, 193))
    ramp = (np.linspace(0, 1, width)[None, :, None] * 0.82
            + np.linspace(0, 1, height)[:, None, None] * 0.18)
    color = np.uint8(top * (1 - ramp) + bottom * ramp)
    mask = rounded_mask(width, height, height // 2)
    scene.paste(Image.fromarray(color, "RGB"), (x, y), mask)
    edge = ImageChops.subtract(mask, rounded_mask(width, height, height // 2, 1))
    scene.paste((225, 237, 255, 255), (x, y), edge.point(lambda a: int(a * 0.72)))
    if width >= 12 and height >= 12:
        inner = ImageChops.subtract(rounded_mask(width, height, height // 2, 2),
                                    rounded_mask(width, height, height // 2, 3))
        scene.paste((255, 255, 255, 255), (x, y), inner.point(lambda a: int(a * 0.24)))


class LabelHandle:
    def __init__(self, view, key):
        self.view, self.key = view, key

    def config(self, **kwargs):
        if "text" in kwargs:
            self.view.labels[self.key] = kwargs["text"]
            self.view.schedule()

    configure = config


class ButtonHandle:
    def __init__(self, view, key):
        self.view, self.key = view, key

    def config(self, **kwargs):
        if "state" in kwargs:
            self.view.button_states[self.key] = kwargs["state"]
            self.view.schedule()

    configure = config


class ProgressHandle:
    def __init__(self, view):
        self.view = view

    def configure(self, **kwargs):
        self.view.progress.update(kwargs)
        self.view.schedule()

    config = configure

    def __getitem__(self, key):
        return self.view.progress[key]


class LiquidUI:
    MODE_COPY = (
        ("Thủy tinh", "Ly, chai, vật thể trong suốt"),
        ("Chi tiết phía trên", "Giữ tia sáng, làm sạch đáy"),
        ("Chi tiết toàn ảnh", "Phù hợp với nền tối / đơn sắc"),
        ("Tự động", "AI nhận diện nền đơn sắc"),
        ("Làm sạch viền", "Tách nền và tinh chỉnh biên"),
        ("AI tiêu chuẩn", "Xóa nền bằng model AI"),
    )

    def __init__(self, root, app, models):
        self.root, self.app, self.models = root, app, models
        self.labels = {"count": "", "status": "Sẵn sàng để xử lý", "device": "Tự động · Ưu tiên GPU"}
        self.button_states = {"start": "normal", "stop": "disabled"}
        self.progress = {"value": 0, "maximum": 100}
        self.regions = []
        self.hover = None
        self.keyboard_focus = None
        self.focus_visible = False
        self.redraw_job = None
        self.count_job = None
        self.size = None
        self.base_scene = None
        self.page = "studio"
        self.settings_tab = "mode"
        self.preview_kind = "original"
        self.preview_paths = {"original": None, "result": None}
        self.preview_images = {}
        root.configure(bg="#e5eaff")
        self.canvas = tk.Canvas(root, highlightthickness=0, bd=0,
                                bg="#e5eaff", takefocus=True)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", self._resize)
        self.canvas.bind("<Motion>", self._motion)
        self.canvas.bind("<Leave>", self._leave)
        self.canvas.bind("<Button-1>", self._click)
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<Button-4>", lambda event: self.canvas.yview_scroll(-2, "units"))
        self.canvas.bind("<Button-5>", lambda event: self.canvas.yview_scroll(2, "units"))
        self.canvas.bind("<Right>", lambda event: self._move_focus(1))
        self.canvas.bind("<Left>", lambda event: self._move_focus(-1))
        self.canvas.bind("<Down>", lambda event: self._move_focus(1))
        self.canvas.bind("<Up>", lambda event: self._move_focus(-1))
        self.canvas.bind("<Return>", self._activate_focus)
        self.canvas.bind("<space>", self._activate_focus)
        root.bind("<Control-Return>", lambda event: app.start())
        root.bind("<Control-o>", lambda event: app._pick(app.in_var))

        self.entries = {}
        self.windows = {}
        for key, var in (("input", app.in_var), ("output", app.out_var),
                         ("pad", app.pad_var), ("size", app.size_var),
                         ("color", app.bg_custom)):
            entry = tk.Entry(self.canvas, textvariable=var, font=("Segoe UI", -13),
                             fg=INK, insertbackground=BLUE, bd=0, relief="flat",
                             highlightthickness=0, selectbackground="#b9cdfb",
                             selectforeground=INK, disabledforeground="#8998ad")
            self.entries[key] = entry
            self.windows[key] = self.canvas.create_window(0, 0, anchor="nw", window=entry)
        self.entries["input"].bind("<FocusOut>", lambda event: app._count())
        self.entries["input"].bind("<Return>", lambda event: app._count())
        self.logbox = tk.Text(self.canvas, wrap="word", bd=0, relief="flat",
                              highlightthickness=0, font=("Segoe UI", -12), fg=MUTED,
                              padx=0, pady=0, state="disabled", cursor="arrow",
                              selectbackground="#cbd9f5")
        self.windows["log"] = self.canvas.create_window(0, 0, anchor="nw", window=self.logbox)
        self.logbox.bind("<MouseWheel>", self._log_wheel)
        app.logbox = self.logbox
        app.count_lbl = LabelHandle(self, "count")
        app.status = LabelHandle(self, "status")
        app.start_btn = ButtonHandle(self, "start")
        app.stop_btn = ButtonHandle(self, "stop")
        app.prog = ProgressHandle(self)
        for var in (app.in_var, app.out_var, app.mode_var, app.model_var,
                    app.crop_var, app.square_var, app.size_on_var, app.pad_var,
                    app.size_var, app.bg_var, app.bg_custom, app.overwrite_var):
            var.trace_add("write", lambda *args: self.schedule())
        app.in_var.trace_add("write", self._defer_count)
        app.out_var.trace_add("write", self._defer_count)

    def _defer_count(self, *args):
        if self.count_job:
            self.root.after_cancel(self.count_job)
        self.count_job = self.root.after(400, self._count)

    def _count(self):
        self.count_job = None
        self.app._count()

    def _resize(self, event):
        self.schedule(80)

    def schedule(self, delay=20):
        if self.redraw_job:
            self.root.after_cancel(self.redraw_job)
        self.redraw_job = self.root.after(delay, self.render)

    def _text(self, x, y, text, size=13, color=INK, weight="normal", anchor="nw", width=None):
        return self.canvas.create_text(x, y, text=text, fill=color,
                                       font=("Segoe UI", -size, weight), anchor=anchor,
                                       width=width or 0, tags="paint")

    def _region(self, key, box, command, enabled=True):
        if enabled:
            self.regions.append((key, box, command))

    def _at(self, event):
        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        return next((region for region in reversed(self.regions)
                     if region[1][0] <= x <= region[1][0] + region[1][2]
                     and region[1][1] <= y <= region[1][1] + region[1][3]), None)

    def _motion(self, event):
        region = self._at(event)
        key = region[0] if region else None
        self.canvas.configure(cursor="hand2" if key else "")
        if key != self.hover:
            self.hover = key
            self.schedule()

    def _leave(self, event):
        if self.hover:
            self.hover = None
            self.schedule()

    def _click(self, event):
        region = self._at(event)
        if region:
            self.canvas.focus_set()
            self.keyboard_focus = region[0]
            self.focus_visible = False
            region[2]()
            self.schedule()

    def _move_focus(self, step):
        if not self.regions:
            return "break"
        keys = [region[0] for region in self.regions]
        index = keys.index(self.keyboard_focus) if self.keyboard_focus in keys else -1
        self.keyboard_focus = keys[(index + step) % len(keys)]
        self.focus_visible = True
        self.schedule()
        return "break"

    def _activate_focus(self, event):
        region = next((r for r in self.regions if r[0] == self.keyboard_focus), None)
        if region:
            region[2]()
        return "break"

    def _wheel(self, event):
        if self.size and self.canvas.winfo_height() < self.size[1]:
            self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
        return "break"

    def _log_wheel(self, event):
        self.logbox.yview_scroll(-2 if event.delta > 0 else 2, "units")
        return "break"

    def _button(self, scene, key, box, label, command, primary=False, enabled=True):
        x, y, width, height = box
        hovered = key in (self.hover, self.keyboard_focus)
        if primary:
            primary_pill(scene, box, hovered, not enabled)
        else:
            glass(scene, box, radius=height // 2, opacity=0.46 if hovered else 0.27)
        self._text(x + width / 2, y + height / 2, label, 13,
                   "#ffffff" if primary else (INK if enabled else "#8c9aaf"),
                   "bold", anchor="center")
        self._region(key, box, command, enabled)

    def _field(self, scene, key, box, enabled=True, visible=True):
        x, y, width, height = box
        if not visible:
            self.canvas.itemconfigure(self.windows[key], state="hidden")
            return
        glass(scene, box, radius=min(14, height // 2), opacity=0.40)
        color = "#%02x%02x%02x" % scene.getpixel((int(x + width / 2), int(y + height / 2)))[:3]
        entry = self.entries[key]
        entry.configure(bg=color, disabledbackground=color, state="normal" if enabled else "disabled")
        self.canvas.coords(self.windows[key], x + 12, y + 9)
        self.canvas.itemconfigure(self.windows[key], width=max(1, width - 24),
                                   height=height - 18, state="normal")

    def _switch(self, scene, key, x, y, var):
        box = (x, y, 42, 24)
        enabled = bool(var.get())
        glass(scene, box, radius=12, opacity=0.16 if enabled else 0.24,
              tint=(74, 125, 237) if enabled else (255, 255, 255))
        draw = ImageDraw.Draw(scene)
        offset = 20 if enabled else 3
        draw.ellipse((x + offset, y + 3, x + offset + 18, y + 21), fill="#ffffff")
        self._region(key, (x - 8, y - 8, 58, 40), lambda: var.set(not var.get()))

    def _model_menu(self):
        if not hasattr(self, "model_menu"):
            self.model_menu = tk.Menu(self.root, tearoff=False, font=("Segoe UI", 11),
                                      bg="#edf3ff", fg=INK, activebackground="#d6e3fc",
                                      activeforeground=BLUE, borderwidth=0)
            for label, value in self.models:
                self.model_menu.add_radiobutton(label=label, variable=self.app.model_var, value=label)
        menu = self.model_menu
        x, y, _, height = self.model_box
        try:
            menu.tk_popup(self.canvas.winfo_rootx() + int(x),
                           self.canvas.winfo_rooty() + int(y + height - self.canvas.canvasy(0)))
        finally:
            menu.grab_release()

    def set_preview(self, source=None, result=None):
        self.preview_paths = {"original": Path(source) if source else None,
                              "result": Path(result) if result else None}
        self.schedule()

    def _select_page(self, page):
        self.page = page
        self.canvas.yview_moveto(0)
        self.schedule()

    def _select_tab(self, tab):
        self.settings_tab = tab
        self.schedule()

    def _select_preview(self, kind):
        self.preview_kind = kind
        self.schedule()

    def _preview(self, scene, box):
        x, y, w, h = map(int, box)
        path = self.preview_paths[self.preview_kind]
        image = None
        if path is not None:
            try:
                stamp = path.stat().st_mtime_ns
                key = (str(path), stamp, w, h)
                image = self.preview_images.get(key)
                if image is None:
                    with Image.open(path) as source:
                        # Decode a reduced JPEG preview when supported by Pillow.
                        source.draft("RGB", (w * 2, h * 2))
                        image = ImageOps.exif_transpose(source).convert("RGBA")
                        image.thumbnail((w - 24, h - 24), Image.Resampling.LANCZOS)
                    if len(self.preview_images) >= 6:
                        self.preview_images.clear()
                    self.preview_images[key] = image
            except (OSError, ValueError, Image.DecompressionBombError):
                image = None
        preview = Image.new("RGBA", (w, h), (245, 246, 255, 255))
        draw = ImageDraw.Draw(preview)
        if image is not None:
            for row in range(0, h, 16):
                for col in range(0, w, 16):
                    if (row // 16 + col // 16) % 2:
                        draw.rectangle((col, row, col + 15, row + 15), fill=(231, 233, 246))
            preview.alpha_composite(image, ((w - image.width) // 2, (h - image.height) // 2))
        else:
            # A simple native icon, not a bitmap of the interface.
            cx, cy = w // 2, h // 2 - 38
            draw.rounded_rectangle((cx - 30, cy - 26, cx + 30, cy + 26), radius=12,
                                   fill=(224, 228, 254), outline=(133, 143, 221), width=2)
            draw.ellipse((cx - 18, cy - 14, cx - 8, cy - 4), fill=(133, 143, 221))
            draw.line((cx - 20, cy + 14, cx - 3, cy - 2, cx + 5, cy + 6,
                       cx + 14, cy - 5, cx + 22, cy + 14), fill=(101, 114, 208), width=3)
        scene.paste(preview, (x, y), rounded_mask(w, h, 22))
        if image is None:
            title = "Chưa có ảnh kết quả" if self.preview_kind == "result" else "Ảnh của bạn, trong diện mạo mới"
            description = ("Kết quả sẽ xuất hiện sau khi xóa nền." if self.preview_kind == "result"
                           else "Chọn thư mục ảnh để bắt đầu.")
            self._text(x + w / 2, y + h / 2 + 9, title, 17, weight="bold", anchor="center", width=w - 40)
            self._text(x + w / 2, y + h / 2 + 45, description, 12, color=MUTED,
                       anchor="center", width=w - 40)
        return image is not None

    def _icon(self, x, y, name, color=BLUE):
        c = self.canvas
        options = {"fill": color, "width": 2, "tags": "paint"}
        if name == "studio":
            c.create_rectangle(x - 10, y - 9, x + 10, y + 9, outline=color,
                               width=2, tags="paint")
            c.create_oval(x - 6, y - 5, x - 2, y - 1, fill=color, outline="", tags="paint")
            c.create_line(x - 7, y + 6, x - 1, y, x + 3, y + 4, x + 7, y - 2, **options)
        elif name == "activity":
            for offset, length in ((-6, 16), (0, 12), (6, 16)):
                c.create_line(x - 8, y + offset, x - 8 + length, y + offset, **options)
        else:
            c.create_line(x - 8, y, x + 8, y, **options)
            c.create_line(x, y - 8, x, y + 8, **options)

    def render(self):
        self.redraw_job = None
        width = max(980, self.canvas.winfo_width())
        height = max(810, self.canvas.winfo_height())
        size = (width, height)
        container = min(1600, width - 48)
        origin = (width - container) // 2
        rail_x = origin
        left = origin + 84
        usable = container - 84
        gap = 20
        right_width = min(440, max(352, int((usable - gap) * 0.36)))
        left_width = usable - gap - right_width
        right = left + left_width + gap
        top, bottom = 132, height - 110
        body_height = bottom - top - 18
        preview_box = (left, top, left_width, body_height - 212)
        folder_box = (left, top + body_height - 194, left_width, 194)
        settings_box = (right, top, right_width, body_height)
        activity_box = (left, top, usable, body_height)
        dock = (left, bottom, usable, 82)
        rail = (rail_x, 26, 64, height - 54)
        key = (size, self.page)
        if key != getattr(self, 'scene_key', None):
            self.scene_key = key
            self.size = size
            self.canvas.configure(scrollregion=(0, 0, width, height))
            self.base_scene = backdrop(width, height)
            glass(self.base_scene, rail, radius=30, opacity=0.18, shadow=True)
            panels = (preview_box, folder_box, settings_box) if self.page == 'studio' else (activity_box,)
            for box in (*panels, dock):
                glass(self.base_scene, box, radius=28, opacity=0.22, shadow=True)
        scene = self.base_scene.copy()
        self.canvas.delete('paint')
        self.regions = []
        app = self.app
        for window in self.windows.values():
            self.canvas.itemconfigure(window, state='hidden')

        # Quiet navigation rail keeps the workspace and activity separate.
        primary_pill(scene, (rail_x + 12, 41, 40, 40))
        self._text(rail_x + 32, 61, '✦', 24, color='#ffffff', anchor='center')
        for index, (name, label) in enumerate((('studio', 'Studio'), ('activity', 'Nhật ký'))):
            ry = 126 + index * 83
            selected = self.page == name
            if selected or self.hover == 'nav-' + name:
                glass(scene, (rail_x + 7, ry - 24, 50, 64), radius=20,
                      opacity=0.40, tint=(231, 230, 255) if selected else (255, 255, 255))
            self._icon(rail_x + 32, ry, name, BLUE if selected else MUTED)
            self._text(rail_x + 32, ry + 24, label, 9,
                       color=BLUE if selected else MUTED, anchor='center')
            self._region('nav-' + name, (rail_x + 4, ry - 26, 56, 68),
                         lambda page=name: self._select_page(page))
        self._text(rail_x + 32, height - 61, 'PNG', 10, color=MUTED,
                   weight='bold', anchor='center')

        self._text(left + 2, 25, 'PHOTO STUDIO', 10, color=BLUE, weight='bold')
        self._text(left, 45, 'Xóa nền ảnh' if self.page == 'studio' else 'Hoạt động xử lý',
                   32, weight='bold')
        self._text(left + 2, 91, 'Tách nền nhẹ nhàng. Giữ trọn từng chi tiết.', 13, color=MUTED)
        badge_width = min(292, usable - 382)
        bx = left + usable - badge_width
        glass(scene, (bx, 53, badge_width, 40), radius=20, opacity=0.30)
        label = self.labels['device']
        device_color = '#238576' if 'GPU' in label else BLUE
        ImageDraw.Draw(scene).ellipse((bx + 15, 69, bx + 23, 77), fill=device_color)
        self._text(bx + 32, 73, label, 11, anchor='w', width=badge_width - 46)

        maximum = max(1, self.progress['maximum'])
        ratio = min(1, max(0, self.progress['value'] / maximum))
        if self.page == 'studio':
            # Real image preview with a checkerboard only where pixels are transparent.
            x, y, w, h = preview_box
            self._text(x + 24, y + 24, 'Xem trước', 18, weight='bold')
            for index, (label, kind) in enumerate((('Ảnh gốc', 'original'), ('Kết quả', 'result'))):
                sx = x + w - 197 + index * 87
                selected = self.preview_kind == kind
                box = (sx, y + 17, 81, 34)
                glass(scene, box, radius=17, opacity=0.52 if selected else 0.16,
                      tint=(232, 231, 255) if selected else (255, 255, 255))
                self._text(sx + 40, y + 34, label, 11, color=BLUE if selected else MUTED,
                           weight='bold' if selected else 'normal', anchor='center')
                self._region('preview-' + kind, box, lambda value=kind: self._select_preview(value))
            self._preview(scene, (x + 20, y + 68, w - 40, h - 113))
            source = self.preview_paths[self.preview_kind]
            name = source.name if source else 'Hỗ trợ JPG, PNG, WEBP và nhiều định dạng ảnh'
            self._text(x + 24, y + h - 24, name, 11, color=MUTED,
                       anchor='w', width=w - 48)

            x, y, w, h = folder_box
            self._text(x + 24, y + 18, 'Thư mục ảnh', 16, weight='bold')
            self._text(x + w - 24, y + 27, self.labels['count'], 10, color=MUTED, anchor='e')
            field_width = w - 48 - 92 - 10
            for index, (label, field, var) in enumerate((('Ảnh gốc', 'input', app.in_var),
                                                        ('Lưu kết quả', 'output', app.out_var))):
                fy = y + 65 + index * 64
                self._text(x + 24, fy - 18, label, 11, color=MUTED)
                self._field(scene, field, (x + 24, fy, field_width, 38))
                self._button(scene, 'pick-' + field, (x + w - 116, fy, 92, 38),
                             'Chọn…', lambda variable=var: app._pick(variable))

            x, y, w, h = settings_box
            self._text(x + 24, y + 24, 'Thiết lập của bạn', 18, weight='bold')
            self._text(x + 24, y + 53, 'Một vài lựa chọn, ảnh đẹp hơn.', 12, color=MUTED)
            tab_width = (w - 52) // 2
            glass(scene, (x + 20, y + 77, w - 40, 38), radius=19, opacity=0.16)
            for index, (label, tab) in enumerate((('Chế độ xử lý', 'mode'), ('Tùy chỉnh', 'output'))):
                tx = x + 24 + index * (tab_width + 4)
                selected = self.settings_tab == tab
                box = (tx, y + 81, tab_width, 30)
                if selected:
                    glass(scene, box, radius=15, opacity=0.66)
                self._text(tx + tab_width / 2, y + 96, label, 12,
                           color=BLUE if selected else MUTED,
                           weight='bold' if selected else 'normal', anchor='center')
                self._region('tab-' + tab, box, lambda value=tab: self._select_tab(value))

            if self.settings_tab == 'mode':
                tile_width = (w - 48 - 10) // 2
                for index, (title, description) in enumerate(self.MODE_COPY):
                    tx = x + 24 + (index % 2) * (tile_width + 10)
                    ty = y + 133 + (index // 2) * 75
                    selected = app.mode_var.get() == index
                    box = (tx, ty, tile_width, 66)
                    glass(scene, box, radius=18, opacity=0.45 if selected else 0.24,
                          tint=(216, 218, 255) if selected else (255, 255, 255))
                    draw = ImageDraw.Draw(scene)
                    if selected:
                        draw.rounded_rectangle((tx, ty, tx + tile_width - 1, ty + 65),
                                               radius=18, outline='#7e87e9', width=2)
                    draw.ellipse((tx + 12, ty + 12, tx + 24, ty + 24),
                                 fill=BLUE if selected else '#ffffff',
                                 outline=BLUE if selected else '#98a1c4', width=1)
                    if selected:
                        draw.line((tx + 15, ty + 18, tx + 17, ty + 20, tx + 21, ty + 16),
                                  fill='#ffffff', width=2)
                    self._text(tx + 33, ty + 11, title, 11, color=BLUE if selected else INK,
                               weight='bold', width=tile_width - 42)
                    self._text(tx + 12, ty + 34, description, 10, color=MUTED, width=tile_width - 24)
                    self._region('mode-' + str(index), box, lambda value=index: app.mode_var.set(value))
                self._text(x + 24, y + 374, 'MODEL AI', 10, color=MUTED, weight='bold')
                self.model_box = (x + 24, y + 396, w - 48, 42)
                glass(scene, self.model_box, radius=16, opacity=0.40)
                selected_model = dict(self.models).get(app.model_var.get())
                self._text(x + 38, y + 417, selected_model or 'Tự chọn theo chế độ', 12, anchor='w')
                self._text(x + w - 39, y + 417, '⌄', 18, color=MUTED, anchor='center')
                self._region('model', self.model_box, self._model_menu)
                self._text(x + 26, y + 455, 'Chọn chế độ phù hợp với ảnh của bạn.', 11,
                           color=MUTED, width=w - 52)
            else:
                for index, (label, key, var) in enumerate((('Cắt sát chủ thể', 'crop', app.crop_var),
                                                         ('Khung vuông', 'square', app.square_var),
                                                         ('Đổi kích thước', 'size', app.size_on_var))):
                    ry = y + 146 + index * 58
                    self._text(x + 24, ry, label, 12, anchor='w')
                    self._switch(scene, key, x + w - 66, ry - 12, var)
                self._field(scene, 'pad', (x + w - 151, y + 131, 48, 30), app.crop_var.get())
                self._text(x + w - 95, y + 146, '%', 11, color=MUTED, anchor='w')
                self._field(scene, 'size', (x + w - 177, y + 247, 100, 30), app.size_on_var.get())
                self._text(x + 24, y + 301, 'NỀN KẾT QUẢ', 10, color=MUTED, weight='bold')
                tile_width = (w - 48 - 16) // 3
                for index, (label, value) in enumerate((('Trong suốt', 'trong'), ('Trắng', 'trang'), ('Màu khác', 'khac'))):
                    sx, sy = x + 24 + index * (tile_width + 8), y + 324
                    selected = app.bg_var.get() == value
                    glass(scene, (sx, sy, tile_width, 70), radius=18,
                          opacity=0.48 if selected else 0.24,
                          tint=(225, 222, 255) if selected else (255, 255, 255))
                    draw = ImageDraw.Draw(scene)
                    cx = sx + tile_width // 2
                    if value == 'trong':
                        for row in range(3):
                            for col in range(3):
                                fill = '#d2d6e9' if (row + col) % 2 else '#ffffff'
                                draw.rectangle((cx - 12 + col * 8, sy + 11 + row * 8,
                                                cx - 5 + col * 8, sy + 18 + row * 8), fill=fill)
                    else:
                        fill = '#ffffff' if value == 'trang' else '#c5a6ee'
                        draw.ellipse((cx - 12, sy + 11, cx + 12, sy + 35), fill=fill,
                                     outline='#ffffff', width=2)
                    self._text(cx, sy + 53, label, 10, color=BLUE if selected else MUTED,
                               weight='bold' if selected else 'normal', anchor='center')
                    self._region('bg-' + value, (sx, sy, tile_width, 70), lambda choice=value: app.bg_var.set(choice))
                custom = app.bg_var.get() == 'khac'
                self._field(scene, 'color', (x + 24, y + 410, 150, 32), visible=custom)
                note = 'RGB · 255,255,255' if custom else ('Xuất PNG với nền trong suốt.' if app.bg_var.get() == 'trong' else 'Xuất PNG với nền trắng.')
                self._text(x + (186 if custom else 26), y + 426, note, 10, color=MUTED, anchor='w')
                self._text(x + 24, y + 459, 'Ghi đè ảnh đã xử lý', 12, anchor='w')
                self._switch(scene, 'overwrite', x + w - 66, y + 447, app.overwrite_var)

            glass(scene, (x + 20, y + h - 68, w - 40, 46), radius=16, opacity=0.24)
            self._text(x + 34, y + h - 45, '✦  Ảnh đẹp, chỉ một lần chạm', 11,
                       color=BLUE, anchor='w')
        else:
            x, y, w, h = activity_box
            self._text(x + 28, y + 26, 'Nhật ký xử lý', 20, weight='bold')
            self._text(x + w - 28, y + 30, f'{int(ratio * 100)}%', 15,
                       color=BLUE, weight='bold', anchor='ne')
            self._text(x + 28, y + 63, self.labels['status'], 12, color=MUTED, width=w - 56)
            glass(scene, (x + 28, y + 103, w - 56, 7), radius=3, opacity=0.20)
            if ratio:
                primary_pill(scene, (x + 28, y + 103, max(4, int((w - 56) * ratio)), 7))
            glass(scene, (x + 20, y + 132, w - 40, h - 152), radius=20, opacity=0.32)
            log_color = '#%02x%02x%02x' % scene.getpixel((int(x + w / 2), int(y + h / 2)))[:3]
            self.logbox.configure(bg=log_color, fg=INK, font=('Consolas', -12))
            self.canvas.coords(self.windows['log'], x + 34, y + 146)
            self.canvas.itemconfigure(self.windows['log'], width=w - 68, height=h - 182,
                                       state='normal' if self.logbox.get('1.0', 'end-1c') else 'hidden')
            if not self.logbox.get('1.0', 'end-1c'):
                self._text(x + 36, y + 152, 'Nhật ký sẽ xuất hiện khi bạn bắt đầu xóa nền.',
                           13, color=MUTED)

        # Floating action dock with a small progress/status area.
        x, y, w, h = dock
        self._button(scene, 'start', (x + 16, y + 17, 196, 48), '✦  Bắt đầu xóa nền',
                     app.start, primary=True, enabled=self.button_states['start'] != 'disabled')
        self._button(scene, 'stop', (x + 224, y + 17, 76, 48), 'Dừng', app.stop,
                     enabled=self.button_states['stop'] != 'disabled')
        status_width = w - 526
        self._text(x + 319, y + 23, self.labels['status'], 10, color=MUTED, width=status_width)
        bar = (x + 320, y + 55, status_width, 5)
        glass(scene, bar, radius=2, opacity=0.22)
        if ratio:
            primary_pill(scene, (bar[0], bar[1], max(4, int(bar[2] * ratio)), 5))
        self._region('show-activity', (x + 310, y + 12, status_width + 16, 59),
                     lambda: self._select_page('activity'))
        self._button(scene, 'open-output', (x + w - 193, y + 17, 177, 48),
                     'Mở thư mục kết quả  ↗', app.open_out)
        if self.focus_visible and self.canvas.focus_get() is self.canvas:
            region = next((r for r in self.regions if r[0] == self.keyboard_focus), None)
            if region:
                fx, fy, fw, fh = region[1]
                ImageDraw.Draw(scene).rounded_rectangle((fx + 3, fy + 3, fx + fw - 3, fy + fh - 3),
                    radius=min(20, max(1, fh // 2 - 3)), outline=BLUE, width=2)
        self.photo = ImageTk.PhotoImage(scene.convert('RGB'), master=self.root)
        self.canvas.create_image(0, 0, anchor='nw', image=self.photo, tags='paint-backdrop')
        old_images = self.canvas.find_withtag('paint-backdrop')
        for item in old_images[:-1]:
            self.canvas.delete(item)
        self.canvas.tag_lower(old_images[-1])
