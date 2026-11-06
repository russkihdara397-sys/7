"""
=====================================================================
 Circuit Construction Kit — AC (Python / CustomTkinter)
=====================================================================

README
------
Имитатор симулятора PhET «Circuit Construction Kit — AC» на Python.

Требования (pip):
    pip install customtkinter matplotlib numpy

Запуск:
    python circuit_kit_ac.py

Как пользоваться:
  • Кнопки палитры слева добавляют компонент: нажмите кнопку, затем
    кликните по холсту — элемент появится под курсором.
  • «Провод»: нажмите кнопку, затем кликните по первому выводу
    компонента, потом по второму. Между выводами появится провод
    (snap-to-pin).
  • «Выбор» — режим по умолчанию. Клик по компоненту выделяет его;
    Shift+клик добавляет/убирает из выделения; перетаскивание мышью
    перемещает компонент.
  • Свойства выделенного элемента редактируются на панели справа
    (R, C, L, амплитуда и частота источника). Пересчёт мгновенный.
  • Осциллограммы внизу показывают U(t) и I(t) для всех выделенных
    компонентов (matplotlib встроен в окно).
  • Масштаб — колесо мыши; панорамирование — правая или средняя
    кнопка мыши.
  • Delete — удалить выделенное; Esc — выйти в режим выбора.

Ограничения модели:
  • Упрощённый установившийся расчёт синусоидального тока через
    комплексные импедансы. Все источники считаются работающими на
    одной частоте (берётся частота первого источника).
  • Провода идеальные (нулевое сопротивление).
  • Лампочка светится пропорционально СКЗ-току через неё.
=====================================================================
"""

import math
import numpy as np
import tkinter as tk
import customtkinter as ctk
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg


# ---------------------------------------------------------------------------
# Константы оформления
# ---------------------------------------------------------------------------
BG_CANVAS   = "#141414"
GRID_MINOR  = "#1f1f1f"
COL_LEAD    = "#9e9e9e"
COL_BODY    = "#e0e0e0"
COL_BODY_F  = "#2d2d2d"
COL_SEL     = "#ff9800"
COL_WIRE    = "#00c8ff"
COL_PIN     = "#ffcc00"
COL_PIN_HOV = "#ff5722"
COL_TEXT    = "#cccccc"

PIN_SNAP    = 14.0     # радиус «захвата» вывода в мировых единицах
PIN_DRAW_R  = 4.0      # радиус отрисовки вывода


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------
def dist_point_segment(px, py, x1, y1, x2, y2):
    """Расстояние от точки (px, py) до отрезка (x1,y1)-(x2,y2)."""
    dx, dy = x2 - x1, y2 - y1
    l2 = dx * dx + dy * dy
    if l2 == 0.0:
        return math.hypot(px - x1, py - y1)
    t = ((px - x1) * dx + (py - y1) * dy) / l2
    t = max(0.0, min(1.0, t))
    cx, cy = x1 + t * dx, y1 + t * dy
    return math.hypot(px - cx, py - cy)


def bulb_color(b):
    """Цвет лампочки: 0 -> тускло-жёлтый, 1 -> ярко-оранжевый."""
    b = max(0.0, min(1.0, b))
    r = int(100 + 155 * b)
    g = int(90 + 75 * b)
    bl = int(30 - 30 * b)
    return f"#{r:02x}{g:02x}{bl:02x}"


def format_number(v):
    """Удобный формат числа для поля ввода."""
    if v == 0:
        return "0"
    if 1e-3 <= abs(v) < 1e4:
        return f"{v:.4g}"
    return f"{v:.4e}"


# ---------------------------------------------------------------------------
# Рендерер: переводит мировые координаты в экранные и рисует примитивы
# ---------------------------------------------------------------------------
class Renderer:
    def __init__(self, canvas, zoom, ox, oy):
        self.canvas = canvas
        self.zoom = zoom
        self.ox = ox
        self.oy = oy

    def s(self, x, y):
        """world -> screen"""
        return x * self.zoom + self.ox, y * self.zoom + self.oy

    def line(self, x1, y1, x2, y2, **kw):
        a = self.s(x1, y1)
        b = self.s(x2, y2)
        self.canvas.create_line(*a, *b, **kw)

    def polyline(self, pts, **kw):
        scr = []
        for i in range(0, len(pts), 2):
            sx, sy = self.s(pts[i], pts[i + 1])
            scr.extend([sx, sy])
        self.canvas.create_line(*scr, **kw)

    def oval(self, x1, y1, x2, y2, **kw):
        a = self.s(x1, y1)
        b = self.s(x2, y2)
        self.canvas.create_oval(*a, *b, **kw)

    def rect(self, x1, y1, x2, y2, **kw):
        a = self.s(x1, y1)
        b = self.s(x2, y2)
        self.canvas.create_rectangle(*a, *b, **kw)

    def arc(self, x1, y1, x2, y2, **kw):
        a = self.s(x1, y1)
        b = self.s(x2, y2)
        self.canvas.create_arc(*a, *b, **kw)

    def text(self, x, y, s, **kw):
        px, py = self.s(x, y)
        kw.setdefault("font", ("Segoe UI", 9))
        kw.setdefault("fill", COL_TEXT)
        self.canvas.create_text(px, py, text=s, **kw)


