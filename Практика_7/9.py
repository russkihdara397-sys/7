#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
 Chart1 Lab — десктопный стенд для тестирования гипотетического UI-компонента
 "Chart1" (столбчатые и круговые диаграммы).
=============================================================================
ОГРАНИЧЕНИЕ ЗАДАЧИ: используется ТОЛЬКО стандартная библиотека Python 3.
Компонент Chart1 написан с нуля поверх tkinter.Canvas: ни matplotlib, ни
numpy, ни pillow, ни pyqt. Все геометрические вычисления (координаты
столбцов, углы секторов, логарифмическая шкала, «красивые» тики оси)
реализованы вручную и вынесены в отдельный, не зависящий от Tkinter слой.

СТРУКТУРА ФАЙЛА
    1. Утилиты (цвет, форматирование чисел, обрезка текста, easing).
    2. Модель данных: DataRow (строка таблицы), ChartConfig (все настройки).
    3. Математический слой (чистые функции + dataclass-геометрия).
    4. Класс Chart1(tk.Canvas) — сам компонент: рендер, анимация, hit-test.
    5. Панели интерфейса: DataPanel, SettingsPanel, BottomPanel.
    6. Контроллер приложения ChartLabApp(tk.Tk) и точка входа.

КРАЙНИЕ СЛУЧАИ, КОТОРЫЕ СПЕЦИАЛЬНО ОБРАБОТАНЫ
    * пустой набор данных / все значения = 0 (нет деления на ноль);
    * отрицательные значения в круговой диаграмме (игнорируются + WARN в лог);
    * логарифмическая шкала при значениях <= 0 (пропуск + WARN, fallback);
    * лог. шкала + накопление (несовместимо -> принудительная группировка);
    * диспропорция 1:1 000 000 (подсказка включить лог. шкалу, компактные
      подписи оси вида 1.0M);
    * 100+ точек (прореживание подписей категорий, поворот на 45/90 градусов,
      минимальная толщина столбца, отключение data labels для тонких столбцов);
    * очень длинные названия (обрезка с «…», полный текст в tooltip);
    * слишком маленькая область Canvas (аккуратная заглушка вместо исключения).
