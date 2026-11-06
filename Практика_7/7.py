"""
Симулятор физики твёрдых тел и частиц (оптимизированный UI).
Полный код в одном файле (Pymunk + PySide6).
Запуск: python main.py
"""
from __future__ import annotations

import json
import math
import os
import random
import sys
import threading
import time
import traceback
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Deque, Optional

# =============================================================================
# ПРОВЕРКА ЗАВИСИМОСТЕЙ
# =============================================================================
def _check_dependencies() -> None:
    missing: list[str] = []
    for pip_name, module in (("PySide6", "PySide6"), ("pymunk", "pymunk"), ("numpy", "numpy")):
        try:
            __import__(module)
        except Exception:
            missing.append(pip_name)
    if missing:
        print("Не установлены зависимости: " + ", ".join(missing))
        print("Установите их командой:  pip install -r requirements.txt")
        raise SystemExit(1)

_check_dependencies()

import numpy as np
import pymunk
from PySide6.QtCore import QPointF, QRectF, QSettings, Qt, QThread, QTimer, Signal, QObject, Slot
from PySide6.QtGui import QAction, QBrush, QColor, QFont, QKeySequence, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QDockWidget, QDoubleSpinBox,
    QFileDialog, QFormLayout, QFrame, QGroupBox, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
    QPushButton, QScrollArea, QSlider, QSpinBox, QSplitter, QToolButton, QVBoxLayout, QWidget,
)

# =============================================================================
# 1. МАТЕРИАЛЫ
# =============================================================================
@dataclass(frozen=True)
class Material:
    key: str
    title: str
    density: float
    friction: float
    elasticity: float
    color: str

MATERIALS: dict[str, Material] = {
    "wood":   Material("wood",   "Дерево", 6.0e-4, 0.70, 0.25, "#C08A4E"),
    "metal":  Material("metal",  "Металл", 2.0e-3, 0.40, 0.45, "#9AA5B1"),
    "rubber": Material("rubber", "Резина", 9.0e-4, 0.95, 0.85, "#E05A5A"),
    "ice":    Material("ice",    "Лёд",    5.5e-4, 0.03, 0.15, "#7FD4F0"),
    "stone":  Material("stone",  "Камень", 1.6e-3, 0.85, 0.20, "#6E7684"),
    "sand":   Material("sand",   "Песок",  1.1e-3, 0.90, 0.05, "#E0C068"),
}

def get_material(key: str) -> Material:
    return MATERIALS.get(key, MATERIALS["wood"])

# =============================================================================
# 2. ФИЗИКА (МИР)
# =============================================================================
@dataclass
class BodyRecord:
    body: pymunk.Body
    shapes: list[pymunk.Shape]
    kind: str
    material: Material
    color: str
    params: dict[str, Any] = field(default_factory=dict)
    name: str = ""
    is_particle: bool = False
    trail: Deque[tuple[float, float]] = field(default_factory=lambda: deque(maxlen=20))

    @property
    def is_static(self) -> bool:
        return self.body.body_type == pymunk.Body.STATIC


