# -*- coding: utf-8 -*-
"""
Сравнение оригинального и искажённого изображений.
Версия 4 — исправлен режим «Разница» (тепловая карта отличий).

Возможности:
  • Загрузка изображений (PNG/JPEG/BMP/TIFF/WebP/AVIF).
  • Авто-масштабирование искажённого к размеру оригинала
    с явным информационным баннером.
  • Метрики PSNR / SSIM / MAE в виде карточек с крупными значениями,
    цветовыми бейджами и подсказками о порогах.
  • Четыре интерактивных режима сравнения:
        Рядом       — синхронный зум и панорамирование + тулбар;
        Слайдер     — перетаскиваемая граница «до/после»;
        Наложение   — плавная прозрачность;
        Разница     — тепловая карта отличий с усилением.
  • Сворачиваемый подробный отчёт и сохранение в .txt.
  • Тултипы для путей к файлам.
"""

import os
from datetime import datetime

import numpy as np
from PIL import Image, ImageTk, UnidentifiedImageError

from skimage.metrics import peak_signal_noise_ratio, structural_similarity

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# Необязательная поддержка AVIF
try:
    import pillow_avif  # noqa: F401
except ImportError:
    pass


# ============================================================
#  Утилиты
# ============================================================
RUSSIAN_MONTHS = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]


def format_datetime_ru(dt: datetime) -> str:
    """Человекочитаемая дата: «2 ноября 2026 г., 14:35:22»."""
    return (f"{dt.day} {RUSSIAN_MONTHS[dt.month - 1]} {dt.year} г., "
            f"{dt.strftime('%H:%M:%S')}")


