import sys
import math
import numpy as np
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QSlider, QLabel, QCheckBox, QPushButton, 
                             QComboBox)
from PyQt6.QtGui import QPainter, QPen, QColor, QFont, QPolygonF
from PyQt6.QtCore import Qt, QPointF, QRectF, QTimer

# --- ФИЗИЧЕСКАЯ МОДЕЛЬ И РАСЧЕТЫ ---
class PhysicsModel:
    @staticmethod
    def bar_magnet_field(x, y, mx, my, strength, polarity=1):
        """Дипольная модель стержневого магнита"""
        length = 120
        half_len = length / 2
        pole_n_pos = np.array([mx + half_len * polarity, my])
        pole_s_pos = np.array([mx - half_len * polarity, my])
        p = np.array([x, y])
        
        # Вектор от N к точке
        r_n = p - pole_n_pos
        dist_n = np.linalg.norm(r_n)**3 + 1e-5
        b_n = strength * r_n / dist_n
        
        # Вектор от S к точке
        r_s = p - pole_s_pos
        dist_s = np.linalg.norm(r_s)**3 + 1e-5
        b_s = -strength * r_s / dist_s
        
        b = (b_n + b_s) * 50000
        return b[0], b[1]

    @staticmethod
    def electromagnet_field(x, y, mx, my, voltage, loops, polarity=1):
        """Модель катушки (электромагнита)"""
        effective_strength = voltage * loops * 15
        if effective_strength == 0:
            return 0.0, 0.0
        
        r = max(math.hypot(x - mx, y - my), 1)
        cos_theta = (mx - x) / r
        
        b_mag = (effective_strength * cos_theta) / (r**2 + 1e-5)
        b_x = b_mag * cos_theta * polarity
        b_y = b_mag * ((my - y) / r) * polarity
        
        return b_x * 2000, b_y * 2000

