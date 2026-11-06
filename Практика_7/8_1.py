"""
Графический симулятор математического анализа (Дифференцирование и Интегрирование)
Исправленная версия для корректного отображения кубической функции и читаемости осей.
"""

import tkinter as tk
from tkinter import ttk
import math

# ==============================================================================
# КЛАСС 1: Математические утилиты
# ==============================================================================
class MathUtils:
    PRESETS = {
        "Синусоида: f(x) = sin(x)": lambda x: math.sin(x),
        "Парабола: f(x) = x²": lambda x: x ** 2,
        "Кубическая: f(x) = x³ - 3x": lambda x: x ** 3 - 3 * x,
        "Ступенчатая: f(x) = sign(x)": lambda x: 1.0 if x >= 0 else -1.0
    }

    @staticmethod
    def get_function(name: str):
        return MathUtils.PRESETS.get(name, MathUtils.PRESETS["Синусоида: f(x) = sin(x)"])

    @staticmethod
    def differentiate(f, x: float, h: float = 0.001) -> float:
        return (f(x + h) - f(x)) / h

    @staticmethod
    def integrate(f, x_start: float, x_end: float, n: int = 500) -> float:
        if x_start == x_end:
            return 0.0
        step = (x_end - x_start) / n
        return sum(f(x_start + i * step) * step for i in range(n))


# ==============================================================================
# КЛАСС 2: Система координат
# ==============================================================================
class CoordinateSystem:
    def __init__(self, width: int, height: int, x_min: float = -5.0, x_max: float = 5.0):
        self.width = width
        self.height = height
        self.x_min = x_min
        self.x_max = x_max
        self.y_min = -5.0
        self.y_max = 5.0

    def auto_scale_y(self, f, x_samples: int = 200, y_limit: float = 20.0):
        """
        Автоматически подбирает масштаб по оси Y.
        :param y_limit: Максимальный абсолютный диапазон Y для сохранения читаемости графика.
                        Если функция выходит за пределы, масштаб фиксируется на этом значении.
        """
        y_values = []
        step = (self.x_max - self.x_min) / x_samples
        
        for i in range(x_samples + 1):
            x = self.x_min + i * step
            try:
                y = f(x)
                # Игнорируем бесконечные значения и NaN
                if not math.isfinite(y):
                    continue
                y_values.append(y)
            except (ZeroDivisionError, ValueError, OverflowError):
                continue

        if not y_values:
            self.y_min, self.y_max = -y_limit, y_limit
            return

        raw_min, raw_max = min(y_values), max(y_values)
        
        # Если реальный диапазон функции превышает лимит, используем лимит
        # Это решает проблему сплющивания кубической функции
        if abs(raw_min) > y_limit or abs(raw_max) > y_limit:
            self.y_min = -y_limit
            self.y_max = y_limit
        else:
            padding = (raw_max - raw_min) * 0.15 if raw_max != raw_min else 1.0
            self.y_min = min(raw_min - padding, -1.0)
            self.y_max = max(raw_max + padding, 1.0)

    def math_to_pixel(self, x: float, y: float) -> tuple:
        px = ((x - self.x_min) / (self.x_max - self.x_min)) * self.width
        py = self.height - ((y - self.y_min) / (self.y_max - self.y_min)) * self.height
        return int(px), int(py)