# ---------------------------------------------------------------------------
# Базовый класс компонента
# ---------------------------------------------------------------------------
class Component:
    type = "base"
    display_name = "Компонент"
    DEFAULT_PARAMS = {}

    def __init__(self, x, y):
        import uuid
        self.uid = str(uuid.uuid4())
        self.x = float(x)
        self.y = float(y)
        self.params = dict(self.DEFAULT_PARAMS)
        self._brightness = 0.0

    def pins(self):
        """Возвращает мировые координаты двух выводов (pin0 = «+», pin1 = «-»)."""
        return [(self.x - 40.0, self.y), (self.x + 40.0, self.y)]

    def pin_at(self, wx, wy, tol=PIN_SNAP):
        for i, (px, py) in enumerate(self.pins()):
            if math.hypot(px - wx, py - wy) <= tol:
                return i
        return None

    def hit(self, wx, wy):
        """Попадание курсора в габаритный прямоугольник компонента."""
        return abs(wx - self.x) <= 45.0 and abs(wy - self.y) <= 26.0

    def impedance(self, omega):
        """Комплексный импеданс на частоте omega (рад/с)."""
        raise NotImplementedError

    def draw(self, r: Renderer, selected=False):
        raise NotImplementedError

    def update_from_results(self, V, I):
        """Хук: вызывается после расчёта цепи."""
        pass


# --- Резистор --------------------------------------------------------------
class Resistor(Component):
    type = "resistor"
    display_name = "Резистор"
    DEFAULT_PARAMS = {"R": 10.0}

    def impedance(self, omega):
        R = max(float(self.params["R"]), 1e-9)
        return complex(R, 0.0)

    def draw(self, r, selected=False):
        x, y = self.x, self.y
        col = COL_SEL if selected else COL_BODY
        r.line(x - 40, y, x - 25, y, fill=COL_LEAD, width=2)
        r.line(x + 25, y, x + 40, y, fill=COL_LEAD, width=2)
        r.rect(x - 25, y - 12, x + 25, y + 12,
               outline=col, fill=COL_BODY_F, width=2)
        r.text(x, y - 22, f"R={format_number(self.params['R'])} Ом")


# --- Конденсатор -----------------------------------------------------------
class Capacitor(Component):
    type = "capacitor"
    display_name = "Конденсатор"
    DEFAULT_PARAMS = {"C": 1e-4}   # Ф

    def impedance(self, omega):
        C = max(float(self.params["C"]), 1e-15)
        # Z_C = 1 / (j*omega*C) = -j / (omega*C)
        return complex(0.0, -1.0 / (omega * C))

    def draw(self, r, selected=False):
        x, y = self.x, self.y
        col = COL_SEL if selected else COL_BODY
        r.line(x - 40, y, x - 6, y, fill=COL_LEAD, width=2)
        r.line(x + 6, y, x + 40, y, fill=COL_LEAD, width=2)
        r.line(x - 6, y - 16, x - 6, y + 16, fill=col, width=3)
        r.line(x + 6, y - 16, x + 6, y + 16, fill=col, width=3)
        r.text(x, y - 26, f"C={format_number(self.params['C'])} Ф")


# --- Катушка индуктивности -------------------------------------------------
class Inductor(Component):
    type = "inductor"
    display_name = "Катушка"
    DEFAULT_PARAMS = {"L": 0.1}    # Гн

    def impedance(self, omega):
        L = max(float(self.params["L"]), 1e-15)
        # Z_L = j*omega*L
        return complex(0.0, omega * L)

    def draw(self, r, selected=False):
        x, y = self.x, self.y
        col = COL_SEL if selected else COL_BODY
        r.line(x - 40, y, x - 24, y, fill=COL_LEAD, width=2)
        r.line(x + 24, y, x + 40, y, fill=COL_LEAD, width=2)
        n = 4
        w = 48.0 / n
        for i in range(n):
            x1 = x - 24 + i * w
            x2 = x1 + w
            r.arc(x1, y - 10, x2, y + 10,
                  start=0, extent=180, style="arc",
                  outline=col, width=2)
        r.text(x, y - 22, f"L={format_number(self.params['L'])} Гн")