class ToolTip:
    """Всплывающая подсказка для любого Tk-виджета."""

    def __init__(self, widget, get_text):
        self.widget = widget
        self.get_text = get_text if callable(get_text) else (lambda: get_text)
        self.tip = None
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")

    def _show(self, _=None):
        text = self.get_text()
        if self.tip or not text:
            return
        x = self.widget.winfo_rootx() + 16
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        tk.Label(self.tip, text=text, bg="#ffffe0", fg="#212121",
                 relief="solid", borderwidth=1,
                 font=("Segoe UI", 9), padx=8, pady=4,
                 justify="left", wraplength=520).pack()

    def _hide(self, _=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None


# ---------- Константы интерфейса ----------
QUALITY_COLORS = {
    "excellent": "#2e7d32",   # зелёный
    "good":      "#f9a825",   # жёлтый
    "fair":      "#ef6c00",   # оранжевый
    "poor":      "#c62828",   # красный
    "none":      "#9e9e9e",   # серый
}

MODE_DESCRIPTIONS = {
    "side":   "Рядом: оба изображения в едином масштабе. Колесо мыши — зум, "
              "перетаскивание — панорамирование обоих превью одновременно. "
              "Кнопки 1:1 и «По размеру» — быстрая установка масштаба.",
    "slider": "Слайдер: перетащите вертикальную линию, чтобы открыть оригинал "
              "(слева) или искажённое изображение (справа).",
    "blend":  "Наложение: плавное смешение — двигайте ползунок прозрачности, "
              "чтобы усилить вклад оригинала или искажённой картинки.",
    "diff":   "Разница: тепловая карта отличий — чёрный (нет отличий), "
              "красный (небольшие), белый (сильные расхождения). "
              "Ползунок «Усиление» повышает чувствительность.",
}

HOT_LEGEND = "чёрный → красный → жёлтый → белый"


# ============================================================
#  Карточка метрики
# ============================================================
class MetricCard(tk.Frame):
    def __init__(self, parent, title, unit="", formatter=None,
                 thresholds=None, higher_is_better=True, legend=""):
        super().__init__(parent, bg="white", highlightbackground="#e0e0e0",
                         highlightthickness=1, padx=16, pady=10)
        self.formatter = formatter or (lambda v: f"{v:.3f}")
        self.thresholds = thresholds or []
        self.higher_is_better = higher_is_better

        tk.Label(self, text=title, font=("Segoe UI", 10),
                 fg="#666", bg="white").pack(anchor="w")

        row = tk.Frame(self, bg="white")
        row.pack(anchor="w", pady=(2, 0))
        self.value_label = tk.Label(row, text="—",
                                    font=("Segoe UI", 22, "bold"),
                                    bg="white", fg="#212121")
        self.value_label.pack(side="left")
        if unit:
            tk.Label(row, text=unit, font=("Segoe UI", 10),
                     fg="#888", bg="white"
                     ).pack(side="left", padx=(4, 0), pady=(8, 0))

        self.badge = tk.Label(self, text="—", font=("Segoe UI", 8, "bold"),
                              fg="white", bg=QUALITY_COLORS["none"],
                              padx=10, pady=2)
        self.badge.pack(anchor="w", pady=(6, 0))

        if legend:
            tk.Label(self, text=legend, font=("Segoe UI", 7),
                     fg="#888", bg="white",
                     wraplength=270, justify="left"
                     ).pack(anchor="w", pady=(6, 0))

    def set_value(self, value):
        if np.isposinf(value):
            self.value_label.config(text="∞")
        elif np.isfinite(value):
            self.value_label.config(text=self.formatter(value))
        else:
            self.value_label.config(text="—")

        color, label = QUALITY_COLORS["none"], "—"
        if np.isfinite(value) or np.isposinf(value):
            for t, key, lbl in self.thresholds:
                ok = (value >= t) if self.higher_is_better else (value <= t)
                if ok:
                    color, label = QUALITY_COLORS[key], lbl
                    break
        self.badge.config(text=label, bg=color)


# ============================================================
#  Базовый режим сравнения
# ============================================================
class BaseView(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg="#1a1a1a")
        self.orig_img = None
        self.dist_img = None

    def set_images(self, orig, dist):
        self.orig_img = orig
        self.dist_img = dist
        self.render()

    def render(self):
        pass


def _toolbar_button(parent, text, command, tooltip=None, bold=True):
    btn = tk.Button(parent, text=text, command=command,
                    bg="#3a3a3a", fg="white", relief="flat",
                    activebackground="#4a4a4a", activeforeground="white",
                    borderwidth=0, padx=8, pady=2,
                    font=("Segoe UI", 10, "bold" if bold else "normal"),
                    cursor="hand2")
    if tooltip:
        ToolTip(btn, tooltip)
    return btn


# ============================================================
#  Режим «Рядом» — синхронный зум + панель инструментов
# ============================================================
class SideBySideView(BaseView):
    def __init__(self, parent):
        super().__init__(parent)
        self.zoom = 1.0             # 1.0 = 100 %
        self.offset_x = 0
        self.offset_y = 0
        self._drag = None

        # --- Панель инструментов ---
        tb = tk.Frame(self, bg="#2a2a2a")
        tb.pack(fill="x", side="top")

        tk.Label(tb, text="Масштаб:", bg="#2a2a2a", fg="#ccc",
                 font=("Segoe UI", 9)).pack(side="left", padx=(10, 4), pady=4)

        _toolbar_button(tb, "−", self._zoom_out,
                        "Уменьшить масштаб").pack(side="left", padx=2, pady=4)
        self.zoom_label = tk.Label(tb, text="—", bg="#2a2a2a", fg="white",
                                   font=("Segoe UI", 10, "bold"), width=7)
        self.zoom_label.pack(side="left", padx=4)
        _toolbar_button(tb, "+", self._zoom_in,
                        "Увеличить масштаб").pack(side="left", padx=2, pady=4)

        _toolbar_button(tb, "1:1", self._reset_zoom,
                        "Реальный размер (100 %)",
                        bold=False).pack(side="left", padx=(12, 2), pady=4)
        _toolbar_button(tb, "По размеру", self._fit_zoom,
                        "Вписать изображение в окно",
                        bold=False).pack(side="left", padx=2, pady=4)
        _toolbar_button(tb, "Центр", self._center_view,
                        "Сбросить панорамирование",
                        bold=False).pack(side="left", padx=(12, 2), pady=4)

        # --- Канвасы ---
        frame = tk.Frame(self, bg="#1a1a1a")
        frame.pack(fill="both", expand=True)
        self.cv_l = tk.Canvas(frame, bg="#1a1a1a", highlightthickness=0)
        self.cv_r = tk.Canvas(frame, bg="#1a1a1a", highlightthickness=0)
        self.cv_l.pack(side="left", fill="both", expand=True)
        self.cv_r.pack(side="left", fill="both", expand=True)

        for cv in (self.cv_l, self.cv_r):
            cv.bind("<Configure>", lambda e: self.render())
            cv.bind("<MouseWheel>", self._on_wheel)
            cv.bind("<Button-4>", self._on_wheel)   # Linux
            cv.bind("<Button-5>", self._on_wheel)
            cv.bind("<ButtonPress-1>", self._on_press)
            cv.bind("<B1-Motion>", self._on_drag)

    # --- загрузка ---
    def set_images(self, orig, dist):
        first_time = self.orig_img is None
        self.orig_img = orig
        self.dist_img = dist
        if first_time:
            # Первая загрузка — подгоняем под окно
            self.offset_x = self.offset_y = 0
            self.after_idle(self._fit_zoom)
        else:
            # При переключении режимов сохраняем масштаб пользователя
            self._update_zoom_label()
            self.after_idle(self.render)

    # --- управление зумом ---
    def _update_zoom_label(self):
        if self.orig_img is None:
            self.zoom_label.config(text="—")
        else:
            self.zoom_label.config(text=f"{self.zoom * 100:.0f}%")

    def _fit_zoom(self):
        if self.orig_img is None:
            return
        w, h = self.orig_img.size
        cw = max(self.cv_l.winfo_width(), 1)
        ch = max(self.cv_l.winfo_height(), 1)
        self.zoom = min(cw / w, ch / h)
        self.offset_x = self.offset_y = 0
        self._update_zoom_label()
        self.render()

    def _zoom_in(self):
        if self.orig_img is None:
            return
        self.zoom = min(20.0, self.zoom * 1.25)
        self._update_zoom_label()
        self.render()

    def _zoom_out(self):
        if self.orig_img is None:
            return
        self.zoom = max(0.05, self.zoom / 1.25)
        self._update_zoom_label()
        self.render()

    def _reset_zoom(self):
        if self.orig_img is None:
            return
        self.zoom = 1.0
        self.offset_x = self.offset_y = 0
        self._update_zoom_label()
        self.render()

    def _center_view(self):
        self.offset_x = self.offset_y = 0
        self.render()

    def _on_wheel(self, event):
        if self.orig_img is None:
            return
        delta = getattr(event, "delta", 0) or (120 if event.num == 4 else -120)
        factor = 1.15 if delta > 0 else 1 / 1.15
        self.zoom = max(0.05, min(20.0, self.zoom * factor))
        self._update_zoom_label()
        self.render()

    def _on_press(self, event):
        self._drag = (event.x, event.y, self.offset_x, self.offset_y)

    def _on_drag(self, event):
        if self._drag is None:
            return
        x0, y0, ox, oy = self._drag
        self.offset_x = ox + (event.x - x0)
        self.offset_y = oy + (event.y - y0)
        self.render()

    # --- отрисовка ---
    def render(self):
        if self.orig_img is None or self.dist_img is None:
            return
        s = self.zoom
        for cv, img in ((self.cv_l, self.orig_img),
                        (self.cv_r, self.dist_img)):
            cv.delete("all")
            cw, ch = cv.winfo_width(), cv.winfo_height()
            if cw < 2 or ch < 2:
                continue
            w, h = img.size
            full_w, full_h = w * s, h * s
            x = (cw - full_w) / 2 + self.offset_x
            y = (ch - full_h) / 2 + self.offset_y

            # Рендерим только видимую часть — не тормозим на больших зумах
            sx0, sy0 = max(0.0, -x / s), max(0.0, -y / s)
            sx1, sy1 = min(float(w), (cw - x) / s), min(float(h), (ch - y) / s)
            if sx1 <= sx0 or sy1 <= sy0:
                continue

            crop = img.crop((int(sx0), int(sy0),
                             int(np.ceil(sx1)), int(np.ceil(sy1))))
            dw = max(1, int((sx1 - sx0) * s))
            dh = max(1, int((sy1 - sy0) * s))
            resized = crop.resize((dw, dh), Image.LANCZOS)

            photo = ImageTk.PhotoImage(resized)
            cv.create_image(x + sx0 * s, y + sy0 * s,
                            anchor="nw", image=photo)
            cv.image = photo  # держим ссылку, иначе Tk уничтожит картинку


# ============================================================
#  Режим «Слайдер»
# ============================================================
class SliderView(BaseView):
    def __init__(self, parent):
        super().__init__(parent)
        self.split = 0.5
        tk.Label(self, bg="#2a2a2a", fg="#ccc", font=("Segoe UI", 9),
                 pady=4,
                 text="Перетащите вертикальную линию: слева — оригинал, "
                      "справа — искажённое").pack(fill="x", side="top")

        self.canvas = tk.Canvas(self, bg="#1a1a1a", highlightthickness=0,
                                cursor="sb_h_double_arrow")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<ButtonPress-1>", self._on_drag)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<Configure>", lambda e: self.render())
        self._photo = None

    def _on_drag(self, e):
        cw = self.canvas.winfo_width()
        if cw > 0:
            self.split = max(0.02, min(0.98, e.x / cw))
            self.render()

    def set_images(self, orig, dist):
        self.orig_img = orig
        self.dist_img = dist
        self.after_idle(self.render)

    def render(self):
        self.canvas.delete("all")
        if self.orig_img is None or self.dist_img is None:
            return
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        if cw < 2 or ch < 2:
            return
        w, h = self.orig_img.size
        s = min(cw / w, ch / h)
        nw, nh = max(1, int(w * s)), max(1, int(h * s))
        x, y = (cw - nw) // 2, (ch - nh) // 2

        orig_r = self.orig_img.resize((nw, nh), Image.LANCZOS)
        dist_r = self.dist_img.resize((nw, nh), Image.LANCZOS)
        split_px = int(nw * self.split)

        composite = orig_r.copy()
        if split_px < nw:
            composite.paste(dist_r.crop((split_px, 0, nw, nh)), (split_px, 0))
        self._photo = ImageTk.PhotoImage(composite)
        self.canvas.create_image(x, y, anchor="nw", image=self._photo)

        div_x = x + split_px
        self.canvas.create_line(div_x, y, div_x, y + nh, fill="#000", width=3)
        self.canvas.create_line(div_x, y, div_x, y + nh, fill="#fff", width=1)

        for label, tx, anchor in (
                ("Оригинал",   x + 10,      "nw"),
                ("Искажённое", x + nw - 10, "ne")):
            tid = self.canvas.create_text(tx, y + 8, text=label,
                                          anchor=anchor, fill="white",
                                          font=("Segoe UI", 9, "bold"))
            bb = self.canvas.bbox(tid)
            rect = self.canvas.create_rectangle(
                bb[0] - 4, bb[1] - 2, bb[2] + 4, bb[3] + 2,
                fill="#000000", outline="")
            self.canvas.tag_lower(rect, tid)


