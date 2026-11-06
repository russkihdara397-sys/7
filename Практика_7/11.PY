import tkinter as tk
import random
import math

# --- КОНСТАНТЫ И НАСТРОЙКИ ---
WIDTH, HEIGHT = 800, 600
GRID_SIZE = 12

class HeatmapApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Визуализация тепловых карт (Метеоданные)")
        self.root.geometry(f"{WIDTH}x{HEIGHT}")
        
        self.view_mode = "3D"
        self.data = self.generate_weather_data()
        
        self.bar_hitboxes = {}
        
        self.tooltip = None
        self.tooltip_bg = None
        self.last_hovered = None
        
        self.create_widgets()
        self.root.after(50, self.draw_visualization)

    def generate_weather_data(self):
        matrix = []
        cx, cy = random.randint(3, 9), random.randint(3, 9)
        for y in range(GRID_SIZE):
            row = []
            for x in range(GRID_SIZE):
                distance = math.sqrt((x - cx)**2 + (y - cy)**2)
                temp = 32.0 - (distance * 5) + random.uniform(-2, 2)
                temp = max(-10.0, min(35.0, temp))
                row.append(temp)
            matrix.append(row)
        return matrix

    def get_color(self, temp):
        min_t, max_t = -10.0, 35.0
        val = (temp - min_t) / (max_t - min_t)
        val = max(0.0, min(1.0, val))
        if val < 0.33:
            r = 0
            g = int((val / 0.33) * 255)
            b = 255 - g
        elif val < 0.66:
            r = int(((val - 0.33) / 0.33) * 255)
            g = 255
            b = 0
        else:
            r = 255
            g = int((1.0 - (val - 0.66) / 0.34) * 255)
            b = 0
        return f"#{r:02x}{g:02x}{b:02x}"

    def get_contrast_color(self, hex_color):
        r = int(hex_color[1:3], 16) / 255.0
        g = int(hex_color[3:5], 16) / 255.0
        b = int(hex_color[5:7], 16) / 255.0
        def linearize(c):
            return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
        r, g, b = linearize(r), linearize(g), linearize(b)
        luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
        return "#000000" if luminance > 0.5 else "#ffffff"

    # --- ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ ДЛЯ ИНФОРМАЦИИ ---
    def get_temp_category(self, temp):
        """Возвращает текстовую категорию температуры."""
        if temp < -5:
            return "Сильный мороз", "#1a5fb4"
        elif temp < 0:
            return "Мороз", "#3584e4"
        elif temp < 10:
            return "Прохладно", "#26a269"
        elif temp < 20:
            return "Умеренно", "#c8a800"
        elif temp < 28:
            return "Тепло", "#e66100"
        else:
            return "Жара", "#c01c28"

    def get_temp_arrow(self, temp):
        """Возвращает стрелку направления отклонения от среднего."""
        avg = self.get_average_temp()
        diff = temp - avg
        if diff > 2:
            return "▲", "#ff4444"
        elif diff > 0.5:
            return "↗", "#ff8844"
        elif diff < -2:
            return "▼", "#4488ff"
        elif diff < -0.5:
            return "↘", "#44aaff"
        else:
            return "●", "#cccccc"

    def get_average_temp(self):
        """Средняя температура по всем зонам."""
        total = sum(sum(row) for row in self.data)
        return total / (GRID_SIZE * GRID_SIZE)

    def get_max_min(self):
        """Максимальная и минимальная температуры."""
        flat = [self.data[y][x] for y in range(GRID_SIZE) for x in range(GRID_SIZE)]
        return max(flat), min(flat)

    def get_zone_description(self, x, y):
        """Позиция в сетке: ряд/столбец и сторона света."""
        # Сторона света относительно центра
        cx, cy = GRID_SIZE // 2, GRID_SIZE // 2
        ns = "север" if y < cy else ("юг" if y > cy else "")
        ew = "запад" if x < cx else ("восток" if x > cx else "")
        direction = (ns + "-" + ew).strip("-") if (ns or ew) else "центр"
        return f"Зона [{x+1}, {y+1}] • {direction}"

    # --- ИНТЕРФЕЙС ---
    def create_widgets(self):
        control_frame = tk.Frame(self.root, bg="#f0f0f0", bd=1, relief=tk.RAISED)
        control_frame.pack(side=tk.TOP, fill=tk.X, ipady=5)
        
        self.btn_2d = tk.Button(control_frame, text="2D-карта",
                                command=lambda: self.set_mode("2D"),
                                font=("Arial", 10, "bold"), width=10)
        self.btn_2d.pack(side=tk.LEFT, padx=(10, 2))
        
        self.btn_3d = tk.Button(control_frame, text="3D-вид",
                                command=lambda: self.set_mode("3D"),
                                font=("Arial", 10, "bold"), width=10)
        self.btn_3d.pack(side=tk.LEFT, padx=2)
        
        btn_refresh = tk.Button(control_frame, text="Обновить данные",
                                command=self.refresh_data, font=("Arial", 10))
        btn_refresh.pack(side=tk.LEFT, padx=10)
        
        lbl_info = tk.Label(control_frame,
                            text="Легенда: Синий (-10°C) → Зеленый → Красный (+35°C)",
                            bg="#f0f0f0", font=("Arial", 10, "italic"))
        lbl_info.pack(side=tk.RIGHT, padx=10)
        
        self.canvas = tk.Canvas(self.root, bg="#1a1a1a")
        self.canvas.pack(fill=tk.BOTH, expand=True)
        
        self.canvas.bind("<Motion>", self.on_mouse_move)
        self.canvas.bind("<Leave>", self.on_mouse_leave)
        
        self.update_mode_buttons()

    def update_mode_buttons(self):
        if self.view_mode == "2D":
            self.btn_2d.config(bg="#4a90d9", fg="white", relief=tk.SUNKEN)
            self.btn_3d.config(bg="#e0e0e0", fg="black", relief=tk.RAISED)
        else:
            self.btn_3d.config(bg="#4a90d9", fg="white", relief=tk.SUNKEN)
            self.btn_2d.config(bg="#e0e0e0", fg="black", relief=tk.RAISED)

    def set_mode(self, mode):
        if self.view_mode != mode:
            self.view_mode = mode
            self.update_mode_buttons()
            self.draw_visualization()

    def refresh_data(self):
        self.data = self.generate_weather_data()
        self.draw_visualization()

    # --- РАСШИРЕННЫЙ TOOLTIP ---
    def build_tooltip_lines(self, x, y, temp):
        """Формирует список строк для расширенного tooltip."""
        cat_name, cat_color = self.get_temp_category(temp)
        avg = self.get_average_temp()
        diff = temp - avg
        arrow, arrow_color = self.get_temp_arrow(temp)
        max_t, min_t = self.get_max_min()
        
        # Нормализация для мини-индикатора (0..1)
        val = (temp - (-10.0)) / (35.0 - (-10.0))
        val = max(0.0, min(1.0, val))
        bar_len = int(val * 20)
        bar = "█" * bar_len + "░" * (20 - bar_len)
        
        sign = "+" if diff >= 0 else ""
        
        lines = [
            # (текст, цвет, шрифт)
            (f"{temp:.1f}°C", "#ffffff", ("Arial", 14, "bold")),
            (cat_name, cat_color, ("Arial", 10, "bold")),
            (self.get_zone_description(x, y), "#cccccc", ("Arial", 9)),
            (f"{arrow} {sign}{diff:.1f}° от среднего ({avg:.1f}°)", arrow_color, ("Arial", 9)),
            (f"Макс: {max_t:.1f}°  Мин: {min_t:.1f}°", "#aaaaaa", ("Arial", 9)),
            (f"[{bar}]", self.get_color(temp), ("Consolas", 9, "bold")),
        ]
        return lines

    def show_tooltip(self, x, y, lines):
        """Рисует многострочный tooltip с фоном и цветными строками."""
        self.hide_tooltip()
        
        padding = 10
        line_spacing = 4
        line_height = 20
        
        # Оцениваем ширину по самой длинной строке
        max_chars = max(len(text) for text, _, _ in lines)
        # Для моноширинного и пропорционального — берём приближённо
        box_width = max(220, max_chars * 7 + padding * 2)
        box_height = len(lines) * line_height + padding * 2 + line_spacing * (len(lines) - 1)
        
        # Корректировка положения, чтобы не уходить за края
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        px = x + 20
        py = y - box_height // 2
        if px + box_width > cw:
            px = x - box_width - 20
        if py < 5:
            py = 5
        if py + box_height > ch - 5:
            py = ch - box_height - 5
        
        # Фон
        self.tooltip_bg = self.canvas.create_rectangle(
            px, py, px + box_width, py + box_height,
            fill="#1e1e2e", outline="#4a90d9", width=2, tags="tooltip"
        )
        
        # Строки
        self.tooltip = []
        cy_text = py + padding
        for i, (text, color, font) in enumerate(lines):
            item = self.canvas.create_text(
                px + padding, cy_text, text=text, anchor=tk.NW,
                fill=color, font=font, tags="tooltip"
            )
            self.tooltip.append(item)
            cy_text += line_height + line_spacing

    def hide_tooltip(self):
        self.canvas.delete("tooltip")
        self.tooltip = None
        self.tooltip_bg = None

    def on_mouse_move(self, event):
        """Поиск столбика под курсором (учитываем 2D и 3D)."""
        found = None
        
        if self.view_mode == "3D":
            for item_id, (bx, by, tx, ty, temp, zx, zy) in self.bar_hitboxes.items():
                if bx <= event.x <= bx + 44 and ty <= event.y <= by:
                    found = (zx, zy, temp)
                    break
        else:
            # 2D: ищем по сохранённым ячейкам
            for item_id, (x1, y1, x2, y2, gx, gy, temp) in self.bar_hitboxes.items():
                if x1 <= event.x <= x2 and y1 <= event.y <= y2:
                    found = (gx, gy, temp)
                    break
        
        if found is not None:
            gx, gy, temp = found
            key = (gx, gy)
            if self.last_hovered != key:
                self.last_hovered = key
                lines = self.build_tooltip_lines(gx, gy, temp)
                self.show_tooltip(event.x, event.y, lines)
            else:
                self.reposition_tooltip(event.x, event.y)
        else:
            if self.last_hovered is not None:
                self.last_hovered = None
                self.hide_tooltip()

    def reposition_tooltip(self, x, y):
        """Перемещает tooltip вслед за курсором."""
        if not self.tooltip or not self.tooltip_bg:
            return
        bbox = self.canvas.bbox("tooltip")
        if not bbox:
            return
        box_width = bbox[2] - bbox[0]
        box_height = bbox[3] - bbox[1]
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        px = x + 20
        py = y - box_height // 2
        if px + box_width > cw:
            px = x - box_width - 20
        if py < 5:
            py = 5
        if py + box_height > ch - 5:
            py = ch - box_height - 5
        dx = px - bbox[0]
        dy = py - bbox[1]
        self.canvas.move("tooltip", dx, dy)

    def on_mouse_leave(self, event):
        self.last_hovered = None
        self.hide_tooltip()

    # --- РИСОВАНИЕ ---
    def draw_visualization(self):
        self.canvas.delete("all")
        self.bar_hitboxes = {}
        self.hide_tooltip()
        self.last_hovered = None
        
        if self.view_mode == "2D":
            self.draw_2d_heatmap()
        else:
            self.draw_3d_bars()

    def draw_2d_heatmap(self):
        cw = self.canvas.winfo_width() if self.canvas.winfo_width() > 1 else WIDTH
        ch = self.canvas.winfo_height() if self.canvas.winfo_height() > 1 else HEIGHT
        
        offset_x = (cw - 450) / 2
        offset_y = (ch - 450) / 2
        cell_size = 450 / GRID_SIZE
        
        for y in range(GRID_SIZE):
            for x in range(GRID_SIZE):
                temp = self.data[y][x]
                color = self.get_color(temp)
                text_color = self.get_contrast_color(color)
                
                x1 = offset_x + x * cell_size
                y1 = offset_y + y * cell_size
                x2 = x1 + cell_size
                y2 = y1 + cell_size
                
                rect_id = self.canvas.create_rectangle(
                    x1, y1, x2, y2, fill=color, outline="#2a2a2a"
                )
                self.canvas.create_text(
                    (x1 + x2) / 2, (y1 + y2) / 2,
                    text=f"{int(temp)}°", fill=text_color,
                    font=("Arial", 8, "bold")
                )
                # Регистрируем ячейку для tooltip
                self.bar_hitboxes[rect_id] = (x1, y1, x2, y2, x, y, temp)

    def draw_3d_bars(self):
        cw = self.canvas.winfo_width() if self.canvas.winfo_width() > 1 else WIDTH
        ch = self.canvas.winfo_height() if self.canvas.winfo_height() > 1 else HEIGHT
        
        start_x = cw / 2
        start_y = ch / 2 - 50
        dx = 22
        dy = 11
        height_scale = 3.5

        for y in range(GRID_SIZE):
            for x in range(GRID_SIZE):
                temp = self.data[y][x]
                color = self.get_color(temp)
                h = (temp + 15) * height_scale
                
                iso_x = start_x + (x - y) * dx
                iso_y = start_y + (x + y) * dy
                
                tx1, ty1 = iso_x, iso_y - h
                tx2, ty2 = iso_x + dx, iso_y + dy - h
                tx3, ty3 = iso_x, iso_y + 2 * dy - h
                tx4, ty4 = iso_x - dx, iso_y + dy - h
                
                self.canvas.create_polygon(
                    tx4, ty4, tx3, ty3, tx3, ty3 + h, tx4, ty4 + h,
                    fill=self.adjust_brightness(color, 0.8), outline="#111111"
                )
                self.canvas.create_polygon(
                    tx3, ty3, tx2, ty2, tx2, ty2 + h, tx3, ty3 + h,
                    fill=self.adjust_brightness(color, 0.6), outline="#111111"
                )
                top_id = self.canvas.create_polygon(
                    tx1, ty1, tx2, ty2, tx3, ty3, tx4, ty4,
                    fill=color, outline="#ffffff"
                )
                
                # Hitbox: прямоугольник вокруг верхней грани + высота
                # Приблизительный bbox ромба + тело
                bx = iso_x - dx
                by = iso_y + 2 * dy
                ty = ty1 - 2
                self.bar_hitboxes[top_id] = (bx, by, tx1, ty, temp, x, y)

    def adjust_brightness(self, hex_color, factor):
        r = int(hex_color[1:3], 16)
        g = int(hex_color[3:5], 16)
        b = int(hex_color[5:7], 16)
        r = min(255, max(0, int(r * factor)))
        g = min(255, max(0, int(g * factor)))
        b = min(255, max(0, int(b * factor)))
        return f"#{r:02x}{g:02x}{b:02x}"


if __name__ == "__main__":
    root = tk.Tk()
    app = HeatmapApp(root)
    root.mainloop()