# --- КАНВАС ДЛЯ ОТРИСОВКИ ---
class SimulationCanvas(QWidget):
    def __init__(self, mode="bar"):
        super().__init__()
        self.mode = mode
        self.setMinimumSize(700, 600)
        
        # Параметры объектов
        self.default_magnet_pos = QPointF(350, 300)
        self.magnet_pos = QPointF(self.default_magnet_pos)
        
        self.default_compass_pos = QPointF(550, 200)
        self.compass_pos = QPointF(self.default_compass_pos)
        
        self.default_meter_pos = QPointF(150, 450)
        self.meter_pos = QPointF(self.default_meter_pos)
        
        self.strength_slider_val = 100
        self.voltage_val = 5.0
        self.loops_val = 4
        self.polarity = 1
        
        # Настройки отображения
        self.show_field = True
        self.show_electrons = False
        self.dragging = None
        
        self.setMouseTracking(True)

    def get_field(self, x, y):
        if self.mode == "bar":
            return PhysicsModel.bar_magnet_field(x, y, self.magnet_pos.x(), self.magnet_pos.y(), self.strength_slider_val, self.polarity)
        else:
            return PhysicsModel.electromagnet_field(x, y, self.magnet_pos.x(), self.magnet_pos.y(), self.voltage_val, self.loops_val, self.polarity)

    def reset_positions(self):
        self.magnet_pos = QPointF(self.default_magnet_pos)
        self.compass_pos = QPointF(self.default_compass_pos)
        self.meter_pos = QPointF(self.default_meter_pos)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(15, 15, 20))
        
        if self.show_field:
            self.draw_field(painter)
            
        if self.mode == "bar":
            self.draw_bar_magnet(painter)
        else:
            self.draw_electromagnet(painter)
            
        self.draw_compass(painter)
        self.draw_meter(painter)

    def draw_field(self, painter):
        step = 45
        painter.setPen(Qt.PenStyle.NoPen)
        
        for x in range(0, self.width(), step):
            for y in range(0, self.height(), step):
                if self.mode == "bar":
                    if abs(x - self.magnet_pos.x()) < 70 and abs(y - self.magnet_pos.y()) < 30:
                        continue
                else:
                    if abs(x - self.magnet_pos.x()) < 45 and abs(y - self.magnet_pos.y()) < 65:
                        continue
                        
                bx, by = self.get_field(x, y)
                mag = math.hypot(bx, by)
                
                if mag > 0.01:
                    angle = math.atan2(by, bx)
                    painter.save()
                    painter.translate(x, y)
                    painter.rotate(math.degrees(angle))
                    
                    color = QColor(200, 50, 50) if mag > 5 else QColor(120, 120, 120)
                    painter.setBrush(color)
                    painter.drawPolygon(QPolygonF([QPointF(6, 0), QPointF(-4, -3), QPointF(-4, 3)]))
                    painter.restore()

    def draw_bar_magnet(self, painter):
        w, h = 120, 40
        rect = QRectF(self.magnet_pos.x() - w/2, self.magnet_pos.y() - h/2, w, h)
        
        if self.dragging == "magnet":
            painter.setPen(QPen(QColor(255, 255, 0), 2, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect.adjusted(-5, -5, 5, 5))
        
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(40, 80, 200))
        painter.drawRect(QRectF(rect.x(), rect.y(), w/2, h))
        painter.setBrush(QColor(200, 40, 40))
        painter.drawRect(QRectF(rect.x() + w/2, rect.y(), w/2, h))
        
        painter.setPen(Qt.GlobalColor.white)
        painter.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        s_text = "S" if self.polarity == 1 else "N"
        n_text = "N" if self.polarity == 1 else "S"
        painter.drawText(QRectF(rect.x(), rect.y(), w/2, h), Qt.AlignmentFlag.AlignCenter, s_text)
        painter.drawText(QRectF(rect.x() + w/2, rect.y(), w/2, h), Qt.AlignmentFlag.AlignCenter, n_text)

    def draw_electromagnet(self, painter):
        w, h = 60, 80
        rect = QRectF(self.magnet_pos.x() - w/2, self.magnet_pos.y() - h/2, w, h)
        
        if self.dragging == "magnet":
            painter.setPen(QPen(QColor(255, 255, 0), 2, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect.adjusted(-15, -30, 15, 5))
            
        painter.setPen(QPen(QColor(200, 120, 50), 4))
        painter.setBrush(QColor(60, 40, 20))
        painter.drawRoundedRect(rect, 5, 5)
        
        painter.setPen(QPen(QColor(220, 180, 120), 2))
        for i in range(self.loops_val * 3):
            y_pos = rect.top() + (i * rect.height() / (self.loops_val * 3))
            painter.drawLine(QPointF(rect.left(), y_pos), QPointF(rect.right(), y_pos))
            
        bat_rect = QRectF(rect.center().x() - 25, rect.top() - 25, 50, 15)
        painter.setBrush(QColor(50, 50, 50))
        painter.setPen(QPen(QColor(150, 150, 150), 2))
        painter.drawRect(bat_rect)
        painter.setBrush(QColor(255, 160, 0) if self.voltage_val > 0 else QColor(30,30,30))
        painter.drawRect(QRectF(bat_rect.x() + bat_rect.width() * 0.6, bat_rect.y(), bat_rect.width() * 0.4, bat_rect.height()))
        
        painter.setPen(Qt.GlobalColor.white)
        painter.setFont(QFont("Arial", 9))
        painter.drawText(bat_rect, Qt.AlignmentFlag.AlignCenter, f"{self.voltage_val:.1f} В")

        if self.show_electrons and self.voltage_val > 0:
            painter.setBrush(QColor(100, 200, 255))
            time_val = QApplication.instance().property("time") or 0
            for i in range(20):
                t = (i / 20.0 + time_val) % 1.0
                ex = rect.left() + 5 + t * (rect.width() - 10)
                ey = rect.top() + 5 + (i % 5) * (rect.height() - 10) / 5
                painter.drawEllipse(QPointF(ex, ey), 3, 3)

    def draw_compass(self, painter):
        painter.setBrush(QColor(40, 40, 40))
        painter.setPen(QPen(QColor(180, 180, 180), 2))
        painter.drawEllipse(self.compass_pos, 25, 25)
        
        bx, by = self.get_field(self.compass_pos.x(), self.compass_pos.y())
        if math.hypot(bx, by) < 0.01:
            return
            
        angle = math.atan2(by, bx)
        painter.save()
        painter.translate(self.compass_pos)
        painter.rotate(math.degrees(angle))
        
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(220, 60, 60))
        painter.drawPolygon(QPolygonF([QPointF(0, -3), QPointF(20, 0), QPointF(0, 3)]))
        painter.setBrush(QColor(240, 240, 240))
        painter.drawPolygon(QPolygonF([QPointF(0, -3), QPointF(-20, 0), QPointF(0, 3)]))
        painter.restore()

    def draw_meter(self, painter):
        x, y = self.meter_pos.x(), self.meter_pos.y()
        
        painter.setBrush(QColor(20, 80, 200))
        painter.setPen(QPen(QColor(100, 180, 255), 2))
        painter.drawRoundedRect(QRectF(x - 40, y - 45, 80, 65), 5, 5)
        
        painter.drawLine(QPointF(x, y - 45), QPointF(x, y - 55))
        painter.drawEllipse(QPointF(x, y - 55), 4, 4)
        
        bx, by = self.get_field(x, y)
        b_total = math.hypot(bx, by)
        theta = math.degrees(math.atan2(by, bx)) % 360
        
        painter.setPen(Qt.GlobalColor.white)
        painter.setFont(QFont("Courier", 8, QFont.Weight.Bold))
        text = f"B:  {b_total:.2f} Гс\nBx: {bx:.2f} Гс\nBy: {by:.2f} Гс\nθ:  {theta:.1f}°"
        painter.drawText(QRectF(x - 35, y - 40, 70, 55), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)

    # --- ИСПРАВЛЕННАЯ Обработка перетаскивания ---
    def mousePressEvent(self, event):
        pos = event.position()
        
        # 1. Проверяем клик по магниту
        is_magnet_clicked = False
        if self.mode == "bar":
            if math.hypot(pos.x() - self.magnet_pos.x(), pos.y() - self.magnet_pos.y()) < 70:
                is_magnet_clicked = True
        else:
            if math.hypot(pos.x() - self.magnet_pos.x(), pos.y() - self.magnet_pos.y()) < 60:
                is_magnet_clicked = True
                
        if is_magnet_clicked:
            self.dragging = "magnet"
        # 2. Проверяем клик по компасу
        elif (pos - self.compass_pos).manhattanLength() < 35:
            self.dragging = "compass"
        # 3. Проверяем клик по датчику
        elif (pos - self.meter_pos).manhattanLength() < 50:
            self.dragging = "meter"

    def mouseMoveEvent(self, event):
        if self.dragging == "magnet":
            self.magnet_pos = event.position()
            self.update()
        elif self.dragging == "compass":
            self.compass_pos = event.position()
            self.update()
        elif self.dragging == "meter":
            self.meter_pos = event.position()
            self.update()

    def mouseReleaseEvent(self, event):
        self.dragging = None
        self.update()