class World:
    FIXED_DT: float = 1.0 / 60.0

    def __init__(self, width: float = 1600.0, height: float = 900.0) -> None:
        self.lock = threading.RLock()
        self.space = pymunk.Space()
        self.space.gravity = (0.0, 900.0)
        self.space.iterations = 10
        self.space.damping = 1.0
        self.space.sleep_time_threshold = 0.5

        self.width = float(width)
        self.height = float(height)
        self.closed_world = True

        self.records: list[BodyRecord] = []
        self.pins: list[dict[str, Any]] = []
        self.wall_shapes: list[pymunk.Shape] = []

        self._next_id = 0
        self._contact_count = 0
        self._contact_points: list[tuple[float, float]] = []

        self._mouse_body = pymunk.Body(body_type=pymunk.Body.KINEMATIC)
        self._mouse_joint: Optional[pymunk.PivotJoint] = None
        self._grabbed: Optional[BodyRecord] = None

        self._install_collision_handlers()
        self._rebuild_walls()

    def _rebuild_walls(self) -> None:
        with self.lock:
            for shape in self.wall_shapes:
                try:
                    self.space.remove(shape)
                except Exception:
                    pass
            self.wall_shapes.clear()

            w, h = self.width, self.height
            segments = [((0.0, h), (w, h))]
            if self.closed_world:
                segments += [((0.0, 0.0), (w, 0.0)), ((0.0, 0.0), (0.0, h)), ((w, 0.0), (w, h))]
            
            for a, b in segments:
                shape = pymunk.Segment(self.space.static_body, a, b, 6.0)
                shape.friction = 0.8
                shape.elasticity = 0.3
                self.space.add(shape)
                self.wall_shapes.append(shape)

            if hasattr(self.space, "reindex_static"):
                self.space.reindex_static()

    def set_bounds(self, width: float, height: float) -> None:
        with self.lock:
            self.width, self.height = float(width), float(height)
            self._rebuild_walls()

    def set_closed_world(self, closed: bool) -> None:
        with self.lock:
            if self.closed_world == closed:
                return
            self.closed_world = bool(closed)
            self._rebuild_walls()

    def set_gravity(self, gx: float, gy: float) -> None:
        with self.lock:
            self.space.gravity = (float(gx), float(gy))

    @property
    def gravity(self) -> tuple[float, float]:
        return (self.space.gravity.x, self.space.gravity.y)

    def set_spatial_hash(self, enabled: bool) -> None:
        with self.lock:
            try:
                if enabled:
                    self.space.use_spatial_hash(64.0, 30000)
                elif hasattr(self.space, "use_bb_tree"):
                    self.space.use_bb_tree()
            except Exception:
                pass

    def _install_collision_handlers(self) -> None:
        def post_solve(arbiter, space, data) -> None:
            self._contact_count += 1
            if len(self._contact_points) < 600:
                for cp in arbiter.contact_point_set.points:
                    self._contact_points.append((cp.point_a.x, cp.point_a.y))

        installed = False
        try:
            self.space.on_collision(None, None, post_solve=post_solve)
            installed = True
        except Exception:
            pass
        if not installed:
            try:
                handler = self.space.add_default_collision_handler()
                handler.post_solve = post_solve
            except Exception:
                pass

    def step(self, dt: float) -> None:
        with self.lock:
            self._contact_count = 0
            self._contact_points.clear()
            self.space.step(dt)

    def _register(self, body: pymunk.Body, shapes: list[pymunk.Shape], kind: str, material: Material, *, color: Optional[str] = None, params: Optional[dict[str, Any]] = None, is_particle: bool = False) -> BodyRecord:
        for shape in shapes:
            shape.friction = material.friction
            shape.elasticity = material.elasticity
        self.space.add(body, *shapes)

        self._next_id += 1
        rec = BodyRecord(
            body=body, shapes=list(shapes), kind=kind, material=material,
            color=color or material.color, params=params or {},
            name=f"{kind} {self._next_id}", is_particle=is_particle,
        )
        self.records.append(rec)
        return rec

    def add_circle(self, pos: tuple[float, float], radius: float, material: Optional[Material] = None, *, dynamic: bool = True, color: Optional[str] = None, is_particle: bool = False, angle: float = 0.0, velocity: tuple[float, float] = (0.0, 0.0)) -> BodyRecord:
        material = material or get_material("wood")
        with self.lock:
            if dynamic:
                mass = max(material.density * math.pi * radius * radius, 0.01)
                moment = pymunk.moment_for_circle(mass, 0.0, radius)
                body = pymunk.Body(mass, moment)
            else:
                body = pymunk.Body(body_type=pymunk.Body.STATIC)
            body.position = (float(pos[0]), float(pos[1]))
            body.angle = float(angle)
            if dynamic:
                body.velocity = (float(velocity[0]), float(velocity[1]))
            shape = pymunk.Circle(body, float(radius))
            return self._register(body, [shape], "circle", material, color=color, params={"radius": float(radius)}, is_particle=is_particle)

    def add_box(self, pos: tuple[float, float], size: tuple[float, float], material: Optional[Material] = None, *, dynamic: bool = True, color: Optional[str] = None, angle: float = 0.0, velocity: tuple[float, float] = (0.0, 0.0)) -> BodyRecord:
        material = material or get_material("wood")
        w, h = float(size[0]), float(size[1])
        hw, hh = w / 2.0, h / 2.0
        verts = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
        with self.lock:
            if dynamic:
                mass = max(material.density * w * h, 0.01)
                moment = pymunk.moment_for_box(mass, (w, h))
                body = pymunk.Body(mass, moment)
            else:
                body = pymunk.Body(body_type=pymunk.Body.STATIC)
            body.position = (float(pos[0]), float(pos[1]))
            body.angle = float(angle)
            if dynamic:
                body.velocity = (float(velocity[0]), float(velocity[1]))
            shape = pymunk.Poly(body, verts)
            return self._register(body, [shape], "box", material, color=color, params={"size": [w, h]})

    def add_polygon(self, pos: tuple[float, float], vertices: list[tuple[float, float]], material: Optional[Material] = None, *, dynamic: bool = True, color: Optional[str] = None, angle: float = 0.0, velocity: tuple[float, float] = (0.0, 0.0)) -> BodyRecord:
        material = material or get_material("wood")
        cx = sum(v[0] for v in vertices) / len(vertices)
        cy = sum(v[1] for v in vertices) / len(vertices)
        verts = [(float(v[0]) - cx, float(v[1]) - cy) for v in vertices]
        area = 0.0
        for i in range(len(verts)):
            x1, y1 = verts[i]
            x2, y2 = verts[(i + 1) % len(verts)]
            area += x1 * y2 - x2 * y1
        area = abs(area) / 2.0

        with self.lock:
            if dynamic:
                mass = max(material.density * area, 0.01)
                moment = pymunk.moment_for_poly(mass, verts)
                body = pymunk.Body(mass, moment)
            else:
                body = pymunk.Body(body_type=pymunk.Body.STATIC)
            body.position = (float(pos[0]), float(pos[1]))
            body.angle = float(angle)
            if dynamic:
                body.velocity = (float(velocity[0]), float(velocity[1]))
            shape = pymunk.Poly(body, verts)
            return self._register(body, [shape], "poly", material, color=color, params={"vertices": [[x, y] for x, y in verts]})

    def add_segment(self, pos: tuple[float, float], length: float, thickness: float, material: Optional[Material] = None, *, dynamic: bool = True, color: Optional[str] = None, angle: float = 0.0, velocity: tuple[float, float] = (0.0, 0.0)) -> BodyRecord:
        material = material or get_material("wood")
        half = float(length) / 2.0
        radius = max(float(thickness) / 2.0, 1.0)
        a, b = (-half, 0.0), (half, 0.0)
        with self.lock:
            if dynamic:
                mass = max(material.density * float(length) * float(thickness), 0.01)
                moment = pymunk.moment_for_segment(mass, a, b, radius)
                body = pymunk.Body(mass, moment)
            else:
                body = pymunk.Body(body_type=pymunk.Body.STATIC)
            body.position = (float(pos[0]), float(pos[1]))
            body.angle = float(angle)
            if dynamic:
                body.velocity = (float(velocity[0]), float(velocity[1]))
            shape = pymunk.Segment(body, a, b, radius)
            return self._register(body, [shape], "segment", material, color=color, params={"length": float(length), "thickness": float(thickness)})

    def add_platform(self, a: tuple[float, float], b: tuple[float, float], thickness: float = 14.0) -> BodyRecord:
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        mid = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
        return self.add_segment(mid, length, thickness, get_material("stone"), dynamic=False, angle=math.atan2(dy, dx))

    def spawn_particles(self, count: int, area: tuple[float, float, float, float], material: Optional[Material] = None, radius: float = 4.0) -> int:
        material = material or get_material("sand")
        x0, y0, x1, y1 = area
        rng = np.random.default_rng()
        xs = rng.uniform(x0, x1, count)
        ys = rng.uniform(y0, y1, count)
        vs = rng.uniform(-25.0, 25.0, count)
        rs = rng.uniform(0.8, 1.2, count)
        with self.lock:
            for i in range(count):
                self.add_circle((float(xs[i]), float(ys[i])), radius * float(rs[i]), material, is_particle=True, velocity=(float(vs[i]), 0.0))
        return count

    def add_pin(self, rec: BodyRecord, world_anchor: tuple[float, float], local_anchor: Optional[tuple[float, float]] = None) -> None:
        with self.lock:
            if local_anchor is None:
                local = rec.body.world_to_local(world_anchor)
                local_anchor = (local.x, local.y)
            joint = pymunk.PivotJoint(self.space.static_body, rec.body, (float(world_anchor[0]), float(world_anchor[1])), (float(local_anchor[0]), float(local_anchor[1])))
            joint.max_bias = 1e9
            joint.error_bias = (1.0 - 0.15) ** 60
            self.space.add(joint)
            self.pins.append({"record": rec, "joint": joint, "world_anchor": (float(world_anchor[0]), float(world_anchor[1])), "local_anchor": (float(local_anchor[0]), float(local_anchor[1]))})

    def remove_record(self, rec: BodyRecord) -> None:
        with self.lock:
            if rec is self._grabbed:
                self.release()
            for pin in list(self.pins):
                if pin["record"] is rec:
                    try:
                        self.space.remove(pin["joint"])
                    except Exception:
                        pass
                    self.pins.remove(pin)
            for shape in rec.shapes:
                try:
                    self.space.remove(shape)
                except Exception:
                    pass
            try:
                self.space.remove(rec.body)
            except Exception:
                pass
            if rec in self.records:
                self.records.remove(rec)

    def clear(self) -> None:
        with self.lock:
            self.release()
            for pin in self.pins:
                try:
                    self.space.remove(pin["joint"])
                except Exception:
                    pass
            self.pins.clear()
            for rec in list(self.records):
                for shape in rec.shapes:
                    try:
                        self.space.remove(shape)
                    except Exception:
                        pass
                try:
                    self.space.remove(rec.body)
                except Exception:
                    pass
            self.records.clear()

    def grab(self, rec: BodyRecord, world_point: tuple[float, float]) -> None:
        with self.lock:
            self.release()
            if rec.is_static:
                return
            self._mouse_body.position = (float(world_point[0]), float(world_point[1]))
            local = rec.body.world_to_local(world_point)
            joint = pymunk.PivotJoint(self._mouse_body, rec.body, (0.0, 0.0), (local.x, local.y))
            joint.max_force = 60000.0
            joint.error_bias = (1.0 - 0.15) ** 60
            self.space.add(joint)
            self._mouse_joint = joint
            self._grabbed = rec

    def move_grab(self, world_point: tuple[float, float]) -> None:
        with self.lock:
            if self._mouse_joint is not None:
                self._mouse_body.position = (float(world_point[0]), float(world_point[1]))

    def release(self) -> None:
        with self.lock:
            if self._mouse_joint is not None:
                try:
                    self.space.remove(self._mouse_joint)
                except Exception:
                    pass
                self._mouse_joint = None
            self._grabbed = None

    @property
    def body_count(self) -> int:
        return len(self.records)

    @property
    def particle_count(self) -> int:
        return sum(1 for r in self.records if r.is_particle)

    @property
    def contact_count(self) -> int:
        return self._contact_count

    @property
    def contact_points(self) -> list[tuple[float, float]]:
        return self._contact_points

    def create_from_data(self, data: dict[str, Any]) -> BodyRecord:
        kind = data["kind"]
        params = data.get("params", {})
        material = get_material(data.get("material", "wood"))
        dynamic = not bool(data.get("static", False))
        pos = data.get("position", (0.0, 0.0))
        angle = float(data.get("angle", 0.0))
        velocity = data.get("velocity", (0.0, 0.0))
        color = data.get("color")

        if kind == "circle":
            rec = self.add_circle(pos, float(params["radius"]), material, dynamic=dynamic, color=color, is_particle=bool(data.get("particle", False)), angle=angle, velocity=velocity)
        elif kind == "box":
            size = params["size"]
            rec = self.add_box(pos, (float(size[0]), float(size[1])), material, dynamic=dynamic, color=color, angle=angle, velocity=velocity)
        elif kind == "poly":
            verts = [(float(v[0]), float(v[1])) for v in params["vertices"]]
            rec = self.add_polygon(pos, verts, material, dynamic=dynamic, color=color, angle=angle, velocity=velocity)
        elif kind == "segment":
            rec = self.add_segment(pos, float(params["length"]), float(params["thickness"]), material, dynamic=dynamic, color=color, angle=angle, velocity=velocity)
        else:
            raise ValueError(f"Неизвестный тип тела: {kind}")

        rec.body.velocity = (float(velocity[0]), float(velocity[1]))
        rec.body.angular_velocity = float(data.get("angular_velocity", 0.0))
        return rec