# ============================================================
#  Режим «Наложение»
# ============================================================
class BlendView(BaseView):
    def __init__(self, parent):
        super().__init__(parent)
        top = tk.Frame(self, bg="#2a2a2a")
        top.pack(fill="x", side="top")
        tk.Label(top, text="Оригинал", bg="#2a2a2a", fg="#aaa",
                 font=("Segoe UI", 9)).pack(side="left", padx=10, pady=4)
        self.alpha_var = tk.DoubleVar(value=0.5)
        ttk.Scale(top, from_=0, to=1, variable=self.alpha_var,
                  command=lambda v: self._on_change()).pack(
            side="left", fill="x", expand=True, padx=4, pady=4)
        tk.Label(top, text="Искажённое", bg="#2a2a2a", fg="#aaa",
                 font=("Segoe UI", 9)).pack(side="left", padx=10)
        self.alpha_label = tk.Label(top, text="50 %", bg="#2a2a2a",
                                    fg="white", font=("Segoe UI", 9, "bold"),
                                    width=6)
        self.alpha_label.pack(side="left", padx=(6, 10))

        self.canvas = tk.Canvas(self, bg="#1a1a1a", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self.render())
        self._photo = None

    def set_images(self, orig, dist):
        self.orig_img = orig
        self.dist_img = dist
        self.after_idle(self.render)

    def _on_change(self):
        self.alpha_label.config(
            text=f"{int(float(self.alpha_var.get()) * 100)} %")
        self.render()

    def render(self):
        self.canvas.delete("all")
        if self.orig_img is None or self.dist_img is None:
            return
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        if cw < 2 or ch < 2:
            return
        w, h = self.orig_img.size
        s = min(cw / w, ch / h)
        nw, nh = max(1, int(w * s)), max(1, int(h * s))
        x, y = (cw - nw) // 2, (ch - nh) // 2
        orig_r = self.orig_img.resize((nw, nh), Image.LANCZOS)
        dist_r = self.dist_img.resize((nw, nh), Image.LANCZOS)
        blended = Image.blend(orig_r, dist_r, float(self.alpha_var.get()))
        self._photo = ImageTk.PhotoImage(blended)
        self.canvas.create_image(x, y, anchor="nw", image=self._photo)