# --- Лампочка --------------------------------------------------------------
class Bulb(Component):
    type = "bulb"
    display_name = "Лампочка"
    DEFAULT_PARAMS = {"R": 10.0}   # Ом
    NOMINAL_RMS = 0.5              # ток полного свечения, А

    def impedance(self, omega):
        return complex(max(float(self.params["R"]), 1e-9), 0.0)

    def update_from_results(self, V, I):
        # СКЗ тока = амплитуда / sqrt(2)
        Irms = abs(I) / math.sqrt(2.0)
        self._brightness = min(1.0, Irms / self.NOMINAL_RMS)

    def draw(self, r, selected=False):
        x, y = self.x, self.y
        col = COL_SEL if selected else COL_BODY
        fill = bulb_color(self._brightness)
        r.line(x - 40, y, x - 20, y, fill=COL_LEAD, width=2)
        r.line(x + 20, y, x + 40, y, fill=COL_LEAD, width=2)
        r.oval(x - 20, y - 20, x + 20, y + 20,
               outline=col, fill=fill, width=2)
        # «нимб» при ярком свечении
        if self._brightness > 0.3:
            r.oval(x - 25, y - 25, x + 25, y + 25,
                   outline=fill, width=1)
        r.text(x, y - 30, f"R={format_number(self.params['R'])} Ом")


# --- Источник переменного напряжения ---------------------------------------
class ACSource(Component):
    type = "acsource"
    display_name = "Источник AC"
    DEFAULT_PARAMS = {"A": 10.0, "f": 60.0}   # В, Гц

    def draw(self, r, selected=False):
        x, y = self.x, self.y
        col = COL_SEL if selected else COL_BODY
        r.line(x - 40, y, x - 24, y, fill=COL_LEAD, width=2)
        r.line(x + 24, y, x + 40, y, fill=COL_LEAD, width=2)
        r.oval(x - 24, y - 24, x + 24, y + 24,
               outline=col, fill=COL_BODY_F, width=2)
        # синусоида внутри
        pts = []
        for i in range(21):
            t = i / 20.0
            pts.append(x - 14 + 28 * t)
            pts.append(y - 8 * math.sin(2.0 * math.pi * t))
        r.polyline(pts, fill=col, width=2)
        r.text(x, y - 32,
               f"~ {format_number(self.params['A'])}В / "
               f"{format_number(self.params['f'])}Гц")


# ---------------------------------------------------------------------------
# Провод
# ---------------------------------------------------------------------------
class Wire:
    def __init__(self, a, b):
        import uuid
        self.uid = str(uuid.uuid4())
        self.a = a          # (uid компонента, индекс вывода)
        self.b = b

    def __eq__(self, other):
        return isinstance(other, Wire) and self.uid == other.uid

    def __hash__(self):
        return hash(self.uid)


