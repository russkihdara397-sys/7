import tkinter as tk
import math

# ==============================================================================
# Класс для реализации всплывающих подсказок (Tooltips) без внешних зависимостей
# ==============================================================================
class ToolTip:
    """
    Легковесный класс для создания всплывающих подсказок при наведении на виджет.
    """
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip_window = None
        # Привязка событий наведения и ухода курсора
        self.widget.bind("<Enter>", self.show_tooltip)
        self.widget.bind("<Leave>", self.hide_tooltip)
        self.widget.bind("<ButtonPress>", self.hide_tooltip) # Скрыть при клике

    def show_tooltip(self, event=None):
        """Отображение окна с подсказкой."""
        if self.tip_window or not self.text:
            return
        # Координаты относительно экрана
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5
        self.tip_window = tk.Toplevel(self.widget)
        self.tip_window.wm_overrideredirect(True) # Убираем рамки окна
        self.tip_window.wm_geometry(f"+{x}+{y}")
        
        label = tk.Label(
            self.tip_window, text=self.text, justify=tk.LEFT,
            background="#ffffe0", relief=tk.SOLID, borderwidth=1,
            font=("Arial", 9), padx=4, pady=2
        )
        label.pack(ipadx=1)

    def hide_tooltip(self, event=None):
        """Уничтожение окна подсказки."""
        if self.tip_window:
            self.tip_window.destroy()
            self.tip_window = None