# ============================================================
#  Режим «Разница» — тепловая карта (исправлено)
# ============================================================
class DiffView(BaseView):
    """
    Тепловая карта различий.

    Исправления по сравнению с предыдущей версией:
      • порог «идентичны» → только если max(diff) == 0 (а не < 2);
      • безопасное приведение массивов: np.asarray(...).astype(float32);
      • усреднение по каналам → осмысленная магнитуда отличий;
      • after_idle при set_images — рисуем после получения Canvas размера;
      • явное сообщение при несовпадении размеров;
      • try/except — ошибки показываются в самом превью, а не глотаются.
    """

    def __init__(self, parent):
        super().__init__(parent)
        top = tk.Frame(self, bg="#2a2a2a")
        top.pack(fill="x", side="top")
        tk.Label(top, text="Усиление ×", bg="#2a2a2a", fg="#ccc",
                 font=("Segoe UI", 9)).pack(side="left", padx=10, pady=4)
        self.gain_var = tk.DoubleVar(value=5.0)
        ttk.Scale(top, from_=1, to=20, variable=self.gain_var,
                  command=lambda v: self._on_change()).pack(
            side="left", fill="x", expand=True, padx=4, pady=4)
        self.gain_label = tk.Label(top, text="×5.0", bg="#2a2a2a",
                                   fg="white", font=("Segoe UI", 9, "bold"),
                                   width=6)
        self.gain_label.pack(side="left", padx=(6, 10))

        self.canvas = tk.Canvas(self, bg="#1a1a1a", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self.render())
        self._photo = None

    def set_images(self, orig, dist):
        self.orig_img = orig
        self.dist_img = dist
        # Даём layout-менеджеру выставить реальный размер Canvas,
        # и только потом рисуем — иначе winfo_width() == 1
        self.after_idle(self.render)

    def _on_change(self):
        self.gain_label.config(text=f"×{float(self.gain_var.get()):.1f}")
        self.render()

    def _show_message(self, text, color="#888", size=12):
        cw = max(self.canvas.winfo_width(), 400)
        ch = max(self.canvas.winfo_height(), 200)
        self.canvas.create_text(
            cw / 2, ch / 2, text=text, fill=color,
            font=("Segoe UI", size),
            width=cw - 40, justify="center")

    def render(self):
        try:
            self._render_impl()
        except Exception as e:  # не даём молча падать — показываем ошибку
            self.canvas.delete("all")
            self._show_message(f"Ошибка отрисовки карты различий:\n{e}",
                               color="#ff6b6b", size=10)

    def _render_impl(self):
        self.canvas.delete("all")
        if self.orig_img is None or self.dist_img is None:
            self._show_message("Загрузите оба изображения, чтобы увидеть "
                               "карту различий")
            return
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        if cw < 2 or ch < 2:
            return

        # Безопасное приведение: сначала array (uint8), затем float32
        a = np.asarray(self.orig_img.convert("RGB")).astype(np.float32)
        b = np.asarray(self.dist_img.convert("RGB")).astype(np.float32)

        if a.shape != b.shape:
            self._show_message(
                f"Размеры не совпадают: {a.shape[1]}×{a.shape[0]} "
                f"и {b.shape[1]}×{b.shape[0]} — карта недоступна",
                color="#ff6b6b", size=11)
            return

        # Разница по пикселям, усреднённая по каналам → (H, W)
        diff_mag = np.abs(a - b).mean(axis=-1)

        if float(diff_mag.max()) == 0.0:
            self._show_message("Изображения полностью идентичны — "
                               "различий не найдено")
            return

        gain = float(self.gain_var.get())
        norm = np.clip(diff_mag * gain / 255.0, 0, 1)

        # Hot colormap: чёрный → красный → жёлтый → белый
        r  = np.clip(norm * 3,     0, 1)
        g  = np.clip(norm * 3 - 1, 0, 1)
        bl = np.clip(norm * 3 - 2, 0, 1)
        rgb = (np.stack([r, g, bl], axis=-1) * 255).astype(np.uint8)

        diff_img = Image.fromarray(rgb)
        w, h = diff_img.size
        s = min(cw / w, ch / h)
        nw, nh = max(1, int(w * s)), max(1, int(h * s))
        x, y = (cw - nw) // 2, (ch - nh) // 2
        resized = diff_img.resize((nw, nh), Image.LANCZOS)
        self._photo = ImageTk.PhotoImage(resized)
        self.canvas.create_image(x, y, anchor="nw", image=self._photo)

        # Заголовок и легенда прямо на карте, чтобы не спутать с фото
        self.canvas.create_text(
            x + 8, y + 8, anchor="nw",
            text=f"Карта различий · {HOT_LEGEND} · "
                 f"макс. разница: {float(diff_mag.max()):.0f}/255",
            fill="#e0e0e0", font=("Segoe UI", 8))


