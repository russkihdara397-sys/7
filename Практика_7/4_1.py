#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
============================================================================
 ВИЗУАЛИЗАЦИЯ ФИЗИЧЕСКИХ ПРОЦЕССОВ ПРОТЕКАНИЯ ЭЛЕКТРИЧЕСКОГО ТОКА
 НА МИКРОУРОВНЕ В ТРЁХ СРЕДАХ: МЕТАЛЛЫ, ЭЛЕКТРОЛИТЫ, ГАЗЫ
============================================================================
"""

import tkinter as tk
import math
import random
import time

# ============================================================================
#                       ГЛОБАЛЬНЫЕ КОНСТАНТЫ ПРИЛОЖЕНИЯ
# ============================================================================

CANVAS_WIDTH = 800
CANVAS_HEIGHT = 480
ELECTRODE_PANEL_WIDTH = 40

BG_COLOR = "#0f0f1e"
PANEL_BG = "#1a1a2e"
PLUS_COLOR = "#ff5555"
MINUS_COLOR = "#55aaff"

ELECTRON_COLOR = "#55ddff"
ION_COLOR = "#ffaa44"
CATION_COLOR = "#ff6677"
ANION_COLOR = "#66aaff"
NEUTRAL_COLOR = "#777788"
GAS_ION_COLOR = "#ffdd55"

ELECTRON_RADIUS = 3
ION_RADIUS = 14
CATION_RADIUS = 9
ANION_RADIUS = 9
NEUTRAL_RADIUS = 7
GAS_ION_RADIUS = 8

METAL_ION_COLS = 8
METAL_ION_ROWS = 5
METAL_ION_AMPLITUDE = 1.2
METAL_ION_MARGIN_LEFT = 60

GAS_NEUTRAL_COUNT = 80
GAS_SEED_ELECTRONS = 3
MAX_GAS_PARTICLES = 280
IONIZATION_SPEED_THRESHOLD = 160

ELECTROLYTE_ION_COUNT = 40

MAX_PARTICLE_SPEED = 260
BROWNIAN_STRENGTH = 40
FRAME_INTERVAL_MS = 20


# ============================================================================
#                           БАЗОВЫЙ КЛАСС ЧАСТИЦЫ
# ============================================================================

class Particle:
    """Базовый класс для всех визуализируемых частиц."""

    def __init__(self, x, y, vx=0.0, vy=0.0, radius=3,
                 color="white", charge=0, label=""):
        self.x = float(x)
        self.y = float(y)
        self.vx = float(vx)
        self.vy = float(vy)
        self.radius = radius
        self.color = color
        self.charge = charge
        self.label = label
        self.canvas_id = None
        self.label_id = None

    def apply_electric_field(self, field_strength, dt):
        """Применение электрического поля к заряженной частице."""
        if self.charge != 0:
            ax = self.charge * field_strength
            self.vx += ax * dt

    def apply_brownian_kick(self, strength):
        """Случайный броуновский толчок."""
        self.vx += random.uniform(-strength, strength)
        self.vy += random.uniform(-strength, strength)

    def limit_speed(self, max_speed):
        """Ограничение модуля скорости."""
        speed = math.hypot(self.vx, self.vy)
        if speed > max_speed:
            scale = max_speed / speed
            self.vx *= scale
            self.vy *= scale

    def update_position(self, dt):
        """Интегрирование координат."""
        self.x += self.vx * dt
        self.y += self.vy * dt

    def wrap_horizontal(self, width):
        """Циклический перенос по горизонтали."""
        if self.x < -self.radius:
            self.x += width + 2 * self.radius
        elif self.x > width + self.radius:
            self.x -= width + 2 * self.radius

    def reflect_vertical(self, height):
        """Упругое отражение от верхней и нижней границ."""
        if self.y - self.radius < 0:
            self.y = self.radius
            self.vy = abs(self.vy)
        elif self.y + self.radius > height:
            self.y = height - self.radius
            self.vy = -abs(self.vy)


# ============================================================================
#                 СПЕЦИАЛИЗИРОВАННЫЕ КЛАССЫ ЧАСТИЦ
# ============================================================================

class MetalIon(Particle):
    """Положительный ион в узле кристаллической решётки металла."""

    def __init__(self, x, y, radius=ION_RADIUS):
        super().__init__(x, y, vx=0.0, vy=0.0,
                         radius=radius, color=ION_COLOR,
                         charge=+1, label="+")
        self.base_x = x
        self.base_y = y

    def vibrate(self, amplitude):
        """Тепловое дрожание иона."""
        self.x = self.base_x + random.uniform(-amplitude, amplitude)
        self.y = self.base_y + random.uniform(-amplitude, amplitude)


class Electron(Particle):
    """Свободный электрон."""

    def __init__(self, x, y, vx=0.0, vy=0.0):
        super().__init__(x, y, vx, vy,
                         radius=ELECTRON_RADIUS, color=ELECTRON_COLOR,
                         charge=-1, label="-")


class Cation(Particle):
    """Положительный ион (катион) в электролите."""

    def __init__(self, x, y, vx=0.0, vy=0.0):
        super().__init__(x, y, vx, vy,
                         radius=CATION_RADIUS, color=CATION_COLOR,
                         charge=+1, label="+")


class Anion(Particle):
    """Отрицательный ион (анион) в электролите."""

    def __init__(self, x, y, vx=0.0, vy=0.0):
        super().__init__(x, y, vx, vy,
                         radius=ANION_RADIUS, color=ANION_COLOR,
                         charge=-1, label="-")


class NeutralAtom(Particle):
    """Нейтральный атом газа."""

    def __init__(self, x, y):
        super().__init__(x, y, vx=0.0, vy=0.0,
                         radius=NEUTRAL_RADIUS, color=NEUTRAL_COLOR,
                         charge=0, label="")
        self.ionized = False
        self.base_x = x
        self.base_y = y

    def vibrate(self, amplitude=0.6):
        """Лёгкое тепловое дрожание."""
        self.x = self.base_x + random.uniform(-amplitude, amplitude)
        self.y = self.base_y + random.uniform(-amplitude, amplitude)


class GasIon(Particle):
    """Положительный ион газа."""

    def __init__(self, x, y, vx=0.0, vy=0.0):
        super().__init__(x, y, vx, vy,
                         radius=GAS_ION_RADIUS, color=GAS_ION_COLOR,
                         charge=+1, label="+")


# ============================================================================
#                  АБСТРАКТНЫЙ БАЗОВЫЙ КЛАСС СРЕДЫ
# ============================================================================

class Environment:
    """Абстрактный базовый класс для физической среды."""

    def __init__(self, canvas, width, height):
        self.canvas = canvas
        self.width = width
        self.height = height
        self.particles = []
        self.static_objects = []

    def initialize(self):
        raise NotImplementedError

    def update(self, dt, field_strength, current_on):
        raise NotImplementedError

    def draw(self):
        raise NotImplementedError

    def cleanup(self):
        """Удаление всех графических примитивов."""
        for obj in self.particles + self.static_objects:
            if obj.canvas_id is not None:
                self.canvas.delete(obj.canvas_id)
            if obj.label_id is not None:
                self.canvas.delete(obj.label_id)
        self.particles.clear()
        self.static_objects.clear()

    def _draw_particle(self, particle):
        """Отрисовка частицы в виде окружности."""
        x, y, r = particle.x, particle.y, particle.radius
        if particle.canvas_id is None:
            # Создание овала (без smooth - этот параметр не поддерживается для oval)
            particle.canvas_id = self.canvas.create_oval(
                x - r, y - r, x + r, y + r,
                fill=particle.color, outline=particle.color, width=1
            )
            if particle.label:
                particle.label_id = self.canvas.create_text(
                    x, y, text=particle.label,
                    fill="black", font=("Arial", max(7, int(r)), "bold")
                )
        else:
            # Обновление позиции
            self.canvas.coords(particle.canvas_id,
                               x - r, y - r, x + r, y + r)
            if particle.label_id is not None:
                self.canvas.coords(particle.label_id, x, y)


# ============================================================================
#              СРЕДА №1: МЕТАЛЛ
# ============================================================================

class MetalEnvironment(Environment):
    """Модель металлического проводника."""

    def __init__(self, canvas, width, height):
        super().__init__(canvas, width, height)
        self.electrons = []
        self.ions = []
        self.electron_count = 60

    def initialize(self):
        """Создание кристаллической решётки и свободных электронов."""
        margin_x = METAL_ION_MARGIN_LEFT
        margin_y = 60
        step_x = (self.width - 2 * margin_x) / max(METAL_ION_COLS - 1, 1)
        step_y = (self.height - 2 * margin_y) / max(METAL_ION_ROWS - 1, 1)

        for row in range(METAL_ION_ROWS):
            for col in range(METAL_ION_COLS):
                x = margin_x + col * step_x
                y = margin_y + row * step_y
                ion = MetalIon(x, y)
                self.ions.append(ion)
                self.static_objects.append(ion)

        attempts = 0
        while len(self.electrons) < self.electron_count and attempts < 2000:
            attempts += 1
            x = random.uniform(20, self.width - 20)
            y = random.uniform(20, self.height - 20)
            too_close = False
            for ion in self.ions:
                if math.hypot(x - ion.base_x, y - ion.base_y) < ION_RADIUS + 8:
                    too_close = True
                    break
            if too_close:
                continue
            vx = random.uniform(-80, 80)
            vy = random.uniform(-80, 80)
            electron = Electron(x, y, vx, vy)
            self.electrons.append(electron)
            self.particles.append(electron)

    def update(self, dt, field_strength, current_on):
        """Обновление состояния металлической среды."""
        for ion in self.ions:
            ion.vibrate(METAL_ION_AMPLITUDE)

        for electron in self.electrons:
            if current_on:
                electron.apply_electric_field(field_strength, dt)
            electron.apply_brownian_kick(BROWNIAN_STRENGTH * dt * 5)
            electron.limit_speed(MAX_PARTICLE_SPEED)
            electron.update_position(dt)

            for ion in self.ions:
                dx = electron.x - ion.x
                dy = electron.y - ion.y
                dist = math.hypot(dx, dy)
                min_dist = ION_RADIUS + ELECTRON_RADIUS
                if dist < min_dist and dist > 0.001:
                    nx, ny = dx / dist, dy / dist
                    electron.x = ion.x + nx * (min_dist + 0.5)
                    electron.y = ion.y + ny * (min_dist + 0.5)
                    scatter_angle = random.uniform(0, 2 * math.pi)
                    speed = math.hypot(electron.vx, electron.vy)
                    electron.vx = speed * math.cos(scatter_angle)
                    electron.vy = speed * math.sin(scatter_angle)

            electron.reflect_vertical(self.height)
            electron.wrap_horizontal(self.width)

    def draw(self):
        """Отрисовка ионов и электронов."""
        for ion in self.ions:
            self._draw_particle(ion)
        for electron in self.electrons:
            self._draw_particle(electron)


# ============================================================================
#                 СРЕДА №2: ЭЛЕКТРОЛИТ
# ============================================================================

class ElectrolyteEnvironment(Environment):
    """Модель электролита."""

    def __init__(self, canvas, width, height):
        super().__init__(canvas, width, height)
        self.cations = []
        self.anions = []

    def initialize(self):
        """Создание катионов и анионов."""
        for _ in range(ELECTROLYTE_ION_COUNT):
            x = random.uniform(40, self.width - 40)
            y = random.uniform(40, self.height - 40)
            vx = random.uniform(-30, 30)
            vy = random.uniform(-30, 30)
            cation = Cation(x, y, vx, vy)
            self.cations.append(cation)
            self.particles.append(cation)

        for _ in range(ELECTROLYTE_ION_COUNT):
            x = random.uniform(40, self.width - 40)
            y = random.uniform(40, self.height - 40)
            vx = random.uniform(-30, 30)
            vy = random.uniform(-30, 30)
            anion = Anion(x, y, vx, vy)
            self.anions.append(anion)
            self.particles.append(anion)

    def update(self, dt, field_strength, current_on):
        """Обновление состояния электролита."""
        for ion in self.cations + self.anions:
            if current_on:
                ion.apply_electric_field(field_strength, dt)
            ion.apply_brownian_kick(BROWNIAN_STRENGTH * dt * 3)
            ion.limit_speed(MAX_PARTICLE_SPEED * 0.6)
            ion.update_position(dt)
            ion.reflect_vertical(self.height)
            ion.wrap_horizontal(self.width)

    def draw(self):
        """Отрисовка катионов и анионов."""
        for cation in self.cations:
            self._draw_particle(cation)
        for anion in self.anions:
            self._draw_particle(anion)


# ============================================================================
#                 СРЕДА №3: ГАЗ
# ============================================================================

class GasEnvironment(Environment):
    """Модель газового разряда."""

    def __init__(self, canvas, width, height):
        super().__init__(canvas, width, height)
        self.neutral_atoms = []
        self.electrons = []
        self.gas_ions = []

    def initialize(self):
        """Создание нейтральных атомов и затравочных электронов."""
        attempts = 0
        while (len(self.neutral_atoms) < GAS_NEUTRAL_COUNT
               and attempts < 3000):
            attempts += 1
            x = random.uniform(30, self.width - 30)
            y = random.uniform(30, self.height - 30)
            too_close = False
            for atom in self.neutral_atoms:
                if math.hypot(x - atom.base_x, y - atom.base_y) < 22:
                    too_close = True
                    break
            if too_close:
                continue
            atom = NeutralAtom(x, y)
            self.neutral_atoms.append(atom)
            self.static_objects.append(atom)

        for _ in range(GAS_SEED_ELECTRONS):
            x = random.uniform(40, self.width - 40)
            y = random.uniform(40, self.height - 40)
            vx = random.uniform(-40, 40)
            vy = random.uniform(-40, 40)
            electron = Electron(x, y, vx, vy)
            self.electrons.append(electron)
            self.particles.append(electron)

    def _count_total_particles(self):
        """Подсчёт общего числа частиц."""
        return len(self.electrons) + len(self.gas_ions)

    def update(self, dt, field_strength, current_on):
        """Обновление состояния газовой среды."""
        for atom in self.neutral_atoms:
            if not atom.ionized:
                atom.vibrate(0.6)

        for electron in list(self.electrons):
            if current_on:
                electron.apply_electric_field(field_strength * 1.5, dt)
            electron.apply_brownian_kick(BROWNIAN_STRENGTH * dt * 1.5)
            electron.limit_speed(MAX_PARTICLE_SPEED * 1.3)
            electron.update_position(dt)

            if current_on:
                electron_speed = math.hypot(electron.vx, electron.vy)
                if electron_speed > IONIZATION_SPEED_THRESHOLD:
                    for atom in self.neutral_atoms:
                        if atom.ionized:
                            continue
                        dx = electron.x - atom.x
                        dy = electron.y - atom.y
                        dist = math.hypot(dx, dy)
                        min_dist = NEUTRAL_RADIUS + ELECTRON_RADIUS
                        if dist < min_dist:
                            atom.ionized = True
                            if atom in self.neutral_atoms:
                                self.neutral_atoms.remove(atom)
                            if atom in self.static_objects:
                                self.static_objects.remove(atom)
                            if atom.canvas_id is not None:
                                self.canvas.delete(atom.canvas_id)

                            new_ion = GasIon(atom.x, atom.y,
                                             vx=random.uniform(-10, 10),
                                             vy=random.uniform(-10, 10))
                            self.gas_ions.append(new_ion)
                            self.particles.append(new_ion)

                            if self._count_total_particles() < MAX_GAS_PARTICLES:
                                new_electron = Electron(
                                    atom.x, atom.y,
                                    vx=random.uniform(-60, 60),
                                    vy=random.uniform(-60, 60)
                                )
                                self.electrons.append(new_electron)
                                self.particles.append(new_electron)
                            
                            electron.vx *= 0.5
                            electron.vy *= 0.5
                            break

            electron.reflect_vertical(self.height)
            electron.wrap_horizontal(self.width)

        for ion in self.gas_ions:
            if current_on:
                ion.apply_electric_field(field_strength * 0.4, dt)
            ion.apply_brownian_kick(BROWNIAN_STRENGTH * dt * 1.2)
            ion.limit_speed(MAX_PARTICLE_SPEED * 0.5)
            ion.update_position(dt)
            ion.reflect_vertical(self.height)
            ion.wrap_horizontal(self.width)

    def draw(self):
        """Отрисовка всех объектов газовой среды."""
        for atom in self.neutral_atoms:
            self._draw_particle(atom)
        for electron in self.electrons:
            self._draw_particle(electron)
        for ion in self.gas_ions:
            self._draw_particle(ion)


# ============================================================================
#                         ГЛАВНЫЙ КЛАСС ПРИЛОЖЕНИЯ
# ============================================================================

class CurrentVisualizationApp:
    """Главный класс приложения."""

    def __init__(self, root):
        self.root = root
        self.root.title("Визуализация электрического тока")
        self.root.resizable(False, False)

        self.current_env_name = "metals"
        self.current_on = False
        self.field_strength = 100.0
        self.environment = None
        self.last_time = None

        self.descriptions = {
            ("metals", False): (
                "МЕТАЛЛ. Ток выключен. Свободные электроны совершают "
                "хаотическое тепловое движение. Положительные ионы "
                "кристаллической решётки колеблются в узлах."
            ),
            ("metals", True): (
                "МЕТАЛЛ. Ток включён. Под действием электрического поля "
                "электроны приобретают упорядоченный дрейф влево (к «+»). "
                "Соударения с ионами решётки создают электрическое "
                "сопротивление (модель Друде)."
            ),
            ("electrolytes", False): (
                "ЭЛЕКТРОЛИТ. Ток выключен. Катионы (+) и анионы (-) "
                "совершают хаотическое броуновское движение в растворе."
            ),
            ("electrolytes", True): (
                "ЭЛЕКТРОЛИТ. Ток включён. Катионы (+) дрейфуют к катоду "
                "(«-»), анионы (-) — к аноду («+»). Направленное движение "
                "ионов обоих знаков создаёт электрический ток в растворе."
            ),
            ("gases", False): (
                "ГАЗ. Ток выключен. Нейтральные атомы газа и небольшое "
                "число затравочных электронов совершают хаотическое "
                "тепловое движение. Разряд отсутствует."
            ),
            ("gases", True): (
                "ГАЗ. Ток включён. Электроны разгоняются полем и при "
                "столкновении с атомами ионизуют их (ударная ионизация). "
                "Рождённые электроны и ионы лавинообразно нарастают — "
                "возникает самостоятельный газовый разряд (лавина "
                "Таунсенда)."
            ),
        }

        self._build_ui()
        self._switch_environment("metals")
        self.root.after(FRAME_INTERVAL_MS, self._animate)

    def _build_ui(self):
        """Построение интерфейса."""
        main_frame = tk.Frame(self.root, bg=PANEL_BG)
        main_frame.pack(fill="both", expand=True)

        top_frame = tk.Frame(main_frame, bg=PANEL_BG)
        top_frame.pack(fill="x", padx=10, pady=(10, 5))

        self.left_panel = tk.Canvas(top_frame, width=ELECTRODE_PANEL_WIDTH,
                                    height=CANVAS_HEIGHT, bg=PANEL_BG,
                                    highlightthickness=0)
        self.left_panel.pack(side="left")
        self.left_panel.create_text(ELECTRODE_PANEL_WIDTH // 2, CANVAS_HEIGHT // 2,
                                    text="+", font=("Arial", 36, "bold"),
                                    fill=PLUS_COLOR)

        self.canvas = tk.Canvas(
            top_frame,
            width=CANVAS_WIDTH,
            height=CANVAS_HEIGHT,
            bg=BG_COLOR,
            highlightthickness=2,
            highlightbackground="#333355"
        )
        self.canvas.pack(side="left", padx=(2, 2))

        self.right_panel = tk.Canvas(top_frame, width=ELECTRODE_PANEL_WIDTH,
                                     height=CANVAS_HEIGHT, bg=PANEL_BG,
                                     highlightthickness=0)
        self.right_panel.pack(side="left")
        self.right_panel.create_text(ELECTRODE_PANEL_WIDTH // 2, CANVAS_HEIGHT // 2,
                                     text="−", font=("Arial", 44, "bold"),
                                     fill=MINUS_COLOR)

        self.info_var = tk.StringVar()
        self.info_label = tk.Label(
            main_frame,
            textvariable=self.info_var,
            wraplength=CANVAS_WIDTH + ELECTRODE_PANEL_WIDTH * 2,
            justify="left",
            font=("Arial", 10),
            bg=PANEL_BG,
            fg="#dddddd",
            padx=10,
            pady=6
        )
        self.info_label.pack(fill="x", padx=10, pady=2)

        control_frame = tk.Frame(main_frame, bg=PANEL_BG, pady=8)
        control_frame.pack(fill="x", padx=10, pady=(2, 10))

        env_frame = tk.Frame(control_frame, bg=PANEL_BG)
        env_frame.pack(fill="x", pady=4)

        tk.Label(env_frame, text="Среда:",
                 font=("Arial", 11, "bold"),
                 bg=PANEL_BG, fg="#dddddd",
                 anchor="w", width=8).pack(side="left", padx=(0, 8))

        self.env_buttons = {}
        envs = [
            ("metals", "Металлы"),
            ("electrolytes", "Электролиты"),
            ("gases", "Газы")
        ]
        for key, label in envs:
            btn = tk.Button(
                env_frame, text=label,
                font=("Arial", 11),
                height=1,
                command=lambda k=key: self._switch_environment(k)
            )
            btn.pack(side="left", padx=4, ipadx=5)
            self.env_buttons[key] = btn

        toggle_frame = tk.Frame(control_frame, bg=PANEL_BG)
        toggle_frame.pack(fill="x", pady=4)

        self.toggle_btn = tk.Button(
            toggle_frame,
            text="ВКЛЮЧИТЬ ТОК",
            font=("Arial", 10, "bold"),
            bg="#555555",
            fg="white",
            activebackground="#777777",
            command=self._toggle_current,
            width=20,
            height=1,
            pady=5
        )
        self.toggle_btn.pack(side="left", padx=(0, 20))

        volt_group = tk.Frame(toggle_frame, bg=PANEL_BG)
        volt_group.pack(side="left", fill="x", expand=True)

        tk.Label(volt_group, text="Напряжение:",
                 font=("Arial", 9),
                 bg=PANEL_BG, fg="#aaaaaa").pack(side="left", padx=(0, 5))

        self.voltage_scale = tk.Scale(
            volt_group,
            from_=0, to=300,
            orient="horizontal",
            length=250,
            bg=PANEL_BG,
            fg="#dddddd",
            troughcolor="#333355",
            highlightthickness=0,
            showvalue=0,
            command=self._on_voltage_change
        )
        self.voltage_scale.set(100)
        self.voltage_scale.pack(side="left", padx=5)

        self.voltage_spinbox = tk.Spinbox(
            volt_group,
            from_=0, to=300,
            width=5,
            font=("Arial", 9),
            bg="#2a2a3e",
            fg="white",
            buttonbackground="#444466",
            command=self._on_spinbox_change
        )
        self.voltage_spinbox.delete(0, "end")
        self.voltage_spinbox.insert(0, "100")
        self.voltage_spinbox.pack(side="left", padx=(5, 0))

        self._update_env_buttons_style()
        self._update_info_label()

    def _switch_environment(self, env_name):
        """Переключение активной среды."""
        if self.environment is not None:
            self.environment.cleanup()

        self.current_env_name = env_name

        if env_name == "metals":
            self.environment = MetalEnvironment(
                self.canvas, CANVAS_WIDTH, CANVAS_HEIGHT)
        elif env_name == "electrolytes":
            self.environment = ElectrolyteEnvironment(
                self.canvas, CANVAS_WIDTH, CANVAS_HEIGHT)
        elif env_name == "gases":
            self.environment = GasEnvironment(
                self.canvas, CANVAS_WIDTH, CANVAS_HEIGHT)

        self.environment.initialize()
        self._update_env_buttons_style()
        self._update_info_label()

    def _update_env_buttons_style(self):
        """Подсветка активной кнопки."""
        for key, btn in self.env_buttons.items():
            if key == self.current_env_name:
                btn.configure(bg="#4477aa", fg="white",
                              activebackground="#5588bb")
            else:
                btn.configure(bg="#dddddd", fg="black",
                              activebackground="#cccccc")

    def _toggle_current(self):
        """Переключение тока."""
        self.current_on = not self.current_on
        if self.current_on:
            self.toggle_btn.configure(
                text="ВЫКЛЮЧИТЬ ТОК",
                bg="#cc4444",
                activebackground="#dd5555"
            )
        else:
            self.toggle_btn.configure(
                text="ВКЛЮЧИТЬ ТОК",
                bg="#555555",
                activebackground="#777777"
            )
        self._update_info_label()

    def _on_voltage_change(self, value):
        """Обработчик ползунка."""
        try:
            val = int(float(value))
            self.voltage_spinbox.delete(0, "end")
            self.voltage_spinbox.insert(0, str(val))
            self.field_strength = val * (400.0 / 300.0)
        except (ValueError, TypeError):
            pass

    def _on_spinbox_change(self):
        """Обработчик Spinbox."""
        try:
            val = int(self.voltage_spinbox.get())
            if val < 0: val = 0
            if val > 300: val = 300
            self.voltage_scale.set(val)
            self.field_strength = val * (400.0 / 300.0)
        except ValueError:
            pass

    def _update_info_label(self):
        """Обновление табло."""
        key = (self.current_env_name, self.current_on)
        text = self.descriptions.get(key, "")
        self.info_var.set(text)

    def _animate(self):
        """Цикл анимации."""
        now_ms = int(time.time() * 1000)
        if self.last_time is None:
            dt = FRAME_INTERVAL_MS / 1000.0
        else:
            dt = (now_ms - self.last_time) / 1000.0
        dt = min(dt, 0.05)
        self.last_time = now_ms

        if self.environment is not None:
            self.environment.update(
                dt=dt,
                field_strength=self.field_strength,
                current_on=self.current_on
            )
            self.environment.draw()

        self.root.after(FRAME_INTERVAL_MS, self._animate)


def main():
    """Точка входа."""
    root = tk.Tk()
    app = CurrentVisualizationApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()