# --- ГЛАВНОЕ ОКНО ---
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Симуляция: Магниты и Электромагниты")
        self.setGeometry(100, 100, 1100, 750)
        self.setStyleSheet("background-color: #1e1e1e; color: white;")

        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QHBoxLayout(main_widget)
        layout.setContentsMargins(0, 0, 0, 0)

        # Левая панель управления
        self.panel = QWidget()
        self.panel.setFixedWidth(280)
        self.panel.setStyleSheet("background-color: #252526; border-right: 1px solid #333;")
        self.panel_layout = QVBoxLayout(self.panel)
        self.panel_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Выбор режима
        self.combo_mode = QComboBox()
        self.combo_mode.addItems(["Постоянный магнит", "Электромагнит"])
        self.combo_mode.currentTextChanged.connect(self.change_mode)
        self.combo_mode.setStyleSheet("padding: 5px; font-weight: bold; font-size: 14px;")
        self.panel_layout.addWidget(self.combo_mode)

        # Заголовок
        self.lbl_title = QLabel("Настройки")
        self.lbl_title.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        self.panel_layout.addWidget(self.lbl_title)

        # Чекбоксы
        self.cb_field = QCheckBox("Магнитное поле (B)")
        self.cb_field.setChecked(True)
        self.cb_field.stateChanged.connect(self.update_settings)
        self.panel_layout.addWidget(self.cb_field)

        self.cb_electrons = QCheckBox("Движение электронов")
        self.cb_electrons.setChecked(False)
        self.cb_electrons.stateChanged.connect(self.update_settings)
        self.panel_layout.addWidget(self.cb_electrons)

        # Настройки силы постоянного магнита
        self.lbl_strength = QLabel("Сила магнита: 100%")
        self.slider_strength = QSlider(Qt.Orientation.Horizontal)
        self.slider_strength.setRange(0, 200)
        self.slider_strength.setValue(100)
        self.slider_strength.valueChanged.connect(self.update_settings)
        self.panel_layout.addWidget(self.lbl_strength)
        self.panel_layout.addWidget(self.slider_strength)

        # Настройки электромагнита
        self.lbl_voltage = QLabel("Напряжение: 5.0 В")
        self.slider_voltage = QSlider(Qt.Orientation.Horizontal)
        self.slider_voltage.setRange(-10, 10)
        self.slider_voltage.setValue(5)
        self.slider_voltage.valueChanged.connect(self.update_settings)
        
        self.lbl_loops = QLabel("Количество витков: 4")
        self.slider_loops = QSlider(Qt.Orientation.Horizontal)
        self.slider_loops.setRange(1, 8)
        self.slider_loops.setValue(4)
        self.slider_loops.valueChanged.connect(self.update_settings)

        self.panel_layout.addWidget(self.lbl_voltage)
        self.panel_layout.addWidget(self.slider_voltage)
        self.panel_layout.addWidget(self.lbl_loops)
        self.panel_layout.addWidget(self.slider_loops)

        # Кнопки управления
        self.btn_flip = QPushButton("Сменить полярность")
        self.btn_flip.setStyleSheet("background-color: #0e639c; padding: 8px; border-radius: 4px; font-weight: bold;")
        self.btn_flip.clicked.connect(self.flip_polarity)
        self.panel_layout.addWidget(self.btn_flip)

        self.btn_reset = QPushButton("Сбросить позиции объектов")
        self.btn_reset.setStyleSheet("background-color: #5c5c5c; padding: 8px; border-radius: 4px; font-weight: bold; margin-top: 10px;")
        self.btn_reset.clicked.connect(self.reset_positions)
        self.panel_layout.addWidget(self.btn_reset)

        # Подсказка
        hint = QLabel("Подсказка: объекты (магнит, компас, датчик) можно перетаскивать мышью.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888; font-size: 11px; margin-top: 20px;")
        self.panel_layout.addWidget(hint)

        layout.addWidget(self.panel)

        # Канвас
        self.canvas = SimulationCanvas()
        layout.addWidget(self.canvas, stretch=1)

        # Начальное состояние
        self.change_mode("Постоянный магнит")

        # Таймер для анимации
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.animate)
        self.timer.start(50)
        self.time_val = 0.0

    def change_mode(self, mode):
        if mode == "Постоянный магнит":
            self.canvas.mode = "bar"
            self.lbl_strength.setVisible(True)
            self.slider_strength.setVisible(True)
            self.lbl_voltage.setVisible(False)
            self.slider_voltage.setVisible(False)
            self.lbl_loops.setVisible(False)
            self.slider_loops.setVisible(False)
            self.cb_electrons.setVisible(False)
        else:
            self.canvas.mode = "electromagnet"
            self.lbl_strength.setVisible(False)
            self.slider_strength.setVisible(False)
            self.lbl_voltage.setVisible(True)
            self.slider_voltage.setVisible(True)
            self.lbl_loops.setVisible(True)
            self.slider_loops.setVisible(True)
            self.cb_electrons.setVisible(True)
            
        self.update_settings()

    def update_settings(self):
        self.lbl_strength.setText(f"Сила магнита: {self.slider_strength.value()}%")
        self.lbl_voltage.setText(f"Напряжение: {self.slider_voltage.value():.1f} В")
        self.lbl_loops.setText(f"Количество витков: {self.slider_loops.value()}")
        
        self.canvas.strength_slider_val = self.slider_strength.value()
        self.canvas.voltage_val = float(self.slider_voltage.value())
        self.canvas.loops_val = self.slider_loops.value()
        
        self.canvas.show_field = self.cb_field.isChecked()
        self.canvas.show_electrons = self.cb_electrons.isChecked()
        
        self.canvas.update()

    def flip_polarity(self):
        self.canvas.polarity *= -1
        self.update_settings()

    def reset_positions(self):
        self.canvas.reset_positions()

    def animate(self):
        if self.canvas.mode == "electromagnet" and self.canvas.show_electrons:
            self.time_val += 0.05
            QApplication.instance().setProperty("time", self.time_val)
            self.canvas.update()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())