# ---------------------------------------------------------------------------
# Расчёт цепи (MNA для синусоидального установившегося режима)
# ---------------------------------------------------------------------------
class CircuitSolver:
    @staticmethod
    def solve(components, wires):
        """
        Возвращает (results, error_text).

        results[comp.uid] = {"V": комплексная фазовая амплитуда напряжения,
                             "I": комплексная фазовая амплитуда тока}

        Метод: модифицированный узловой анализ (MNA) с комплексными
        проводимостями. Все фазоры нормированы на cos(omega*t).
        """
        if not components:
            return {}, "Схема пуста"

        # ---- 1. Объединение выводов через провода (union-find) -------------
        parent = {}

        def find(k):
            root = k
            while parent[root] != root:
                root = parent[root]
            while parent[k] != root:
                parent[k], k = root, parent[k]
            return root

        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        for c in components:
            for i in (0, 1):
                parent[(c.uid, i)] = (c.uid, i)

        for w in wires:
            if w.a in parent and w.b in parent:
                union(w.a, w.b)

        # ---- 2. Присвоение номеров электрическим узлам --------------------
        node_index = {}
        pin_node = {}
        for c in components:
            for i in (0, 1):
                k = (c.uid, i)
                rt = find(k)
                if rt not in node_index:
                    node_index[rt] = len(node_index)
                pin_node[k] = node_index[rt]

        n = len(node_index)
        if n < 2:
            return {}, "Все выводы соединены в один узел — короткое замыкание"

        # ---- 3. Частота (все источники считаются на одной частоте) --------
        sources = [c for c in components if c.type == "acsource"]
        if not sources:
            return {}, "Добавьте источник переменного напряжения"
        f = float(sources[0].params["f"])
        if f <= 0:
            return {}, "Частота источника должна быть > 0"
        omega = 2.0 * math.pi * f

        # ---- 4. Построение системы MNA ------------------------------------
        GROUND = 0
        n_unk_v = n - 1                  # напряжения узлов 1..n-1
        n_src = len(sources)
        size = n_unk_v + n_src
        A = np.zeros((size, size), dtype=complex)
        rhs = np.zeros(size, dtype=complex)

        def vi(node):
            return -1 if node == GROUND else node - 1

        # 4.1 пассивные ветви (R, C, L, лампочка)
        for c in components:
            if c.type == "acsource":
                continue
            na = pin_node[(c.uid, 0)]
            nb = pin_node[(c.uid, 1)]
            if na == nb:
                # Оба вывода на одном узле — элемент замкнут, ток 0.
                continue
            Z = c.impedance(omega)
            if abs(Z) < 1e-12:
                return {}, f"Нулевой импеданс у компонента {c.display_name}"
            Y = 1.0 / Z
            ia, ib = vi(na), vi(nb)
            if ia >= 0:
                A[ia, ia] += Y
            if ib >= 0:
                A[ib, ib] += Y
            if ia >= 0 and ib >= 0:
                A[ia, ib] -= Y
                A[ib, ia] -= Y

        # 4.2 источники напряжения (AC source — идеальный источник ЭДС)
        src_col = {}
        for k, c in enumerate(sources):
            na = pin_node[(c.uid, 0)]      # «+» вывод
            nb = pin_node[(c.uid, 1)]      # «-» вывод
            if na == nb:
                return {}, "Источник замкнут: оба вывода на одном узле"
            ia, ib = vi(na), vi(nb)
            col = n_unk_v + k
            src_col[c.uid] = col
            # KCL-строки: ток источника «заходит» в узел «+», «выходит» из «-»
            if ia >= 0:
                A[ia, col] += 1.0
            if ib >= 0:
                A[ib, col] -= 1.0
            # уравнение источника: V(na) - V(nb) = E
            if ia >= 0:
                A[col, ia] += 1.0
            if ib >= 0:
                A[col, ib] -= 1.0
            # фазовая амплитуда ЭДС (фаза 0)
            rhs[col] = complex(float(c.params["A"]), 0.0)

        # 4.3 Регуляризация: чтобы «висящие» подцепи не давали сингулярность.
        #     Крошечная проводимость на «землю» практически не влияет на
        #     разности потенциалов между узлами подцепи.
        for i in range(n_unk_v):
            A[i, i] += 1e-12

        try:
            x = np.linalg.solve(A, rhs)
        except np.linalg.LinAlgError:
            return {}, ("Система вырождена: возможны параллельные идеальные "
                        "источники напряжения или короткое замыкание")

        # ---- 5. Восстановление узловых напряжений -------------------------
        V_node = np.zeros(n, dtype=complex)
        for i in range(1, n):
            V_node[i] = x[i - 1]

        # ---- 6. Расчёт напряжений и токов по компонентам ------------------
        results = {}
        for c in components:
            na = pin_node[(c.uid, 0)]
            nb = pin_node[(c.uid, 1)]
            V = V_node[na] - V_node[nb]
            if c.type == "acsource":
                # Ток источника из MNA (направлен от «+» к «-» внутри источника)
                I = x[src_col[c.uid]]
            else:
                if na == nb:
                    I = 0.0 + 0.0j
                else:
                    Z = c.impedance(omega)
                    I = V / Z if abs(Z) > 1e-15 else 0.0 + 0.0j
            results[c.uid] = {"V": complex(V), "I": complex(I)}

        return results, None


# ---------------------------------------------------------------------------
# Определения параметров для панели свойств
# ---------------------------------------------------------------------------
PARAM_DEFS = {
    "resistor":  [("R", "R, Ом")],
    "capacitor": [("C", "C, Ф (напр. 1e-4)")],
    "inductor":  [("L", "L, Гн")],
    "bulb":      [("R", "R, Ом")],
    "acsource":  [("A", "Амплитуда, В"), ("f", "Частота, Гц")],
}


