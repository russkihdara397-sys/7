# -*- coding: utf-8 -*-
"""
Десктопное приложение: симулятор передачи изображения по сети.

Изменения в этой версии (по замечаниям):
  • Имя файла — крупным жирным шрифтом с цветовым статусом (серый → зелёный).
  • Ползунки получили дискретные деления (tickinterval) и метки значений.
  • Подсказки к параметрам вынесены в отдельные «инфо-блоки» с фоном и рамкой.
  • Кнопка запуска — tk.Button (не ttk), текст гарантированно виден; при работе
    меняет текст на «Идёт расчёт…» и цвет.
  • Статистика расположена непосредственно под изображениями «было/стало».
  • Единицы измерения перенесены в подписи полей, отдельной колонки нет.
  • Добавлен цветной индикатор состояния (idle/ready/busy/error),
    прогресс-бар, смена курсора, блокировка контролов во время расчёта.
  • Поле ввода скорости валидируется (только целые числа).
"""

import os
import random
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from math import comb

from PIL import Image, ImageTk


# ---------------------------------------------------------------------------
# Константы и вспомогательные таблицы
# ---------------------------------------------------------------------------

POPCOUNT = [bin(i).count("1") for i in range(256)]

MASKS_BY_POPCOUNT = [[] for _ in range(9)]
for _mask in range(256):
    MASKS_BY_POPCOUNT[POPCOUNT[_mask]].append(_mask)

DEFAULT_PACKET_SIZE = 1024
DISPLAY_MAX_SIZE = (360, 360)

# Подсказки под каждым ползунком (показываются в отдельном информационном блоке).
PARAM_HINTS = {
    "bit_error": ("0 % — байты передаются без искажений. "
                  "100 % — инвертируется каждый бит (негатив изображения)."),
    "speed":     ("Условная скорость канала. Влияет только на оценку "
                  "времени передачи; на само изображение не влияет."),
    "loss":      ("0 % — все пакеты доходят. "
                  "100 % — теряются все (получится чёрное изображение)."),
}


# ---------------------------------------------------------------------------
# Логика симуляции (функции не зависят от GUI)
# ---------------------------------------------------------------------------

def split_into_packets(raw_data: bytes, packet_size: int) -> list:
    """
    Разбивает поток байт на пакеты фиксированного размера.

    Параметры:
        raw_data    — байты изображения (image.tobytes());
        packet_size — размер пакета в байтах (> 0).

    Возвращает:
        Список пакетов (bytes). Последний может быть короче.
    """
    if packet_size <= 0:
        raise ValueError("Размер пакета должен быть положительным числом")
    return [raw_data[i:i + packet_size]
            for i in range(0, len(raw_data), packet_size)]


def apply_bit_errors(packet: bytes, bit_error_prob: float,
                     rng: random.Random) -> tuple:
    """
    Имитирует битовые ошибки в одном пакете.

    Как именно происходит инверсия битов:
      • Для каждого байта разыгрывается число k инвертируемых битов
        по биномиальному закону Binomial(8, bit_error_prob).
      • При k > 0 из списка MASKS_BY_POPCOUNT[k] выбирается случайная
        8-битная маска ровно с k единицами.
      • Байт заменяется на (исходный ^ mask). XOR с единицей инвертирует
        бит, с нулём — оставляет без изменений.

    Возвращает:
        (новый_пакет, количество_инвертированных_битов).
    """
    if bit_error_prob <= 0.0:
        return packet, 0
    if bit_error_prob >= 1.0:
        inverted = bytes(b ^ 0xFF for b in packet)
        return inverted, len(packet) * 8

    probs = [
        comb(8, k) * (bit_error_prob ** k) * ((1.0 - bit_error_prob) ** (8 - k))
        for k in range(9)
    ]
    cumulative, acc = [], 0.0
    for pr in probs:
        acc += pr
        cumulative.append(acc)
    cumulative[-1] = 1.0

    out = bytearray(packet)
    flipped_total = 0
    for i in range(len(out)):
        u = rng.random()
        k = 0
        while k < 8 and u > cumulative[k]:
            k += 1
        if k == 0:
            continue
        mask = rng.choice(MASKS_BY_POPCOUNT[k])
        out[i] ^= mask
        flipped_total += k

    return bytes(out), flipped_total