# ==============================================================================
# Основной класс приложения
# ==============================================================================
class ChargesAndFieldsApp:
    def __init__(self, root):
        """
        Инициализация главного окна, физических констант и компонентов интерфейса.
        """
        self.root = root
        self.root.title("Заряды и поля: Расширенная симуляция")
        self.root.geometry("1000x750")
        self.root.minsize(800, 600)
        
        # --- Физические и визуальные константы ---
        self.grid_size = 40         # Размер основной ячейки сетки (шаг привязки)
        self.vector_spacing = 25    # Шаг отрисовки векторов поля (высокая плотность)
        self.k_scaled = 5000.0      # Масштабированная постоянная Кулона
        self.charge_radius = 18     # Визуальный радиус заряда
        self.sensor_radius = 12     # Визуальный радиус датчика
        
        # Хранилища объектов
        self.charges = []
        self.sensors = []
        
        # Состояние интерфейса (переменные Tkinter)
        self.show_field = tk.BooleanVar(value=True)
        self.show_equipotential = tk.BooleanVar(value=False)
        
        # Состояние перетаскивания (Drag-and-Drop)
        self.dragged_item = None
        self.drag_type = None # 'charge' или 'sensor'
        self.drag_offset_x = 0
        self.drag_offset_y = 0
        
        # Построение UI и привязка событий
        self._create_ui()
        self._bind_events()
        
        # Принудительное обновление окна для получения точных размеров холста
        self.root.update()
        
        # Отрисовка базовой сетки и индикатора масштаба
        self.draw_background_grid()
        self.update_scale_indicator()
        
        # Вычисление центра экрана для эталонной расстановки
        self.center_x = self.canvas.winfo_width() // 2
        self.center_y = self.canvas.winfo_height() // 2
        
        # Эталонная расстановка зарядов строго в узлах сетки
        self.add_charge(1, self.center_x - 2 * self.grid_size, self.center_y)
        self.add_charge(1, self.center_x + 2 * self.grid_size, self.center_y)
        self.add_charge(-1, self.center_x, self.center_y + 2 * self.grid_size)
        
        # Добавление демонстрационного датчика
        self.add_sensor(self.center_x, self.center_y)
        
        # Первичная отрисовка физических полей
        self.update_visuals()

    def _create_ui(self):
        """
        Создание оптимизированной панели управления с учетом UX-требований.
        """
        # Основная панель управления
        control_frame = tk.Frame(self.root, bg="#f5f5f5", pady=6, highlightbackground="#ccc", highlightthickness=1)
        control_frame.pack(fill=tk.X)
        
        # --- ЛЕВАЯ ЧАСТЬ: Кнопки добавления объектов ---
        left_frame = tk.Frame(control_frame, bg="#f5f5f5")
        left_frame.pack(side=tk.LEFT, padx=5)
        
        # Кнопка положительного заряда (Красный фон, белый текст)
        btn_pos = tk.Button(left_frame, text="+ Заряд", command=lambda: self.add_charge(1), 
                            bg="#d32f2f", fg="white", font=("Arial", 10, "bold"),
                            activebackground="#b71c1c", activeforeground="white",
                            relief=tk.FLAT, cursor="hand2", padx=10, pady=4)
        btn_pos.pack(side=tk.LEFT, padx=2)
        ToolTip(btn_pos, "Добавить положительный точечный заряд (+1 Кл)")
        
        # Кнопка отрицательного заряда (Синий фон, белый текст)
        btn_neg = tk.Button(left_frame, text="− Заряд", command=lambda: self.add_charge(-1), 
                            bg="#1976d2", fg="white", font=("Arial", 10, "bold"),
                            activebackground="#0d47a1", activeforeground="white",
                            relief=tk.FLAT, cursor="hand2", padx=10, pady=4)
        btn_neg.pack(side=tk.LEFT, padx=2)
        ToolTip(btn_neg, "Добавить отрицательный точечный заряд (−1 Кл)")
        
        # Кнопка датчика (Желтый/Оранжевый фон, темный текст для контраста на светлом)
        btn_sens = tk.Button(left_frame, text="📍 Датчик", command=self.add_sensor_at_center, 
                             bg="#fbc02d", fg="#212121", font=("Arial", 10, "bold"),
                             activebackground="#f9a825", activeforeground="#212121",
                             relief=tk.FLAT, cursor="hand2", padx=10, pady=4)
        btn_sens.pack(side=tk.LEFT, padx=2)
        ToolTip(btn_sens, "Добавить измеритель напряженности поля (Sensor)")
        
        # --- ЦЕНТРАЛЬНАЯ ЧАСТЬ: Компактный блок настроек отображения ---
        # Используем LabelFrame для визуального группирования чекбоксов
        display_frame = tk.LabelFrame(control_frame, text=" Отображение ", font=("Arial", 9, "bold"),
                                      bg="#f5f5f5", fg="#555", relief=tk.GROOVE, borderwidth=1)
        display_frame.pack(side=tk.LEFT, padx=15)
        
        chk_field = tk.Checkbutton(display_frame, text="Векторы E", variable=self.show_field, 
                                   command=self.update_visuals, bg="#f5f5f5", activebackground="#f5f5f5",
                                   font=("Arial", 9))
        chk_field.pack(side=tk.LEFT, padx=(5, 10))
        ToolTip(chk_field, "Показать векторное поле напряженности с градиентом яркости")
        
        chk_eq = tk.Checkbutton(display_frame, text="Эквипотенциали", variable=self.show_equipotential, 
                                command=self.update_visuals, bg="#f5f5f5", activebackground="#f5f5f5",
                                font=("Arial", 9))
        chk_eq.pack(side=tk.LEFT, padx=(0, 5))
        ToolTip(chk_eq, "Показать линии равного электрического потенциала")
        
        # --- ПРАВАЯ ЧАСТЬ: Деструктивное действие ---
        btn_clear = tk.Button(control_frame, text="🗑️ Очистить всё", command=self.clear_all, 
                              bg="#ef5350", fg="white", font=("Arial", 10, "bold"),
                              activebackground="#c62828", activeforeground="white",
                              relief=tk.FLAT, cursor="hand2", padx=12, pady=4)
        btn_clear.pack(side=tk.RIGHT, padx=10)
        ToolTip(btn_clear, "Удалить все заряды, датчики и линии поля")
        
        # --- ХОЛСТ ДЛЯ СИМУЛЯЦИИ ---
        self.canvas = tk.Canvas(self.root, bg="white", cursor="crosshair", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

    def _bind_events(self):
        """
        Привязка обработчиков событий мыши и изменения размера окна.
        """
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<Configure>", self.on_resize)

    def draw_background_grid(self):
        """
        Отрисовка детализированной фоновой координатной сетки (эффект миллиметровки).
        """
        self.canvas.delete("bg_grid")
        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        
        # 1. Мелкая вспомогательная сетка (каждые 10 пикселей)
        for x in range(0, width, 10):
            self.canvas.create_line(x, 0, x, height, fill="#f4f4f4", tags="bg_grid")
        for y in range(0, height, 10):
            self.canvas.create_line(0, y, width, y, fill="#f4f4f4", tags="bg_grid")
            
        # 2. Основная сетка (каждые 40 пикселей - шаг привязки)
        for x in range(0, width, self.grid_size):
            self.canvas.create_line(x, 0, x, height, fill="#e0e0e0", width=1, tags="bg_grid")
        for y in range(0, height, self.grid_size):
            self.canvas.create_line(0, y, width, y, fill="#e0e0e0", width=1, tags="bg_grid")
            
        # 3. Центральные оси координат (более темные)
        center_x = width // 2
        center_y = height // 2
        self.canvas.create_line(center_x, 0, center_x, height, fill="#bdbdbd", width=2, tags="bg_grid")
        self.canvas.create_line(0, center_y, width, center_y, fill="#bdbdbd", width=2, tags="bg_grid")

    def update_scale_indicator(self):
        """
        Обновление текстового индикатора масштаба в левом нижнем углу холста.
        """
        self.canvas.delete("scale_indicator")
        height = self.canvas.winfo_height()
        # Текст привязан к левому нижнему углу (SW) с небольшим отступом
        self.canvas.create_text(
            15, height - 15, 
            text=f"1 клетка = 1 м", 
            anchor=tk.SW, fill="#757575", font=("Arial", 9, "italic"), tags="scale_indicator"
        )

    def add_charge(self, q, x=None, y=None):
        """
        Создание нового точечного заряда с автоматической привязкой к узлу сетки.
        """
        if x is None:
            cx = self.canvas.winfo_width() // 2
            cy = self.canvas.winfo_height() // 2
            offset = (len(self.charges) % 5 - 2) * self.grid_size * 2
            x, y = cx + offset, cy
            
        snapped_x = round(x / self.grid_size) * self.grid_size
        snapped_y = round(y / self.grid_size) * self.grid_size
        
        color = "#ff4d4d" if q > 0 else "#4d4dff"
        sign = "+" if q > 0 else "−"
        
        oval_id = self.canvas.create_oval(
            snapped_x - self.charge_radius, snapped_y - self.charge_radius,
            snapped_x + self.charge_radius, snapped_y + self.charge_radius,
            fill=color, outline="black", width=1.5, tags="charge"
        )
        text_id = self.canvas.create_text(
            snapped_x, snapped_y, text=sign, fill="white", font=("Arial", 14, "bold"), tags="charge"
        )
        
        self.charges.append({
            'x': float(snapped_x), 'y': float(snapped_y), 'q': q,
            'oval_id': oval_id, 'text_id': text_id
        })
        self.update_visuals()

    def add_sensor(self, x, y):
        """
        Создание интерактивного датчика электрического поля.
        """
        snapped_x = round(x / self.grid_size) * self.grid_size
        snapped_y = round(y / self.grid_size) * self.grid_size
        
        sensor_id = self.canvas.create_oval(
            snapped_x - self.sensor_radius, snapped_y - self.sensor_radius,
            snapped_x + self.sensor_radius, snapped_y + self.sensor_radius,
            fill="#ffcc00", outline="black", width=1.5, tags="sensor"
        )
        
        arrow_id = self.canvas.create_line(
            snapped_x, snapped_y, snapped_x + 20, snapped_y,
            fill="black", arrow=tk.LAST, width=2, tags="sensor"
        )
        
        text_id = self.canvas.create_text(
            snapped_x, snapped_y - 25, text="E = 0.0\n0°", 
            fill="black", font=("Arial", 10, "bold"), tags="sensor", justify=tk.CENTER
        )
        
        self.sensors.append({
            'x': float(snapped_x), 'y': float(snapped_y),
            'oval_id': sensor_id, 'arrow_id': arrow_id, 'text_id': text_id
        })
        self.update_sensors()

    def add_sensor_at_center(self):
        """Вспомогательный метод для кнопки добавления датчика."""
        cx = self.canvas.winfo_width() // 2
        cy = self.canvas.winfo_height() // 2
        self.add_sensor(cx, cy)
        self.update_visuals()

    def clear_all(self):
        """Полная очистка холста от всех физических объектов."""
        self.charges.clear()
        self.sensors.clear()
        self.canvas.delete("charge")
        self.canvas.delete("sensor")
        self.canvas.delete("field_arrow")
        self.canvas.delete("equipotential")

    def calculate_field(self, x, y):
        """
        Вычисление вектора напряженности E и его модуля в точке (x, y).
        """
        ex, ey = 0.0, 0.0
        for charge in self.charges:
            dx = x - charge['x']
            dy = y - charge['y']
            r2 = dx*dx + dy*dy
            
            if r2 > (self.charge_radius ** 2):
                r = math.sqrt(r2)
                e_mag = self.k_scaled * charge['q'] / r2
                ex += e_mag * (dx / r)
                ey += e_mag * (dy / r)
                
        mag = math.hypot(ex, ey)
        return ex, ey, mag

    def calculate_potential(self, x, y):
        """
        Вычисление скалярного электрического потенциала V в точке (x, y).
        """
        v = 0.0
        for charge in self.charges:
            dx = x - charge['x']
            dy = y - charge['y']
            r = math.hypot(dx, dy)
            if r < self.charge_radius:
                r = self.charge_radius
            v += (self.k_scaled * charge['q'] / r) * 10
        return v

    def get_arrow_color(self, mag, max_mag):
        """
        Динамическое вычисление цвета стрелки (градиент яркости).
        От тускло-серого (слабое поле) к ярко-красному (сильное поле).
        """
        ratio = min(1.0, mag / max_mag) if max_mag > 0 else 0
        r = int(120 + 135 * ratio)
        g = int(120 * (1 - ratio**2))
        b = int(120 * (1 - ratio))
        return f"#{r:02x}{g:02x}{b:02x}"

    def draw_field_vectors(self):
        """
        Отрисовка плотной сетки векторов с градиентом цвета и толщины.
        """
        self.canvas.delete("field_arrow")
        if not self.show_field.get() or not self.charges: return
            
        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        
        max_mag = 0.1
        vectors_data = []
        for gx in range(self.vector_spacing, width, self.vector_spacing):
            for gy in range(self.vector_spacing, height, self.vector_spacing):
                too_close = any(math.hypot(gx - c['x'], gy - c['y']) < self.charge_radius * 1.2 for c in self.charges)
                if too_close: continue
                
                ex, ey, mag = self.calculate_field(gx, gy)
                if mag > max_mag: max_mag = mag
                vectors_data.append((gx, gy, ex, ey, mag))
                
        for gx, gy, ex, ey, mag in vectors_data:
            if mag > 0.05:
                arrow_length = min(18, mag * 1.5)
                if arrow_length > 2:
                    angle = math.atan2(ey, ex)
                    end_x = gx + arrow_length * math.cos(angle)
                    end_y = gy + arrow_length * math.sin(angle)
                    
                    color = self.get_arrow_color(mag, max_mag)
                    line_width = 1.0 + 1.5 * (mag / max_mag) if max_mag > 0 else 1.0
                    
                    self.canvas.create_line(
                        gx, gy, end_x, end_y,
                        fill=color, arrow=tk.LAST, width=line_width, tags="field_arrow"
                    )

    def draw_equipotential_lines(self):
        """
        Отрисовка линий равного потенциала с помощью алгоритма Marching Squares.
        """
        self.canvas.delete("equipotential")
        if not self.show_equipotential.get() or len(self.charges) < 1: return
            
        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        
        step = 20
        cols = width // step + 1
        rows = height // step + 1
        
        v_grid = [[self.calculate_potential(i * step, j * step) for i in range(cols)] for j in range(rows)]
        
        valid_vs = [v_grid[j][i] for j in range(1, rows-1, 2) for i in range(1, cols-1, 2) if abs(v_grid[j][i]) < 5000]
        if not valid_vs: return
        
        max_v, min_v = max(valid_vs), min(valid_vs)
        levels = [min_v + (max_v - min_v) * i / 8 for i in range(1, 8)]
        
        def interp(v1, v2, p1, p2, level):
            if abs(v2 - v1) < 1e-6: return (p1 + p2) / 2
            return p1 + (level - v1) / (v2 - v1) * (p2 - p1)

        for level in levels:
            for j in range(rows - 1):
                for i in range(cols - 1):
                    v_tl, v_tr, v_br, v_bl = v_grid[j][i], v_grid[j][i+1], v_grid[j+1][i+1], v_grid[j+1][i]
                    
                    idx = 0
                    if v_tl >= level: idx |= 8
                    if v_tr >= level: idx |= 4
                    if v_br >= level: idx |= 2
                    if v_bl >= level: idx |= 1
                    
                    if idx == 0 or idx == 15: continue
                    
                    x_tl, y_tl = i * step, j * step
                    x_br, y_br = (i+1) * step, (j+1) * step
                    
                    p_top = (interp(v_tl, v_tr, x_tl, x_br, level), y_tl)
                    p_right = (x_br, interp(v_tr, v_br, y_tl, y_br, level))
                    p_bottom = (interp(v_bl, v_br, x_tl, x_br, level), y_br)
                    p_left = (x_tl, interp(v_tl, v_bl, y_tl, y_br, level))
                    
                    lines = []
                    if idx in [1, 14]: lines.append((p_bottom, p_left))
                    elif idx in [2, 13]: lines.append((p_bottom, p_right))
                    elif idx in [3, 12]: lines.append((p_left, p_right))
                    elif idx in [4, 11]: lines.append((p_top, p_right))
                    elif idx in [6, 9]: lines.append((p_top, p_bottom))
                    elif idx in [7, 8]: lines.append((p_top, p_left))
                    elif idx == 5:
                        if (v_tl + v_tr + v_br + v_bl) / 4 >= level:
                            lines.extend([(p_top, p_right), (p_left, p_bottom)])
                        else:
                            lines.extend([(p_top, p_left), (p_bottom, p_right)])
                    elif idx == 10:
                        if (v_tl + v_tr + v_br + v_bl) / 4 >= level:
                            lines.extend([(p_top, p_left), (p_bottom, p_right)])
                        else:
                            lines.extend([(p_top, p_right), (p_left, p_bottom)])
                            
                    for p1, p2 in lines:
                        self.canvas.create_line(p1[0], p1[1], p2[0], p2[1], fill="#4dd2ff", width=1.5, tags="equipotential")

    def update_sensors(self):
        """
        Обновление графических элементов и текстовых показаний всех датчиков.
        """
        for sensor in self.sensors:
            ex, ey, mag = self.calculate_field(sensor['x'], sensor['y'])
            
            if mag > 0.01:
                arrow_len = min(40, mag * 3.0)
                angle = math.atan2(ey, ex)
                end_x = sensor['x'] + arrow_len * math.cos(angle)
                end_y = sensor['y'] + arrow_len * math.sin(angle)
                self.canvas.coords(sensor['arrow_id'], sensor['x'], sensor['y'], end_x, end_y)
                
                angle_deg = math.degrees(angle)
                text = f"E = {mag:.1f} В/м\n{angle_deg:.0f}°"
            else:
                self.canvas.coords(sensor['arrow_id'], sensor['x'], sensor['y'], sensor['x'], sensor['y'])
                text = "E = 0.0 В/м\n0°"
                
            self.canvas.itemconfig(sensor['text_id'], text=text)
            self.canvas.coords(sensor['text_id'], sensor['x'], sensor['y'] - 25)

    def update_visuals(self, is_dragging=False):
        """
        Главный метод оркестрации отрисовки всех физических слоев.
        """
        self.draw_field_vectors()
        self.update_sensors()
        if not is_dragging:
            self.draw_equipotential_lines()

    def on_press(self, event):
        """Обработка нажатия мыши: поиск объекта для перетаскивания."""
        for sensor in self.sensors:
            if math.hypot(event.x - sensor['x'], event.y - sensor['y']) <= self.sensor_radius + 5:
                self.dragged_item, self.drag_type = sensor, 'sensor'
                self.drag_offset_x, self.drag_offset_y = event.x - sensor['x'], event.y - sensor['y']
                self.canvas.tag_raise(sensor['oval_id'])
                self.canvas.tag_raise(sensor['arrow_id'])
                self.canvas.tag_raise(sensor['text_id'])
                return
                
        for charge in self.charges:
            if math.hypot(event.x - charge['x'], event.y - charge['y']) <= self.charge_radius:
                self.dragged_item, self.drag_type = charge, 'charge'
                self.drag_offset_x, self.drag_offset_y = event.x - charge['x'], event.y - charge['y']
                self.canvas.tag_raise(charge['oval_id'])
                self.canvas.tag_raise(charge['text_id'])
                return

    def on_drag(self, event):
        """Обработка перемещения мыши: плавное обновление координат и поля."""
        if self.dragged_item:
            new_x = max(20, min(self.canvas.winfo_width() - 20, event.x - self.drag_offset_x))
            new_y = max(20, min(self.canvas.winfo_height() - 20, event.y - self.drag_offset_y))
            
            self.dragged_item['x'], self.dragged_item['y'] = new_x, new_y
            
            if self.drag_type == 'charge':
                self.canvas.coords(self.dragged_item['oval_id'], 
                                   new_x - self.charge_radius, new_y - self.charge_radius,
                                   new_x + self.charge_radius, new_y + self.charge_radius)
                self.canvas.coords(self.dragged_item['text_id'], new_x, new_y)
                self.update_visuals(is_dragging=True)
            elif self.drag_type == 'sensor':
                self.canvas.coords(self.dragged_item['oval_id'], 
                                   new_x - self.sensor_radius, new_y - self.sensor_radius,
                                   new_x + self.sensor_radius, new_y + self.sensor_radius)
                self.update_sensors()

    def on_release(self, event):
        """
        Отпускание мыши: жесткая привязка (Snap) к ближайшему узлу сетки.
        """
        if self.dragged_item:
            snapped_x = round(self.dragged_item['x'] / self.grid_size) * self.grid_size
            snapped_y = round(self.dragged_item['y'] / self.grid_size) * self.grid_size
            
            self.dragged_item['x'], self.dragged_item['y'] = snapped_x, snapped_y
            
            if self.drag_type == 'charge':
                self.canvas.coords(self.dragged_item['oval_id'], 
                                   snapped_x - self.charge_radius, snapped_y - self.charge_radius,
                                   snapped_x + self.charge_radius, snapped_y + self.charge_radius)
                self.canvas.coords(self.dragged_item['text_id'], snapped_x, snapped_y)
                
            elif self.drag_type == 'sensor':
                self.canvas.coords(self.dragged_item['oval_id'], 
                                   snapped_x - self.sensor_radius, snapped_y - self.sensor_radius,
                                   snapped_x + self.sensor_radius, snapped_y + self.sensor_radius)
                
            self.update_visuals(is_dragging=False)
            
        self.dragged_item, self.drag_type = None, None

    def on_resize(self, event):
        """Обработка изменения размера окна: перерисовка сетки и индикатора масштаба."""
        self.draw_background_grid()
        self.update_scale_indicator()
        # Возвращаем физические объекты поверх фоновой сетки
        self.canvas.tag_raise("charge")
        self.canvas.tag_raise("sensor")
        self.update_visuals()

if __name__ == "__main__":
    root = tk.Tk()
    app = ChargesAndFieldsApp(root)
    root.mainloop()