=============================================================================
"""

import math
import random
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter import font as tkfont
from dataclasses import dataclass
from datetime import datetime
from typing import List, Tuple, Optional, Callable, Any

# =============================================================================
# 1. УТИЛИТЫ
# =============================================================================


def clamp(v: float, lo: float, hi: float) -> float:
    """Ограничение значения диапазоном [lo, hi] (защита геометрии от выхода за края)."""
    return lo if v < lo else hi if v > hi else v


def hex_to_rgb(color: str) -> Tuple[int, int, int]:
    """'#4285F4' -> (66, 133, 244). Поддерживает короткий формат '#abc'."""
    c = color.lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def rgb_to_hex(rgb) -> str:
    """(66, 133, 244) -> '#4285f4' c округлением и защитой от выхода за 0..255."""
    return "#%02x%02x%02x" % tuple(int(clamp(round(c), 0, 255)) for c in rgb)


def mix_colors(c1: str, c2: str, t: float) -> str:
    """Линейная интерполяция двух цветов. Основа «градиентной заливки»."""
    t = clamp(t, 0.0, 1.0)
    a, b = hex_to_rgb(c1), hex_to_rgb(c2)
    return rgb_to_hex([a[i] + (b[i] - a[i]) * t for i in range(3)])


def lighten(c: str, t: float) -> str:
    """Осветление цвета (смешивание с белым)."""
    return mix_colors(c, "#ffffff", t)


def darken(c: str, t: float) -> str:
    """Затемнение цвета (смешивание с чёрным)."""
    return mix_colors(c, "#000000", t)


def luminance(c: str) -> float:
    """Относительная яркость 0..1 — чтобы подобрать читаемый цвет подписи."""
    r, g, b = hex_to_rgb(c)
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255.0


def text_on(c: str) -> str:
    """Контрастный цвет текста для фона c (data labels внутри столбца/сектора)."""
    return "#ffffff" if luminance(c) < 0.55 else "#1f2124"


def compact_number(v: float) -> str:
    """
    Компактное представление числа для подписей оси: 1000000 -> '1M'.
    Спасает читаемость при сценарии «Диспропорция».
    """
    a = abs(v)
    for div, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= div:
            s = f"{v / div:.2f}".rstrip("0").rstrip(".")
            return s + suf
    if a == int(a):
        return str(int(v))
    return f"{v:.3f}".rstrip("0").rstrip(".")


def format_value(v: float, cfg: "ChartConfig", percent: bool = False) -> str:
    """Форматирование значения с учётом префикса/суффикса и точности из настроек."""
    if percent:
        d = cfg.decimals if cfg.decimals > 0 else 1
        return f"{v:.{d}f}%"
    s = f"{v:,.{cfg.decimals}f}".replace(",", " ")  # разделитель разрядов — пробел
    return f"{cfg.prefix}{s}{cfg.suffix}"


def truncate(text: str, font: tkfont.Font, max_w: float) -> str:
    """
    Обрезка строки по пиксельной ширине с добавлением «…».
    Бинарный поиск по количеству символов — O(log n) измерений вместо O(n).
    Нужна для сценария «Длинные названия» и для легенды.
    """
    if max_w <= 8:
        return ""
    if font.measure(text) <= max_w:
        return text
    ell = "…"
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if font.measure(text[:mid] + ell) <= max_w:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo] + ell if lo > 0 else ell


def ease_out_cubic(t: float) -> float:
    """Плавное замедление анимации (cubic ease-out)."""
    t = clamp(t, 0.0, 1.0)
    return 1.0 - (1.0 - t) ** 3


# Палитры компонента. Цвет категории/ряда = palette[index % len(palette)].
PALETTES = {
    "Классика": ["#4285F4", "#EA4335", "#FBBC05", "#34A853",
                 "#FF6D01", "#46BDC6", "#7B61FF", "#F538A0"],
    "Пастель": ["#A8C8F0", "#F4B6B0", "#F7DFA5", "#B7DFB9",
                "#D7C4EC", "#B3E0E3", "#F6C7DE", "#CFD8DC"],
    "Океан": ["#0B3C5D", "#1D6A96", "#2E96C7", "#57B8D9",
              "#8AD3E8", "#B9E6F2", "#3F7CAC", "#155E75"],
    "Закат": ["#3D0B37", "#7A1E4B", "#B32C50", "#E15A46",
              "#F08A3C", "#F7B733", "#FCD770", "#9C2760"],
    "Монохром": ["#263238", "#455A64", "#607D8B", "#78909C",
                 "#90A4AE", "#B0BEC5", "#CFD8DC", "#ECEFF1"],
    "Контраст": ["#000000", "#E69F00", "#56B4E9", "#009E73",
                 "#F0E442", "#0072B2", "#D55E00", "#CC79A7"],
}

SERIES_NAMES = ["Ряд 1", "Ряд 2"]  # имена смоделированных рядов для Grouped/Stacked


def palette_color(name: str, index: int) -> str:
    """Циклический выбор цвета из палитры (безопасен при 100+ категориях)."""
    pal = PALETTES.get(name, PALETTES["Классика"])
    return pal[index % len(pal)]


# =============================================================================
# 2. МОДЕЛЬ ДАННЫХ
# =============================================================================


@dataclass
class DataRow:
    """
    Одна строка таблицы «Категория / Значение».
    v2 — второй (необязательный) ряд: нужен для демонстрации режимов
    Grouped / Stacked, т.к. в задании разрешено «смоделировать» многорядность.
    """
    category: str
    v1: float = 0.0
    v2: float = 0.0


@dataclass
class ChartConfig:
    """
    Полный набор свойств компонента Chart1 (его «API настроек»).
    Объект разделяется между панелью настроек (запись) и Chart1 (чтение),
    что упрощает синхронизацию: любой контроллер меняет поле и вызывает refresh().
    """
    # --- Общие -------------------------------------------------------------
    chart_type: str = "bar"          # 'bar' (столбчатая) | 'pie' (круговая)
    title: str = "Chart1 — демонстрационная диаграмма"
    show_title: bool = True
    legend_visible: bool = True
    legend_position: str = "right"   # 'top' | 'bottom' | 'left' | 'right'
    label_mode: str = "value"        # 'none' | 'value' | 'percent'
    animated: bool = True
    anim_duration: int = 650         # мс

    # --- Столбчатые --------------------------------------------------------
    horizontal: bool = False         # False = Column, True = Bar
    stack_mode: str = "grouped"      # 'grouped' | 'stacked'
    gap: float = 0.25                # 0..0.9 — доля полосы, отданная зазорам
    palette: str = "Классика"
    gradient: bool = False           # градиентная заливка (полосами/кольцами)
    color_by_category: bool = False  # раскрашивать по категориям, а не по рядам

    # --- Круговые ----------------------------------------------------------
    donut: bool = False
    inner_ratio: float = 0.55        # радиус «дырки» относительно внешнего
    rotation: float = 0.0            # стартовый угол, градусы (0 = 12 часов)
    explode_index: int = -1          # индекс «взорванного» сектора (-1 = нет)
    explode_offset: float = 18.0     # сдвиг сектора от центра, px
    click_explode: bool = True       # разрешить взрыв по клику на Canvas

    # --- Оси (только bar) --------------------------------------------------
    grid: bool = True
    log_scale: bool = False
    prefix: str = ""
    suffix: str = ""
    decimals: int = 0

    # --- Оформление --------------------------------------------------------
    bg: str = "#ffffff"
    fg: str = "#202124"
    axis_color: str = "#9aa0a6"
    grid_color: str = "#e8eaed"


def effective_stacked(cfg: ChartConfig, series_count: int) -> bool:
    """
    Накопление включается только если: выбран режим stacked, рядов > 1
    и шкала линейная (в лог. шкале суммирование геометрически бессмысленно).
    """
    return cfg.stack_mode == "stacked" and series_count > 1 and not cfg.log_scale


def bar_color_by_category(cfg: ChartConfig, series_count: int) -> bool:
    """Единое правило и для отрисовки, и для легенды: чем раскрашиваем столбцы."""
    return cfg.color_by_category or series_count == 1


# =============================================================================
# 3. МАТЕМАТИЧЕСКИЙ СЛОЙ (никакого Tkinter — только числа и геометрия)
# =============================================================================


@dataclass
class Area:
    """Прямоугольная область в пикселях Canvas. Immutable-стиль через shrink()."""
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def w(self) -> float:
        return max(0.0, self.x1 - self.x0)

    @property
    def h(self) -> float:
        return max(0.0, self.y1 - self.y0)

    def shrink(self, l: float = 0, t: float = 0, r: float = 0, b: float = 0) -> "Area":
        """Отступить от краёв (место под оси, заголовок, легенду)."""
        return Area(self.x0 + l, self.y0 + t, self.x1 - r, self.y1 - b)


class ValueScale:
    """
    Отображение числового значения в нормированную позицию 0..1.
    Инкапсулирует линейную и логарифмическую (log10) шкалы, а также
    защиту от деления на ноль при нулевом диапазоне.
    """

    def __init__(self, lo: float, hi: float, logarithmic: bool = False):
        self.lo, self.hi, self.log = lo, hi, logarithmic
        if logarithmic:
            # lo гарантированно > 0 (см. build_value_axis)
            self._llo = math.log10(lo)
            self._lhi = math.log10(hi)
            self._lspan = (self._lhi - self._llo) or 1.0
        else:
            self._span = (hi - lo) or 1.0

    def norm(self, v: float) -> float:
        if self.log:
            if v <= 0:
                return 0.0  # неположительные значения в лог. шкале не отображаются
            return clamp((math.log10(v) - self._llo) / self._lspan, 0.0, 1.0)
        return clamp((v - self.lo) / self._span, 0.0, 1.0)


def nice_ticks(vmin: float, vmax: float, target: int = 6) -> Tuple[float, float, List[float]]:
    """
    Классический алгоритм «красивых» делений оси (шаг 1/2/2.5/5 * 10^k).
    Возвращает (низ домена, верх домена, список делений).
    Крайний случай vmin == vmax (все нули) обработан явно.
    """
    if not math.isfinite(vmin) or not math.isfinite(vmax):
        return 0.0, 1.0, [0.0, 0.5, 1.0]
    if vmax - vmin <= 1e-12:
        if abs(vmax) < 1e-12:
            vmin, vmax = 0.0, 1.0            # все значения нулевые
        else:
            pad = abs(vmax) * 0.1
            vmin, vmax = vmin - pad, vmax + pad
    span = vmax - vmin
    raw = span / max(1, target)
    mag = 10.0 ** math.floor(math.log10(raw))
    norm = raw / mag
    step = mag * (1 if norm <= 1 else 2 if norm <= 2 else 2.5 if norm <= 2.5 else 5 if norm <= 5 else 10)
    lo = math.floor(vmin / step) * step
    hi = math.ceil(vmax / step) * step
    count = int(round((hi - lo) / step))
    count = max(1, min(count, 1000))          # страховка от гигантских циклов
    ticks = [round(lo + i * step, 12) for i in range(count + 1)]
    return lo, hi, ticks


def build_value_axis(categories: List[str], series: List[List[float]],
                     cfg: ChartConfig) -> Tuple[ValueScale, List[float], List[str]]:
    """
    Рассчитать домен и деления оси значений. НЕ зависит от размеров Canvas,
    поэтому вызывается до раскладки — это разрывает «циклическую зависимость»
    (подписи оси влияют на отступы, отступы влияют на длину оси).
    Возвращает (шкала, деления, список предупреждений для лога).
    """
    warns: List[str] = []
    n, m = len(categories), len(series)
    per_cat = [[series[j][i] for j in range(m)] for i in range(n)]
    stacked = effective_stacked(cfg, m)

    if cfg.stack_mode == "stacked" and m > 1 and cfg.log_scale:
        warns.append("Лог. шкала несовместима с накоплением — включена группировка (Grouped).")

    if stacked:
        highs = [sum(v for v in row if v > 0) for row in per_cat] or [0.0]
        lows = [sum(v for v in row if v < 0) for row in per_cat] or [0.0]
        vmax, vmin = max(highs + [0.0]), min(lows + [0.0])
        positives = [h for h in highs if h > 0]
    else:
        flat = [v for row in per_cat for v in row] or [0.0]
        vmax, vmin = max(flat + [0.0]), min(flat + [0.0])
        positives = [v for v in flat if v > 0]

    if cfg.log_scale:
        if positives:
            lo = 10.0 ** math.floor(math.log10(min(positives)))
            hi = 10.0 ** math.ceil(math.log10(max(positives)))
            if hi <= lo:
                hi = lo * 10.0
            decades = int(round(math.log10(hi / lo)))
            ticks: List[float] = []
            if decades <= 3:  # мало декад — добавляем деления 1-2-5 для читаемости
                for d in range(decades + 1):
                    base = lo * (10 ** d)
                    for mult in ((1, 2, 5) if d < decades else (1,)):
                        val = base * mult
                        if lo <= val <= hi:
                            ticks.append(val)
            else:
                ticks = [lo * (10 ** d) for d in range(decades + 1)]
            skipped = sum(1 for row in per_cat for v in row if v <= 0)
            if skipped:
                warns.append(f"Лог. шкала: {skipped} значений ≤ 0 отображены быть не могут и пропущены.")
            return ValueScale(lo, hi, True), ticks, warns
        warns.append("Логарифмическая шкала невозможна (нет положительных значений) — использована линейная.")

    lo, hi, ticks = nice_ticks(vmin, vmax, 6)
    return ValueScale(lo, hi, False), ticks, warns


@dataclass
class BarGeom:
    """Готовый к отрисовке прямоугольник одного столбца (или сегмента стека)."""
    x0: float
    y0: float
    x1: float
    y1: float
    value: float          # исходное значение (для tooltip / data label)
    category: str
    series: int           # индекс ряда
    color_index: int      # индекс в палитре
    percent: float        # доля, % (для режима подписей «Проценты»)
    baseline: float       # px нулевой линии — точка «вырастания» анимации

    @property
    def thickness(self) -> float:
        return min(self.x1 - self.x0, self.y1 - self.y0)


@dataclass
class CatTick:
    """Подпись категории: позиция центра полосы вдоль оси категорий."""
    pos: float
    text: str
    index: int


@dataclass
class BarLayout:
    """Результат раскладки столбчатой диаграммы."""
    bars: List[BarGeom]
    cat_ticks: List[CatTick]
    baseline: float
    band: float           # ширина полосы на одну категорию, px
    area: Area            # область построения (без осей)
    scale: ValueScale
    horizontal: bool

    def vpx(self, v: float) -> float:
        """Значение -> пиксель по оси значений (единая формула для сетки и столбцов)."""
        t = self.scale.norm(v)
        if self.horizontal:
            return self.area.x0 + t * self.area.w
        return self.area.y1 - t * self.area.h


def compute_bar_layout(categories: List[str], series: List[List[float]], area: Area,
                       cfg: ChartConfig, scale: ValueScale) -> BarLayout:
    """
    ГЛАВНАЯ ГЕОМЕТРИЯ СТОЛБЧАТОЙ ДИАГРАММЫ.
    Поддерживает: Column/Bar, Grouped/Stacked, отрицательные значения,
    регулировку зазоров, лог. шкалу, 100+ категорий.
    """
    n, m = len(categories), len(series)
    stacked = effective_stacked(cfg, m)
    horizontal = cfg.horizontal

    cat_len = area.h if horizontal else area.w
    band = cat_len / n if n else cat_len
    usable = max(1.0, band * (1.0 - clamp(cfg.gap, 0.0, 0.9)))  # место под столбцы
    bar_t = usable if stacked else usable / max(1, m)           # толщина одного столбца
    origin = area.y0 if horizontal else area.x0

    zero_value = scale.lo if scale.log else 0.0   # в лог. шкале база = низ домена
    layout_probe = BarLayout([], [], 0.0, band, area, scale, horizontal)
    baseline = layout_probe.vpx(zero_value)

    total_abs = sum(abs(v) for row in series for v in row) or 1.0  # защита от /0
    by_cat = bar_color_by_category(cfg, m)

    bars: List[BarGeom] = []
    cat_ticks: List[CatTick] = []

    for i in range(n):
        center = origin + i * band + band / 2.0
        cat_ticks.append(CatTick(center, str(categories[i]), i))
        row_total = sum(abs(series[j][i]) for j in range(m)) or 1.0
        pos_acc, neg_acc = 0.0, 0.0  # накопители для стека (вверх и вниз отдельно)

        for j in range(m):
            v = series[j][i]
            if scale.log and v <= 0:
                continue  # физически не отображается в лог. шкале

            if stacked:
                if v >= 0:
                    a, b = pos_acc, pos_acc + v
                    pos_acc = b
                else:
                    a, b = neg_acc + v, neg_acc
                    neg_acc = a
                off, thick = center - usable / 2.0, usable
                pct = abs(v) / row_total * 100.0     # % внутри стека категории
            else:
                a, b = zero_value, v
                off, thick = center - usable / 2.0 + j * bar_t, bar_t
                pct = abs(v) / total_abs * 100.0     # % от общей суммы

            p0, p1 = layout_probe.vpx(a), layout_probe.vpx(b)
            lo_px, hi_px = (p0, p1) if p0 <= p1 else (p1, p0)
            if horizontal:
                x0, y0, x1, y1 = lo_px, off, hi_px, off + thick
            else:
                x0, y0, x1, y1 = off, lo_px, off + thick, hi_px

            cidx = i if by_cat else j
            bars.append(BarGeom(x0, y0, x1, y1, v, str(categories[i]), j, cidx, pct, baseline))

    layout_probe.bars = bars
    layout_probe.cat_ticks = cat_ticks
    layout_probe.baseline = baseline
    return layout_probe


def animated_bar_rect(b: BarGeom, progress: float, horizontal: bool) -> Tuple[float, float, float, float]:
    """
    Анимация «вырастания»: интерполируем координаты вдоль оси значений
    к нулевой линии. Работает и для отрицательных столбцов, и для стеков.
    """
    if progress >= 1.0:
        return b.x0, b.y0, b.x1, b.y1
    base = b.baseline
    if horizontal:
        return (base + (b.x0 - base) * progress, b.y0,
                base + (b.x1 - base) * progress, b.y1)
    return (b.x0, base + (b.y0 - base) * progress,
            b.x1, base + (b.y1 - base) * progress)


@dataclass
class SliceGeom:
    """
    Сектор круговой диаграммы.
    start/sweep — в «диаграммных» градусах: по часовой стрелке от 12 часов,
    БЕЗ учёта cfg.rotation (поворот добавляется при отрисовке и hit-test,
    что позволяет анимировать развёртку и менять вращение без пересчёта данных).
    """
    index: int          # индекс строки в исходной таблице (для explode)
    category: str
    value: float
    percent: float
    start: float
    sweep: float
    color_index: int


def compute_pie_slices(categories: List[str], values: List[float]
                       ) -> Tuple[List[SliceGeom], List[str], float]:
    """
    Расчёт углов секторов. Отрицательные значения отбрасываются с предупреждением
    (классическое поведение pie-chart), нулевые дают сектор нулевой ширины.
    Возвращает (секторы, предупреждения, сумма положительных).
    """
    warns: List[str] = []
    negatives = [(c, v) for c, v in zip(categories, values) if v < 0]
    zeros = [c for c, v in zip(categories, values) if v == 0]
    if negatives:
        sample = ", ".join(f"{c}={compact_number(v)}" for c, v in negatives[:3])
        warns.append(f"Круговая диаграмма: проигнорировано отрицательных значений — "
                     f"{len(negatives)} ({sample}{'…' if len(negatives) > 3 else ''}).")
    if zeros:
        warns.append(f"Круговая диаграмма: нулевых значений — {len(zeros)} (секторы нулевой ширины).")

    kept = [(i, str(c), v) for i, (c, v) in enumerate(zip(categories, values)) if v > 0]
    total = sum(v for _, _, v in kept)
    if total <= 0:
        warns.append("Круговая диаграмма не построена: сумма положительных значений равна 0 "
                     "(защита от деления на ноль).")
        return [], warns, 0.0

    slices: List[SliceGeom] = []
    acc = 0.0
    for i, c, v in kept:
        sweep = 360.0 * v / total
        slices.append(SliceGeom(i, c, v, v / total * 100.0, acc, sweep, i))
        acc += sweep
    return slices, warns, total


def polar(cx: float, cy: float, r: float, chart_deg: float) -> Tuple[float, float]:
    """
    Полярные координаты -> пиксели.
    Угол в «диаграммных» градусах: 0° = 12 часов, рост по часовой стрелке.
    Именно здесь используются math.sin / math.cos, как требует задание.
    """
    a = math.radians(chart_deg)
    return cx + r * math.sin(a), cy - r * math.cos(a)


def ring_polygon(cx: float, cy: float, r_out: float, r_in: float,
                 a0: float, a1: float, step: float = 2.0) -> List[float]:
    """
    Плоский список координат [x0,y0,x1,y1,...] для сектора или сегмента кольца.
    Дуга аппроксимируется ломаной с шагом <= step градусов (визуально гладко),
    что позволяет рисовать и Pie, и Donut, и «взорванные» секторы одним кодом
    (create_arc не умеет кольца со сдвигом).
    """
    sweep = max(0.0, a1 - a0)
    if sweep <= 0:
        return []
    steps = max(1, int(math.ceil(sweep / step)))
    pts: List[float] = []
    for k in range(steps + 1):                      # внешняя дуга a0 -> a1
        x, y = polar(cx, cy, r_out, a0 + sweep * k / steps)
        pts.extend((x, y))
    if r_in > 0.5:
        for k in range(steps, -1, -1):              # внутренняя дуга a1 -> a0
            x, y = polar(cx, cy, r_in, a0 + sweep * k / steps)
            pts.extend((x, y))
    else:
        pts.extend((cx, cy))                        # классический сектор — в центр
    return pts


# =============================================================================
# 4. КОМПОНЕНТ Chart1 (единственный класс, который знает про Canvas)
# =============================================================================


class Chart1(tk.Canvas):
    """
    Гипотетический UI-компонент "Chart1".

    ПУБЛИЧНОЕ API:
        set_data(categories, series, series_names)  — задать данные (series: список рядов)
        refresh(animate=None, reason=None)          — перерисовать (с анимацией или без)
        export_postscript(path)                     — векторный экспорт в .ps
        last_render_ms                              — время последней полной отрисовки, мс
        cfg                                         — ссылка на ChartConfig

    Колбэки: on_log(msg, level), on_metric(ms, items, frames), on_pick(index).

            Вся отрисовка идёт с тегом "chart" (полная очистка одним delete),
            вспомогательные элементы (tooltip, подсветка) — с тегом "overlay".
    """

    def __init__(self, master, config: ChartConfig,
                 on_log: Optional[Callable] = None,
                 on_metric: Optional[Callable] = None,
                 on_pick: Optional[Callable] = None, **kw):
        super().__init__(master, bg=config.bg, highlightthickness=0, **kw)
        self.cfg = config
        self.categories: List[str] = []
        self.series: List[List[float]] = []
        self.series_names: List[str] = list(SERIES_NAMES)

        self._on_log = on_log or (lambda m, l="INFO": None)
        self._on_metric = on_metric
        self._on_pick = on_pick

        # --- Шрифты (наследуют системный шрифт Tk, чтобы выглядеть нативно) ---
        base = tkfont.nametofont("TkDefaultFont")
        fam = base.actual("family")
        size = abs(base.actual("size")) or 10
        self.font_small = tkfont.Font(self, family=fam, size=max(7, size - 1))
        self.font_normal = tkfont.Font(self, family=fam, size=size)
        self.font_title = tkfont.Font(self, family=fam, size=size + 3, weight="bold")

        # --- Состояние отрисовки / анимации ---
        self._anim_after: Optional[str] = None
        self._resize_after: Optional[str] = None
        self._anim_t0 = 0.0
        self._frames = 0
        self.last_render_ms = 0.0
        self._last_warn_key = ""     # дедупликация предупреждений между кадрами

        # --- Данные для hit-test (заполняются при отрисовке) ---
        self._bars: List[BarGeom] = []
        self._drawn_slices: List[SliceGeom] = []
        self._pie_meta: Optional[Tuple[float, float, float, float, float]] = None
        self._pie_total = 0.0
        self._prepared_slices: List[SliceGeom] = []
        self._hover_key = None

        self.bind("<Configure>", self._on_configure)
        self.bind("<Motion>", self._on_motion)
        self.bind("<Leave>", lambda e: self._clear_overlay())
        self.bind("<Button-1>", self._on_click)

    # ------------------------------------------------------------------ API
    def set_data(self, categories: List[str], series: List[List[float]],
                 series_names: Optional[List[str]] = None) -> None:
        """Только сохраняет данные; отрисовка — отдельным вызовом refresh()."""
        self.categories = list(categories)
        self.series = [list(map(float, row)) for row in series]
        if series_names:
            self.series_names = list(series_names)

    def refresh(self, animate: Optional[bool] = None, reason: Optional[str] = None) -> None:
        """Перерисовка. animate=None -> взять из cfg.animated."""
        if self._anim_after:
            self.after_cancel(self._anim_after)
            self._anim_after = None
        if reason:
            self._on_log(reason, "INFO")
        anim = self.cfg.animated if animate is None else animate
        self._frames = 0
        if anim and self.cfg.anim_duration > 0:
            self._anim_t0 = time.perf_counter()
            self._anim_step()
        else:
            self._render(1.0)

    def export_postscript(self, path: str) -> None:
        """
        Векторный экспорт средствами чистого Tkinter.
        ВАЖНО: canvas.postscript() — единственный встроенный способ сохранить
        изображение Canvas. Формат — Encapsulated PostScript, НЕ PNG.
        Получить PNG без сторонних библиотек (Pillow) или внешних программ
        (Ghostscript/ImageMagick) невозможно, поэтому кнопка «Экспорт в PNG»
        честно сохраняет .ps и пишет объяснение в лог.
        """
        self._clear_overlay()
        self.update_idletasks()
        w, h = max(1, self.winfo_width()), max(1, self.winfo_height())
        self.postscript(file=path, colormode="color",
                        x=0, y=0, width=w, height=h,
                        pagewidth=w - 1, pageheight=h - 1, rotate=0)

    # ------------------------------------------------------- внутренний цикл
    def _on_configure(self, event) -> None:
        """Дебаунс ресайза: не перерисовываем на каждый пиксель изменения окна."""
        if self._resize_after:
            self.after_cancel(self._resize_after)
        self._resize_after = self.after(90, self._resize_done)

    def _resize_done(self) -> None:
        self._resize_after = None
        self.refresh(animate=False)

    def _anim_step(self) -> None:
        """Один кадр анимации. Планируется через .after(16) ≈ 60 FPS."""
        dur = max(1, self.cfg.anim_duration)
        t = (time.perf_counter() - self._anim_t0) * 1000.0 / dur
        self._frames += 1
        if t >= 1.0:
            self._anim_after = None
            self._render(1.0)
            return
        self._render(ease_out_cubic(t))
        self._anim_after = self.after(16, self._anim_step)

    # ------------------------------------------------------------- РЕНДЕР
    def _render(self, progress: float = 1.0) -> None:
        """
        Полный кадр. Порядок: заголовок -> резерв под легенду -> тело -> легенда.
        Замер времени и вывод предупреждений — только на финальном кадре,
        чтобы анимация не искажала метрику производительности.
        """
        t0 = time.perf_counter()
        self.delete("chart")
        self._bars, self._drawn_slices, self._pie_meta = [], [], None
        w, h = self.winfo_width(), self.winfo_height()
        if w < 24 or h < 24:
            return
        cfg = self.cfg
        self.configure(bg=cfg.bg)
        warns: List[str] = []
        area = Area(8, 8, w - 8, h - 8)

        # 1) Заголовок
        if cfg.show_title and cfg.title.strip():
            self.create_text(w / 2, area.y0, text=truncate(cfg.title, self.font_title, w - 20),
                             font=self.font_title, fill=cfg.fg, anchor="n", tags="chart")
            area = Area(area.x0, area.y0 + self.font_title.metrics("linespace") + 10, area.x1, area.y1)

        # 2) Подготовка данных и записей легенды
        m = len(self.series)
        if cfg.chart_type == "pie":
            vals = self.series[0] if self.series else []
            slices, pw, total = compute_pie_slices(self.categories, vals)
            warns += pw
            self._prepared_slices, self._pie_total = slices, total
            entries = [(palette_color(cfg.palette, s.color_index), s.category) for s in slices]
        else:
            self._prepared_slices = []
            if bar_color_by_category(cfg, m):
                entries = [(palette_color(cfg.palette, i), str(c)) for i, c in enumerate(self.categories)]
            else:
                entries = [(palette_color(cfg.palette, j), self.series_names[j] if j < len(self.series_names)
                            else f"Ряд {j + 1}") for j in range(m)]

        # 3) Легенда (уменьшает область построения)
        legend_items = []
        if cfg.legend_visible and entries:
            area, legend_items = self._reserve_legend(area, entries)

        # 4) Тело диаграммы
        if not self.categories:
            self._placeholder(area, "Нет данных.\nДобавьте строки слева или запустите генератор сценариев.")
        elif area.w < 40 or area.h < 40:
            self._placeholder(area, "Недостаточно места для отрисовки\n(уменьшите легенду или увеличьте окно).")
        elif cfg.chart_type == "pie":
            self._draw_pie(area, progress)
        else:
            scale, ticks, aw = build_value_axis(self.categories, self.series, cfg)
            warns += aw
            self._draw_bars(area, progress, scale, ticks)

        # 5) Легенда поверх зарезервированной полосы
        self._draw_legend(legend_items)
        self.tag_raise("overlay")

        # 6) Метрики и предупреждения
        if progress >= 1.0:
            self.last_render_ms = (time.perf_counter() - t0) * 1000.0
            key = "|".join(warns)
            if key != self._last_warn_key:
                self._last_warn_key = key
                for msg in warns:
                    self._on_log(msg, "WARN")
            if self._on_metric:
                self._on_metric(self.last_render_ms, len(self.find_all()), self._frames)

    def _placeholder(self, area: Area, text: str) -> None:
        """Аккуратная заглушка вместо исключения при пустых/невыразимых данных."""
        self.create_rectangle(area.x0, area.y0, area.x1, area.y1,
                              outline="#dadce0", dash=(4, 3), tags="chart")
        self.create_text((area.x0 + area.x1) / 2, (area.y0 + area.y1) / 2,
                         text=text, font=self.font_normal, fill="#80868b",
                         justify="center", tags="chart")

    # ----------------------------------------------------------- ЛЕГЕНДА
    def _reserve_legend(self, area: Area, entries: List[Tuple[str, str]]
                        ) -> Tuple[Area, List[Tuple[Optional[str], str, float, float]]]:
        """
        Вычислить полосу под легенду и позиции её элементов.
        Ограничения: слева/справа — не более 32% ширины, вертикально — по числу
        строк, которые физически влезают; сверху/снизу — перенос, максимум 3 строки.
        Всё, что не влезло, сворачивается в «… ещё N» (важно для 100+ точек).
        """
        f = self.font_small
        lh = f.metrics("linespace")
        row_h = lh + 4
        sw, pad = 12, 8
        pos = self.cfg.legend_position
        items: List[Tuple[Optional[str], str, float, float]] = []

        if pos in ("left", "right"):
            max_w = min(240.0, max(90.0, area.w * 0.32))
            texts = [truncate(t, f, max_w - sw - 8) for _, t in entries]
            box_w = min(max_w, max((f.measure(t) for t in texts), default=40) + sw + 14)
            fit = max(1, int((area.h - 2 * pad) / row_h))
            shown = min(len(entries), fit)
            extra = len(entries) - shown
            if extra > 0:
                shown = max(1, shown - 1)
                extra = len(entries) - shown
            x = area.x0 if pos == "left" else area.x1 - box_w
            y = area.y0 + pad
            for k in range(shown):
                items.append((entries[k][0], texts[k], x, y + k * row_h))
            if extra > 0:
                items.append((None, f"… ещё {extra}", x, y + shown * row_h))
            if pos == "left":
                new_area = Area(area.x0 + box_w + 12, area.y0, area.x1, area.y1)
            else:
                new_area = Area(area.x0, area.y0, area.x1 - box_w - 12, area.y1)
            return new_area, items

        # top / bottom — горизонтальный перенос
        max_rows = 3
        lines: List[List[Tuple[str, str, float]]] = [[]]
        cur_w = 0.0
        limit = area.w - 2 * pad
        hidden = 0
        for color, text in entries:
            t = truncate(text, f, 220)
            iw = f.measure(t) + sw + 20
            if cur_w + iw > limit and lines[-1]:
                if len(lines) >= max_rows:
                    hidden += 1
                    continue
                lines.append([])
                cur_w = 0.0
            if len(lines) <= max_rows:
                lines[-1].append((color, t, iw))
                cur_w += iw
        box_h = len(lines) * row_h + 2 * pad
        top = area.y0 if pos == "top" else area.y1 - box_h
        for r, line in enumerate(lines):
            x = area.x0 + pad
            y = top + pad + r * row_h
            for color, t, iw in line:
                items.append((color, t, x, y))
                x += iw
        if hidden:
            items.append((None, f"… ещё {hidden}", area.x0 + pad, top + pad + len(lines) * row_h - row_h))
        if pos == "top":
            new_area = Area(area.x0, area.y0 + box_h, area.x1, area.y1)
        else:
            new_area = Area(area.x0, area.y0, area.x1, area.y1 - box_h)
        return new_area, items

    def _draw_legend(self, items) -> None:
        """Отрисовка预先 рассчитанных элементов легенды (цветной квадрат + текст)."""
        f = self.font_small
        lh = f.metrics("linespace")
        for color, text, x, y in items:
            if color:
                self.create_rectangle(x, y + 2, x + 12, y + lh - 2,
                                      fill=color, outline=darken(color, 0.25), tags="chart")
            self.create_text(x + 16, y, text=text, font=f, fill=self.cfg.fg,
                             anchor="nw", tags="chart")

    # -------------------------------------------------- СТОЛБЧАТАЯ ДИАГРАММА
    def _draw_bars(self, area: Area, progress: float, scale: ValueScale, ticks: List[float]) -> None:
        cfg = self.cfg
        f = self.font_small
        lh = f.metrics("linespace")
        n = len(self.categories)
        horizontal = cfg.horizontal

        # --- Шаг 1. Оценка ширины полосы, чтобы выбрать стиль подписей категорий.
        probe = area.shrink(l=(110 if horizontal else 56), t=6, r=20, b=(lh + 16 if horizontal else 40))
        band_probe = max(1.0, (probe.h if horizontal else probe.w) / max(1, n))
        cat_texts = [str(c) for c in self.categories]
        max_cat_w = max((f.measure(t) for t in cat_texts), default=0)

        angle = 0
        if horizontal:
            left_w = clamp(max_cat_w + 12, 40, 190)
            bottom_h = lh + 16
            top_h, right_w = 6, 24
        else:
            tick_labels = [f"{cfg.prefix}{compact_number(t)}{cfg.suffix}" for t in ticks]
            left_w = max(34, max((f.measure(t) for t in tick_labels), default=20) + 12)
            # Три стратегии подписей при росте числа категорий:
            if max_cat_w + 8 <= band_probe:
                angle, bottom_h = 0, lh + 12                      # помещаются горизонтально
            elif band_probe >= 11:
                angle, bottom_h = 45, min(120, max_cat_w * 0.72 + 14)   # наклон 45°
            else:
                angle, bottom_h = 90, min(140, max_cat_w + 12)     # вертикально / прореживание
            top_h, right_w = 8, 20

        plot = area.shrink(l=left_w, t=top_h, r=right_w, b=bottom_h)
        if plot.w < 20 or plot.h < 20:
            self._placeholder(area, "Слишком мало места для осей и столбцов.")
            return

        layout = compute_bar_layout(self.categories, self.series, plot, cfg, scale)
        self._bars = layout.bars

        # --- Шаг 2. Сетка (рисуется первой, чтобы быть под столбцами)
        if cfg.grid:
            for t in ticks:
                p = layout.vpx(t)
                if horizontal:
                    self.create_line(p, plot.y0, p, plot.y1, fill=cfg.grid_color, tags="chart")
                else:
                    self.create_line(plot.x0, p, plot.x1, p, fill=cfg.grid_color, tags="chart")

        # --- Шаг 3. Столбцы (с анимацией и, при желании, градиентом)
        m = len(self.series)
        by_cat = bar_color_by_category(cfg, m)
        for b in layout.bars:
            color = palette_color(cfg.palette, b.color_index)
            if by_cat and m > 1 and b.series > 0:
                color = lighten(color, 0.35)  # второй ряд чуть светлее при раскраске по категориям
            x0, y0, x1, y1 = animated_bar_rect(b, progress, horizontal)
            if x1 - x0 < 0.4 or y1 - y0 < 0.4:
                continue  # нулевая высота (значение 0) — рисовать нечего
            if cfg.gradient:
                self._gradient_rect(x0, y0, x1, y1, color, horizontal)
            else:
                self.create_rectangle(x0, y0, x1, y1, fill=color,
                                      outline=darken(color, 0.2) if b.thickness >= 4 else "",
                                      tags="chart")

        # --- Шаг 4. Оси поверх данных
        if horizontal:
            self.create_line(plot.x0, plot.y1, plot.x1, plot.y1, fill=cfg.axis_color, tags="chart")
            self.create_line(layout.baseline, plot.y0, layout.baseline, plot.y1,
                             fill=darken(cfg.axis_color, 0.25), tags="chart")
        else:
            self.create_line(plot.x0, plot.y0, plot.x0, plot.y1, fill=cfg.axis_color, tags="chart")
            self.create_line(plot.x0, layout.baseline, plot.x1, layout.baseline,
                             fill=darken(cfg.axis_color, 0.25), tags="chart")

        # --- Шаг 5. Подписи оси значений
        for t in ticks:
            p = layout.vpx(t)
            label = f"{cfg.prefix}{compact_number(t)}{cfg.suffix}"
            if horizontal:
                self.create_text(p, plot.y1 + 6, text=label, font=f, fill="#5f6368",
                                 anchor="n", tags="chart")
                self.create_line(p, plot.y1, p, plot.y1 + 4, fill=cfg.axis_color, tags="chart")
            else:
                self.create_text(plot.x0 - 6, p, text=label, font=f, fill="#5f6368",
                                 anchor="e", tags="chart")
                self.create_line(plot.x0 - 4, p, plot.x0, p, fill=cfg.axis_color, tags="chart")

        # --- Шаг 6. Подписи категорий: прореживание + поворот + обрезка
        if horizontal:
            need = lh + 3
            skip = max(1, int(math.ceil(need / max(1.0, layout.band))))
            for ct in layout.cat_ticks:
                if ct.index % skip:
                    continue
                self.create_text(plot.x0 - 6, ct.pos, text=truncate(ct.text, f, left_w - 10),
                                 font=f, fill="#5f6368", anchor="e", tags="chart")
        else:
            need = (max_cat_w + 10) if angle == 0 else (lh + 4)
            skip = max(1, int(math.ceil(need / max(1.0, layout.band))))
            max_len = (layout.band - 4) if angle == 0 else (bottom_h - 10) * (1.0 if angle == 90 else 1.4)
            for ct in layout.cat_ticks:
                if ct.index % skip:
                    continue
                txt = truncate(ct.text, f, max(10, max_len))
                if angle == 0:
                    self.create_text(ct.pos, plot.y1 + 6, text=txt, font=f,
                                     fill="#5f6368", anchor="n", tags="chart")
                else:
                    self.create_text(ct.pos, plot.y1 + 8, text=txt, font=f,
                                     fill="#5f6368", anchor="e", angle=angle, tags="chart")

        # --- Шаг 7. Data labels (только на финальном кадре анимации)
        if cfg.label_mode != "none" and progress >= 0.999:
            self._bar_labels(layout, plot)

    def _gradient_rect(self, x0, y0, x1, y1, color, horizontal) -> None:
        """
        Градиентная заливка без сторонних библиотек: прямоугольник режется
        на K полос, цвет каждой — интерполяция от светлого к базовому.
        K адаптивный: не более 24 и не больше, чем пикселей/3 (экономия времени).
        """
        length = (x1 - x0) if horizontal else (y1 - y0)
        k = int(clamp(length / 3.0, 3, 24))
        light = lighten(color, 0.45)
        for i in range(k):
            t0, t1 = i / k, (i + 1) / k
            c = mix_colors(light, color, t0)
            if horizontal:
                self.create_rectangle(x0 + length * t0, y0, x0 + length * t1 + 0.6, y1,
                                      fill=c, outline="", tags="chart")
            else:
                self.create_rectangle(x0, y1 - length * t0, x1, y1 - length * t1 - 0.6,
                                      fill=c, outline="", tags="chart")

    def _bar_labels(self, layout: BarLayout, plot: Area) -> None:
        """
        Подписи данных. Правила читаемости: не рисуем на тонких столбцах
        и если текст шире полосы (иначе при 100+ точках получится «каша»).
        Снаружи — если есть место, иначе внутри контрастным цветом.
        """
        cfg, f = self.cfg, self.font_small
        lh = f.metrics("linespace")
        pct_mode = cfg.label_mode == "percent"
        for b in layout.bars:
            if b.thickness < 12:
                continue
            txt = format_value(b.percent if pct_mode else b.value, cfg, percent=pct_mode)
            tw = f.measure(txt)
            if layout.horizontal:
                if tw + 8 > layout.band * 3:
                    continue
                if b.x1 + tw + 6 <= plot.x1:
                    self.create_text(b.x1 + 5, (b.y0 + b.y1) / 2, text=txt, font=f,
                                     fill="#3c4043", anchor="w", tags="chart")
                elif b.x1 - b.x0 > tw + 8:
                    self.create_text(b.x1 - 5, (b.y0 + b.y1) / 2, text=txt, font=f,
                                     fill=text_on(palette_color(cfg.palette, b.color_index)),
                                     anchor="e", tags="chart")
            else:
                if tw > layout.band * 1.15:
                    continue
                cx = (b.x0 + b.x1) / 2
                if b.value >= 0:
                    if b.y0 - lh - 2 >= plot.y0:
                        self.create_text(cx, b.y0 - 3, text=txt, font=f, fill="#3c4043",
                                         anchor="s", tags="chart")
                    elif b.y1 - b.y0 > lh + 6:
                        self.create_text(cx, b.y0 + 3, text=txt, font=f,
                                         fill=text_on(palette_color(cfg.palette, b.color_index)),
                                         anchor="n", tags="chart")
                else:
                    if b.y1 + lh + 2 <= plot.y1:
                        self.create_text(cx, b.y1 + 3, text=txt, font=f, fill="#3c4043",
                                         anchor="n", tags="chart")
                    elif b.y1 - b.y0 > lh + 6:
                        self.create_text(cx, b.y1 - 3, text=txt, font=f,
                                         fill=text_on(palette_color(cfg.palette, b.color_index)),
                                         anchor="s", tags="chart")

    # --------------------------------------------------- КРУГОВАЯ ДИАГРАММА
    def _draw_pie(self, area: Area, progress: float) -> None:
        cfg = self.cfg
        slices = self._prepared_slices
        if not slices:
            self._placeholder(area, "Круговая диаграмма недоступна:\n"
                                    "нет положительных значений\n(см. предупреждения в логе).")
            return

        labels_on = cfg.label_mode != "none"
        margin = 34 if labels_on else 12
        explode = cfg.explode_offset if cfg.explode_index >= 0 else 0
        r_out = min(area.w, area.h) / 2.0 - margin - explode
        if r_out < 14:  # деградация при очень маленькой области
            r_out = max(6.0, min(area.w, area.h) / 2.0 - 4)
            labels_on = False
        r_in = r_out * clamp(cfg.inner_ratio, 0.05, 0.92) if cfg.donut else 0.0
        cx, cy = (area.x0 + area.x1) / 2.0, (area.y0 + area.y1) / 2.0
        self._pie_meta = (cx, cy, r_out, r_in, cfg.rotation)

        for s in slices:
            # Анимация развёртки: и стартовый угол, и ширина сектора растут от 0.
            a0 = cfg.rotation + s.start * progress
            sweep = s.sweep * progress
            if sweep <= 0.01:
                continue
            a1 = a0 + sweep
            color = palette_color(cfg.palette, s.color_index)

            ox = oy = 0.0
            if s.index == cfg.explode_index:  # «взорванный» сектор сдвигается по биссектрисе
                ox, oy = polar(0, 0, cfg.explode_offset, cfg.rotation + s.start + s.sweep / 2.0)
            scx, scy = cx + ox, cy + oy

            if cfg.gradient:
                # Радиальный градиент кольцами (от светлого внутри к базовому снаружи)
                rings = 10
                for k in range(rings):
                    ri0 = r_in + (r_out - r_in) * k / rings
                    ri1 = r_in + (r_out - r_in) * (k + 1) / rings
                    c = mix_colors(lighten(color, 0.4), color, k / max(1, rings - 1))
                    pts = ring_polygon(scx, scy, ri1 + 0.6, ri0, a0, a1, step=2.5)
                    if pts:
                        self.create_polygon(pts, fill=c, outline="", tags="chart")
                outline_pts = ring_polygon(scx, scy, r_out, r_in, a0, a1, step=2.0)
                if outline_pts:
                    self.create_polygon(outline_pts, fill="", outline="#ffffff", width=1.5, tags="chart")
            else:
                pts = ring_polygon(scx, scy, r_out, r_in, a0, a1, step=2.0)
                if pts:
                    self.create_polygon(pts, fill=color, outline="#ffffff", width=1.5, tags="chart")

            #Sector geometry для hit-test хранится в финальных (не анимированных) углах
            self._drawn_slices.append(SliceGeom(s.index, s.category, s.value, s.percent,
                                                cfg.rotation + s.start, s.sweep, s.color_index))

            # --- Подписи данных ---
            if labels_on and progress >= 0.999:
                txt = format_value(s.percent if cfg.label_mode == "percent" else s.value,
                                   cfg, percent=cfg.label_mode == "percent")
                mid = cfg.rotation + s.start + s.sweep / 2.0
                if s.sweep >= 20:  # достаточно места внутри сектора
                    r_mid = (r_in + r_out) / 2.0 if cfg.donut else r_out * 0.66
                    tx, ty = polar(scx, scy, r_mid, mid)
                    if self.font_small.measure(txt) <= max(24, (r_out - r_in) * 1.4):
                        self.create_text(tx, ty, text=txt, font=self.font_small,
                                         fill=text_on(color), tags="chart")
                elif s.sweep >= 2.5:  # узкий сектор — выносная подпись с лидером
                    x1, y1 = polar(scx, scy, r_out + 2, mid)
                    x2, y2 = polar(scx, scy, r_out + 12, mid)
                    right = math.sin(math.radians(mid)) >= 0
                    self.create_line(x1, y1, x2, y2, fill="#9aa0a6", tags="chart")
                    self.create_text(x2 + (3 if right else -3), y2, text=txt,
                                     font=self.font_small, fill="#3c4043",
                                     anchor="w" if right else "e", tags="chart")

        # Центр «бублика»: итоговая сумма
        if cfg.donut and r_in > 26 and progress >= 0.999:
            self.create_text(cx, cy - 8, text="Всего", font=self.font_small,
                             fill="#80868b", tags="chart")
            self.create_text(cx, cy + 8, text=truncate(format_value(self._pie_total, cfg),
                                                       self.font_normal, r_in * 1.7),
                             font=self.font_normal, fill=cfg.fg, tags="chart")

    # ------------------------------------------------- ИНТЕРАКТИВ / HIT-TEST
    def _hit_test(self, x: float, y: float):
        """
        Определение элемента под курсором.
        Для секторов — честная полярная математика (atan2 + проверка радиуса),
        поэтому «дырка» бублика и сдвинутые секторы обрабатываются корректно.
        """
        if self._pie_meta and self._drawn_slices:
            cx, cy, r_out, r_in, rot = self._pie_meta
            for s in self._drawn_slices:
                ox = oy = 0.0
                if s.index == self.cfg.explode_index:
                    ox, oy = polar(0, 0, self.cfg.explode_offset, s.start + s.sweep / 2.0)
                dx, dy = x - (cx + ox), y - (cy + oy)
                dist = math.hypot(dx, dy)
                if not (r_in <= dist <= r_out):
                    continue
                ang = math.degrees(math.atan2(dx, -dy)) % 360.0  # 0° = верх, по часовой
                rel = (ang - s.start) % 360.0
                if rel <= s.sweep:
                    return ("slice", s)
            return None
        for b in self._bars:
            if b.x0 <= x <= b.x1 and b.y0 <= y <= b.y1:
                return ("bar", b)
        return None

    def _on_motion(self, event) -> None:
        """Подсветка элемента + tooltip. Перерисовка всего графика НЕ выполняется."""
        hit = self._hit_test(event.x, event.y)
        key = None
        if hit:
            key = (hit[0], id(hit[1]))
        if key == self._hover_key:
            return
        self._hover_key = key
        self._clear_overlay()
        if not hit:
            return
        cfg = self.cfg
        if hit[0] == "bar":
            b: BarGeom = hit[1]
            self.create_rectangle(b.x0, b.y0, b.x1, b.y1, outline="#202124",
                                  width=2, tags="overlay")
            name = self.series_names[b.series] if b.series < len(self.series_names) else f"Ряд {b.series+1}"
            lines = [b.category,
                     f"{name}: {format_value(b.value, cfg)}",
                     f"Доля: {b.percent:.2f}%"]
        else:
            s: SliceGeom = hit[1]
            cx, cy, r_out, r_in, rot = self._pie_meta
            ox = oy = 0.0
            if s.index == cfg.explode_index:
                ox, oy = polar(0, 0, cfg.explode_offset, s.start + s.sweep / 2.0)
            pts = ring_polygon(cx + ox, cy + oy, r_out, r_in, s.start, s.start + s.sweep, step=2.0)
            if pts:
                self.create_polygon(pts, fill="", outline="#202124", width=2, tags="overlay")
            lines = [s.category,
                     f"Значение: {format_value(s.value, cfg)}",
                     f"Доля: {s.percent:.2f}%",
                     "Клик — «взорвать» сектор" if cfg.click_explode else ""]
        self._tooltip(event.x, event.y, [l for l in lines if l])

    def _tooltip(self, x: float, y: float, lines: List[str]) -> None:
        """Простой tooltip средствами Canvas (без Toplevel и без сторонних библиотек)."""
        f = self.font_small
        text = "\n".join(lines)
        w = max(f.measure(l) for l in lines) + 14
        h = f.metrics("linespace") * len(lines) + 10
        tx = clamp(x + 16, 4, max(4, self.winfo_width() - w - 4))
        ty = clamp(y + 16, 4, max(4, self.winfo_height() - h - 4))
        self.create_rectangle(tx, ty, tx + w, ty + h, fill="#ffffe1",
                              outline="#9aa0a6", tags="overlay")
        self.create_text(tx + 7, ty + 5, text=text, font=f, anchor="nw",
                         fill="#202124", justify="left", tags="overlay")

    def _clear_overlay(self) -> None:
        self.delete("overlay")
        self._hover_key = None

    def _on_click(self, event) -> None:
        """Интерактивность круговой диаграммы: «взрыв» сектора по клику."""
        cfg = self.cfg
        if cfg.chart_type != "pie" or not cfg.click_explode:
            return
        hit = self._hit_test(event.x, event.y)
        if hit and hit[0] == "slice":
            idx = hit[1].index
            cfg.explode_index = -1 if cfg.explode_index == idx else idx
            if self._on_pick:
                self._on_pick(cfg.explode_index)
            self.refresh(animate=False)


# =============================================================================
# 5. ПАНЕЛИ ИНТЕРФЕЙСА
# =============================================================================


class DataPanel(ttk.Frame):
    """
    ЛЕВАЯ ПАНЕЛЬ: таблица данных (Treeview) с ручным добавлением/удалением/
    редактированием (в том числе inline по двойному клику) и генератор
    тестовых сценариев для проверки экстремальных наборов данных.
    """

    def __init__(self, master, app: "ChartLabApp"):
        super().__init__(master, padding=6)
        self.app = app
        self._editor: Optional[ttk.Entry] = None
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        ttk.Label(self, text="Источник данных Chart1", font=("TkDefaultFont", 10, "bold"))\
            .grid(row=0, column=0, sticky="w", pady=(0, 4))

        # --- Таблица ---
        tbl = ttk.Frame(self)
        tbl.grid(row=1, column=0, sticky="nsew")
        tbl.columnconfigure(0, weight=1)
        tbl.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(tbl, columns=("cat", "v1", "v2"), show="headings", selectmode="extended")
        for col, title, width, anchor in (("cat", "Категория", 150, "w"),
                                          ("v1", "Значение", 80, "e"),
                                          ("v2", "Ряд 2", 70, "e")):
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width, anchor=anchor, stretch=(col == "cat"))
        self.tree.grid(row=0, column=0, sticky="nsew")
        vs = ttk.Scrollbar(tbl, orient="vertical", command=self.tree.yview)
        vs.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", self._begin_inline_edit)
        self.tree.bind("<Delete>", lambda e: self.delete_selected())

        # --- Поля быстрого ввода / редактирования ---
        edit = ttk.LabelFrame(self, text="Запись (двойной клик по ячейке — правка на месте)", padding=5)
        edit.grid(row=2, column=0, sticky="ew", pady=6)
        edit.columnconfigure(1, weight=1)
        self.e_cat, self.e_v1, self.e_v2 = tk.StringVar(), tk.StringVar(), tk.StringVar()
        for r, (label, var) in enumerate((("Категория", self.e_cat), ("Значение", self.e_v1), ("Ряд 2", self.e_v2))):
            ttk.Label(edit, text=label).grid(row=r, column=0, sticky="w", pady=1)
            ent = ttk.Entry(edit, textvariable=var)
            ent.grid(row=r, column=1, sticky="ew", padx=4, pady=1)
            ent.bind("<Return>", lambda e: self.apply_fields())
        btns = ttk.Frame(edit)
        btns.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        ttk.Button(btns, text="Применить", command=self.apply_fields).pack(side="left")
        ttk.Button(btns, text="+ Добавить", command=self.add_row).pack(side="left", padx=3)
        ttk.Button(btns, text="− Удалить", command=self.delete_selected).pack(side="left")

        nav = ttk.Frame(self)
        nav.grid(row=3, column=0, sticky="ew")
        ttk.Button(nav, text="↑", width=3, command=lambda: self.move(-1)).pack(side="left")
        ttk.Button(nav, text="↓", width=3, command=lambda: self.move(1)).pack(side="left", padx=2)
        ttk.Button(nav, text="Очистить всё", command=self.clear_all).pack(side="left", padx=4)
        self.v_use2 = tk.BooleanVar(value=False)
        ttk.Checkbutton(nav, text="Ряд 2 активен", variable=self.v_use2,
                        command=lambda: self.app.data_changed("Переключение второго ряда")).pack(side="left", padx=4)

        # --- Генератор тестовых сценариев ---
        gen = ttk.LabelFrame(self, text="Генератор тестовых сценариев", padding=5)
        gen.grid(row=4, column=0, sticky="ew", pady=6)
        gen.columnconfigure(0, weight=1)
        row = ttk.Frame(gen)
        row.grid(row=0, column=0, sticky="ew")
        ttk.Label(row, text="Точек:").pack(side="left")
        self.v_count = tk.IntVar(value=120)
        ttk.Spinbox(row, from_=10, to=5000, increment=10, textvariable=self.v_count, width=7)\
            .pack(side="left", padx=4)
        ttk.Button(gen, text="Много точек", command=self.scn_many)\
            .grid(row=1, column=0, sticky="ew", pady=2)
        ttk.Button(gen, text="Отрицательные и 0", command=self.scn_negative)\
            .grid(row=2, column=0, sticky="ew", pady=2)
        ttk.Button(gen, text="Диспропорция (1 : 1 000 000)", command=self.scn_disproportion)\
            .grid(row=3, column=0, sticky="ew", pady=2)
        ttk.Button(gen, text="Длинные названия", command=self.scn_long)\
            .grid(row=4, column=0, sticky="ew", pady=2)
        ttk.Button(gen, text="Все нули (деление на 0)", command=self.scn_zeros)\
            .grid(row=5, column=0, sticky="ew", pady=2)
        ttk.Button(gen, text="Сброс к демо-набору", command=self.scn_default)\
            .grid(row=6, column=0, sticky="ew", pady=2)

    # -------------------------------------------------------- работа с таблицей
    def reload_tree(self, select_index: Optional[int] = None) -> None:
        """Полная пересборка Treeview из модели (просто и надёжно до ~1000 строк)."""
        self.tree.delete(*self.tree.get_children())
        for i, r in enumerate(self.app.rows):
            self.tree.insert("", "end", iid=str(i),
                             values=(r.category, compact_number(r.v1), compact_number(r.v2)))
        if select_index is not None and 0 <= select_index < len(self.app.rows):
            self.tree.selection_set(str(select_index))
            self.tree.see(str(select_index))

    def _selected_index(self) -> Optional[int]:
        sel = self.tree.selection()
        return int(sel[0]) if sel else None

    def _on_select(self, _evt=None) -> None:
        i = self._selected_index()
        if i is None:
            return
        r = self.app.rows[i]
        self.e_cat.set(r.category)
        self.e_v1.set(str(r.v1))
        self.e_v2.set(str(r.v2))

    @staticmethod
    def _parse_float(text: str) -> float:
        """Терпимый парсер числа: пробелы-разделители, запятая как точка."""
        t = text.strip().replace(" ", "").replace("\u00a0", "").replace(",", ".")
        if t in ("", "-", "+"):
            raise ValueError("пустое значение")
        return float(t)

    def apply_fields(self) -> None:
        i = self._selected_index()
        if i is None:
            self.app.log("Не выбрана строка для редактирования — используйте «+ Добавить».", "WARN")
            return
        try:
            v1 = self._parse_float(self.e_v1.get())
            v2 = self._parse_float(self.e_v2.get()) if self.e_v2.get().strip() else 0.0
        except ValueError as ex:
            self.app.log(f"Ошибка ввода значения: {ex}. Ожидается число (например -50, 0, 1234.5).", "ERROR")
            return
        cat = self.e_cat.get().strip() or f"Категория {i + 1}"
        self.app.rows[i] = DataRow(cat, v1, v2)
        self.reload_tree(i)
        self.app.data_changed(f"Изменена запись #{i + 1}: «{cat}»")

    def add_row(self) -> None:
        try:
            v1 = self._parse_float(self.e_v1.get()) if self.e_v1.get().strip() else round(random.uniform(10, 100), 1)
            v2 = self._parse_float(self.e_v2.get()) if self.e_v2.get().strip() else round(v1 * 0.6, 1)
        except ValueError as ex:
            self.app.log(f"Не удалось добавить строку: {ex}", "ERROR")
            return
        cat = self.e_cat.get().strip() or f"Категория {len(self.app.rows) + 1}"
        self.app.rows.append(DataRow(cat, v1, v2))
        self.reload_tree(len(self.app.rows) - 1)
        self.app.data_changed(f"Добавлена запись «{cat}» = {v1}")

    def delete_selected(self) -> None:
        sel = self.tree.selection()
        if not sel:
            self.app.log("Удаление: строки не выбраны.", "WARN")
            return
        idxs = sorted((int(s) for s in sel), reverse=True)
        for i in idxs:
            del self.app.rows[i]
        self.reload_tree(min(idxs[-1], len(self.app.rows) - 1) if self.app.rows else None)
        self.app.data_changed(f"Удалено записей: {len(idxs)}")

    def move(self, delta: int) -> None:
        i = self._selected_index()
        if i is None:
            return
        j = i + delta
        if 0 <= j < len(self.app.rows):
            self.app.rows[i], self.app.rows[j] = self.app.rows[j], self.app.rows[i]
            self.reload_tree(j)
            self.app.data_changed("Порядок категорий изменён")

    def clear_all(self) -> None:
        self.app.rows = []
        self.reload_tree()
        self.app.data_changed("Таблица данных очищена (проверка поведения при пустом наборе)")

    # -------------------------------------------------- INLINE-РЕДАКТИРОВАНИЕ
    def _begin_inline_edit(self, event) -> None:
        """ttk.Entry поверх ячейки Treeview — стандартный приём без сторонних библиотек."""
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        col = self.tree.identify_column(event.x)
        row = self.tree.identify_row(event.y)
        if not row or not col:
            return
        box = self.tree.bbox(row, col)
        if not box:
            return
        x, y, w, h = box
        idx, cidx = int(row), int(col[1:]) - 1
        value = (self.app.rows[idx].category, self.app.rows[idx].v1, self.app.rows[idx].v2)[cidx]
        if self._editor:
            self._editor.destroy()
        var = tk.StringVar(value=str(value))
        self._editor = ttk.Entry(self.tree, textvariable=var)
        self._editor.place(x=x, y=y, width=w, height=h)
        self._editor.focus_set()
        self._editor.select_range(0, "end")

        def commit(_e=None):
            if not self._editor:
                return
            raw = var.get()
            self._editor.destroy()
            self._editor = None
            r = self.app.rows[idx]
            try:
                if cidx == 0:
                    r.category = raw.strip() or r.category
                else:
                    val = self._parse_float(raw)
                    if cidx == 1:
                        r.v1 = val
                    else:
                        r.v2 = val
            except ValueError as ex:
                self.app.log(f"Правка ячейки отменена: {ex}", "ERROR")
                return
            self.reload_tree(idx)
            self.app.data_changed(f"Inline-правка строки #{idx + 1}")

        def cancel(_e=None):
            if self._editor:
                self._editor.destroy()
                self._editor = None

        self._editor.bind("<Return>", commit)
        self._editor.bind("<Escape>", cancel)
        self._editor.bind("<FocusOut>", commit)

    # ----------------------------------------------------------- СЦЕНАРИИ
    def scn_many(self) -> None:
        n = max(2, int(self.v_count.get()))
        self.app.rows = [DataRow(f"Категория {i + 1}",
                                 round(random.uniform(5, 500), 1),
                                 round(random.uniform(5, 500), 1)) for i in range(n)]
        self.reload_tree(0)
        self.app.data_changed(f"Сценарий «Много точек»: сгенерировано {n} категорий", animate=True)
        self.app.log("Проверяется читаемость: подписи категорий прореживаются и поворачиваются, "
                     "data labels отключаются для тонких столбцов, легенда сворачивается в «… ещё N».", "INFO")

    def scn_negative(self) -> None:
        self.app.rows = [DataRow("Отрицательное", -50, -20),
                         DataRow("Ноль", 0, 0),
                         DataRow("Положительное", 100, 60),
                         DataRow("Малое отрицательное", -5, -75),
                         DataRow("Большое положительное", 250, 120),
                         DataRow("Ещё ноль", 0, 15)]
        self.reload_tree(0)
        self.app.data_changed("Сценарий «Отрицательные и 0»: -50, 0, 100, …", animate=True)
        self.app.log("Переключитесь на круговую диаграмму — отрицательные значения будут "
                     "проигнорированы с предупреждением в этом логе.", "INFO")

    def scn_disproportion(self) -> None:
        self.app.rows = [DataRow("Гигант", 1_000_000, 1_000_000)]
        self.app.rows += [DataRow(f"Карлик {i}", 1, 1) for i in range(1, 8)]
        self.reload_tree(0)
        self.app.data_changed("Сценарий «Диспропорция»: 1 000 000 против семи единиц", animate=True)
        self.app.log("На линейной шкале малые столбцы вырождаются в 1 px. Включите "
                     "«Оси координат → Логарифмическая» для сравнения.", "INFO")

    def scn_long(self) -> None:
        base = "Очень длинное наименование категории №{} — департамент перспективных исследований и разработки пользовательских интерфейсов"
        self.app.rows = [DataRow(base.format(i + 1), round(random.uniform(20, 200), 1),
                                 round(random.uniform(20, 200), 1)) for i in range(6)]
        self.reload_tree(0)
        self.app.data_changed("Сценарий «Длинные названия»: проверка обрезки/переноса текста", animate=True)
        self.app.log("Длинные подписи обрезаются с «…»; полный текст доступен в tooltip при "
                     "наведении на столбец или сектор.", "INFO")

    def scn_zeros(self) -> None:
        self.app.rows = [DataRow(f"Ноль {i + 1}", 0, 0) for i in range(5)]
        self.reload_tree(0)
        self.app.data_changed("Сценарий «Все нули»: проверка защиты от деления на ноль", animate=True)

    def scn_default(self) -> None:
        self.app.rows = default_rows()
        self.reload_tree(0)
        self.app.data_changed("Загружен демонстрационный набор данных", animate=True)


class SettingsPanel(ttk.Frame):
    """
    ПРАВАЯ ПАНЕЛЬ: ttk.Notebook с четырьмя секциями настроек.
    Все контроллеры связаны с tk-переменными; единый обработчик _push()
    переносит их значения в ChartConfig и запрашивает перерисовку.
    """

    def __init__(self, master, app: "ChartLabApp"):
        super().__init__(master, padding=6)
        self.app = app
        self.cfg = app.cfg
        self._syncing = False   # защита от рекурсии при программной установке переменных

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True)
        self.tab_general = ttk.Frame(self.nb, padding=8)
        self.tab_bar = ttk.Frame(self.nb, padding=8)
        self.tab_pie = ttk.Frame(self.nb, padding=8)
        self.tab_axes = ttk.Frame(self.nb, padding=8)
        self.nb.add(self.tab_general, text="Общие")
        self.nb.add(self.tab_bar, text="Столбчатые")
        self.nb.add(self.tab_pie, text="Круговые")
        self.nb.add(self.tab_axes, text="Оси координат")

        self._build_general()
        self._build_bar()
        self._build_pie()
        self._build_axes()

        # Единая трассировка всех переменных настроек
        for var in self._vars:
            var.trace_add("write", self._push)
        self._update_states()

    # ------------------------------------------------------------- хелперы
    @property
    def _vars(self):
        return (self.v_type, self.v_title, self.v_show_title, self.v_legend, self.v_legend_pos,
                self.v_labels, self.v_anim, self.v_anim_dur,
                self.v_orient, self.v_stack, self.v_gap, self.v_palette, self.v_gradient, self.v_by_cat,
                self.v_pie_kind, self.v_inner, self.v_rotation, self.v_explode, self.v_explode_off, self.v_click,
                self.v_grid, self.v_scale, self.v_prefix, self.v_suffix, self.v_decimals)

    def _scale(self, parent, row, text, var, lo, hi, fmt="{:.2f}"):
        """Строка «подпись + Slider + текущее значение»."""
        ttk.Label(parent, text=text).grid(row=row, column=0, sticky="w", pady=3)
        sc = ttk.Scale(parent, from_=lo, to=hi, variable=var)
        sc.grid(row=row, column=1, sticky="ew", pady=3)
        lbl = ttk.Label(parent, width=7, text=fmt.format(var.get()))
        lbl.grid(row=row, column=2, sticky="e")
        var.trace_add("write", lambda *a: lbl.configure(text=fmt.format(var.get())))
        return sc

    # ---------------------------------------------------------- вкладка «Общие»
    def _build_general(self) -> None:
        p = self.tab_general
        p.columnconfigure(1, weight=1)
        c = self.cfg
        self.v_type = tk.StringVar(value="Столбчатая (Bar/Column)")
        self.v_title = tk.StringVar(value=c.title)
        self.v_show_title = tk.BooleanVar(value=c.show_title)
        self.v_legend = tk.BooleanVar(value=c.legend_visible)
        self.v_legend_pos = tk.StringVar(value="Справа")
        self.v_labels = tk.StringVar(value="Абсолютные значения")
        self.v_anim = tk.BooleanVar(value=c.animated)
        self.v_anim_dur = tk.DoubleVar(value=c.anim_duration)

        ttk.Label(p, text="Тип диаграммы").grid(row=0, column=0, sticky="w")
        ttk.Combobox(p, textvariable=self.v_type, state="readonly",
                     values=["Столбчатая (Bar/Column)", "Круговая (Pie/Donut)"])\
            .grid(row=0, column=1, columnspan=2, sticky="ew", pady=3)

        ttk.Label(p, text="Заголовок").grid(row=1, column=0, sticky="w")
        ttk.Entry(p, textvariable=self.v_title).grid(row=1, column=1, columnspan=2, sticky="ew", pady=3)
        ttk.Checkbutton(p, text="Показывать заголовок", variable=self.v_show_title)\
            .grid(row=2, column=0, columnspan=3, sticky="w")

        ttk.Separator(p).grid(row=3, column=0, columnspan=3, sticky="ew", pady=6)
        ttk.Checkbutton(p, text="Легенда включена", variable=self.v_legend)\
            .grid(row=4, column=0, columnspan=3, sticky="w")
        ttk.Label(p, text="Позиция легенды").grid(row=5, column=0, sticky="w")
        ttk.Combobox(p, textvariable=self.v_legend_pos, state="readonly",
                     values=["Сверху", "Снизу", "Слева", "Справа"])\
            .grid(row=5, column=1, columnspan=2, sticky="ew", pady=3)

        ttk.Separator(p).grid(row=6, column=0, columnspan=3, sticky="ew", pady=6)
        ttk.Label(p, text="Подписи данных").grid(row=7, column=0, sticky="w")
        ttk.Combobox(p, textvariable=self.v_labels, state="readonly",
                     values=["Скрыты", "Абсолютные значения", "Проценты %"])\
            .grid(row=7, column=1, columnspan=2, sticky="ew", pady=3)

        ttk.Separator(p).grid(row=8, column=0, columnspan=3, sticky="ew", pady=6)
        ttk.Checkbutton(p, text="Плавная анимация (через .after)", variable=self.v_anim)\
            .grid(row=9, column=0, columnspan=3, sticky="w")
        self._scale(p, 10, "Длительность, мс", self.v_anim_dur, 100, 2000, "{:.0f}")

        ttk.Button(p, text="Перерисовать с анимацией",
                   command=lambda: self.app.request_refresh(animate=True, delay=0,
                                                            reason="Ручная перерисовка"))\
            .grid(row=11, column=0, columnspan=3, sticky="ew", pady=(10, 2))
        ttk.Button(p, text="О компоненте Chart1 (в лог)", command=self.app.about)\
            .grid(row=12, column=0, columnspan=3, sticky="ew")

    # ---------------------------------------------------- вкладка «Столбчатые»
    def _build_bar(self) -> None:
        p = self.tab_bar
        p.columnconfigure(1, weight=1)
        c = self.cfg
        self.v_orient = tk.StringVar(value="Вертикальные (Column)")
        self.v_stack = tk.StringVar(value="Группировка (Grouped)")
        self.v_gap = tk.DoubleVar(value=c.gap)
        self.v_palette = tk.StringVar(value=c.palette)
        self.v_gradient = tk.BooleanVar(value=c.gradient)
        self.v_by_cat = tk.BooleanVar(value=c.color_by_category)

        ttk.Label(p, text="Ориентация").grid(row=0, column=0, sticky="w")
        ttk.Combobox(p, textvariable=self.v_orient, state="readonly",
                     values=["Вертикальные (Column)", "Горизонтальные (Bar)"])\
            .grid(row=0, column=1, columnspan=2, sticky="ew", pady=3)

        ttk.Label(p, text="Многорядность").grid(row=1, column=0, sticky="w")
        ttk.Combobox(p, textvariable=self.v_stack, state="readonly",
                     values=["Группировка (Grouped)", "Накопление (Stacked)"])\
            .grid(row=1, column=1, columnspan=2, sticky="ew", pady=3)
        ttk.Label(p, text="Ряды берутся из колонок «Значение» и «Ряд 2».\n"
                          "Включите «Ряд 2 активен» слева.", foreground="#5f6368",
                  justify="left").grid(row=2, column=0, columnspan=3, sticky="w", pady=(0, 6))

        ttk.Separator(p).grid(row=3, column=0, columnspan=3, sticky="ew", pady=6)
        self._scale(p, 4, "Зазор (Gap)", self.v_gap, 0.0, 0.9, "{:.2f}")
        ttk.Label(p, text="Палитра").grid(row=5, column=0, sticky="w")
        ttk.Combobox(p, textvariable=self.v_palette, state="readonly", values=list(PALETTES.keys()))\
            .grid(row=5, column=1, columnspan=2, sticky="ew", pady=3)
        ttk.Checkbutton(p, text="Градиентная заливка", variable=self.v_gradient)\
            .grid(row=6, column=0, columnspan=3, sticky="w")
        ttk.Checkbutton(p, text="Раскрашивать по категориям", variable=self.v_by_cat)\
            .grid(row=7, column=0, columnspan=3, sticky="w")
        ttk.Label(p, text="Градиент рисуется полосами средствами Canvas\n"
                          "(без изображений) — влияет на производительность.",
                  foreground="#5f6368", justify="left")\
            .grid(row=8, column=0, columnspan=3, sticky="w", pady=6)

    # ----------------------------------------------------- вкладка «Круговые»
    def _build_pie(self) -> None:
        p = self.tab_pie
        p.columnconfigure(1, weight=1)
        c = self.cfg
        self.v_pie_kind = tk.StringVar(value="Классический круг (Pie)")
        self.v_inner = tk.DoubleVar(value=c.inner_ratio)
        self.v_rotation = tk.DoubleVar(value=c.rotation)
        self.v_explode = tk.StringVar(value="(нет)")
        self.v_explode_off = tk.DoubleVar(value=c.explode_offset)
        self.v_click = tk.BooleanVar(value=c.click_explode)

        ttk.Label(p, text="Вид").grid(row=0, column=0, sticky="w")
        ttk.Combobox(p, textvariable=self.v_pie_kind, state="readonly",
                     values=["Классический круг (Pie)", "Бублик (Donut)"])\
            .grid(row=0, column=1, columnspan=2, sticky="ew", pady=3)
        self.sc_inner = self._scale(p, 1, "Внутр. радиус", self.v_inner, 0.05, 0.9, "{:.2f}")

        ttk.Separator(p).grid(row=2, column=0, columnspan=3, sticky="ew", pady=6)
        self._scale(p, 3, "Поворот, °", self.v_rotation, 0, 360, "{:.0f}")

        ttk.Separator(p).grid(row=4, column=0, columnspan=3, sticky="ew", pady=6)
        ttk.Label(p, text="«Взорвать» сектор").grid(row=5, column=0, sticky="w")
        self.cb_explode = ttk.Combobox(p, textvariable=self.v_explode, state="readonly", values=["(нет)"])
        self.cb_explode.grid(row=5, column=1, columnspan=2, sticky="ew", pady=3)
        self._scale(p, 6, "Сдвиг, px", self.v_explode_off, 0, 60, "{:.0f}")
        ttk.Checkbutton(p, text="Взрывать по клику на секторе", variable=self.v_click)\
            .grid(row=7, column=0, columnspan=3, sticky="w")
        ttk.Label(p, text="Клик по сектору переключает «взрыв»;\n"
                          "список выше синхронизируется автоматически.",
                  foreground="#5f6368", justify="left")\
            .grid(row=8, column=0, columnspan=3, sticky="w", pady=6)

    # --------------------------------------------------------- вкладка «Оси»
    def _build_axes(self) -> None:
        p = self.tab_axes
        p.columnconfigure(1, weight=1)
        c = self.cfg
        self.v_grid = tk.BooleanVar(value=c.grid)
        self.v_scale = tk.StringVar(value="Линейная")
        self.v_prefix = tk.StringVar(value=c.prefix)
        self.v_suffix = tk.StringVar(value=c.suffix)
        self.v_decimals = tk.IntVar(value=c.decimals)

        ttk.Checkbutton(p, text="Сетка (Grid)", variable=self.v_grid)\
            .grid(row=0, column=0, columnspan=3, sticky="w", pady=3)
        ttk.Label(p, text="Шкала").grid(row=1, column=0, sticky="w")
        ttk.Combobox(p, textvariable=self.v_scale, state="readonly",
                     values=["Линейная", "Логарифмическая (log10)"])\
            .grid(row=1, column=1, columnspan=2, sticky="ew", pady=3)

        ttk.Separator(p).grid(row=2, column=0, columnspan=3, sticky="ew", pady=6)
        ttk.Label(p, text="Префикс").grid(row=3, column=0, sticky="w")
        ttk.Entry(p, textvariable=self.v_prefix, width=10)\
            .grid(row=3, column=1, sticky="ew", pady=3)
        ttk.Label(p, text="Суффикс").grid(row=4, column=0, sticky="w")
        ttk.Entry(p, textvariable=self.v_suffix, width=10)\
            .grid(row=4, column=1, sticky="ew", pady=3)
        ttk.Label(p, text="Знаков после запятой").grid(row=5, column=0, sticky="w")
        ttk.Spinbox(p, from_=0, to=4, textvariable=self.v_decimals, width=6)\
            .grid(row=5, column=1, sticky="w", pady=3)
        ttk.Button(p, text="Префикс «$»", command=lambda: self.v_prefix.set("$ "))\
            .grid(row=6, column=0, columnspan=3, sticky="ew", pady=2)
        ttk.Button(p, text="Суффикс « ₽»", command=lambda: self.v_suffix.set(" ₽"))\
            .grid(row=7, column=0, columnspan=3, sticky="ew", pady=2)
        ttk.Label(p, text="Вкладка активна только для столбчатых диаграмм.\n"
                          "Лог. шкала игнорирует значения ≤ 0 (см. лог).",
                  foreground="#5f6368", justify="left")\
            .grid(row=8, column=0, columnspan=3, sticky="w", pady=8)

    # ------------------------------------------------------- синхронизация
    def _push(self, *_args) -> None:
        """Перенос значений контроллеров в ChartConfig + запрос перерисовки."""
        if self._syncing:
            return
        c = self.cfg
        # Анимация уместна при «структурных» изменениях, но не при拖动 слайдеров.
        structural = (c.chart_type, c.donut, c.horizontal, c.stack_mode)

        c.chart_type = "pie" if self.v_type.get().startswith("Круговая") else "bar"
        c.title = self.v_title.get()
        c.show_title = self.v_show_title.get()
        c.legend_visible = self.v_legend.get()
        c.legend_position = {"Сверху": "top", "Снизу": "bottom",
                             "Слева": "left", "Справа": "right"}[self.v_legend_pos.get()]
        c.label_mode = {"Скрыты": "none", "Абсолютные значения": "value",
                        "Проценты %": "percent"}[self.v_labels.get()]
        c.animated = self.v_anim.get()
        c.anim_duration = int(self.v_anim_dur.get())

        c.horizontal = self.v_orient.get().startswith("Горизонтальные")
        c.stack_mode = "stacked" if self.v_stack.get().startswith("Накопление") else "grouped"
        c.gap = float(self.v_gap.get())
        c.palette = self.v_palette.get()
        c.gradient = self.v_gradient.get()
        c.color_by_category = self.v_by_cat.get()

        c.donut = self.v_pie_kind.get().startswith("Бублик")
        c.inner_ratio = float(self.v_inner.get())
        c.rotation = float(self.v_rotation.get())
        c.explode_offset = float(self.v_explode_off.get())
        c.click_explode = self.v_click.get()
        idx = self.cb_explode.current()
        c.explode_index = idx - 1 if idx > 0 else -1

        c.grid = self.v_grid.get()
        c.log_scale = self.v_scale.get().startswith("Логарифмическая")
        c.prefix = self.v_prefix.get()
        c.suffix = self.v_suffix.get()
        try:
            c.decimals = int(self.v_decimals.get())
        except tk.TclError:
            c.decimals = 0

        animate = structural != (c.chart_type, c.donut, c.horizontal, c.stack_mode)
        self._update_states()
        self.app.request_refresh(animate=animate)

    def _update_states(self) -> None:
        """Блокировка неактуальных секций: оси — только для bar, дырка — только для donut."""
        is_bar = self.cfg.chart_type == "bar"
        self.nb.tab(3, state="normal" if is_bar else "disabled")
        set_enabled(self.tab_axes, is_bar)
        try:
            self.sc_inner.state(["!disabled"] if self.cfg.donut else ["disabled"])
        except tk.TclError:
            pass

    def update_categories(self, categories: List[str]) -> None:
        """Обновление списка секторов для «взрыва» при изменении данных."""
        self._syncing = True
        try:
            values = ["(нет)"] + [f"{i + 1}. {truncate(c, self.app.chart.font_small, 180)}"
                                  for i, c in enumerate(categories)]
            self.cb_explode.configure(values=values)
            idx = self.cfg.explode_index + 1
            if 0 <= idx < len(values) and idx > 0:
                self.cb_explode.current(idx)
            else:
                self.cfg.explode_index = -1
                self.cb_explode.current(0)
        finally:
            self._syncing = False

    def set_explode_from_chart(self, index: int) -> None:
        """Обратная синхронизация: клик по Canvas -> выпадающий список."""
        self._syncing = True
        try:
            self.cb_explode.current(index + 1 if index >= 0 else 0)
        finally:
            self._syncing = False


def set_enabled(widget, enabled: bool) -> None:
    """Рекурсивное включение/отключение группы контроллеров (ttk и tk)."""
    for child in widget.winfo_children():
        if isinstance(child, (ttk.Frame, ttk.LabelFrame)):
            set_enabled(child, enabled)
            continue
        try:
            if isinstance(child, ttk.Widget) and not isinstance(child, ttk.Label):
                child.state(["!disabled"] if enabled else ["disabled"])
            elif isinstance(child, (tk.Entry, tk.Scale, tk.Checkbutton, tk.Radiobutton)):
                child.configure(state="normal" if enabled else "disabled")
        except tk.TclError:
            pass


class BottomPanel(ttk.Frame):
    """
    НИЖНЯЯ ПАНЕЛЬ: цветной лог выполнения/ошибок, метрики производительности,
    кнопки бенчмарка и экспорта.
    """

    def __init__(self, master, app: "ChartLabApp"):
        super().__init__(master, padding=(6, 4))
        self.app = app
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        box = ttk.LabelFrame(self, text="Журнал выполнения и ошибок", padding=3)
        box.grid(row=0, column=0, sticky="nsew")
        box.columnconfigure(0, weight=1)
        box.rowconfigure(0, weight=1)

        mono = "TkFixedFont"
        for fam in ("Consolas", "DejaVu Sans Mono", "Menlo", "Courier New"):
            if fam in tkfont.families(self):
                mono = fam
                break
        self.text = tk.Text(box, height=9, wrap="word", bg="#1e1f22", fg="#e8eaed",
                            insertbackground="#e8eaed", font=(mono, 9), relief="flat")
        self.text.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(box, orient="vertical", command=self.text.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.text.configure(yscrollcommand=sb.set, state="disabled")
        # Цветовые теги уровней логирования
        self.text.tag_configure("TIME", foreground="#80868b")
        self.text.tag_configure("INFO", foreground="#8ab4f8")
        self.text.tag_configure("WARN", foreground="#fdd663")
        self.text.tag_configure("ERROR", foreground="#f28b82")
        self.text.tag_configure("OK", foreground="#81c995")

        side = ttk.Frame(self)
        side.grid(row=0, column=1, sticky="ns", padx=(8, 0))
        metrics = ttk.LabelFrame(side, text="Метрики", padding=6)
        metrics.pack(fill="x")
        self.lbl_ms = ttk.Label(metrics, text="Отрисовка: — мс", font=("TkDefaultFont", 10, "bold"))
        self.lbl_ms.pack(anchor="w")
        self.lbl_items = ttk.Label(metrics, text="Элементов Canvas: —")
        self.lbl_items.pack(anchor="w")
        self.lbl_points = ttk.Label(metrics, text="Точек данных: —")
        self.lbl_points.pack(anchor="w")
        self.lbl_frames = ttk.Label(metrics, text="Кадров анимации: —")
        self.lbl_frames.pack(anchor="w")

        self.pb = ttk.Progressbar(side, mode="determinate", maximum=50)
        self.pb.pack(fill="x", pady=6)
        self.btn_bench = ttk.Button(side, text="Тест производительности (Бенчмарк)",
                                    command=app.run_benchmark)
        self.btn_bench.pack(fill="x", pady=2)
        ttk.Button(side, text="Экспорт в PNG (.ps)", command=app.export_image).pack(fill="x", pady=2)
        ttk.Button(side, text="Очистить лог", command=self.clear).pack(fill="x", pady=2)

    def log(self, msg: str, level: str = "INFO") -> None:
        """Потокобезопасность не нужна: все вызовы идут из главного цикла Tk."""
        self.text.configure(state="normal")
        self.text.insert("end", datetime.now().strftime("[%H:%M:%S] "), "TIME")
        self.text.insert("end", f"{level:<5} ", level)
        self.text.insert("end", msg + "\n", level)
        # Ограничиваем историю, чтобы лог не съедал память при 1000+ сообщений
        if int(self.text.index("end-1c").split(".")[0]) > 1200:
            self.text.delete("1.0", "300.0")
        self.text.see("end")
        self.text.configure(state="disabled")

    def clear(self) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")
        self.log("Журнал очищен.", "INFO")

    def set_metrics(self, ms: float, items: int, frames: int) -> None:
        self.lbl_ms.configure(text=f"Отрисовка: {ms:.2f} мс")
        self.lbl_items.configure(text=f"Элементов Canvas: {items}")
        self.lbl_frames.configure(text=f"Кадров анимации: {frames if frames else '—'}")


# =============================================================================
# 6. КОНТРОЛЛЕР ПРИЛОЖЕНИЯ
# =============================================================================


def default_rows() -> List[DataRow]:
    """Демонстрационный набор: 6 категорий, два ряда — годится для всех режимов."""
    return [DataRow("Север", 120, 90), DataRow("Юг", 95, 130),
            DataRow("Запад", 160, 70), DataRow("Восток", 80, 110),
            DataRow("Центр", 210, 150), DataRow("Онлайн", 140, 190)]


class ChartLabApp(tk.Tk):
    """
    Главное окно. Собирает панели, владеет моделью (rows) и настройками (cfg),
    маршрутизирует события: данные/настройки -> Chart1.refresh(),
    Chart1 -> лог и метрики.
    """

    def __init__(self):
        super().__init__()
        self.title("Chart1 Lab — стенд исследования компонента диаграмм (только стандартная библиотека)")
        self.geometry("1440x880")
        self.minsize(1100, 700)

        self.cfg = ChartConfig()
        self.rows: List[DataRow] = default_rows()
        self._log_buffer: List[Tuple[str, str]] = []
        self._bottom: Optional[BottomPanel] = None
        self._refresh_after: Optional[str] = None
        self._pending_anim = False
        self._pending_reason: Optional[str] = None
        self._bench: Optional[dict] = None

        self._build_ui()

        self.log("Chart1 Lab запущен. Используются только tkinter/ttk, math, time, random, dataclasses.", "OK")
        self.log("Компонент Chart1 реализован с нуля на tkinter.Canvas; сторонние библиотеки не подключались.", "INFO")
        self.log("Подсказка: наведите курсор на столбец/сектор — появится tooltip; клик по сектору — «взрыв».", "INFO")
        self.data_changed("Инициализация интерфейса", animate=True)
        self.bind("<F5>", lambda e: self.request_refresh(animate=True, delay=0, reason="Обновление по F5"))

    # ------------------------------------------------------------- построение UI
    def _build_ui(self) -> None:
        self.rowconfigure(0, weight=1)
        self.rowconfigure(1, weight=0)
        self.columnconfigure(0, weight=1)

        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)

        # Левая панель
        left = ttk.Frame(paned, width=330)
        self.data_panel = DataPanel(left, self)
        self.data_panel.pack(fill="both", expand=True)
        paned.add(left, weight=0)

        # Центр: мини-строка состояния + Canvas компонента
        center = ttk.Frame(paned)
        center.rowconfigure(1, weight=1)
        center.columnconfigure(0, weight=1)
        self.lbl_mode = ttk.Label(center, text="Chart1", font=("TkDefaultFont", 9), foreground="#5f6368")
        self.lbl_mode.grid(row=0, column=0, sticky="ew", pady=(0, 3))
        holder = ttk.Frame(center, relief="solid", borderwidth=1)
        holder.grid(row=1, column=0, sticky="nsew")
        holder.rowconfigure(0, weight=1)
        holder.columnconfigure(0, weight=1)
        self.chart = Chart1(holder, self.cfg, on_log=self.log,
                            on_metric=self._on_metric, on_pick=self._on_pick)
        self.chart.grid(row=0, column=0, sticky="nsew")
        paned.add(center, weight=1)

        # Правая панель
        right = ttk.Frame(paned, width=350)
        self.settings = SettingsPanel(right, self)
        self.settings.pack(fill="both", expand=True)
        paned.add(right, weight=0)

        # Низ
        self._bottom = BottomPanel(self, self)
        self._bottom.grid(row=1, column=0, sticky="ew", padx=6, pady=(0, 6))
        for msg, lvl in self._log_buffer:
            self._bottom.log(msg, lvl)
        self._log_buffer.clear()

        self.data_panel.reload_tree(0)

    # -------------------------------------------------------------- логирование
    def log(self, msg: str, level: str = "INFO") -> None:
        if self._bottom is None:
            self._log_buffer.append((msg, level))
        else:
            self._bottom.log(msg, level)

    def about(self) -> None:
        self.log("Chart1 API: set_data(categories, series, names); refresh(animate, reason); "
                 "export_postscript(path); свойства — в ChartConfig.", "INFO")
        self.log("Возможности: Column/Bar, Grouped/Stacked, Pie/Donut, легенда 4 позиции, "
                 "data labels (значения/%), линейная и log10 шкала, сетка, префикс/суффикс, "
                 "6 палитр, градиент, поворот, «взрыв» сектора, анимация через .after(), tooltip.", "INFO")

    # -------------------------------------------------------- доступ к данным
    def categories(self) -> List[str]:
        return [r.category for r in self.rows]

    def series_values(self) -> List[List[float]]:
        """Возвращает список рядов; второй ряд — только если он включён чекбоксом."""
        s = [[r.v1 for r in self.rows]]
        if self.data_panel.v_use2.get():
            s.append([r.v2 for r in self.rows])
        return s

    def data_changed(self, reason: str, animate: bool = True) -> None:
        """Единая точка входа при любом изменении таблицы/сценария."""
        self.settings.update_categories(self.categories())
        self._bottom.lbl_points.configure(
            text=f"Точек данных: {len(self.rows)} × {len(self.series_values())} ряд(ов)")
        self.request_refresh(animate=animate, reason=reason, delay=10)

    # --------------------------------------------- отложенная перерисовка (debounce)
    def request_refresh(self, animate: bool = False, reason: Optional[str] = None, delay: int = 45) -> None:
        """
        Слайдеры генерируют десятки событий в секунду — склеиваем их в одну
        перерисовку через .after(45). Это ключевой приём отзывчивости UI.
        """
        self._pending_anim = self._pending_anim or animate
        if reason:
            self._pending_reason = reason
        if self._refresh_after:
            self.after_cancel(self._refresh_after)
        self._refresh_after = self.after(delay, self._do_refresh)

    def _do_refresh(self) -> None:
        self._refresh_after = None
        anim, reason = self._pending_anim, self._pending_reason
        self._pending_anim, self._pending_reason = False, None
        series = self.series_values()
        try:
            self.chart.set_data(self.categories(), series, SERIES_NAMES[:len(series)])
            self.chart.refresh(animate=anim, reason=reason)
        except Exception as ex:  # перехват любых ошибок отрисовки — стенд не должен падать
            self.log(f"Исключение при отрисовке: {type(ex).__name__}: {ex}", "ERROR")
        self._update_mode_label()

    def _update_mode_label(self) -> None:
        c = self.cfg
        if c.chart_type == "bar":
            kind = "Bar (горизонтальные)" if c.horizontal else "Column (вертикальные)"
            mode = "Stacked" if effective_stacked(c, len(self.series_values())) else "Grouped"
            scale = "log10" if c.log_scale else "linear"
            txt = f"Chart1 • {kind} • {mode} • шкала {scale} • рядов: {len(self.series_values())}"
        else:
            kind = "Donut" if c.donut else "Pie"
            txt = (f"Chart1 • {kind} • поворот {c.rotation:.0f}° • "
                   f"взорван сектор: {c.explode_index + 1 if c.explode_index >= 0 else 'нет'}")
        self.lbl_mode.configure(text=txt + f" • категорий: {len(self.rows)}")

    def _on_metric(self, ms: float, items: int, frames: int) -> None:
        self._bottom.set_metrics(ms, items, frames)

    def _on_pick(self, index: int) -> None:
        """Клик по сектору внутри Chart1 -> синхронизация выпадающего списка."""
        self.settings.set_explode_from_chart(index)
        name = self.rows[index].category if 0 <= index < len(self.rows) else "—"
        self.log(f"Интерактивность: {'взорван' if index >= 0 else 'сброшен'} сектор «{name}»." , "INFO")
        self._update_mode_label()

    # ------------------------------------------------------------- БЕНЧМАРК
    def run_benchmark(self) -> None:
        """
        50 циклов «новые данные -> полная отрисовка -> update_idletasks».
        Итерации разложены по .after(1), чтобы не блокировать главный цикл Tk
        (иначе окно «зависает», а измерения включают простой очереди событий).
        По окончании исходные данные восстанавливаются.
        """
        if self._bench is not None:
            self.log("Бенчмарк уже выполняется.", "WARN")
            return
        if not self.rows:
            self.log("Бенчмарк невозможен: таблица данных пуста.", "ERROR")
            return
        snapshot = [DataRow(r.category, r.v1, r.v2) for r in self.rows]
        self._bench = {"i": 0, "n": 50, "times": [], "snapshot": snapshot,
                       "t0": time.perf_counter()}
        self._bottom.btn_bench.state(["disabled"])
        self._bottom.pb.configure(value=0, maximum=50)
        self.log(f"БЕНЧМАРК: старт, 50 итераций, {len(self.rows)} категорий, "
                 f"тип={self.cfg.chart_type}, градиент={self.cfg.gradient}, "
                 f"анимация принудительно выключена.", "INFO")
        self.after(1, self._bench_step)

    def _bench_step(self) -> None:
        st = self._bench
        if st is None:
            return
        i = st["i"]
        if i >= st["n"]:
            self._bench_finish()
            return
        # Новые случайные значения при сохранении категорий и текущего режима
        for r in self.rows:
            r.v1 = round(random.uniform(1, 500), 2)
            r.v2 = round(random.uniform(1, 500), 2)
        t0 = time.perf_counter()
        try:
            series = self.series_values()
            self.chart.set_data(self.categories(), series, SERIES_NAMES[:len(series)])
            self.chart.refresh(animate=False)
            self.chart.update_idletasks()   # принудительно доводим отрисовку до конца
        except Exception as ex:
            self.log(f"Бенчмарк прерван на итерации {i + 1}: {ex}", "ERROR")
            self._bench_finish()
            return
        st["times"].append((time.perf_counter() - t0) * 1000.0)
        st["i"] = i + 1
        self._bottom.pb.configure(value=st["i"])
        if st["i"] % 10 == 0:
            self.log(f"  … итерация {st['i']}/{st['n']}, последняя {st['times'][-1]:.2f} мс", "INFO")
        self.after(1, self._bench_step)

    def _bench_finish(self) -> None:
        st = self._bench
        self._bench = None
        self._bottom.btn_bench.state(["!disabled"])
        if not st:
            return
        self.rows = st["snapshot"]
        self.data_panel.reload_tree(0)
        times = st["times"]
        if times:
            total = (time.perf_counter() - st["t0"]) * 1000.0
            avg = sum(times) / len(times)
            self.log(f"БЕНЧМАРК ЗАВЕРШЁН: итераций {len(times)}, "
                     f"суммарно чистого рендеринга {sum(times):.1f} мс, "
                     f"полное время цикла {total:.1f} мс.", "OK")
            self.log(f"  Среднее время рендеринга одной итерации: {avg:.2f} мс "
                     f"(min {min(times):.2f} / max {max(times):.2f} мс, "
                     f"≈{1000.0 / avg if avg else 0:.1f} FPS-эквивалент).", "OK")
        self.data_changed("Данные восстановлены после бенчмарка", animate=False)

    # --------------------------------------------------------------- ЭКСПОРТ
    def export_image(self) -> None:
        """
        «Экспорт в PNG»: чистый tkinter не умеет PNG, поэтому сохраняется
        векторный PostScript (.ps) штатным методом canvas.postscript().
        Пользователь честно информируется в логе (см. комментарий в Chart1).
        """
        path = filedialog.asksaveasfilename(
            title="Экспорт диаграммы (PostScript)",
            defaultextension=".ps",
            initialfile=f"chart1_{datetime.now().strftime('%Y%m%d_%H%M%S')}.ps",
            filetypes=[("PostScript", "*.ps"), ("Encapsulated PostScript", "*.eps"), ("Все файлы", "*.*")])
        if not path:
            self.log("Экспорт отменён пользователем.", "WARN")
            return
        try:
            t0 = time.perf_counter()
            self.chart.export_postscript(path)
            ms = (time.perf_counter() - t0) * 1000.0
            self.log(f"Файл сохранён: {path} ({ms:.1f} мс).", "OK")
            self.log("Формат — векторный PostScript: canvas.postscript() — единственный "
                     "встроенный механизм экспорта Tkinter. Прямое сохранение PNG невозможно "
                     "без сторонних библиотек (Pillow) или внешнего конвертера "
                     "(Ghostscript: gs -sDEVICE=png16m -r150 -o chart.png chart.ps), "
                     "которые запрещены условиями задачи.", "INFO")
        except Exception as ex:
            self.log(f"Ошибка экспорта: {type(ex).__name__}: {ex}", "ERROR")
            messagebox.showerror("Экспорт не удался",
                                 f"Не удалось сохранить PostScript:\n{ex}")


# =============================================================================
# ТОЧКА ВХОДА
# =============================================================================


def main() -> None:
    app = ChartLabApp()
    # Единый перехватчик исключений Tk-колбэков: стенд пишет ошибку в лог и живёт дальше.
    def tk_error(exc, val, tb):
        app.log(f"Необработанное исключение Tk: {exc.__name__}: {val}", "ERROR")
    app.report_callback_exception = tk_error
    app.mainloop()


if __name__ == "__main__":
    main()