# ============================================================
#  Главное окно
# ============================================================
class App:
    def __init__(self, root):
        self.root = root
        self.root.title("Сравнение изображений — оригинал vs искажённое")
        self.root.geometry("1280x900")
        self.root.minsize(1024, 700)

        self.orig_path = None
        self.dist_path = None
        self.orig_img = None
        self.dist_img = None
        self.dist_scaled = None
        self.last_metrics = None
        self.last_report_text = ""
        self._report_visible = False

        self._build_ui()

    # ----------------------------------------------------------------
    def _build_ui(self):
        # --- Шапка: basename + размер, полный путь в тултипе ---
        header = ttk.Frame(self.root, padding=(12, 10, 12, 6))
        header.pack(fill="x")

        left = ttk.Frame(header)
        left.pack(side="left", fill="x", expand=True)
        ttk.Button(left, text="Открыть оригинал…",
                   command=self.load_orig).pack(side="left")
        self.orig_info = ttk.Label(left, text="не выбран",
                                   foreground="#666", cursor="hand2")
        self.orig_info.pack(side="left", padx=8)
        ToolTip(self.orig_info, lambda: self.orig_path or "")

        right = ttk.Frame(header)
        right.pack(side="left", fill="x", expand=True)
        ttk.Button(right, text="Открыть искажённое…",
                   command=self.load_dist).pack(side="left")
        self.dist_info = ttk.Label(right, text="не выбран",
                                   foreground="#666", cursor="hand2")
        self.dist_info.pack(side="left", padx=8)
        ToolTip(self.dist_info, lambda: self.dist_path or "")

        # --- Информационный баннер авто-масштабирования ---
        self.warning_banner = tk.Frame(self.root, bg="#e7f3ff",
                                       highlightbackground="#b6d4fe",
                                       highlightthickness=1)
        self.warning_label = tk.Label(
            self.warning_banner, bg="#e7f3ff", fg="#084298",
            font=("Segoe UI", 10), padx=12, pady=8,
            anchor="w", justify="left", wraplength=1180)
        self.warning_label.pack(side="left", fill="x", expand=True)
        ttk.Button(self.warning_banner, text="Скрыть",
                   command=self._hide_warning).pack(side="right", padx=8)

        # --- Переключатель режимов + подсказка ---
        mode_row = ttk.Frame(self.root, padding=(12, 0, 12, 0))
        mode_row.pack(fill="x")
        ttk.Label(mode_row, text="Режим сравнения:").pack(side="left")
        self.mode_var = tk.StringVar(value="side")
        for text, val in (
                ("Рядом",     "side"),
                ("Слайдер",   "slider"),
                ("Наложение", "blend"),
                ("Разница",   "diff")):
            ttk.Radiobutton(mode_row, text=text, value=val,
                            variable=self.mode_var,
                            command=self._switch_mode
                            ).pack(side="left", padx=(12, 0))

        self.mode_desc = ttk.Label(
            self.root, text=MODE_DESCRIPTIONS["side"],
            foreground="#666", font=("Segoe UI", 9))
        self.mode_desc.pack(fill="x", padx=16, pady=(2, 8))

        # --- Область превью ---
        self.view_container = ttk.Frame(self.root)
        self.view_container.pack(fill="both", expand=True, padx=12, pady=(0, 6))

        self.views = {
            "side":   SideBySideView(self.view_container),
            "slider": SliderView(self.view_container),
            "blend":  BlendView(self.view_container),
            "diff":   DiffView(self.view_container),
        }
        self.current_view = None
        self._switch_mode()

        # --- Карточки метрик ---
        metrics_row = ttk.Frame(self.root, padding=(12, 6, 12, 6))
        metrics_row.pack(fill="x")

        self.psnr_card = MetricCard(
            metrics_row, "PSNR", "дБ",
            formatter=lambda v: f"{v:.2f}",
            thresholds=[(40, "excellent", "Отлично"),
                        (30, "good",      "Хорошо"),
                        (20, "fair",      "Удовл."),
                        (0,  "poor",      "Плохо")],
            higher_is_better=True,
            legend="≥40 — отлично · ≥30 — хорошо · ≥20 — удовл. · <20 — плохо")
        self.psnr_card.pack(side="left", padx=(0, 8))

        self.ssim_card = MetricCard(
            metrics_row, "SSIM", "",
            formatter=lambda v: f"{v:.4f}",
            thresholds=[(0.95, "excellent", "Отлично"),
                        (0.90, "good",      "Хорошо"),
                        (0.80, "fair",      "Удовл."),
                        (0.0,  "poor",      "Плохо")],
            higher_is_better=True,
            legend="≥0.95 — отлично · ≥0.90 — хорошо · "
                   "≥0.80 — удовл. · <0.80 — плохо")
        self.ssim_card.pack(side="left", padx=(0, 8))

        self.mae_card = MetricCard(
            metrics_row, "MAE", "",
            formatter=lambda v: f"{v:.2f}",
            thresholds=[(5,            "excellent", "Отлично"),
                        (10,           "good",      "Хорошо"),
                        (20,           "fair",      "Удовл."),
                        (float("inf"), "poor",      "Плохо")],
            higher_is_better=False,
            legend="≤5 — отлично · ≤10 — хорошо · ≤20 — удовл. · >20 — плохо")
        self.mae_card.pack(side="left")

        actions = ttk.Frame(metrics_row)
        actions.pack(side="right")
        self.report_btn = ttk.Button(actions, text="Показать отчёт…",
                                     command=self.toggle_report,
                                     state="disabled")
        self.report_btn.pack(side="right", padx=4)
        ttk.Button(actions, text="Сохранить отчёт…",
                   command=self.save_report).pack(side="right", padx=4)

        # --- Скрываемая панель подробного отчёта ---
        self.report_frame = ttk.LabelFrame(self.root, text="Подробный отчёт",
                                           padding=8)
        self.report_text = tk.Text(self.report_frame, height=10, wrap="word",
                                   font=("Consolas", 9))
        self.report_text.pack(fill="both", expand=True)

    # ----------------------------------------------------------------
    def _switch_mode(self):
        mode = self.mode_var.get()
        if self.current_view is not None:
            self.current_view.pack_forget()
        self.current_view = self.views[mode]
        self.current_view.pack(fill="both", expand=True)
        self.mode_desc.config(text=MODE_DESCRIPTIONS[mode])
        if self.orig_img is not None and self.dist_scaled is not None:
            self.current_view.set_images(self.orig_img, self.dist_scaled)

    def _set_view_images(self):
        if self.orig_img is None or self.dist_scaled is None:
            return
        for view in self.views.values():
            view.set_images(self.orig_img, self.dist_scaled)

    # ----------------------------------------------------------------
    def _open_image(self):
        path = filedialog.askopenfilename(
            title="Выберите изображение",
            filetypes=[("Изображения",
                        "*.png *.jpg *.jpeg *.bmp *.tif *.tiff "
                        "*.webp *.avif"),
                       ("Все файлы", "*.*")])
        if not path:
            return None, None
        try:
            img = Image.open(path).convert("RGB")
        except (UnidentifiedImageError, OSError) as e:
            hint = ""
            if path.lower().endswith(".avif"):
                hint = ("\n\nДля AVIF установите пакет pillow-avif-plugin "
                        "(pip install pillow-avif-plugin).")
            messagebox.showerror("Ошибка",
                                 f"Не удалось открыть файл:\n{e}{hint}")
            return None, None
        return path, img

    def load_orig(self):
        path, img = self._open_image()
        if path is None:
            return
        self.orig_path, self.orig_img = path, img
        self.orig_info.config(
            text=f"{os.path.basename(path)} · "
                 f"{img.size[0]}×{img.size[1]} px",
            foreground="#212121")
        self._refresh_pair()

    def load_dist(self):
        path, img = self._open_image()
        if path is None:
            return
        self.dist_path, self.dist_img = path, img
        self.dist_info.config(
            text=f"{os.path.basename(path)} · "
                 f"{img.size[0]}×{img.size[1]} px",
            foreground="#212121")
        self._refresh_pair()

    # ----------------------------------------------------------------
    def _refresh_pair(self):
        if self.orig_img is None or self.dist_img is None:
            return

        ow, oh = self.orig_img.size
        dw, dh = self.dist_img.size

        if (ow, oh) != (dw, dh):
            self.dist_scaled = self.dist_img.resize((ow, oh), Image.LANCZOS)
            self._show_warning(
                f"✓  Автоматическое масштабирование.  "
                f"Размеры не совпадают: {ow}×{oh} px и {dw}×{dh} px. "
                f"Система автоматически привела искажённое изображение "
                f"к размеру оригинала ({ow}×{oh} px), чтобы корректно "
                f"рассчитать метрики. Это штатное поведение — "
                f"дополнительных действий не требуется.")
        else:
            self.dist_scaled = self.dist_img
            self._hide_warning()

        self._set_view_images()
        self.compare()

    def _show_warning(self, text):
        self.warning_label.config(text=text)
        self.warning_banner.pack(fill="x", padx=12, pady=(0, 6),
                                 before=self.mode_desc)

    def _hide_warning(self):
        self.warning_banner.pack_forget()

    # ----------------------------------------------------------------
    def compare(self):
        if self.orig_img is None or self.dist_scaled is None:
            return

        a = np.asarray(self.orig_img.convert("RGB"),
                       dtype=np.float64) / 255.0
        b = np.asarray(self.dist_scaled.convert("RGB"),
                       dtype=np.float64) / 255.0

        try:
            psnr = peak_signal_noise_ratio(a, b, data_range=1.0)
        except ValueError:
            psnr = float("inf")

        try:
            try:
                ssim = structural_similarity(a, b, data_range=1.0,
                                             channel_axis=-1)
            except TypeError:
                ssim = structural_similarity(a, b, data_range=1.0,
                                             multichannel=True)
        except Exception:
            ssim = float("nan")

        mae = float(np.mean(np.abs(a - b) * 255.0))

        self.psnr_card.set_value(psnr)
        self.ssim_card.set_value(ssim)
        self.mae_card.set_value(mae)

        self.last_metrics = {"psnr": psnr, "ssim": ssim, "mae": mae}
        self._build_report()
        self.report_btn.config(state="normal")

    # ----------------------------------------------------------------
    def _build_report(self):
        now = datetime.now()
        m = self.last_metrics
        orig_name = os.path.basename(self.orig_path)
        dist_name = os.path.basename(self.dist_path)

        lines = [
            f"Сформировано: {format_datetime_ru(now)}",
            "",
            f"Оригинал:   {orig_name}",
            f"  Размер:   {self.orig_img.size[0]}×{self.orig_img.size[1]} px",
            f"Искажённое: {dist_name}",
            f"  Размер:   {self.dist_img.size[0]}×{self.dist_img.size[1]} px",
        ]
        if self.orig_img.size != self.dist_img.size:
            lines.append(
                f"  Примечание: размеры не совпадают; искажённое "
                f"автоматически приведено к "
                f"{self.orig_img.size[0]}×{self.orig_img.size[1]} px.")
        lines += [
            "",
            "Метрики:",
            f"  PSNR = {m['psnr']:.2f} дБ"
            if np.isfinite(m["psnr"])
            else "  PSNR = ∞ (изображения идентичны)",
            f"  SSIM = {m['ssim']:.4f}"
            if np.isfinite(m["ssim"])
            else "  SSIM = —",
            f"  MAE  = {m['mae']:.2f}",
            "",
            "Технические детали:",
            f"  Полный путь оригинала:   {self.orig_path}",
            f"  Полный путь искажённого: {self.dist_path}",
            "",
            "—" * 40,
            "Примечание: дата и время взяты из системных часов компьютера.",
            "Если они указаны неверно — проверьте настройки даты и "
            "времени ОС.",
        ]
        self.last_report_text = "\n".join(lines)
        self.report_text.config(state="normal")
        self.report_text.delete("1.0", "end")
        self.report_text.insert("1.0", self.last_report_text)
        self.report_text.config(state="disabled")

    def toggle_report(self):
        if self._report_visible:
            self.report_frame.pack_forget()
            self.report_btn.config(text="Показать отчёт…")
            self._report_visible = False
        else:
            self.report_frame.pack(fill="x", padx=12, pady=(0, 10))
            self.report_btn.config(text="Скрыть отчёт")
            self._report_visible = True

    def save_report(self):
        if not self.last_report_text:
            messagebox.showinfo("Нет данных",
                                "Сначала загрузите оба изображения.")
            return
        path = filedialog.asksaveasfilename(
            title="Сохранить отчёт", defaultextension=".txt",
            filetypes=[("Текст", "*.txt"), ("Все файлы", "*.*")])
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.last_report_text)
        messagebox.showinfo("Готово", f"Отчёт сохранён:\n{path}")


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("clam")
    except tk.TclError:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()