# ==============================================================================
# КЛАСС 3: Панель графика
# ==============================================================================
class GraphPanel:
    COLOR_GRID = "#e0e0e0"
    COLOR_AXIS = "#000000"
    COLOR_TEXT = "#111111"
    COLOR_HIGHLIGHT = "#0D47A1"
    COLOR_TANGENT = "#B71C1C"
    COLOR_INTEGRAL = "#1B5E20"
    COLOR_AREA = "#90CAF9"

    def __init__(self, parent, title: str, initial_width: int = 600, initial_height: int = 250):
        self.title = title
        self.width = initial_width
        self.height = initial_height
        
        self.frame = tk.Frame(parent, bg="#f5f5f5")
        self.frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        self.label = tk.Label(self.frame, text=title, font=("Arial", 12, "bold"), fg="#000000", bg="#f5f5f5")
        self.label.pack(anchor=tk.W)
        
        self.canvas = tk.Canvas(self.frame, bg="#ffffff", relief=tk.SUNKEN, bd=1, highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Configure>", self._on_resize)
        
        self.coords = CoordinateSystem(self.width, self.height, x_min=-5.0, x_max=5.0)
        self.last_draw_args = None

    def _on_resize(self, event):
        if event.width > 100 and event.height > 100:
            self.width = event.width
            self.height = event.height
            self.coords.width = event.width
            self.coords.height = event.height
            self.redraw()

    def redraw(self):
        if self.last_draw_args:
            self.update_display(*self.last_draw_args)

    def clear(self):
        self.canvas.delete("all")

    def _draw_text_with_halo(self, x: int, y: int, text: str, color: str, font_tuple: tuple, anchor: str = tk.CENTER):
        """Рисует текст с белой обводкой для читаемости поверх любых линий."""
        for dx in [-1, 0, 1]:
            for dy in [-1, 0, 1]:
                if dx != 0 or dy != 0:
                    self.canvas.create_text(x + dx, y + dy, text=text, font=font_tuple, fill="#ffffff", anchor=anchor)
        self.canvas.create_text(x, y, text=text, font=font_tuple, fill=color, anchor=anchor)

    def draw_grid_and_axes(self):
        """Отрисовывает сетку и оси с адаптивным шагом и форматированием чисел."""
        
        # Вертикальные линии (пропускаем x=0)
        for x in range(int(self.coords.x_min), int(self.coords.x_max) + 1):
            if x == 0:
                continue
            
            px, _ = self.coords.math_to_pixel(x, 0)
            _, py_top = self.coords.math_to_pixel(x, self.coords.y_max)
            _, py_bottom = self.coords.math_to_pixel(x, self.coords.y_min)
            
            self.canvas.create_line(px, py_top, px, py_bottom, fill=self.COLOR_GRID, width=1)
            _, py_zero = self.coords.math_to_pixel(0, 0)
            self.canvas.create_line(px, py_zero, px, py_zero + 6, fill=self.COLOR_AXIS, width=2)
            
            self._draw_text_with_halo(px, py_zero + 20, str(x), self.COLOR_TEXT, ("Arial", 11, "bold"))

        # Горизонтальные линии с АДАПТИВНЫМ шагом
        y_range = self.coords.y_max - self.coords.y_min
        if y_range <= 10:
            y_step = 1.0
        elif y_range <= 30:
            y_step = 2.0
        elif y_range <= 60:
            y_step = 5.0
        else:
            y_step = 10.0
            
        y = math.ceil(self.coords.y_min / y_step) * y_step
        
        while y <= self.coords.y_max + 1e-9: # Небольшой допуск для float
            if abs(y) > 1e-9:  # Пропускаем y=0
                _, py = self.coords.math_to_pixel(0, y)
                px_left, _ = self.coords.math_to_pixel(self.coords.x_min, y)
                px_right, _ = self.coords.math_to_pixel(self.coords.x_max, y)
                
                self.canvas.create_line(px_left, py, px_right, py, fill=self.COLOR_GRID, width=1)
                px_zero, _ = self.coords.math_to_pixel(0, 0)
                self.canvas.create_line(px_zero, py, px_zero - 6, py, fill=self.COLOR_AXIS, width=2)
                
                # Форматирование: целые числа без .0, дробные с одним знаком
                label = str(int(y)) if y == int(y) else f"{y:.1f}"
                self._draw_text_with_halo(px_zero - 15, py, label, 
                                         self.COLOR_TEXT, ("Arial", 11, "bold"), anchor=tk.E)
            y += y_step

        # Оси координат
        px_zero, py_zero = self.coords.math_to_pixel(0, 0)
        px_right_end, _ = self.coords.math_to_pixel(self.coords.x_max, 0)
        _, py_top_end = self.coords.math_to_pixel(0, self.coords.y_max)

        self.canvas.create_line(px_zero, py_zero, px_right_end, py_zero, fill=self.COLOR_AXIS, width=2, arrow=tk.LAST)
        self._draw_text_with_halo(px_right_end - 20, py_zero - 20, "X", self.COLOR_TEXT, ("Arial", 12, "bold"))
        
        self.canvas.create_line(px_zero, self.height, px_zero, py_top_end, fill=self.COLOR_AXIS, width=2, arrow=tk.LAST)
        self._draw_text_with_halo(px_zero + 20, py_top_end + 15, "Y", self.COLOR_TEXT, ("Arial", 12, "bold"))

    def _draw_text_with_bg(self, x: int, y: int, text: str, color: str, font_tuple: tuple, offset_x: int = 20, offset_y: int = -20):
        text_id = self.canvas.create_text(x + offset_x, y + offset_y, text=text, font=font_tuple, fill=color)
        bbox = self.canvas.bbox(text_id)
        if bbox:
            self.canvas.create_rectangle(
                bbox[0]-8, bbox[1]-6, bbox[2]+8, bbox[3]+6, 
                fill="#ffffff", outline=color, width=2
            )
            self.canvas.tag_raise(text_id)

    def draw_function(self, f, color: str, width: int = 3):
        self.coords.auto_scale_y(f, y_limit=20.0) # Лимит для сохранения читаемости
        self.draw_grid_and_axes()
        
        points = []
        num_points = 800 # Увеличено для плавности кубической параболы
        step = (self.coords.x_max - self.coords.x_min) / num_points
        prev_py = None
        
        for i in range(num_points + 1):
            x = self.coords.x_min + i * step
            try:
                y = f(x)
                px, py = self.coords.math_to_pixel(x, y)
                
                if prev_py is not None and abs(py - prev_py) > self.height * 0.8:
                    if len(points) >= 2:
                        self.canvas.create_line(*points, fill=color, width=width, smooth=True)
                    points = [(px, py)]
                else:
                    points.extend([px, py])
                prev_py = py
            except (ZeroDivisionError, ValueError, OverflowError):
                prev_py = None
                continue
                
        if len(points) >= 2:
            self.canvas.create_line(*points, fill=color, width=width, smooth=True)

    def draw_tangent_line(self, x_current: float, f):
        y0 = f(x_current)
        slope = MathUtils.differentiate(f, x_current)
        
        x1, x2 = self.coords.x_min, self.coords.x_max
        y1 = y0 + slope * (x1 - x_current)
        y2 = y0 + slope * (x2 - x_current)
        
        px1, py1 = self.coords.math_to_pixel(x1, y1)
        px2, py2 = self.coords.math_to_pixel(x2, y2)
        
        self.canvas.create_line(px1, py1, px2, py2, fill=self.COLOR_TANGENT, width=2, dash=(5, 3))
        px0, py0 = self.coords.math_to_pixel(x_current, y0)
        self.canvas.create_oval(px0-5, py0-5, px0+5, py0+5, fill=self.COLOR_TANGENT, outline="#ffffff", width=2)

    def draw_integral_area(self, x_current: float, f):
        if x_current <= self.coords.x_min:
            return
            
        points = []
        num_points = 300
        step = (x_current - self.coords.x_min) / num_points
        
        start_px, zero_py = self.coords.math_to_pixel(self.coords.x_min, 0)
        points.extend([start_px, zero_py])
        
        for i in range(num_points + 1):
            x = self.coords.x_min + i * step
            try:
                y = f(x)
                px, py = self.coords.math_to_pixel(x, y)
                points.extend([px, py])
            except:
                continue
                
        end_px, _ = self.coords.math_to_pixel(x_current, 0)
        points.extend([end_px, zero_py])
        
        if len(points) >= 6:
            self.canvas.create_polygon(*points, fill=self.COLOR_AREA, outline=self.COLOR_HIGHLIGHT, width=2)

    def draw_reference_line(self, x_current: float):
        px, py_top = self.coords.math_to_pixel(x_current, self.coords.y_max)
        _, py_bottom = self.coords.math_to_pixel(x_current, self.coords.y_min)
        
        self.canvas.create_line(px, py_top, px, py_bottom, fill=self.COLOR_HIGHLIGHT, width=2, dash=(4, 4))
        
        _, py_zero = self.coords.math_to_pixel(0, 0)
        self._draw_text_with_bg(
            x=px, y=py_zero, 
            text=f"x = {x_current:.2f}", 
            color=self.COLOR_HIGHLIGHT, 
            font_tuple=("Arial", 12, "bold"),
            offset_x=20, offset_y=-20
        )

    def update_display(self, mode: str, f, x_current: float):
        self.last_draw_args = (mode, f, x_current)
        self.clear()
        
        if mode == "derivative":
            self.draw_function(f, color="#1565C0", width=3)
            self.draw_tangent_line(x_current, f)
            self.draw_reference_line(x_current)
        elif mode == "integral":
            self.draw_function(f, color="#1565C0", width=3)
            self.draw_integral_area(x_current, f)
            self.draw_reference_line(x_current)
        elif mode == "function_only":
            self.draw_function(f, color=self.COLOR_INTEGRAL, width=3)
            self.draw_reference_line(x_current)


# ==============================================================================
# КЛАСС 4: Основное приложение
# ==============================================================================
class CalculusGrapherApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Симулятор математического анализа")
        self.root.geometry("1000x900")
        self.root.resizable(True, True)
        self.root.configure(bg="#f0f2f5")
        
        self.current_func_name = tk.StringVar(value="Кубическая: f(x) = x³ - 3x") # По умолчанию кубическая для проверки
        self.current_mode = tk.StringVar(value="derivative")
        self.current_x = tk.DoubleVar(value=0.0)
        self.x_var_str = tk.StringVar(value="0.00")
        self.current_x.trace_add("write", self._sync_vars)
        
        self._build_ui()
        self._update_graphs()

    def _sync_vars(self, *args):
        try:
            self.x_var_str.set(f"{self.current_x.get():.2f}")
        except tk.TclError:
            pass

    def _on_spinbox_change(self, event=None):
        try:
            val = float(self.x_var_str.get().replace(',', '.'))
            val = max(-5.0, min(5.0, val))
            self.current_x.set(val)
            self._update_graphs()
        except ValueError:
            self.x_var_str.set(f"{self.current_x.get():.2f}")

    def _build_ui(self):
        control_frame = tk.LabelFrame(self.root, text=" Управление ", font=("Arial", 12, "bold"), bg="#ffffff", padx=20, pady=15)
        control_frame.pack(fill=tk.X, padx=20, pady=15)
        
        label_style = {"font": ("Arial", 11, "bold"), "bg": "#ffffff", "fg": "#000000"}
        
        tk.Label(control_frame, text="Функция f(x):", **label_style).grid(row=0, column=0, sticky=tk.W, pady=8)
        func_combo = ttk.Combobox(control_frame, textvariable=self.current_func_name, values=list(MathUtils.PRESETS.keys()), state="readonly", width=35, font=("Arial", 11))
        func_combo.grid(row=0, column=1, sticky=tk.W, pady=8, padx=10)
        func_combo.bind("<<ComboboxSelected>>", lambda e: self._update_graphs())
        
        tk.Label(control_frame, text="Нижний график показывает:", **label_style).grid(row=1, column=0, sticky=tk.W, pady=8)
        mode_frame = tk.Frame(control_frame, bg="#ffffff")
        mode_frame.grid(row=1, column=1, sticky=tk.W, pady=8)
        
        tk.Radiobutton(mode_frame, text="Производная f'(x)", variable=self.current_mode, value="derivative", 
                       command=self._update_graphs, bg="#ffffff", font=("Arial", 11, "bold")).pack(side=tk.LEFT, padx=10)
        tk.Radiobutton(mode_frame, text="Интеграл F(x)", variable=self.current_mode, value="integral", 
                       command=self._update_graphs, bg="#ffffff", font=("Arial", 11, "bold")).pack(side=tk.LEFT, padx=10)
        
        tk.Label(control_frame, text="Позиция X (опорная линия):", **label_style).grid(row=2, column=0, sticky=tk.W, pady=12)
        
        slider_frame = tk.Frame(control_frame, bg="#ffffff")
        slider_frame.grid(row=2, column=1, sticky=tk.EW, pady=12)
        slider_frame.columnconfigure(0, weight=1)
        
        slider = tk.Scale(slider_frame, from_=-5.0, to=5.0, resolution=0.01, orient=tk.HORIZONTAL, 
                          variable=self.current_x, command=lambda _: self._update_graphs(), 
                          showvalue=0, bg="#ffffff", highlightthickness=0, length=500, font=("Arial", 10))
        slider.grid(row=0, column=0, sticky=tk.EW, padx=(0, 15))
        
        self.x_spinbox = ttk.Spinbox(
            slider_frame, from_=-5.0, to=5.0, increment=0.1,
            textvariable=self.x_var_str, width=8, 
            font=("Arial", 12, "bold"), justify="center"
        )
        self.x_spinbox.grid(row=0, column=1, sticky=tk.W)
        
        self.x_spinbox.bind("<Return>", self._on_spinbox_change)
        self.x_spinbox.bind("<FocusOut>", self._on_spinbox_change)
        self.x_spinbox.bind("<<Increment>>", self._on_spinbox_change)
        self.x_spinbox.bind("<<Decrement>>", self._on_spinbox_change)
        
        graphs_frame = tk.Frame(self.root, bg="#f0f2f5")
        graphs_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=5)
        
        self.top_panel = GraphPanel(graphs_frame, title="Исходная функция f(x)", initial_width=900, initial_height=350)
        self.bottom_panel = GraphPanel(graphs_frame, title="Производная f'(x)", initial_width=900, initial_height=350)
        
        legend_frame = tk.Frame(self.root, bg="#f0f2f5")
        legend_frame.pack(fill=tk.X, padx=20, pady=(0, 20))
        
        self.legend_label = tk.Label(
            legend_frame, text="", font=("Arial", 12, "bold"), fg="#000000",          
            bg="#ffffff", relief=tk.SOLID, borderwidth=2, padx=20, pady=12, justify=tk.LEFT
        )
        self.legend_label.pack(fill=tk.X, anchor=tk.W)

    def _update_graphs(self, *args):
        f = MathUtils.get_function(self.current_func_name.get())
        x_val = self.current_x.get()
        mode = self.current_mode.get()
        
        self.top_panel.update_display(mode=mode, f=f, x_current=x_val)
        
        if mode == "derivative":
            self.bottom_panel.label.config(text="Нижний график: Производная f'(x)")
            self.legend_label.config(text="■ Синяя линия: f(x)  |  ■ Красная линия: Касательная  |  ■ Зелёная линия: График f'(x)  |  ■ Пунктир: Опорная линия X")
            def df(x): return MathUtils.differentiate(f, x)
            self.bottom_panel.update_display(mode="function_only", f=df, x_current=x_val)
        elif mode == "integral":
            self.bottom_panel.label.config(text="Нижний график: Интегральная функция F(x) = ∫f(t)dt")
            self.legend_label.config(text="■ Синяя линия: f(x)  |  ■ Голубая область: Площадь ∫f(x)dx  |  ■ Зелёная линия: График F(x)  |  ■ Пунктир: Опорная линия X")
            
            x_min = self.bottom_panel.coords.x_min
            def F(x): return MathUtils.integrate(f, x_min, x, n=300)
            
            self.bottom_panel.clear()
            self.bottom_panel.draw_function(F, color=GraphPanel.COLOR_INTEGRAL, width=3)
            self.bottom_panel.draw_reference_line(x_val)
            
            current_area = MathUtils.integrate(f, x_min, x_val, n=500)
            px, py = self.bottom_panel.coords.math_to_pixel(x_val, F(x_val))
            self.bottom_panel._draw_text_with_bg(
                x=px, y=py, text=f"F({x_val:.1f}) = {current_area:.2f}", 
                color="#000000", font_tuple=("Arial", 12, "bold"), offset_x=20, offset_y=-20
            )


if __name__ == "__main__":
    root = tk.Tk()
    app = CalculusGrapherApp(root)
    root.mainloop()