# ---------------------------------------------------------------------------
# Главное окно приложения
# ---------------------------------------------------------------------------
class CircuitApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title("Circuit Construction Kit — AC (Python)")
        self.geometry("1440x900")

        # Модель
        self.components = []
        self.wires = []
        self.selection = []
        self.last_results = {}
        self.last_error = None

        # Вид/режимы
        self.zoom = 1.0
        self.ox = 0.0
        self.oy = 0.0
        self.mode = "select"       # "select" | "add" | "wire"
        self.add_type = None
        self.wire_start = None
        self.drag_comp = None
        self.drag_offset = (0.0, 0.0)
        self.pan_anchor = None
        self._hover_pin = None

        self._build_ui()
        self._bind_events()

        # Первая отрисовка
        self.after(50, self._initial_refresh)

    # -- построение UI ---------------------------------------------------
    def _build_ui(self):
        self.grid_rowconfigure(0, weight=3)
        self.grid_rowconfigure(1, weight=2)
        self.grid_columnconfigure(0, weight=1)

        main = ctk.CTkFrame(self)
        main.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        main.grid_rowconfigure(0, weight=1)
        main.grid_columnconfigure(0, weight=0, minsize=190)
        main.grid_columnconfigure(1, weight=1)
        main.grid_columnconfigure(2, weight=0, minsize=240)

        # палитра
        palette = ctk.CTkFrame(main, width=190)
        palette.grid(row=0, column=0, sticky="nsw", padx=(0, 4))
        self._build_palette(palette)

        # холст
        cf = ctk.CTkFrame(main)
        cf.grid(row=0, column=1, sticky="nsew")
        cf.grid_rowconfigure(0, weight=1)
        cf.grid_columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(cf, bg=BG_CANVAS, highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")

        # свойства
        props = ctk.CTkFrame(main, width=240)
        props.grid(row=0, column=2, sticky="nse", padx=(4, 0))
        self._build_properties(props)

        # осциллограф
        scope = ctk.CTkFrame(self)
        scope.grid(row=1, column=0, sticky="nsew", padx=4, pady=(0, 4))
        scope.grid_rowconfigure(0, weight=1)
        scope.grid_columnconfigure(0, weight=1)
        self.fig = Figure(figsize=(8, 3.4), dpi=90, facecolor="#202020")
        self.ax_v = self.fig.add_subplot(2, 1, 1)
        self.ax_i = self.fig.add_subplot(2, 1, 2)
        self.fig.subplots_adjust(left=0.08, right=0.99, top=0.93,
                                 bottom=0.13, hspace=0.50)
        self.mpl_canvas = FigureCanvasTkAgg(self.fig, master=scope)
        self.mpl_canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")

    def _build_palette(self, parent):
        ctk.CTkLabel(parent, text="Компоненты",
                     font=("Segoe UI", 14, "bold")).pack(pady=(8, 4))
        for cls in (ACSource, Resistor, Capacitor, Inductor, Bulb):
            ctk.CTkButton(
                parent, text=cls.display_name,
                command=lambda c=cls: self._begin_add(c)
            ).pack(fill="x", padx=8, pady=3)

        ctk.CTkLabel(parent, text="").pack(pady=2)
        ctk.CTkButton(parent, text="Провод", fg_color="#00695c",
                      hover_color="#00897b",
                      command=self._begin_wire).pack(fill="x", padx=8, pady=3)
        ctk.CTkButton(parent, text="Выбор", fg_color="#37474f",
                      hover_color="#546e7a",
                      command=self._begin_select).pack(fill="x", padx=8, pady=3)

        ctk.CTkLabel(parent, text="").pack(pady=6)
        ctk.CTkButton(parent, text="Удалить выделенное",
                      fg_color="#b71c1c", hover_color="#d32f2f",
                      command=self._delete_selection).pack(fill="x", padx=8, pady=3)
        ctk.CTkButton(parent, text="Сбросить вид", fg_color="#455a64",
                      hover_color="#607d8b",
                      command=self._reset_view).pack(fill="x", padx=8, pady=3)
        ctk.CTkButton(parent, text="Демо-схема", fg_color="#4a148c",
                      hover_color="#6a1b9a",
                      command=self._load_demo).pack(fill="x", padx=8, pady=3)

        self.status = ctk.CTkLabel(parent, text="", wraplength=170,
                                   justify="left", text_color="#ffb74d")
        self.status.pack(side="bottom", fill="x", padx=8, pady=8)

    def _build_properties(self, parent):
        ctk.CTkLabel(parent, text="Свойства",
                     font=("Segoe UI", 14, "bold")).pack(pady=(8, 4))
        self.props_inner = ctk.CTkScrollableFrame(parent)
        self.props_inner.pack(fill="both", expand=True, padx=4, pady=4)
        self.props_widgets = []

    # -- события ---------------------------------------------------------
    def _bind_events(self):
        self.canvas.bind("<Button-1>", self._on_left_click)
        self.canvas.bind("<B1-Motion>", self._on_left_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_left_release)
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Button-4>", self._on_wheel)     # Linux
        self.canvas.bind("<Button-5>", self._on_wheel)
        self.canvas.bind("<ButtonPress-3>", self._on_pan_start)
        self.canvas.bind("<B3-Motion>", self._on_pan_move)
        self.canvas.bind("<ButtonPress-2>", self._on_pan_start)
        self.canvas.bind("<B2-Motion>", self._on_pan_move)
        self.canvas.bind("<Configure>", lambda e: self._refresh_canvas())
        self.bind("<Delete>", lambda e: self._delete_selection())
        self.bind("<Escape>", lambda e: self._begin_select())

    # -- координатные преобразования -------------------------------------
    def _s2w(self, x, y):
        return (x - self.ox) / self.zoom, (y - self.oy) / self.zoom

    def _renderer(self):
        return Renderer(self.canvas, self.zoom, self.ox, self.oy)

    # -- режимы ----------------------------------------------------------
    def _begin_add(self, cls):
        self.mode = "add"
        self.add_type = cls
        self.wire_start = None
        self.canvas.configure(cursor="crosshair")
        self.status.configure(
            text=f"Кликните по холсту, чтобы поставить: {cls.display_name}",
            text_color="#4fc3f7")

    def _begin_wire(self):
        self.mode = "wire"
        self.add_type = None
        self.wire_start = None
        self.canvas.configure(cursor="crosshair")
        self.status.configure(
            text="Кликните по первому, затем по второму выводу",
            text_color="#4fc3f7")

    def _begin_select(self):
        self.mode = "select"
        self.add_type = None
        self.wire_start = None
        self.canvas.configure(cursor="")

    # -- мышь ------------------------------------------------------------
    def _on_wheel(self, event):
        if event.num == 4:
            factor = 1.12
        elif event.num == 5:
            factor = 1.0 / 1.12
        else:
            factor = 1.12 if event.delta > 0 else 1.0 / 1.12
        wx, wy = self._s2w(event.x, event.y)
        new_zoom = max(0.2, min(5.0, self.zoom * factor))
        self.zoom = new_zoom
        # держим точку под курсором неподвижной
        self.ox = event.x - wx * self.zoom
        self.oy = event.y - wy * self.zoom
        self._refresh_canvas()

    def _on_pan_start(self, event):
        self.pan_anchor = (event.x, event.y, self.ox, self.oy)

    def _on_pan_move(self, event):
        if not self.pan_anchor:
            return
        x0, y0, ox0, oy0 = self.pan_anchor
        self.ox = ox0 + (event.x - x0)
        self.oy = oy0 + (event.y - y0)
        self._refresh_canvas()

    def _on_motion(self, event):
        if self.mode == "wire":
            wx, wy = self._s2w(event.x, event.y)
            new_hover = self._find_pin(wx, wy)
            if new_hover != self._hover_pin:
                self._hover_pin = new_hover
                self._refresh_canvas()

    def _on_left_click(self, event):
        wx, wy = self._s2w(event.x, event.y)

        # 1) режим добавления компонента
        if self.mode == "add" and self.add_type is not None:
            comp = self.add_type(wx, wy)
            self.components.append(comp)
            self.mode = "select"
            self.add_type = None
            self.canvas.configure(cursor="")
            self.selection = [comp]
            self._show_properties(comp)
            self.refresh()
            return

        # 2) режим провода
        if self.mode == "wire":
            pin = self._find_pin(wx, wy)
            if pin is None:
                return
            if self.wire_start is None:
                self.wire_start = pin
                self._refresh_canvas()
            else:
                if pin != self.wire_start:
                    self.wires.append(Wire(self.wire_start, pin))
                self.wire_start = None
                self.refresh()
            return

        # 3) режим выбора
        comp = self._find_component(wx, wy)
        if comp is not None:
            shift = bool(event.state & 0x0001)
            if shift:
                if comp in self.selection:
                    self.selection.remove(comp)
                else:
                    self.selection.append(comp)
            else:
                self.selection = [comp]
            self.drag_comp = comp
            self.drag_offset = (comp.x - wx, comp.y - wy)
            self._show_properties(comp if len(self.selection) == 1 else None)
            self.refresh()
            return

        w = self._find_wire(wx, wy)
        if w is not None:
            self.selection = [w]
            self._show_properties(None)
            self.refresh()
            return

        # пустое место — снять выделение
        self.selection = []
        self._show_properties(None)
        self.refresh()

    def _on_left_drag(self, event):
        if self.drag_comp is None:
            return
        wx, wy = self._s2w(event.x, event.y)
        self.drag_comp.x = wx + self.drag_offset[0]
        self.drag_comp.y = wy + self.drag_offset[1]
        self._refresh_canvas()

    def _on_left_release(self, event):
        if self.drag_comp is not None:
            self.drag_comp = None
            self.refresh()

    # -- поиск объектов --------------------------------------------------
    def _find_pin(self, wx, wy, tol=PIN_SNAP):
        best = None
        best_d = tol
        for c in self.components:
            for i, (px, py) in enumerate(c.pins()):
                d = math.hypot(px - wx, py - wy)
                if d <= best_d:
                    best_d = d
                    best = (c.uid, i)
        return best

    def _find_component(self, wx, wy):
        for c in reversed(self.components):
            if c.hit(wx, wy):
                return c
        return None

    def _find_wire(self, wx, wy, tol=6.0):
        for w in self.wires:
            a = self._pin_world(w.a)
            b = self._pin_world(w.b)
            if a and b:
                if dist_point_segment(wx, wy, a[0], a[1], b[0], b[1]) <= tol:
                    return w
        return None

    def _comp_by_uid(self, uid):
        for c in self.components:
            if c.uid == uid:
                return c
        return None

    def _pin_world(self, pin):
        c = self._comp_by_uid(pin[0])
        if c is None:
            return None
        return c.pins()[pin[1]]

    # -- свойства --------------------------------------------------------
    def _show_properties(self, comp):
        for w in self.props_widgets:
            w.destroy()
        self.props_widgets = []

        if comp is None or not isinstance(comp, Component):
            lbl = ctk.CTkLabel(self.props_inner, text="Ничего не выбрано",
                               text_color="#888888")
            lbl.pack(pady=8)
            self.props_widgets.append(lbl)
            return

        ctk.CTkLabel(self.props_inner, text=comp.display_name,
                     font=("Segoe UI", 13, "bold")).pack(pady=(2, 8))

        for key, label in PARAM_DEFS.get(comp.type, []):
            ctk.CTkLabel(self.props_inner, text=label, anchor="w"
                         ).pack(fill="x", padx=4)
            var = tk.StringVar(value=format_number(comp.params[key]))
            entry = ctk.CTkEntry(self.props_inner, textvariable=var)
            entry.pack(fill="x", padx=4, pady=(0, 6))
            self.props_widgets.append(entry)
            var.trace_add(
                "write",
                lambda *a, k=key, v=var, c=comp: self._on_param_change(c, k, v)
            )
        self.props_widgets.append(
            ctk.CTkLabel(self.props_inner, text="")

        )

    def _on_param_change(self, comp, key, var):
        txt = var.get().strip().replace(",", ".")
        try:
            val = float(txt)
        except ValueError:
            return
        # простая валидация
        if key in ("R", "C", "L") and val <= 0:
            return
        if key == "A" and val < 0:
            return
        if key == "f" and val <= 0:
            return
        comp.params[key] = val
        # мгновенный пересчёт и обновление графиков
        self.refresh()

    # -- удаление --------------------------------------------------------
    def _delete_selection(self):
        if not self.selection:
            return
        del_uids = set()
        for item in self.selection:
            if isinstance(item, Component):
                del_uids.add(item.uid)
        self.components = [c for c in self.components if c.uid not in del_uids]
        sel_wires = {w for w in self.selection if isinstance(w, Wire)}
        self.wires = [
            w for w in self.wires
            if w not in sel_wires
            and w.a[0] not in del_uids
            and w.b[0] not in del_uids
        ]
        self.selection = []
        self._show_properties(None)
        self.refresh()

    # -- сброс вида ------------------------------------------------------
    def _reset_view(self):
        self.zoom = 1.0
        self.ox = 0.0
        self.oy = 0.0
        self._refresh_canvas()

    # -- демо ------------------------------------------------------------
    def _load_demo(self):
        self.components = []
        self.wires = []
        self.selection = []

        src = ACSource(250, 250)
        src.params.update({"A": 10.0, "f": 60.0})
        res = Resistor(450, 250)
        res.params["R"] = 10.0
        bulb = Bulb(450, 450)
        bulb.params["R"] = 10.0

        self.components = [src, res, bulb]
        self.wires = [
            Wire((src.uid, 1), (res.uid, 0)),
            Wire((res.uid, 1), (bulb.uid, 0)),
            Wire((bulb.uid, 1), (src.uid, 0)),
        ]
        self.selection = [bulb]
        self._show_properties(bulb)
        self.refresh()

    # -- отрисовка -------------------------------------------------------
    def _initial_refresh(self):
        self._refresh_canvas()
        self._update_scope()

    def _draw_grid(self):
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w <= 1 or h <= 1:
            return
        step = 40.0 * self.zoom
        while step < 12.0:
            step *= 2.0
        if step < 6.0:
            return
        x = self.ox % step
        while x <= w:
            self.canvas.create_line(x, 0, x, h, fill=GRID_MINOR)
            x += step
        y = self.oy % step
        while y <= h:
            self.canvas.create_line(0, y, w, y, fill=GRID_MINOR)
            y += step

    def _refresh_canvas(self):
        self.canvas.delete("all")
        self._draw_grid()
        r = self._renderer()

        # провода
        for w in self.wires:
            a = self._pin_world(w.a)
            b = self._pin_world(w.b)
            if not a or not b:
                continue
            sel = w in self.selection
            r.line(a[0], a[1], b[0], b[1],
                   fill=(COL_SEL if sel else COL_WIRE),
                   width=(4 if sel else 2))

        # компоненты
        for c in self.components:
            c.draw(r, selected=(c in self.selection))

        # выводы
        for c in self.components:
            for i, (px, py) in enumerate(c.pins()):
                hover = (self.mode == "wire" and self._hover_pin == (c.uid, i))
                start = (self.wire_start == (c.uid, i))
                col = COL_PIN_HOV if (hover or start) else COL_PIN
                rad = PIN_DRAW_R + (2.0 if (hover or start) else 0.0)
                r.oval(px - rad, py - rad, px + rad, py + rad,
                       outline=col, fill=BG_CANVAS)

    # -- расчёт + обновление ---------------------------------------------
    def refresh(self):
        self._refresh_canvas()
        self._solve()
        self._update_scope()

    def _solve(self):
        results, err = CircuitSolver.solve(self.components, self.wires)
        self.last_results = results
        self.last_error = err
        if err:
            self.status.configure(text="⚠ " + err, text_color="#ff7043")
        else:
            self.status.configure(text="OK", text_color="#81c784")
        # обновляем яркость лампочек
        for c in self.components:
            if c.uid in results:
                c.update_from_results(results[c.uid]["V"], results[c.uid]["I"])
            else:
                c.update_from_results(0.0j, 0.0j)

    def _update_scope(self):
        self.ax_v.clear()
        self.ax_i.clear()
        for ax in (self.ax_v, self.ax_i):
            ax.set_facecolor("#202020")
            ax.tick_params(colors="#cccccc", labelsize=8)
            for sp in ax.spines.values():
                sp.set_color("#555555")
            ax.grid(True, color="#333333", linewidth=0.5)

        if self.last_error:
            self.ax_v.text(0.5, 0.5, "Нет расчёта",
                           ha="center", va="center",
                           transform=self.ax_v.transAxes,
                           color="#ff7043", fontsize=11)
            self.ax_v.set_xticks([]); self.ax_v.set_yticks([])
            self.ax_i.set_xticks([]); self.ax_i.set_yticks([])
            self.mpl_canvas.draw_idle()
            return

        sources = [c for c in self.components if c.type == "acsource"]
        if not sources:
            self.ax_v.text(0.5, 0.5, "Добавьте источник AC",
                           ha="center", va="center",
                           transform=self.ax_v.transAxes,
                           color="#888888", fontsize=11)
            self.ax_v.set_xticks([]); self.ax_v.set_yticks([])
            self.ax_i.set_xticks([]); self.ax_i.set_yticks([])
            self.mpl_canvas.draw_idle()
            return

        f = float(sources[0].params["f"])
        omega = 2.0 * math.pi * f
        T = 1.0 / f

        # какие компоненты показывать
        comps = [c for c in self.selection if isinstance(c, Component)]
        if not comps:
            comps = sources[:1]        # по умолчанию — первый источник

        # временная сетка (2 периода)
        t = np.linspace(0.0, 2.0 * T, 400)
        colors = ["#4fc3f7", "#ffb74d", "#81c784", "#e57373", "#ba68c8"]

        for idx, c in enumerate(comps):
            res = self.last_results.get(c.uid)
            if res is None:
                continue
            V = res["V"]
            I = res["I"]
            # v(t) = Re(V * exp(j*omega*t)) = |V|*cos(omega*t + arg(V))
            vt = np.real(V * np.exp(1j * omega * t))
            it = np.real(I * np.exp(1j * omega * t))
            col = colors[idx % len(colors)]
            label = f"{c.display_name} [{c.uid[:4]}]"
            self.ax_v.plot(t * 1000.0, vt, color=col, linewidth=1.6, label=label)
            self.ax_i.plot(t * 1000.0, it * 1000.0, color=col,
                           linewidth=1.6, label=label)

        self.ax_v.set_ylabel("U, В", color="#cccccc", fontsize=9)
        self.ax_i.set_ylabel("I, мА", color="#cccccc", fontsize=9)
        self.ax_i.set_xlabel("t, мс", color="#cccccc", fontsize=9)
        self.ax_v.set_title("Напряжение", color="#dddddd",
                            fontsize=10, loc="left")
        self.ax_i.set_title("Ток", color="#dddddd", fontsize=10, loc="left")

        if len(comps) <= 5:
            leg = self.ax_v.legend(fontsize=7, loc="upper right")
            if leg:
                leg.get_frame().set_facecolor("#2a2a2a")
                leg.get_frame().set_edgecolor("#555555")
                for txt in leg.get_texts():
                    txt.set_color("#cccccc")

        self.mpl_canvas.draw_idle()


# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------
def main():
    app = CircuitApp()
    app.mainloop()


if __name__ == "__main__":
    main()