# =============================================================================
# 3. ПОТОК СИМУЛЯЦИИ
# =============================================================================
class SimulationWorker(QObject):
    stats = Signal(dict)

    def __init__(self, world: World, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._world = world
        self._running = True
        self._paused = True
        self._speed = 1.0
        self._substeps = 2
        self._single_step = False

    def set_paused(self, paused: bool) -> None:
        self._paused = paused

    def set_speed(self, speed: float) -> None:
        self._speed = max(0.05, float(speed))

    def set_substeps(self, substeps: int) -> None:
        self._substeps = max(1, int(substeps))

    def request_single_step(self) -> None:
        self._single_step = True

    def stop(self) -> None:
        self._running = False

    @Slot()
    def run(self) -> None:
        last = time.perf_counter()
        stat_start = last
        steps_total = 0
        step_time_total = 0.0

        while self._running:
            frame_start = time.perf_counter()
            frame_dt = min(frame_start - last, 0.1)
            last = frame_start

            if not self._paused or self._single_step:
                h = World.FIXED_DT / self._substeps
                if self._single_step:
                    budget = World.FIXED_DT
                    self._single_step = False
                else:
                    budget = frame_dt * self._speed

                steps = int(math.ceil(budget / h)) if budget > 0 else 0
                steps = max(1, min(steps, 240))

                t0 = time.perf_counter()
                with self._world.lock:
                    for _ in range(steps):
                        self._world.step(h)
                step_time_total += (time.perf_counter() - t0) * 1000.0
                steps_total += steps

            now = time.perf_counter()
            if now - stat_start >= 0.25:
                with self._world.lock:
                    payload = {
                        "steps_per_sec": steps_total / (now - stat_start),
                        "step_ms": step_time_total / max(1, steps_total),
                        "bodies": self._world.body_count,
                        "particles": self._world.particle_count,
                        "contacts": self._world.contact_count,
                    }
                self.stats.emit(payload)
                stat_start = now
                steps_total = 0
                step_time_total = 0.0

            elapsed = time.perf_counter() - frame_start
            rest = World.FIXED_DT - elapsed
            if rest > 0:
                time.sleep(rest)

# =============================================================================
# 4. РЕНДЕР
# =============================================================================
class SceneRenderer:
    def __init__(self) -> None:
        self.show_grid = True
        self.show_velocity = False
        self.show_centers = False
        self.show_contacts = False
        self.show_trails = False

        self.background = QColor("#181825")
        self.grid_color = QColor("#26263A")
        self.border_color = QColor("#3A3A55")
        self.selection_color = QColor("#7C5CFF")
        self.velocity_color = QColor("#57D9A3")
        self.center_color = QColor("#F2C14E")
        self.contact_color = QColor("#FF6B6B")

        self.trail_limit = 700
        self._brushes: dict[str, QBrush] = {}
        self._pens: dict[str, QPen] = {}

    def _brush(self, color: str) -> QBrush:
        brush = self._brushes.get(color)
        if brush is None:
            brush = QBrush(QColor(color))
            self._brushes[color] = brush
        return brush

    def _pen(self, color: str) -> QPen:
        pen = self._pens.get(color)
        if pen is None:
            pen = QPen(QColor(color))
            pen.setCosmetic(True)
            pen.setWidthF(1.0)
            self._pens[color] = pen
        return pen

    @staticmethod
    def _geometry(body: pymunk.Body, shape: pymunk.Shape):
        if isinstance(shape, pymunk.Circle):
            c = body.local_to_world(shape.offset)
            return ("circle", QPointF(c.x, c.y), float(shape.radius))
        if isinstance(shape, pymunk.Segment):
            a = body.local_to_world(shape.a)
            b = body.local_to_world(shape.b)
            return ("segment", QPointF(a.x, a.y), QPointF(b.x, b.y), float(shape.radius))
        if isinstance(shape, pymunk.Poly):
            pts = [body.local_to_world(v) for v in shape.get_vertices()]
            return ("poly", QPolygonF([QPointF(p.x, p.y) for p in pts]))
        return None

    def draw(self, painter: QPainter, world: World, selection: Optional[BodyRecord], zoom: float, offset: QPointF) -> None:
        painter.fillRect(painter.viewport(), self.background)
        if self.show_grid:
            self._draw_grid(painter, world, zoom, offset)

        painter.save()
        painter.translate(offset)
        painter.scale(zoom, zoom)

        with world.lock:
            for rec in world.records:
                self._draw_record(painter, rec)
            if self.show_trails:
                self._draw_trails(painter, world)
            if self.show_velocity or self.show_centers:
                self._draw_overlays(painter, world)
            if self.show_contacts:
                self._draw_contacts(painter, world, zoom)
            if selection is not None:
                self._draw_selection(painter, selection)

        painter.restore()

    def _draw_record(self, painter: QPainter, rec: BodyRecord) -> None:
        painter.setBrush(self._brush(rec.color))
        painter.setPen(self._pen(rec.color))
        for shape in rec.shapes:
            geo = self._geometry(rec.body, shape)
            if geo is None:
                continue
            if geo[0] == "circle":
                painter.drawEllipse(geo[1], geo[2], geo[2])
            elif geo[0] == "poly":
                painter.drawPolygon(geo[1])
            else:
                _, a, b, radius = geo
                pen = QPen(QColor(rec.color))
                pen.setWidthF(max(1.0, radius * 2.0))
                pen.setCapStyle(Qt.RoundCap)
                painter.setPen(pen)
                painter.drawLine(a, b)
                painter.setPen(self._pen(rec.color))

    def _draw_selection(self, painter: QPainter, rec: BodyRecord) -> None:
        pen = QPen(self.selection_color)
        pen.setCosmetic(True)
        pen.setWidthF(2.0)
        pen.setStyle(Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        for shape in rec.shapes:
            geo = self._geometry(rec.body, shape)
            if geo is None:
                continue
            if geo[0] == "circle":
                painter.drawEllipse(geo[1], geo[2] + 2.0, geo[2] + 2.0)
            elif geo[0] == "poly":
                painter.drawPolygon(geo[1])
            else:
                _, a, b, _r = geo
                painter.drawLine(a, b)

    def _draw_trails(self, painter: QPainter, world: World) -> None:
        pen = QPen(QColor("#FFFFFF"))
        pen.setCosmetic(True)
        pen.setWidthF(1.0)
        for i, rec in enumerate(world.records):
            if not rec.is_particle or i > self.trail_limit:
                continue
            pos = rec.body.position
            rec.trail.append((pos.x, pos.y))
            if len(rec.trail) < 2:
                continue
            pen.setColor(QColor(rec.color))
            painter.setPen(pen)
            painter.drawPolyline([QPointF(x, y) for x, y in rec.trail])

    def _draw_overlays(self, painter: QPainter, world: World) -> None:
        vpen = QPen(self.velocity_color)
        vpen.setCosmetic(True)
        vpen.setWidthF(1.5)
        for rec in world.records:
            if rec.is_particle:
                continue
            body = rec.body
            if self.show_velocity and body.body_type != pymunk.Body.STATIC:
                vel = body.velocity
                if vel.length > 1.0:
                    c = body.position
                    painter.setPen(vpen)
                    painter.drawLine(QPointF(c.x, c.y), QPointF(c.x + vel.x * 0.15, c.y + vel.y * 0.15))
            if self.show_centers:
                com = body.local_to_world(body.center_of_gravity)
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(self.center_color))
                painter.drawEllipse(QPointF(com.x, com.y), 2.5, 2.5)
        painter.setBrush(Qt.NoBrush)

    def _draw_contacts(self, painter: QPainter, world: World, zoom: float) -> None:
        painter.setPen(QPen(self.contact_color))
        painter.setBrush(QBrush(self.contact_color))
        r = max(1.5, 2.0 / max(zoom, 0.05))
        for x, y in world.contact_points:
            painter.drawEllipse(QPointF(x, y), r, r)
        painter.setBrush(Qt.NoBrush)

    def _draw_grid(self, painter: QPainter, world: World, zoom: float, offset: QPointF) -> None:
        step = 100.0 * zoom
        if step < 10.0:
            return
        w = painter.viewport().width()
        h = painter.viewport().height()
        pen = QPen(self.grid_color)
        pen.setCosmetic(True)
        painter.setPen(pen)
        x = offset.x() % step
        while x < w:
            painter.drawLine(QPointF(x, 0), QPointF(x, h))
            x += step
        y = offset.y() % step
        while y < h:
            painter.drawLine(QPointF(0, y), QPointF(w, y))
            y += step
        pen = QPen(self.border_color)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(QRectF(offset.x(), offset.y(), world.width * zoom, world.height * zoom))

# =============================================================================
# 5. IO / СЕРИАЛИЗАЦИЯ
# =============================================================================
SCENE_VERSION = 1

def _r(value: float, ndigits: int = 4) -> float:
    return round(float(value), ndigits)

def world_to_dict(world: World) -> dict[str, Any]:
    with world.lock:
        index = {id(rec): i for i, rec in enumerate(world.records)}
        bodies: list[dict[str, Any]] = []
        for rec in world.records:
            body = rec.body
            params: dict[str, Any] = {}
            for key, value in rec.params.items():
                if isinstance(value, (list, tuple)):
                    params[key] = [list(v) if isinstance(v, (list, tuple)) else v for v in value]
                else:
                    params[key] = value
            bodies.append({
                "kind": rec.kind, "params": params, "material": rec.material.key,
                "color": rec.color, "particle": rec.is_particle, "static": rec.is_static,
                "position": [_r(body.position.x), _r(body.position.y)], "angle": _r(body.angle),
                "velocity": [_r(body.velocity.x), _r(body.velocity.y)], "angular_velocity": _r(body.angular_velocity),
            })
        pins = []
        for pin in world.pins:
            idx = index.get(id(pin["record"]))
            if idx is not None:
                pins.append({"body": idx, "world_anchor": [_r(pin["world_anchor"][0]), _r(pin["world_anchor"][1])], "local_anchor": [_r(pin["local_anchor"][0]), _r(pin["local_anchor"][1])]})
        gx, gy = world.gravity
        return {"version": SCENE_VERSION, "gravity": [_r(gx), _r(gy)], "bounds": [world.width, world.height], "closed_world": world.closed_world, "bodies": bodies, "pins": pins}

def apply_dict_to_world(world: World, data: dict[str, Any]) -> None:
    if not isinstance(data, dict) or "bodies" not in data:
        raise ValueError("Некорректный формат сцены: отсутствует раздел 'bodies'.")
    with world.lock:
        world.clear()
        bounds = data.get("bounds") or [world.width, world.height]
        world.set_bounds(float(bounds[0]), float(bounds[1]))
        world.set_closed_world(bool(data.get("closed_world", True)))
        gravity = data.get("gravity") or [0.0, 900.0]
        world.set_gravity(float(gravity[0]), float(gravity[1]))
        created = [world.create_from_data(item) for item in data["bodies"]]
        for pin in data.get("pins", []):
            idx = int(pin["body"])
            if 0 <= idx < len(created):
                world.add_pin(created[idx], tuple(pin["world_anchor"]), tuple(pin["local_anchor"]))

def save_scene(path: str, world: World) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(world_to_dict(world), fh, ensure_ascii=False, indent=2)

def load_scene(path: str, world: World) -> None:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    apply_dict_to_world(world, data)

def export_screenshot(widget: QWidget, path: str) -> bool:
    return bool(widget.grab().save(path, "PNG"))

# =============================================================================
# 6. ДЕМО-СЦЕНЫ
# =============================================================================
def demo_falling_boxes(world: World) -> None:
    world.clear()
    world.set_bounds(1600.0, 900.0)
    world.set_closed_world(True)
    world.set_gravity(0.0, 900.0)
    world.add_platform((250.0, 780.0), (700.0, 700.0), 18.0)
    world.add_platform((900.0, 700.0), (1350.0, 780.0), 18.0)
    world.add_platform((650.0, 480.0), (950.0, 480.0), 16.0)
    rng = np.random.default_rng(42)
    for i in range(26):
        world.add_box((float(rng.uniform(150.0, 1450.0)), float(rng.uniform(80.0, 260.0))), (float(rng.uniform(34.0, 62.0)), float(rng.uniform(34.0, 62.0))), get_material("metal" if i % 3 == 0 else "wood"), angle=float(rng.uniform(0.0, math.pi)))
    for _ in range(6):
        world.add_circle((700.0, 200.0), 26.0, get_material("rubber"))

def demo_hourglass(world: World) -> None:
    world.clear()
    world.set_bounds(1600.0, 900.0)
    world.set_closed_world(True)
    world.set_gravity(0.0, 900.0)
    mat = get_material("ice")
    world.add_segment((450.0, 300.0), 760.0, 18.0, mat, dynamic=False, angle=math.radians(34.0))
    world.add_segment((1150.0, 300.0), 760.0, 18.0, mat, dynamic=False, angle=math.radians(-34.0))
    world.add_segment((320.0, 700.0), 120.0, 18.0, mat, dynamic=False, angle=math.radians(90.0))
    world.add_segment((1280.0, 700.0), 120.0, 18.0, mat, dynamic=False, angle=math.radians(90.0))
    world.spawn_particles(700, (480.0, 80.0, 1120.0, 260.0), get_material("sand"), radius=5.0)

def demo_pendulum(world: World) -> None:
    world.clear()
    world.set_bounds(1600.0, 900.0)
    world.set_closed_world(True)
    world.set_gravity(0.0, 900.0)
    
    # Маятник: шар создается смещенным влево, чтобы начать качаться
    ball = world.add_circle((600.0, 250.0), 46.0, get_material("metal"))
    world.add_pin(ball, (900.0, 100.0))
    
    # Мишень: башня из ящиков прямо под маятником
    world.add_platform((800.0, 700.0), (1000.0, 700.0), 18.0)
    for i in range(4):
        for j in range(2):
            world.add_box((850.0 + j * 46.0, 650.0 - i * 44.0), (42.0, 42.0), get_material("wood"))
            
    # Левая платформа (для красоты)
    world.add_platform((200.0, 640.0), (450.0, 640.0), 16.0)
    for i in range(3):
        world.add_box((250.0 + i * 54.0, 560.0), (50.0, 50.0), get_material("stone"))

DEMOS = {"Падающие ящики": demo_falling_boxes, "Песочные часы": demo_hourglass, "Маятник": demo_pendulum}

def load_demo(world: World, name: str) -> None:
    with world.lock:
        DEMOS.get(name, demo_falling_boxes)(world)

# =============================================================================
# 7. СТИЛИ (QSS)
# =============================================================================
DARK = {"bg": "#1E1E2E", "panel": "#252537", "panel_alt": "#2C2C42", "border": "#383854", "text": "#E4E4F0", "text_dim": "#A0A0B8", "accent": "#7C5CFF", "accent_hover": "#9277FF", "danger": "#FF6B6B", "viewport": "#181825"}
LIGHT = {"bg": "#F5F5FA", "panel": "#FFFFFF", "panel_alt": "#ECECF5", "border": "#D3D3E3", "text": "#20202E", "text_dim": "#60607A", "accent": "#6B4EFF", "accent_hover": "#8266FF", "danger": "#D64242", "viewport": "#FAFAFF"}

def build_stylesheet(dark: bool = True) -> str:
    c = DARK if dark else LIGHT
    return f"""
    QWidget {{ background-color: {c['bg']}; color: {c['text']}; font-family: "Segoe UI", "Inter", sans-serif; font-size: 13px; }}
    QMainWindow::separator {{ background: {c['border']}; width: 2px; height: 2px; }}
    QToolTip {{ background-color: {c['panel_alt']}; color: {c['text']}; border: 1px solid {c['border']}; padding: 4px; border-radius: 4px; }}
    
    /* Компактное меню */
    QMenuBar {{ background-color: {c['panel']}; }}
    QMenuBar::item {{ padding: 2px 8px; background: transparent; border-radius: 4px; }}
    QMenuBar::item:selected {{ background: {c['accent']}; color: white; }}
    QMenu {{ background-color: {c['panel']}; border: 1px solid {c['border']}; }}
    QMenu::item {{ padding: 6px 26px 6px 22px; }}
    QMenu::item:selected {{ background: {c['accent']}; color: white; }}
    
    QDockWidget::title {{ background: {c['panel']}; padding: 7px 10px; border-bottom: 1px solid {c['border']}; font-weight: 600; }}
    QToolButton {{ background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 9px; padding: 2px; color: {c['text']}; }}
    QToolButton:hover {{ background: {c['panel_alt']}; border-color: {c['accent']}; }}
    QToolButton:checked {{ background: {c['accent']}; border-color: {c['accent']}; color: white; }}
    QPushButton {{ background: {c['panel_alt']}; border: 1px solid {c['border']}; border-radius: 7px; padding: 7px 12px; }}
    QPushButton:hover {{ border-color: {c['accent']}; }}
    QPushButton:pressed {{ background: {c['accent']}; color: white; }}
    
    QComboBox, QSpinBox, QDoubleSpinBox {{ background: {c['panel_alt']}; border: 1px solid {c['border']}; border-radius: 6px; padding: 4px 6px; min-height: 20px; }}
    QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {{ border-color: {c['accent']}; }}
    
    QSlider::groove:horizontal {{ height: 4px; background: {c['border']}; border-radius: 2px; }}
    QSlider::sub-page:horizontal {{ background: {c['accent']}; border-radius: 2px; }}
    QSlider::handle:horizontal {{ background: {c['accent']}; width: 14px; margin: -6px 0; border-radius: 7px; }}
    
    /* Чёткие разделители для QGroupBox */
    QGroupBox {{ border: 1px solid {c['border']}; border-radius: 9px; margin-top: 14px; padding-top: 10px; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 5px; color: {c['accent']}; font-weight: 600; }}
    
    QStatusBar {{ background: {c['panel']}; border-top: 1px solid {c['border']}; }}
    QStatusBar QLabel {{ padding: 0 8px; color: {c['text_dim']}; }}
    QSplitter::handle {{ background: {c['border']}; }}
    QCheckBox::indicator {{ width: 15px; height: 15px; border-radius: 4px; border: 1px solid {c['border']}; background: {c['panel_alt']}; }}
    QCheckBox::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; }}
    QLabel#TitleLabel {{ font-size: 14px; font-weight: 600; }}
    QLabel#HintLabel {{ color: {c['text_dim']}; }}
    QFrame[frameShape="4"] {{ color: {c['border']}; }} /* HLine */
    """

# =============================================================================
# 8. UI: ВЬЮПОРТ
# =============================================================================
class Tool(str, Enum):
    SELECT = "select"
    DRAG = "drag"
    CIRCLE = "circle"
    BOX = "box"
    POLY = "poly"
    SEGMENT = "segment"
    PLATFORM = "platform"
    THROW = "throw"
    DELETE = "delete"
    PAN = "pan"

TOOL_HINTS = {
    Tool.SELECT: "Выбор: щёлкните по телу", Tool.DRAG: "Перетаскивание: зажмите ЛКМ на теле",
    Tool.CIRCLE: "Круг: щёлкните, чтобы создать", Tool.BOX: "Ящик: щёлкните, чтобы создать",
    Tool.POLY: "Многоугольник: щёлкните", Tool.SEGMENT: "Палка: щёлкните", Tool.PLATFORM: "Платформа: протяните линию",
    Tool.THROW: "Бросок: потяните тело и отпустите", Tool.DELETE: "Удаление: щёлкните по телу", Tool.PAN: "Панорама: тяните ЛКМ",
}

CURSORS = {
    Tool.SELECT: Qt.ArrowCursor, Tool.DRAG: Qt.OpenHandCursor, Tool.CIRCLE: Qt.CrossCursor,
    Tool.BOX: Qt.CrossCursor, Tool.POLY: Qt.CrossCursor, Tool.SEGMENT: Qt.CrossCursor,
    Tool.PLATFORM: Qt.CrossCursor, Tool.THROW: Qt.CrossCursor, Tool.DELETE: Qt.CrossCursor, Tool.PAN: Qt.OpenHandCursor,
}

TOOL_BUTTONS = [
    (Tool.SELECT, "➤", "Выбор (V)"), (Tool.DRAG, "✥", "Перетаскивание (G)"),
    (Tool.CIRCLE, "●", "Круг (C)"), (Tool.BOX, "■", "Ящик (B)"),
    (Tool.POLY, "⬟", "Многоугольник (P)"), (Tool.SEGMENT, "／", "Палка (L)"),
    (Tool.PLATFORM, "▬", "Платформа (R)"), (Tool.THROW, "⟶", "Швырнуть (T)"),
    (Tool.DELETE, "✖", "Удалить (X)"), (Tool.PAN, "✋", "Панорама (H)"),
]

class SceneView(QWidget):
    selection_changed = Signal(object)
    about_to_modify = Signal()
    scene_modified = Signal()
    status_text = Signal(str)

    def __init__(self, world: World, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.world = world
        self.renderer = SceneRenderer()
        self.tool = Tool.SELECT
        self.material_key = "wood"
        self.spawn_radius = 28.0
        self.spawn_size = 56.0
        self.stick_length = 120.0
        self.zoom = 1.0
        self.offset = QPointF(20.0, 20.0)
        self.selection: Optional[BodyRecord] = None
        self._panning = False
        self._pan_start = QPointF()
        self._pan_offset = QPointF()
        self._platform_start = None
        self._platform_end = None
        self._throw_start = None
        self._throw_current = None
        self._throw_record = None
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumSize(480, 360)
        self.setCursor(CURSORS[self.tool])

    def world_to_screen(self, point) -> QPointF:
        return QPointF(point[0] * self.zoom + self.offset.x(), point[1] * self.zoom + self.offset.y())

    def screen_to_world(self, point: QPointF) -> pymunk.Vec2d:
        return pymunk.Vec2d((point.x() - self.offset.x()) / self.zoom, (point.y() - self.offset.y()) / self.zoom)

    def fit_scene(self) -> None:
        w, h = max(1, self.width()), max(1, self.height())
        self.zoom = max(0.1, min(w / max(1.0, self.world.width), h / max(1.0, self.world.height)) * 0.95)
        self.offset = QPointF((w - self.world.width * self.zoom) / 2.0, (h - self.world.height * self.zoom) / 2.0)
        self.update()

    def set_tool(self, tool: Tool) -> None:
        self.tool = tool
        self.setCursor(CURSORS[tool])
        self.status_text.emit(TOOL_HINTS[tool])
        self.update()

    def set_selection(self, rec: Optional[BodyRecord]) -> None:
        if rec is not self.selection:
            self.selection = rec
            self.selection_changed.emit(rec)
            self.update()

    def refresh_selection(self) -> None:
        if self.selection is not None and self.selection not in self.world.records:
            self.set_selection(None)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        self.renderer.draw(painter, self.world, self.selection, self.zoom, self.offset)
        pen = QPen(QColor("#7C5CFF"))
        pen.setWidthF(1.5)
        pen.setStyle(Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        if self.tool == Tool.PLATFORM and self._platform_start is not None and self._platform_end is not None:
            painter.drawLine(self.world_to_screen(self._platform_start), self.world_to_screen(self._platform_end))
        if self.tool == Tool.THROW and self._throw_start is not None and self._throw_current is not None:
            painter.drawLine(self.world_to_screen(self._throw_start), self.world_to_screen(self._throw_current))
        painter.end()

    def _pick(self, world_point: pymunk.Vec2d) -> Optional[BodyRecord]:
        with self.world.lock:
            for rec in reversed(self.world.records):
                for shape in rec.shapes:
                    try:
                        if shape.point_query(world_point).distance <= 0.0:
                            return rec
                    except Exception:
                        continue
        return None

    def mousePressEvent(self, event) -> None:
        pos = event.position()
        wp = self.screen_to_world(pos)
        if event.button() == Qt.MiddleButton:
            self._panning = True
            self._pan_start = pos
            self._pan_offset = QPointF(self.offset)
            self.setCursor(Qt.ClosedHandCursor)
            return
        if event.button() != Qt.LeftButton:
            return
        if self.tool == Tool.PAN:
            self._panning = True
            self._pan_start = pos
            self._pan_offset = QPointF(self.offset)
            self.setCursor(Qt.ClosedHandCursor)
            return

        if self.tool == Tool.SELECT:
            self.set_selection(self._pick(wp))
        elif self.tool == Tool.DRAG:
            rec = self._pick(wp)
            if rec is not None and not rec.is_static:
                self.set_selection(rec)
                with self.world.lock:
                    self.world.grab(rec, (wp.x, wp.y))
                self.setCursor(Qt.ClosedHandCursor)
                self.scene_modified.emit()
        elif self.tool in (Tool.CIRCLE, Tool.BOX, Tool.POLY, Tool.SEGMENT):
            self.about_to_modify.emit()
            material = get_material(self.material_key)
            rec = None
            with self.world.lock:
                if self.tool == Tool.CIRCLE:
                    rec = self.world.add_circle((wp.x, wp.y), self.spawn_radius, material)
                elif self.tool == Tool.BOX:
                    rec = self.world.add_box((wp.x, wp.y), (self.spawn_size, self.spawn_size), material)
                elif self.tool == Tool.POLY:
                    verts = [(self.spawn_radius * 1.2 * math.cos(2 * math.pi * i / 6 + random.uniform(-0.08, 0.08)), self.spawn_radius * 1.2 * math.sin(2 * math.pi * i / 6 + random.uniform(-0.08, 0.08))) for i in range(6)]
                    rec = self.world.add_polygon((wp.x, wp.y), verts, material)
                else:
                    rec = self.world.add_segment((wp.x, wp.y), self.stick_length, 14.0, material, angle=random.uniform(0, math.pi))
            self.set_selection(rec)
            self.scene_modified.emit()
        elif self.tool == Tool.PLATFORM:
            self._platform_start = wp
            self._platform_end = wp
        elif self.tool == Tool.THROW:
            rec = self._pick(wp)
            if rec is not None and not rec.is_static:
                self._throw_record, self._throw_start, self._throw_current = rec, wp, wp
                self.set_selection(rec)
        elif self.tool == Tool.DELETE:
            rec = self._pick(wp)
            if rec is not None:
                self.about_to_modify.emit()
                with self.world.lock:
                    self.world.remove_record(rec)
                if rec is self.selection:
                    self.set_selection(None)
                self.scene_modified.emit()
        self.update()

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        wp = self.screen_to_world(pos)
        self.status_text.emit(f"{TOOL_HINTS[self.tool]}    |    x={wp.x:.0f}  y={wp.y:.0f}")
        if self._panning:
            self.offset = self._pan_offset + (pos - self._pan_start)
            self.update()
            return
        if self.tool == Tool.DRAG and event.buttons() & Qt.LeftButton:
            with self.world.lock:
                self.world.move_grab((wp.x, wp.y))
            self.update()
        if self.tool == Tool.PLATFORM and self._platform_start is not None:
            self._platform_end = wp
            self.update()
        if self.tool == Tool.THROW and self._throw_start is not None:
            self._throw_current = wp
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        pos = event.position()
        wp = self.screen_to_world(pos)
        if self._panning and event.button() in (Qt.LeftButton, Qt.MiddleButton):
            self._panning = False
            self.setCursor(CURSORS[self.tool])
            return
        if event.button() != Qt.LeftButton:
            return
        if self.tool == Tool.DRAG:
            with self.world.lock:
                self.world.release()
            self.setCursor(CURSORS[self.tool])
        elif self.tool == Tool.PLATFORM and self._platform_start is not None:
            start = self._platform_start
            self._platform_start = self._platform_end = None
            if math.hypot(wp.x - start.x, wp.y - start.y) > 12.0:
                self.about_to_modify.emit()
                with self.world.lock:
                    rec = self.world.add_platform((start.x, start.y), (wp.x, wp.y))
                self.set_selection(rec)
                self.scene_modified.emit()
            self.update()
        elif self.tool == Tool.THROW and self._throw_start is not None and self._throw_record is not None:
            dx, dy = wp.x - self._throw_start.x, wp.y - self._throw_start.y
            rec, self._throw_record, self._throw_start, self._throw_current = self._throw_record, None, None, None
            if rec in self.world.records:
                with self.world.lock:
                    rec.body.velocity = (max(-4000.0, min(4000.0, dx * 6.0)), max(-4000.0, min(4000.0, dy * 6.0)))
            self.scene_modified.emit()
            self.update()

    def wheelEvent(self, event) -> None:
        pos = event.position()
        before = self.screen_to_world(pos)
        self.zoom = max(0.12, min(6.0, self.zoom * (1.0015 ** event.angleDelta().y())))
        self.offset = QPointF(pos.x() - before.x * self.zoom, pos.y() - before.y * self.zoom)
        self.update()

# =============================================================================
# 9. UI: ПАНЕЛИ
# =============================================================================
class PropertiesPanel(QWidget):
    changed = Signal()
    delete_requested = Signal()

    def __init__(self, world: World, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.world = world
        self.record: Optional[BodyRecord] = None
        self._updating = False
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)
        self.lbl_title = QLabel("Ничего не выбрано")
        self.lbl_title.setObjectName("TitleLabel")
        self.lbl_title.setWordWrap(True)
        root.addWidget(self.lbl_title)
        
        box = QGroupBox("Физические свойства")
        form = QFormLayout(box)
        form.setLabelAlignment(Qt.AlignRight)
        self.cmb_material = QComboBox()
        for key, mat in MATERIALS.items():
            self.cmb_material.addItem(mat.title, key)
        form.addRow("Материал", self.cmb_material)
        
        self.spn_mass = QDoubleSpinBox()
        self.spn_mass.setRange(0.01, 100000.0)
        self.spn_mass.setDecimals(3)
        self.spn_mass.setSuffix(" кг")
        form.addRow("Масса", self.spn_mass)
        
        self.spn_friction = QDoubleSpinBox()
        self.spn_friction.setRange(0.0, 2.0)
        self.spn_friction.setToolTip("Коэффициент трения (0 - скольжение, >1 - высокое трение)")
        form.addRow("Трение", self.spn_friction)
        
        self.spn_elasticity = QDoubleSpinBox()
        self.spn_elasticity.setRange(0.0, 1.0)
        self.spn_elasticity.setToolTip("Упругость (0 - неупругий удар, 1 - абсолютно упругий)")
        form.addRow("Упругость", self.spn_elasticity)
        
        self.spn_angle = QDoubleSpinBox()
        self.spn_angle.setRange(-3600.0, 3600.0)
        self.spn_angle.setSuffix(" °")
        form.addRow("Угол", self.spn_angle)
        root.addWidget(box)

        # Разделитель
        line1 = QFrame()
        line1.setFrameShape(QFrame.HLine)
        line1.setFrameShadow(QFrame.Sunken)
        root.addWidget(line1)

        live = QGroupBox("Динамика")
        live_form = QFormLayout(live)
        self.lbl_velocity = QLabel("—")
        self.lbl_angular = QLabel("—")
        self.lbl_moment = QLabel("—")
        live_form.addRow("Скорость", self.lbl_velocity)
        live_form.addRow("Угл. скорость", self.lbl_angular)
        live_form.addRow("Момент имп.", self.lbl_moment)
        root.addWidget(live)
        
        root.addStretch(1)
        
        self.btn_delete = QPushButton("Удалить тело")
        self.btn_delete.setStyleSheet("background-color: #E05A5A; color: white;")
        root.addWidget(self.btn_delete)
        
        for w in (self.spn_mass, self.spn_friction, self.spn_elasticity, self.spn_angle):
            w.valueChanged.connect(self._apply)
        self.cmb_material.currentIndexChanged.connect(self._apply)
        self.btn_delete.clicked.connect(self.delete_requested.emit)
        self.set_record(None)

    def set_record(self, rec: Optional[BodyRecord]) -> None:
        self.record = rec
        self._updating = True
        try:
            enabled = rec is not None
            for w in (self.cmb_material, self.spn_mass, self.spn_friction, self.spn_elasticity, self.spn_angle, self.btn_delete):
                w.setEnabled(enabled)
            if rec is None:
                self.lbl_title.setText("Ничего не выбрано")
                self.lbl_velocity.setText("—")
                self.lbl_angular.setText("—")
                self.lbl_moment.setText("—")
                return
            with self.world.lock:
                self.lbl_title.setText(f"{rec.name} ({rec.kind})")
                self.cmb_material.setCurrentIndex(max(0, self.cmb_material.findData(rec.material.key)))
                self.spn_mass.setValue(rec.body.mass)
                self.spn_mass.setEnabled(not rec.is_static)
                self.spn_friction.setValue(rec.shapes[0].friction)
                self.spn_elasticity.setValue(rec.shapes[0].elasticity)
                self.spn_angle.setValue(math.degrees(rec.body.angle))
        finally:
            self._updating = False

    def update_live(self) -> None:
        rec = self.record
        if rec is None or rec not in self.world.records:
            return
        with self.world.lock:
            self.lbl_velocity.setText(f"{rec.body.velocity.x:.1f}, {rec.body.velocity.y:.1f}")
            self.lbl_angular.setText(f"{rec.body.angular_velocity:.2f} рад/с")
            self.lbl_moment.setText(f"{rec.body.moment:.2f}")

    def _apply(self) -> None:
        if self._updating or self.record is None or self.record not in self.world.records:
            return
        with self.world.lock:
            material = get_material(str(self.cmb_material.currentData()))
            if material.key != self.record.material.key:
                self.record.material = material
                self.record.color = material.color
            for shape in self.record.shapes:
                shape.friction = float(self.spn_friction.value())
                shape.elasticity = float(self.spn_elasticity.value())
            if not self.record.is_static:
                new_mass = float(self.spn_mass.value())
                old_mass = float(self.record.body.mass)
                if new_mass > 0.0 and abs(new_mass - old_mass) > 1e-9 and old_mass > 0.0:
                    self.record.body.moment *= (new_mass / old_mass)
                    self.record.body.mass = new_mass
            self.record.body.angle = math.radians(float(self.spn_angle.value()))
        self.changed.emit()


class ScenePanel(QWidget):
    gravity_changed = Signal(float, float)
    closed_changed = Signal(bool)
    speed_changed = Signal(float)
    substeps_changed = Signal(int)
    spawn_requested = Signal(int)
    stress_requested = Signal()
    clear_requested = Signal()
    spatial_hash_changed = Signal(bool)

    PRESETS = [("Земля", (0.0, 900.0)), ("Луна", (0.0, 150.0)), ("Марс", (0.0, 370.0)), ("Невесомость", (0.0, 0.0)), ("Своя", None)]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._updating = False
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)
        
        gbox = QGroupBox("Гравитация")
        gl = QVBoxLayout(gbox)
        self.cmb_preset = QComboBox()
        for title, _ in self.PRESETS:
            self.cmb_preset.addItem(title)
        gl.addWidget(self.cmb_preset)
        
        # gY
        self.lbl_gy = QLabel("gY = 900 px/s²")
        gl.addWidget(self.lbl_gy)
        self.sld_gy = QSlider(Qt.Horizontal)
        self.sld_gy.setRange(-2000, 2000)
        self.sld_gy.setValue(900)
        gl.addWidget(self.sld_gy)
        row_y = QHBoxLayout()
        row_y.setContentsMargins(0, 0, 0, 5)
        lbl_min_y = QLabel("-2000")
        lbl_min_y.setStyleSheet("color: #A0A0B8; font-size: 10px;")
        lbl_max_y = QLabel("2000")
        lbl_max_y.setStyleSheet("color: #A0A0B8; font-size: 10px;")
        row_y.addWidget(lbl_min_y)
        row_y.addStretch()
        row_y.addWidget(lbl_max_y)
        gl.addLayout(row_y)
        
        # gX
        self.lbl_gx = QLabel("gX = 0 px/s²")
        gl.addWidget(self.lbl_gx)
        self.sld_gx = QSlider(Qt.Horizontal)
        self.sld_gx.setRange(-2000, 2000)
        gl.addWidget(self.sld_gx)
        row_x = QHBoxLayout()
        row_x.setContentsMargins(0, 0, 0, 5)
        lbl_min_x = QLabel("-2000")
        lbl_min_x.setStyleSheet("color: #A0A0B8; font-size: 10px;")
        lbl_max_x = QLabel("2000")
        lbl_max_x.setStyleSheet("color: #A0A0B8; font-size: 10px;")
        row_x.addWidget(lbl_min_x)
        row_x.addStretch()
        row_x.addWidget(lbl_max_x)
        gl.addLayout(row_x)
        
        self.chk_closed = QCheckBox("Закрытый мир")
        self.chk_closed.setToolTip("Добавить невидимые стены по краям мира, чтобы объекты не улетали")
        self.chk_closed.setChecked(True)
        gl.addWidget(self.chk_closed)
        root.addWidget(gbox)

        # Разделитель
        line1 = QFrame()
        line1.setFrameShape(QFrame.HLine)
        line1.setFrameShadow(QFrame.Sunken)
        root.addWidget(line1)

        tbox = QGroupBox("Время и Solver")
        tl = QVBoxLayout(tbox)
        self.lbl_speed = QLabel("Скорость: 1.0x")
        self.sld_speed = QSlider(Qt.Horizontal)
        self.sld_speed.setRange(10, 400)
        self.sld_speed.setValue(100)
        tl.addWidget(self.lbl_speed)
        tl.addWidget(self.sld_speed)
        
        self.lbl_substeps = QLabel("Субшагов: 2")
        self.sld_substeps = QSlider(Qt.Horizontal)
        self.sld_substeps.setRange(1, 8)
        self.sld_substeps.setValue(2)
        tl.addWidget(self.lbl_substeps)
        tl.addWidget(self.sld_substeps)
        
        self.chk_spatial = QCheckBox("Пространственный хэш")
        self.chk_spatial.setToolTip("Ускоряет поиск коллизий при тысячах частиц, но замедляет при малом их числе")
        tl.addWidget(self.chk_spatial)
        root.addWidget(tbox)

        # Разделитель
        line2 = QFrame()
        line2.setFrameShape(QFrame.HLine)
        line2.setFrameShadow(QFrame.Sunken)
        root.addWidget(line2)

        pbox = QGroupBox("Частицы")
        pl = QVBoxLayout(pbox)
        row = QHBoxLayout()
        row.addWidget(QLabel("Кол-во:"))
        self.spn_count = QSpinBox()
        self.spn_count.setRange(10, 5000)
        self.spn_count.setValue(300)
        self.spn_count.setSingleStep(50)
        row.addWidget(self.spn_count, 1)
        pl.addLayout(row)
        self.btn_spawn = QPushButton("Дождь частиц")
        self.btn_stress = QPushButton("Стресс-тест (2000)")
        self.btn_clear = QPushButton("Очистить сцену")
        pl.addWidget(self.btn_spawn)
        pl.addWidget(self.btn_stress)
        pl.addWidget(self.btn_clear)
        root.addWidget(pbox)
        
        root.addStretch(1)
        
        self.lbl_info = QLabel("Тел: 0   Частиц: 0")
        self.lbl_info.setObjectName("HintLabel")
        root.addWidget(self.lbl_info)

        self.cmb_preset.currentIndexChanged.connect(self._on_preset)
        self.sld_gy.valueChanged.connect(self._on_sliders)
        self.sld_gx.valueChanged.connect(self._on_sliders)
        self.chk_closed.toggled.connect(self.closed_changed.emit)
        self.sld_speed.valueChanged.connect(lambda v: self.speed_changed.emit(v / 100.0))
        self.sld_speed.valueChanged.connect(lambda v: self.lbl_speed.setText(f"Скорость: {v/100.0:.1f}x"))
        self.sld_substeps.valueChanged.connect(lambda v: self.substeps_changed.emit(v))
        self.sld_substeps.valueChanged.connect(lambda v: self.lbl_substeps.setText(f"Субшагов: {v}"))
        self.chk_spatial.toggled.connect(self.spatial_hash_changed.emit)
        self.btn_spawn.clicked.connect(lambda: self.spawn_requested.emit(self.spn_count.value()))
        self.btn_stress.clicked.connect(self.stress_requested.emit)
        self.btn_clear.clicked.connect(self.clear_requested.emit)

    def _on_preset(self, index: int) -> None:
        preset = self.PRESETS[index][1]
        if preset:
            self._updating = True
            self.sld_gx.setValue(int(preset[0]))
            self.sld_gy.setValue(int(preset[1]))
            self._updating = False
            self._on_sliders()

    def _on_sliders(self) -> None:
        gx, gy = float(self.sld_gx.value()), float(self.sld_gy.value())
        self.lbl_gx.setText(f"gX = {gx:.0f} px/s²")
        self.lbl_gy.setText(f"gY = {gy:.0f} px/s²")
        if not self._updating:
            self._updating = True
            self.cmb_preset.setCurrentIndex(len(self.PRESETS) - 1)
            self._updating = False
        self.gravity_changed.emit(gx, gy)

    def sync_from_world(self, world: World) -> None:
        gx, gy = world.gravity
        self._updating = True
        self.sld_gx.setValue(int(max(-2000, min(2000, gx))))
        self.sld_gy.setValue(int(max(-2000, min(2000, gy))))
        self.chk_closed.setChecked(world.closed_world)
        self._updating = False

    def set_info(self, bodies: int, particles: int) -> None:
        self.lbl_info.setText(f"Тел: {bodies}   Частиц: {particles}")

# =============================================================================
# 10. ГЛАВНОЕ ОКНО
# =============================================================================
class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = QSettings("PhysicsSandbox", "RigidParticles")
        self.world = World(1600.0, 900.0)
        self.view = SceneView(self.world)
        self.properties = PropertiesPanel(self.world)
        self.scene_panel = ScenePanel()
        self._current_path: Optional[str] = None
        self._undo_stack: list[dict] = []
        self._dark_theme = True
        self._render_frames = 0
        self._render_last = time.perf_counter()
        self._render_fps = 0.0
        self._physics_stats = {"steps_per_sec": 0.0, "step_ms": 0.0, "bodies": 0, "particles": 0, "contacts": 0}
        self._paused = True
        self.setWindowTitle("Симулятор физики")
        self.setMinimumSize(1280, 720)
        self.resize(1500, 920)
        self._build_ui()
        self._dark_theme = bool(self.settings.value("dark_theme", True, type=bool))
        self._apply_theme()
        load_demo(self.world, "Падающие ящики")
        self.view.set_selection(None)
        self.scene_panel.sync_from_world(self.world)
        self._start_physics()
        self._render_timer = QTimer(self)
        self._render_timer.timeout.connect(self._on_tick)
        self._render_timer.start(16)
        QTimer.singleShot(50, self.view.fit_scene)

    def _build_ui(self) -> None:
        # Компактная панель инструментов
        panel = QWidget()
        panel.setFixedWidth(56)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)
        self._tool_group = QButtonGroup(panel)
        self._tool_group.setExclusive(True)
        self._tool_buttons = {}
        
        for tool, glyph, tip in TOOL_BUTTONS:
            btn = QToolButton(panel)
            btn.setText(glyph)
            btn.setToolTip(tip)
            btn.setCheckable(True)
            btn.setFixedSize(44, 36)
            btn.setFont(QFont("Segoe UI", 12))
            btn.clicked.connect(lambda _c=False, t=tool: self._set_tool(t))
            lay.addWidget(btn)
            self._tool_group.addButton(btn)
            self._tool_buttons[tool] = btn
            
        lay.addStretch(1)
        
        self.btn_play = QToolButton(panel)
        self.btn_play.setText("▶")
        self.btn_play.setToolTip("Старт/Пауза")
        self.btn_play.setCheckable(True)
        self.btn_play.setFixedSize(44, 36)
        self.btn_play.setFont(QFont("Segoe UI", 12))
        self.btn_play.clicked.connect(self._toggle_pause)
        lay.addWidget(self.btn_play)
        
        self.btn_step = QToolButton(panel)
        self.btn_step.setText("⏭")
        self.btn_step.setToolTip("Шаг")
        self.btn_step.setFixedSize(44, 32)
        self.btn_step.clicked.connect(self._step_once)
        lay.addWidget(self.btn_step)
        
        self.btn_reset = QToolButton(panel)
        self.btn_reset.setText("⟲")
        self.btn_reset.setToolTip("Сброс")
        self.btn_reset.setFixedSize(44, 32)
        self.btn_reset.clicked.connect(self._reset_scene)
        lay.addWidget(self.btn_reset)
        self._tool_buttons[Tool.SELECT].setChecked(True)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(panel)
        splitter.addWidget(self.view)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([56, 1200])
        splitter.setChildrenCollapsible(False)
        self.setCentralWidget(splitter)

        self.props_dock = QDockWidget("Свойства", self)
        props_scroll = QScrollArea()
        props_scroll.setWidgetResizable(True)
        props_scroll.setWidget(self.properties)
        self.props_dock.setWidget(props_scroll)
        self.props_dock.setMinimumWidth(280)
        self.addDockWidget(Qt.RightDockWidgetArea, self.props_dock)

        self.scene_dock = QDockWidget("Сцена", self)
        scene_scroll = QScrollArea()
        scene_scroll.setWidgetResizable(True)
        scene_scroll.setWidget(self.scene_panel)
        self.scene_dock.setWidget(scene_scroll)
        self.scene_dock.setMinimumWidth(280)
        self.addDockWidget(Qt.RightDockWidgetArea, self.scene_dock)

        self._build_menus()
        self._build_statusbar()
        self._connect_signals()

    def _build_menus(self) -> None:
        menubar = self.menuBar()
        file_menu = menubar.addMenu("Файл")
        self._add_action(file_menu, "Новый", "Ctrl+N", self._new_scene)
        self._add_action(file_menu, "Открыть…", "Ctrl+O", self._open_scene)
        self._add_action(file_menu, "Сохранить", "Ctrl+S", self._save_scene)
        self._add_action(file_menu, "Экспорт PNG…", "Ctrl+E", self._export_png)
        file_menu.addSeparator()
        self._add_action(file_menu, "Выход", "Ctrl+Q", self.close)

        sim_menu = menubar.addMenu("Симуляция")
        self._add_action(sim_menu, "Старт/Пауза", "Space", self._toggle_pause)
        self._add_action(sim_menu, "Шаг", "Ctrl+Right", self._step_once)
        self._add_action(sim_menu, "Сброс", "Ctrl+R", self._reset_scene)
        sim_menu.addSeparator()
        demos_menu = sim_menu.addMenu("Демо-сцены")
        for name in DEMOS:
            act = QAction(name, self)
            act.triggered.connect(lambda _c=False, n=name: self._load_demo(n))
            demos_menu.addAction(act)
        sim_menu.addSeparator()
        self._add_action(sim_menu, "Стресс-тест", "Ctrl+T", self._stress_test)

        view_menu = menubar.addMenu("Вид")
        self.act_dark = QAction("Тёмная тема", self, checkable=True)
        self.act_dark.setChecked(True)
        self.act_dark.triggered.connect(self._on_theme_toggled)
        view_menu.addAction(self.act_dark)
        self.act_grid = QAction("Сетка", self, checkable=True)
        self.act_grid.setChecked(True)
        self.act_grid.triggered.connect(lambda v: self._set_renderer_flag("show_grid", v))
        view_menu.addAction(self.act_grid)
        self.act_velocity = QAction("Векторы скорости", self, checkable=True)
        self.act_velocity.triggered.connect(lambda v: self._set_renderer_flag("show_velocity", v))
        view_menu.addAction(self.act_velocity)
        self.act_contacts = QAction("Контакты", self, checkable=True)
        self.act_contacts.triggered.connect(lambda v: self._set_renderer_flag("show_contacts", v))
        view_menu.addAction(self.act_contacts)
        view_menu.addSeparator()
        self._add_action(view_menu, "Вписать сцену", "F", self.view.fit_scene)

        help_menu = menubar.addMenu("Справка")
        self._add_action(help_menu, "Горячие клавиши", "F1", self._show_help)

    def _add_action(self, menu, title: str, shortcut: Optional[str], slot) -> None:
        act = QAction(title, self)
        if shortcut:
            act.setShortcut(QKeySequence(shortcut))
            act.setShortcutContext(Qt.ApplicationShortcut)
        act.triggered.connect(slot)
        menu.addAction(act)

    def _build_statusbar(self) -> None:
        bar = self.statusBar()
        self.lbl_hint = QLabel(TOOL_HINTS[Tool.SELECT])
        self.lbl_bodies = QLabel("Тел: 0")
        self.lbl_contacts = QLabel("Контактов: 0")
        self.lbl_fps = QLabel("FPS: —")
        bar.addWidget(self.lbl_hint, 1)
        bar.addPermanentWidget(self.lbl_bodies)
        bar.addPermanentWidget(self.lbl_contacts)
        bar.addPermanentWidget(self.lbl_fps)

    def _connect_signals(self) -> None:
        self.view.selection_changed.connect(self.properties.set_record)
        self.view.about_to_modify.connect(self._push_undo)
        self.view.scene_modified.connect(self._on_scene_modified)
        self.view.status_text.connect(self.lbl_hint.setText)
        self.properties.delete_requested.connect(self._delete_selected)
        self.properties.changed.connect(self.view.update)
        self.scene_panel.gravity_changed.connect(self.world.set_gravity)
        self.scene_panel.closed_changed.connect(lambda c: (self.world.set_closed_world(c), self.view.update()))
        self.scene_panel.speed_changed.connect(lambda s: self.worker.set_speed(s))
        self.scene_panel.substeps_changed.connect(lambda n: self.worker.set_substeps(n))
        self.scene_panel.spawn_requested.connect(self._spawn_particles)
        self.scene_panel.stress_requested.connect(self._stress_test)
        self.scene_panel.clear_requested.connect(self._clear_scene)
        self.scene_panel.spatial_hash_changed.connect(self.world.set_spatial_hash)

    def _start_physics(self) -> None:
        self.thread = QThread(self)
        self.worker = SimulationWorker(self.world)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.stats.connect(lambda p: setattr(self, "_physics_stats", p))
        self.worker.set_paused(self._paused)
        self.thread.start()

    def _on_tick(self) -> None:
        self.view.refresh_selection()
        self.view.update()
        self.properties.update_live()
        self._render_frames += 1
        now = time.perf_counter()
        if now - self._render_last >= 0.5:
            self._render_fps = self._render_frames / (now - self._render_last)
            self._render_frames = 0
            self._render_last = now
            self._update_statusbar()

    def _update_statusbar(self) -> None:
        with self.world.lock:
            b, p, c = self.world.body_count, self.world.particle_count, self.world.contact_count
        st = self._physics_stats
        self.lbl_fps.setText(f"FPS: {self._render_fps:.0f} | физ: {st['steps_per_sec']:.0f} шаг/с")
        self.lbl_bodies.setText(f"Тел: {b} (частиц: {p})")
        self.lbl_contacts.setText(f"Контактов: {c}")
        self.scene_panel.set_info(b, p)

    def _set_tool(self, tool: Tool) -> None:
        self.view.set_tool(tool)
        if btn := self._tool_buttons.get(tool):
            btn.setChecked(True)

    def _toggle_pause(self) -> None:
        self._paused = not self._paused
        self.worker.set_paused(self._paused)
        self.btn_play.setChecked(not self._paused)
        self.btn_play.setText("⏸" if not self._paused else "▶")

    def _step_once(self) -> None:
        self.worker.request_single_step()
        if not self._paused:
            self._toggle_pause()

    def _reset_scene(self) -> None:
        if QMessageBox.question(self, "Сброс", "Очистить сцену?", QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            self._push_undo()
            self._clear_scene()

    def _clear_scene(self) -> None:
        with self.world.lock:
            self.world.clear()
        self.view.set_selection(None)
        self._on_scene_modified()

    def _delete_selected(self) -> None:
        if rec := self.view.selection:
            self._push_undo()
            with self.world.lock:
                self.world.remove_record(rec)
            self.view.set_selection(None)
            self._on_scene_modified()

    def _spawn_particles(self, count: int) -> None:
        self._push_undo()
        with self.world.lock:
            self.world.spawn_particles(count, (40.0, 40.0, self.world.width - 40.0, 160.0))
        self._on_scene_modified()

    def _stress_test(self) -> None:
        self.scene_panel.chk_spatial.setChecked(True)
        self._push_undo()
        with self.world.lock:
            self.world.spawn_particles(2000, (40.0, 30.0, self.world.width - 40.0, 220.0), radius=4.0)
        self._on_scene_modified()

    def _load_demo(self, name: str) -> None:
        self._push_undo()
        with self.world.lock:
            load_demo(self.world, name)
        self.view.set_selection(None)
        self.scene_panel.sync_from_world(self.world)
        self.view.fit_scene()
        self._on_scene_modified()

    def _on_scene_modified(self) -> None:
        self.properties.set_record(self.view.selection)
        self.view.update()
        self._update_statusbar()

    def _push_undo(self) -> None:
        with self.world.lock:
            if self.world.body_count <= 2500:
                self._undo_stack.append(world_to_dict(self.world))
        if len(self._undo_stack) > 30:
            self._undo_stack.pop(0)

    def _undo(self) -> None:
        if self._undo_stack:
            with self.world.lock:
                apply_dict_to_world(self.world, self._undo_stack.pop())
            self.view.set_selection(None)
            self.scene_panel.sync_from_world(self.world)
            self._on_scene_modified()

    def _new_scene(self) -> None:
        if QMessageBox.question(self, "Новая сцена", "Очистить?", QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            self._push_undo()
            self._clear_scene()
            self._current_path = None
            self.setWindowTitle("Симулятор физики")

    def _open_scene(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Открыть", "", "JSON (*.json)")
        if path:
            try:
                self._push_undo()
                with self.world.lock:
                    load_scene(path, self.world)
                self._current_path = path
                self.setWindowTitle(f"Симулятор физики — {path}")
                self.view.set_selection(None)
                self.scene_panel.sync_from_world(self.world)
                self.view.fit_scene()
                self._on_scene_modified()
            except Exception as exc:
                QMessageBox.critical(self, "Ошибка", f"Не удалось загрузить:\n{exc}")

    def _save_scene(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить", "scene.json", "JSON (*.json)")
        if path:
            if not path.endswith(".json"): path += ".json"
            try:
                with self.world.lock:
                    save_scene(path, self.world)
                self._current_path = path
                self.setWindowTitle(f"Симулятор физики — {path}")
            except Exception as exc:
                QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить:\n{exc}")

    def _export_png(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт PNG", "scene.png", "PNG (*.png)")
        if path:
            if not path.endswith(".png"): path += ".png"
            export_screenshot(self.view, path)

    def _set_renderer_flag(self, attr: str, value: bool) -> None:
        setattr(self.view.renderer, attr, value)
        self.view.update()

    def _on_theme_toggled(self, checked: bool) -> None:
        self._dark_theme = checked
        self._apply_theme()
        self.settings.setValue("dark_theme", checked)

    def _apply_theme(self) -> None:
        self.setStyleSheet(build_stylesheet(self._dark_theme))
        self.act_dark.setChecked(self._dark_theme)
        self.view.renderer.background = QColor("#181825" if self._dark_theme else "#FAFAFF")
        self.view.update()

    def _show_help(self) -> None:
        QMessageBox.information(self, "Помощь", "Space — пауза\nCtrl+Z — отмена\nDel — удалить\nF — вписать сцену\nКолесо — зум")

    def closeEvent(self, event) -> None:
        try:
            self.worker.stop()
            self.thread.quit()
            self.thread.wait(3000)
        except Exception:
            pass
        super().closeEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.matches(QKeySequence.Undo):
            self._undo()
            return
        if event.key() == Qt.Key_Delete:
            self._delete_selected()
            return
        hotkeys = {Qt.Key_V: Tool.SELECT, Qt.Key_G: Tool.DRAG, Qt.Key_C: Tool.CIRCLE, Qt.Key_B: Tool.BOX, Qt.Key_P: Tool.POLY, Qt.Key_L: Tool.SEGMENT, Qt.Key_R: Tool.PLATFORM, Qt.Key_T: Tool.THROW, Qt.Key_X: Tool.DELETE, Qt.Key_H: Tool.PAN}
        if event.key() in hotkeys:
            self._set_tool(hotkeys[event.key()])
            return
        super().keyPressEvent(event)

# =============================================================================
# 11. ЗАПУСК
# =============================================================================
def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Physics Sandbox")
    app.setOrganizationName("PhysicsSandbox")
    app.setStyle("Fusion")

    def excepthook(exc_type, exc_value, exc_tb):
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        print(text)
        QMessageBox.critical(None, "Ошибка", f"Произошла ошибка:\n{exc_value}")

    sys.excepthook = excepthook
    window = MainWindow()
    window.show()
    return app.exec()

if __name__ == "__main__":
    raise SystemExit(main())