def simulate_transmission(image: Image.Image,
                          packet_size: int = DEFAULT_PACKET_SIZE,
                          loss_percent: float = 0.0,
                          bit_error_percent: float = 0.0,
                          speed: float = 100.0,
                          rng: random.Random = None,
                          progress_callback=None) -> tuple:
    """
    Полная модель передачи изображения.

    Параметры:
        image, packet_size, loss_percent, bit_error_percent, speed — настройки;
        rng                — генератор случайных чисел;
        progress_callback  — функция(done, total) для GUI-прогресса.

    Возвращает:
        (corrupted_image, stats: dict).
    """
    if rng is None:
        rng = random.Random()

    if not (0.0 <= loss_percent <= 100.0):
        raise ValueError("Процент потери пакетов должен быть 0..100")
    if not (0.0 <= bit_error_percent <= 100.0):
        raise ValueError("Процент ошибочных битов должен быть 0..100")
    if speed <= 0:
        raise ValueError("Скорость сети должна быть положительной")

    raw = image.tobytes()
    total_bytes = len(raw)
    packets = split_into_packets(raw, packet_size)
    total_packets = len(packets)

    loss_prob = loss_percent / 100.0
    bit_prob = bit_error_percent / 100.0

    reconstructed = bytearray(total_bytes)

    lost_packets = 0
    delivered_packets = 0
    clean_packets = 0
    bits_flipped_total = 0
    step = max(1, total_packets // 100)

    for idx, packet in enumerate(packets):
        if rng.random() < loss_prob:
            lost_packets += 1
        else:
            delivered_packets += 1
            corrupted_packet, flips = apply_bit_errors(packet, bit_prob, rng)
            bits_flipped_total += flips
            if flips == 0:
                clean_packets += 1
            start = idx * packet_size
            reconstructed[start:start + len(corrupted_packet)] = corrupted_packet

        if progress_callback and (idx % step == 0 or idx == total_packets - 1):
            progress_callback(idx + 1, total_packets)

    corrupted_image = Image.frombytes(image.mode, image.size, bytes(reconstructed))

    delivered_percent = (delivered_packets / total_packets * 100.0) if total_packets else 0.0
    clean_percent = (clean_packets / total_packets * 100.0) if total_packets else 0.0
    estimated_time = total_packets / speed if speed > 0 else float("inf")

    stats = {
        "packets_total": total_packets,
        "packets_lost": lost_packets,
        "packets_delivered": delivered_packets,
        "clean_packets": clean_packets,
        "bits_flipped": bits_flipped_total,
        "delivered_percent": delivered_percent,
        "clean_percent": clean_percent,
        "estimated_time_sec": estimated_time,
        "packet_size": packet_size,
        "total_bytes": total_bytes,
    }
    return corrupted_image, stats


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

class ImageTransmissionApp:
    """Графический интерфейс приложения."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Симулятор передачи изображения по сети")
        self.root.minsize(1140, 780)

        self.original_image = None
        self.corrupted_image = None
        self.original_photo = None
        self.corrupted_photo = None

        # Виджеты, блокируемые во время расчёта.
        self._lockable_widgets = []

        self._build_ui()
        self._set_status("Готово к работе", "idle")

    # ------------------------------------------------------------------
    # Построение интерфейса
    # ------------------------------------------------------------------
    def _build_ui(self):
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        self._build_file_bar(main)

        middle = ttk.Frame(main)
        middle.pack(fill=tk.BOTH, expand=True, pady=(10, 0))

        self._build_params(middle)              # левая колонка
        self._build_images_and_stats(middle)    # правая колонка (изображения + статистика под ними)

    # --- Верхняя панель: файл ---
    def _build_file_bar(self, parent):
        file_frame = ttk.LabelFrame(parent, text="Файл", padding=8)
        file_frame.pack(fill=tk.X)

        self.load_btn = ttk.Button(file_frame, text="Выбрать изображение...",
                                   command=self.load_image)
        self.load_btn.pack(side=tk.LEFT)
        self._lockable_widgets.append(self.load_btn)

        # Крупная жирная метка: серая до загрузки, зелёная после.
        self.file_label = ttk.Label(
            file_frame,
            text="Файл не выбран",
            foreground="#999999",
            font=("TkDefaultFont", 12, "bold"),
        )
        self.file_label.pack(side=tk.LEFT, padx=(16, 0))

    # --- Левая колонка: параметры, кнопки, индикатор состояния ---
    def _build_params(self, parent):
        params = ttk.LabelFrame(parent, text="Параметры передачи", padding=10)
        params.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 12))

        # Единицы измерения — уже в подписи (в скобках), отдельной колонки нет.
        self._build_param_row(params, "Процент ошибочных битов, %",
                              "bit_error", 0.0, 100.0, 0.1, 0.0, tickinterval=20)
        self._build_param_row(params, "Скорость сети, пакетов/с",
                              "speed", 1, 1000, 1, 100, tickinterval=200)
        self._build_param_row(params, "Потери пакетов, %",
                              "loss", 0.0, 100.0, 0.1, 0.0, tickinterval=20)

        ttk.Separator(params, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(12, 10))

        # Кнопка «Запустить» — tk.Button с явными цветами, текст всегда виден.
        self.run_btn = tk.Button(
            params,
            text="▶   Запустить симуляцию",
            command=self.run_simulation,
            bg="#2e7d32", fg="white",
            activebackground="#1b5e20", activeforeground="white",
            disabledforeground="white",
            font=("TkDefaultFont", 11, "bold"),
            relief=tk.RAISED, bd=2, padx=10, pady=6, cursor="hand2",
        )
        self.run_btn.pack(fill=tk.X, pady=(0, 8))

        # Кнопка «Сохранить» — обычная, без акцента.
        self.save_btn = ttk.Button(params, text="Сохранить искажённое...",
                                   command=self.save_corrupted, state=tk.DISABLED)
        self.save_btn.pack(fill=tk.X)

        # Индикатор состояния: цветной кружок + текст.
        status_frame = ttk.Frame(params)
        status_frame.pack(fill=tk.X, pady=(14, 0))

        self.status_dot = tk.Label(status_frame, text="●",
                                   fg="#888888",
                                   font=("TkDefaultFont", 16))
        self.status_dot.pack(side=tk.LEFT)

        self.status_label = ttk.Label(status_frame, text="",
                                      font=("TkDefaultFont", 9))
        self.status_label.pack(side=tk.LEFT, padx=(6, 0), anchor="w")

        # Прогресс-бар.
        self.progress = ttk.Progressbar(params, mode="determinate")
        self.progress.pack(fill=tk.X, pady=(10, 0))

    def _build_param_row(self, parent, label_text, name,
                         from_, to, resolution, default, tickinterval=10):
        """Одна строка параметра: подпись, ползунок с делениями, поле ввода, подсказка."""
        ttk.Label(parent, text=label_text,
                  font=("TkDefaultFont", 10, "bold")).pack(anchor="w", pady=(10, 2))

        row = ttk.Frame(parent)
        row.pack(fill=tk.X)
        row.columnconfigure(0, weight=1)

        # Тип значения: IntVar для скорости, DoubleVar для остальных.
        is_int = isinstance(default, int) and resolution >= 1
        var = tk.IntVar(value=default) if is_int else tk.DoubleVar(value=default)
        setattr(self, f"{name}_var", var)

        entry_var = tk.StringVar()
        setattr(self, f"{name}_entry_var", entry_var)

        # Валидация: скорость — только целые; остальные — числа с одной точкой.
        vcmd = (self.root.register(
            self._make_int_validator() if is_int else self._make_float_validator()
        ), "%P")

        # Ползунок с делениями — занимает всю ширину строки.
        slider = tk.Scale(
            row, from_=from_, to=to, resolution=resolution,
            orient=tk.HORIZONTAL, variable=var, showvalue=False,
            highlightthickness=0,
            tickinterval=tickinterval,     # ← дискретные деления с метками
            sliderlength=14, width=12,
        )
        slider.grid(row=0, column=0, sticky="nsew")
        setattr(self, f"{name}_slider", slider)
        self._lockable_widgets.append(slider)

        # Поле ввода — справа сверху, валидируется на лету.
        entry = ttk.Entry(
            row, width=7, justify=tk.RIGHT, textvariable=entry_var,
            validate="key", validatecommand=vcmd,
        )
        entry.grid(row=0, column=1, padx=(8, 0), sticky="ne")
        setattr(self, f"{name}_entry", entry)
        self._lockable_widgets.append(entry)

        # --- Двусторонняя синхронизация var ↔ entry_var ---
        def _fmt(v):
            return str(int(round(v))) if is_int else f"{v:.1f}"

        def _on_var_changed(*_):
            entry_var.set(_fmt(var.get()))

        var.trace_add("write", _on_var_changed)
        _on_var_changed()

        def _commit_entry(event=None):
            raw = entry_var.get().strip().replace(",", ".")
            try:
                val = int(round(float(raw))) if is_int else float(raw)
            except ValueError:
                _on_var_changed()
                return
            val = max(from_, min(to, val))
            var.set(val)
            _on_var_changed()

        entry.bind("<Return>", _commit_entry)
        entry.bind("<FocusOut>", _commit_entry)

        # --- Информационный блок подсказки (с фоном и рамкой) ---
        hint_box = tk.Label(
            parent,
            text="ⓘ  " + PARAM_HINTS[name],
            bg="#f0f4f8", fg="#2c3e50",
            font=("TkDefaultFont", 9),
            wraplength=290, justify=tk.LEFT, anchor="w",
            padx=8, pady=6,
            relief=tk.SOLID, bd=1, highlightthickness=0,
        )
        hint_box.pack(fill=tk.X, pady=(4, 0))

    # --- Валидаторы ввода ---
    @staticmethod
    def _make_int_validator():
        def _v(proposed: str) -> bool:
            if proposed == "":
                return True
            return proposed.isdigit()
        return _v

    @staticmethod
    def _make_float_validator():
        def _v(proposed: str) -> bool:
            if proposed == "":
                return True
            if proposed.count(".") > 1:
                return False
            return proposed.replace(".", "", 1).isdigit()
        return _v

    # --- Правая колонка: изображения и статистика под ними ---
    def _build_images_and_stats(self, parent):
        right = ttk.Frame(parent)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)

        images = ttk.Frame(right)
        images.grid(row=0, column=0, sticky="nsew")
        images.columnconfigure(0, weight=1)
        images.columnconfigure(1, weight=1)
        images.rowconfigure(0, weight=1)

        orig_frame = ttk.LabelFrame(images, text="Исходное изображение", padding=5)
        orig_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        self.original_label = ttk.Label(orig_frame, text="(не загружено)",
                                        foreground="#888888")
        self.original_label.pack(fill=tk.BOTH, expand=True)

        corr_frame = ttk.LabelFrame(images, text="После симуляции передачи", padding=5)
        corr_frame.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        self.corrupted_label = ttk.Label(corr_frame, text="(нет результата)",
                                         foreground="#888888")
        self.corrupted_label.pack(fill=tk.BOTH, expand=True)

        # Статистика — прямо под изображениями, «привязана» к паре было/стало.
        stats_frame = ttk.LabelFrame(right, text="Статистика передачи", padding=8)
        stats_frame.grid(row=1, column=0, sticky="ew", pady=(10, 0))

        self.stats_text = tk.Text(
            stats_frame, height=7, wrap=tk.WORD,
            state=tk.DISABLED, relief=tk.FLAT,
            background=self.root.cget("background"),
            font=("TkFixedFont", 9),
        )
        self.stats_text.pack(fill=tk.X)

    # ------------------------------------------------------------------
    # Загрузка изображения
    # ------------------------------------------------------------------
    def load_image(self):
        path = filedialog.askopenfilename(
            title="Выберите изображение",
            filetypes=[
                ("Изображения", "*.png *.jpg *.jpeg *.bmp"),
                ("Все файлы", "*.*"),
            ],
        )
        if not path:
            return

        try:
            img = Image.open(path)
            img.load()
            if img.mode != "RGB":
                img = img.convert("RGB")
        except Exception as exc:
            messagebox.showerror("Ошибка", f"Не удалось открыть файл:\n{exc}")
            self._set_status("Ошибка загрузки файла", "error")
            return

        self.original_image = img
        self.corrupted_image = None

        # Имя файла — крупно и зелёным (успешная загрузка).
        name = os.path.basename(path)
        self.file_label.configure(text=f"Выбран файл:  {name}", foreground="#2e7d32")

        self._show_image(img, self.original_label, is_original=True)
        self.corrupted_label.configure(image="", text="(нет результата)",
                                       foreground="#888888")
        self.corrupted_photo = None
        self.save_btn.configure(state=tk.DISABLED)
        self.progress["value"] = 0
        self._set_stats("Изображение загружено. Настройте параметры "
                        "и нажмите «Запустить симуляцию».")
        self._set_status(f"Изображение готово: {name}", "ok")

    # ------------------------------------------------------------------
    # Отображение
    # ------------------------------------------------------------------
    def _show_image(self, image: Image.Image, label: ttk.Label, is_original: bool):
        display = image.copy()
        display.thumbnail(DISPLAY_MAX_SIZE, Image.LANCZOS)
        photo = ImageTk.PhotoImage(display)
        label.configure(image=photo, text="")
        if is_original:
            self.original_photo = photo
        else:
            self.corrupted_photo = photo

    # ------------------------------------------------------------------
    # Симуляция
    # ------------------------------------------------------------------
    def run_simulation(self):
        if self.original_image is None:
            messagebox.showwarning("Внимание", "Сначала выберите изображение.")
            return

        try:
            loss = float(self.loss_var.get())
            bit_err = float(self.bit_error_var.get())
            speed = float(self.speed_var.get())
        except (tk.TclError, ValueError):
            messagebox.showerror("Ошибка", "Некорректные значения параметров.")
            return

        if not (0.0 <= loss <= 100.0):
            messagebox.showerror("Ошибка", "Потери пакетов должны быть 0..100%.")
            return
        if not (0.0 <= bit_err <= 100.0):
            messagebox.showerror("Ошибка", "Процент ошибочных битов должен быть 0..100%.")
            return
        if not (1.0 <= speed <= 1000.0):
            messagebox.showerror("Ошибка", "Скорость сети должна быть 1..1000 пакетов/с.")
            return

        self._set_busy(True)
        self.progress["value"] = 0

        def progress_callback(done, total):
            self.progress["maximum"] = total
            self.progress["value"] = done
            self._set_status(f"Обработка пакетов: {done} / {total}", "busy")
            self.root.update_idletasks()

        try:
            corrupted, stats = simulate_transmission(
                self.original_image,
                packet_size=DEFAULT_PACKET_SIZE,
                loss_percent=loss,
                bit_error_percent=bit_err,
                speed=speed,
                progress_callback=progress_callback,
            )
        except Exception as exc:
            self._set_busy(False)
            self._set_status("Ошибка симуляции", "error")
            messagebox.showerror("Ошибка симуляции", str(exc))
            return

        self.corrupted_image = corrupted
        self._show_image(corrupted, self.corrupted_label, is_original=False)
        self._set_busy(False)
        self._display_stats(stats)

    def _display_stats(self, stats: dict):
        text = (
            f"Размер пакета: {stats['packet_size']} байт   "
            f"|   Всего байт изображения: {stats['total_bytes']}\n"
            f"Пакетов отправлено: {stats['packets_total']}   "
            f"|   потеряно: {stats['packets_lost']}   "
            f"|   доставлено: {stats['packets_delivered']} "
            f"({stats['delivered_percent']:.2f}%)\n"
            f"Пакетов без единой битовой ошибки: {stats['clean_packets']} "
            f"({stats['clean_percent']:.2f}% от отправленных)\n"
            f"Битов инвертировано: {stats['bits_flipped']}\n"
            f"Оценочное время передачи: {stats['estimated_time_sec']:.3f} с\n\n"
            "Примечание: «пакет без ошибок» — доставленный пакет, в котором\n"
            "не инвертирован ни один бит. При большом проценте битовых ошибок\n"
            "этот показатель может быть 0% даже при 100% доставке."
        )
        self._set_stats(text)

    # ------------------------------------------------------------------
    # Сохранение
    # ------------------------------------------------------------------
    def save_corrupted(self):
        if self.corrupted_image is None:
            messagebox.showwarning("Внимание", "Сначала запустите симуляцию.")
            return

        path = filedialog.asksaveasfilename(
            title="Сохранить искажённое изображение",
            defaultextension=".png",
            filetypes=[("PNG", "*.png")],
        )
        if not path:
            return

        try:
            self.corrupted_image.save(path, format="PNG")
        except Exception as exc:
            messagebox.showerror("Ошибка", f"Не удалось сохранить файл:\n{exc}")
            self._set_status("Ошибка сохранения", "error")
            return

        self._set_status(f"Сохранено: {os.path.basename(path)}", "ok")
        messagebox.showinfo("Готово", f"Изображение сохранено:\n{path}")

    # ------------------------------------------------------------------
    # Состояния и индикация
    # ------------------------------------------------------------------
    def _set_busy(self, busy: bool):
        """Блокирует/разблокирует контролы и меняет состояние индикаторов."""
        state = tk.DISABLED if busy else tk.NORMAL
        for w in self._lockable_widgets:
            try:
                w.configure(state=state)
            except tk.TclError:
                pass

        if busy:
            self.save_btn.configure(state=tk.DISABLED)
            self.run_btn.configure(text="⏳   Идёт расчёт...",
                                   state=tk.DISABLED, bg="#7f8c8d")
            self.root.configure(cursor="watch")
            self._set_status("Выполняется симуляция...", "busy")
        else:
            self.run_btn.configure(text="▶   Запустить симуляцию",
                                   state=tk.NORMAL, bg="#2e7d32")
            self.root.configure(cursor="")
            if self.corrupted_image is not None:
                self.save_btn.configure(state=tk.NORMAL)
                self._set_status("Симуляция завершена", "ok")
            else:
                self._set_status("Готово к работе", "idle")

    def _set_status(self, text: str, kind: str = "idle"):
        """
        Обновляет текстовый статус и цвет кружка-индикатора.
        kind: idle | ok | busy | error
        """
        colors = {
            "idle":  "#888888",  # серый  — ничего не происходит
            "ok":    "#2e7d32",  # зелёный — успех
            "busy":  "#f9a825",  # жёлтый  — идёт работа
            "error": "#c62828",  # красный — ошибка
        }
        self.status_dot.configure(fg=colors.get(kind, "#888888"))
        self.status_label.configure(text=text)

    def _set_stats(self, text: str):
        self.stats_text.configure(state=tk.NORMAL)
        self.stats_text.delete("1.0", tk.END)
        self.stats_text.insert(tk.END, text)
        self.stats_text.configure(state=tk.DISABLED)


# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------

def main():
    root = tk.Tk()
    app = ImageTransmissionApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()