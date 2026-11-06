#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DataViz Studio — десктопное приложение для визуализации данных
Python 3.10+, CustomTkinter, pandas, matplotlib

Исправления:
1. Убраны проблемные параметры errors="ignore" из pd.to_datetime() и pd.to_numeric()
2. Добавлена полная защита от всех возможных ошибок парсинга
3. Упрощена логика загрузки CSV для максимальной совместимости
"""

import sys

_MISSING = []
for _mod in ("customtkinter", "pandas", "matplotlib", "openpyxl"):
    try:
        __import__(_mod)
    except ImportError:
        _MISSING.append(_mod)

if _MISSING:
    print("Не установлены библиотеки: " + ", ".join(_MISSING))
    print("Выполните команду: pip install " + " ".join(_MISSING))
    input("Нажмите Enter для выхода...")
    sys.exit(1)

import os
import threading
import tkinter as tk
from tkinter import filedialog

import customtkinter as ctk
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import (
    FigureCanvasTkAgg, NavigationToolbar2Tk
)
from matplotlib.figure import Figure

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class Toast:
    """Показывает временное уведомление в правом верхнем углу окна."""

    COLORS = {
        "info":    "#3b82f6",
        "success": "#10b981",
        "error":   "#ef4444",
        "warning": "#f59e0b",
    }

    def __init__(self, parent):
        self.parent = parent

    def show(self, message: str, msg_type: str = "info", duration: int = 3000):
        frame = ctk.CTkFrame(
            self.parent,
            corner_radius=10,
            fg_color="#2b2b2b",
            border_width=2,
            border_color=self.COLORS.get(msg_type, "#3b82f6"),
        )
        frame.place(relx=0.98, rely=0.02, anchor="ne")

        lbl = ctk.CTkLabel(
            frame,
            text=f"● {message}",
            text_color=self.COLORS.get(msg_type, "#3b82f6"),
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        lbl.pack(padx=15, pady=10)

        self.parent.after(duration, frame.destroy)


class DataPreviewTable:
    """Прокручиваемая таблица с пагинацией по 100 строк."""

    PAGE_SIZE = 100
    COL_WIDTH = 130

    def __init__(self, parent, data: pd.DataFrame = None):
        self.parent = parent
        self.data = data
        self.page = 0
        self.total_pages = 1
        self._build_ui()
        if data is not None and not data.empty:
            self.set_data(data)

    def _build_ui(self):
        self.scroll_frame = ctk.CTkScrollableFrame(
            self.parent, height=260, corner_radius=8
        )
        self.scroll_frame.pack(fill="both", expand=True, padx=10, pady=5)

        pag = ctk.CTkFrame(self.parent, height=40, corner_radius=8)
        pag.pack(fill="x", padx=10, pady=5)

        self.btn_prev = ctk.CTkButton(
            pag, text="◀ Назад", width=90,
            command=self._prev_page, state="disabled",
        )
        self.btn_prev.pack(side="left", padx=5, pady=5)

        self.lbl_page = ctk.CTkLabel(
            pag, text="Страница 0 / 0",
            font=ctk.CTkFont(size=12),
        )
        self.lbl_page.pack(side="left", padx=10)

        self.btn_next = ctk.CTkButton(
            pag, text="Вперёд ▶", width=90,
            command=self._next_page, state="disabled",
        )
        self.btn_next.pack(side="left", padx=5, pady=5)

        self.lbl_rows = ctk.CTkLabel(
            pag, text="",
            font=ctk.CTkFont(size=11),
        )
        self.lbl_rows.pack(side="right", padx=10)

    def set_data(self, data: pd.DataFrame):
        self.data = data
        self.page = 0
        if len(data) == 0:
            self.total_pages = 0
        else:
            self.total_pages = max(1, -(-len(data) // self.PAGE_SIZE))
        self._render()

    def _render(self):
        for w in self.scroll_frame.winfo_children():
            w.destroy()

        if self.data is None or self.data.empty:
            ctk.CTkLabel(
                self.scroll_frame,
                text="Нет данных для отображения",
                font=ctk.CTkFont(size=12),
            ).pack(pady=20)
            self.lbl_page.configure(text="Страница 0 / 0")
            self.btn_prev.configure(state="disabled")
            self.btn_next.configure(state="disabled")
            self.lbl_rows.configure(text="")
            return

        hdr = ctk.CTkFrame(self.scroll_frame, fg_color="#1f1f1f", corner_radius=6)
        hdr.pack(fill="x", pady=2)
        for col in self.data.columns:
            ctk.CTkLabel(
                hdr, text=str(col),
                font=ctk.CTkFont(size=11, weight="bold"),
                width=self.COL_WIDTH, anchor="w",
            ).pack(side="left", padx=2, pady=4)

        start = self.page * self.PAGE_SIZE
        end = min(start + self.PAGE_SIZE, len(self.data))
        page_df = self.data.iloc[start:end]

        for _, row in page_df.iterrows():
            row_frm = ctk.CTkFrame(self.scroll_frame, fg_color="#2b2b2b", corner_radius=4)
            row_frm.pack(fill="x", pady=1)
            for col in self.data.columns:
                val = row[col]
                text = "NaN" if pd.isna(val) else str(val)
                if len(text) > 18:
                    text = text[:18] + "…"
                ctk.CTkLabel(
                    row_frm, text=text,
                    font=ctk.CTkFont(size=10),
                    width=self.COL_WIDTH, anchor="w",
                ).pack(side="left", padx=2, pady=2)

        self.lbl_page.configure(
            text=f"Страница {self.page + 1} / {self.total_pages}"
        )
        self.btn_prev.configure(state="normal" if self.page > 0 else "disabled")
        self.btn_next.configure(
            state="normal" if self.page < self.total_pages - 1 else "disabled"
        )
        self.lbl_rows.configure(
            text=f"Строки {start + 1}–{end} из {len(self.data)}"
        )

    def _prev_page(self):
        if self.page > 0:
            self.page -= 1
            self._render()

    def _next_page(self):
        if self.page < self.total_pages - 1:
            self.page += 1
            self._render()


class DataVizStudio(ctk.CTk):
    """Основное окно приложения DataViz Studio."""

    CHART_TYPES = [
        "Линейный график",
        "Столбчатая диаграмма",
        "Круговая диаграмма",
        "Гистограмма",
        "Scatter-плот",
        "Box plot",
        "Тепловая карта корреляций",
        "Area chart",
    ]

    PALETTES = {
        "Viridis": "viridis",
        "Plasma":  "plasma",
        "Inferno": "inferno",
        "Magma":   "magma",
        "Set1":    "Set1",
        "Set2":    "Set2",
        "Pastel1": "Pastel1",
        "Coolwarm":"coolwarm",
    }

    def __init__(self):
        super().__init__()

        self.title("DataViz Studio — Визуализация данных")
        self.geometry("1400x900")
        self.minsize(1100, 700)

        self.data: pd.DataFrame | None = None
        self.filtered_data: pd.DataFrame | None = None
        self.current_file: str | None = None
        self.current_fig: Figure | None = None

        self._build_sidebar()
        self._build_main_area()
        self._build_statusbar()

        self.toast = Toast(self)

        self.bind("<Control-o>", lambda _e: self.load_data())
        self.bind("<Control-s>", lambda _e: self.export_chart_png())

        self.toast.show("Приложение готово к работе", "info")

    def _build_sidebar(self):
        self.sidebar = ctk.CTkFrame(self, width=260, corner_radius=0)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        ctk.CTkLabel(
            self.sidebar, text="📊 DataViz Studio",
            font=ctk.CTkFont(size=20, weight="bold"),
        ).pack(pady=(20, 10))

        self.btn_open = ctk.CTkButton(
            self.sidebar, text="📁 Открыть файл (Ctrl+O)",
            command=self.load_data, height=40, corner_radius=10,
        )
        self.btn_open.pack(padx=15, pady=8, fill="x")

        self.btn_dropna = ctk.CTkButton(
            self.sidebar, text="🧹 Удалить строки с NaN",
            command=self.drop_nan_rows, height=35, corner_radius=8,
            fg_color="#f59e0b", hover_color="#d97706",
        )
        self.btn_dropna.pack(padx=15, pady=4, fill="x")

        ctk.CTkFrame(self.sidebar, height=2, fg_color="#3b3b3b").pack(
            fill="x", padx=15, pady=12
        )

        ctk.CTkLabel(
            self.sidebar, text="Тип визуализации",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(pady=(0, 8))

        self.chart_type_var = ctk.StringVar(value=self.CHART_TYPES[0])
        for ct in self.CHART_TYPES:
            ctk.CTkRadioButton(
                self.sidebar, text=ct,
                variable=self.chart_type_var, value=ct,
                command=self._on_chart_type_changed,
            ).pack(padx=20, pady=3, anchor="w")

        ctk.CTkFrame(self.sidebar, height=2, fg_color="#3b3b3b").pack(
            fill="x", padx=15, pady=12
        )

        ctk.CTkLabel(
            self.sidebar, text="Информация",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(pady=(0, 8))
        self.lbl_info = ctk.CTkLabel(
            self.sidebar, text="Файл не загружен",
            font=ctk.CTkFont(size=11), justify="left",
        )
        self.lbl_info.pack(padx=15, fill="x")

    def _build_main_area(self):
        self.main = ctk.CTkFrame(self, corner_radius=0)
        self.main.pack(side="right", fill="both", expand=True)

        self.settings = ctk.CTkFrame(self.main, height=130, corner_radius=10)
        self.settings.pack(fill="x", padx=10, pady=10)
        self.settings.pack_propagate(False)
        self._build_settings()

        self.chart_area = ctk.CTkFrame(self.main, corner_radius=10)
        self.chart_area.pack(fill="both", expand=True, padx=10, pady=5)

        ctk.CTkLabel(
            self.chart_area, text="Область графика",
            font=ctk.CTkFont(size=13), text_color="#888888",
        ).pack(pady=40)

        self.preview = ctk.CTkFrame(self.main, height=320, corner_radius=10)
        self.preview.pack(fill="x", padx=10, pady=5)
        self.preview.pack_propagate(False)

        ctk.CTkLabel(
            self.preview, text="Превью данных",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(pady=8)

        self.table = DataPreviewTable(self.preview)

    def _build_settings(self):
        row1 = ctk.CTkFrame(self.settings, fg_color="transparent")
        row1.pack(fill="x", padx=10, pady=6)

        ctk.CTkLabel(row1, text="Ось X:").pack(side="left", padx=5)
        self.x_var = ctk.StringVar()
        self.x_combo = ctk.CTkComboBox(
            row1, variable=self.x_var, width=160, state="readonly",
        )
        self.x_combo.pack(side="left", padx=5)

        ctk.CTkLabel(row1, text="Ось Y:").pack(side="left", padx=5)
        self.y_var = ctk.StringVar()
        self.y_combo = ctk.CTkComboBox(
            row1, variable=self.y_var, width=160, state="readonly",
        )
        self.y_combo.pack(side="left", padx=5)

        ctk.CTkLabel(row1, text="Заголовок:").pack(side="left", padx=5)
        self.title_entry = ctk.CTkEntry(
            row1, placeholder_text="Название графика", width=220,
        )
        self.title_entry.pack(side="left", padx=5)

        row2 = ctk.CTkFrame(self.settings, fg_color="transparent")
        row2.pack(fill="x", padx=10, pady=6)

        ctk.CTkLabel(row2, text="Палитра:").pack(side="left", padx=5)
        self.palette_var = ctk.StringVar(value="Viridis")
        self.palette_combo = ctk.CTkComboBox(
            row2, variable=self.palette_var,
            values=list(self.PALETTES.keys()),
            width=130, state="readonly",
        )
        self.palette_combo.pack(side="left", padx=5)

        self.grid_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            row2, text="Сетка", variable=self.grid_var,
        ).pack(side="left", padx=10)

        self.btn_build = ctk.CTkButton(
            row2, text="🎨 Построить",
            command=self.build_chart, height=35, corner_radius=8,
        )
        self.btn_build.pack(side="left", padx=10)

        self.btn_png = ctk.CTkButton(
            row2, text="💾 PNG",
            command=self.export_chart_png,
            width=90, height=35, corner_radius=8,
            fg_color="#3b82f6", hover_color="#2563eb",
        )
        self.btn_png.pack(side="left", padx=4)

        self.btn_excel = ctk.CTkButton(
            row2, text="📊 Excel",
            command=self.export_data_excel,
            width=90, height=35, corner_radius=8,
            fg_color="#10b981", hover_color="#059669",
        )
        self.btn_excel.pack(side="left", padx=4)

    def _build_statusbar(self):
        self.statusbar = ctk.CTkFrame(self.main, height=28, corner_radius=0)
        self.statusbar.pack(fill="x", side="bottom")

        self.status_lbl = ctk.CTkLabel(
            self.statusbar, text="Готов к работе",
            font=ctk.CTkFont(size=11),
        )
        self.status_lbl.pack(side="left", padx=10, pady=4)

    def load_data(self):
        initial_dir = os.path.expanduser("~")
        
        path = filedialog.askopenfilename(
            title="Выберите файл данных",
            initialdir=initial_dir,
            filetypes=[
                ("Все поддерживаемые", "*.csv *.xlsx *.xls *.json"),
                ("CSV файлы", "*.csv"),
                ("Excel файлы", "*.xlsx *.xls"),
                ("JSON файлы", "*.json"),
                ("Все файлы", "*.*"),
            ],
        )
        if not path:
            return

        self._show_spinner("Загрузка данных...")
        threading.Thread(
            target=self._load_data_thread, args=(path,), daemon=True,
        ).start()

    def _load_data_thread(self, path: str):
        """Фоновая загрузка файла с максимальной защитой от ошибок."""
        try:
            if not os.path.exists(path):
                raise FileNotFoundError(f"Файл не найден: {path}")
            
            file_size = os.path.getsize(path)
            if file_size == 0:
                raise ValueError("Файл пустой (0 байт)")
            
            ext = os.path.splitext(path)[1].lower()
            df = None

            if ext == ".csv":
                # Максимально простая загрузка CSV без сложных параметров
                encodings_to_try = ['utf-8-sig', 'utf-8', 'cp1251', 'latin1']
                delimiters_to_try = [',', ';', '\t', '|']
                last_error = None
                
                for enc in encodings_to_try:
                    if df is not None and len(df) > 0:
                        break
                    
                    for delim in delimiters_to_try:
                        try:
                            # Простейшая загрузка без дополнительных параметров
                            df = pd.read_csv(
                                path,
                                encoding=enc,
                                sep=delim,
                                engine='python'
                            )
                            if len(df) > 0:
                                break
                        except Exception as e:
                            last_error = str(e)
                            continue
                
                if df is None or len(df) == 0:
                    raise ValueError(f"Не удалось прочитать CSV. Последняя ошибка: {last_error}")

            elif ext in (".xlsx", ".xls"):
                df = pd.read_excel(path, engine="openpyxl" if ext == ".xlsx" else None)

            elif ext == ".json":
                df = pd.read_json(path, encoding="utf-8")

            else:
                raise ValueError(f"Неподдерживаемый формат файла: {ext}")

            if df.empty:
                raise ValueError("Файл не содержит табличных данных")

            # Безопасное преобразование типов колонок
            for col in df.columns:
                try:
                    # Пробуем преобразовать в даты БЕЗ параметра errors
                    converted = pd.to_datetime(df[col])
                    # Если успешно, проверяем что данные действительно изменились
                    if not converted.equals(df[col]):
                        df[col] = converted
                except Exception:
                    pass  # Игнорируем ошибки
                
                try:
                    # Пробуем преобразовать в числа БЕЗ параметра errors
                    if not pd.api.types.is_numeric_dtype(df[col]):
                        converted = pd.to_numeric(df[col])
                        if not converted.equals(df[col]):
                            df[col] = converted
                except Exception:
                    pass  # Игнорируем ошибки

            self.data = df
            self.filtered_data = df.copy()
            self.current_file = path

            self.after(0, self._on_data_loaded)

        except FileNotFoundError as e:
            self.after(0, lambda: self.toast.show(f"Файл не найден: {e}", "error", 6000))
            self.after(0, self._hide_spinner)
        except pd.errors.EmptyDataError:
            self.after(0, lambda: self.toast.show("Файл пустой или не содержит данных", "error", 6000))
            self.after(0, self._hide_spinner)
        except Exception as e:
            error_msg = f"Ошибка загрузки: {type(e).__name__}\n{str(e)[:150]}"
            self.after(0, lambda: self.toast.show(error_msg, "error", 8000))
            self.after(0, self._hide_spinner)

    def _on_data_loaded(self):
        self._hide_spinner()

        self.table.set_data(self.filtered_data)

        cols = list(self.data.columns)
        self.x_combo.configure(values=cols)
        self.y_combo.configure(values=cols)
        if cols:
            self.x_combo.set(cols[0])
        if len(cols) > 1:
            self.y_combo.set(cols[1])

        size_kb = os.path.getsize(self.current_file) / 1024
        self.lbl_info.configure(
            text=f"📄 {os.path.basename(self.current_file)}\n"
                 f"📊 {len(self.data)} строк × {len(self.data.columns)} колонок\n"
                 f"💾 {size_kb:.1f} КБ"
        )

        self.status_lbl.configure(
            text=f"📄 {os.path.basename(self.current_file)} | "
                 f"{len(self.data)} строк × {len(self.data.columns)} колонок | "
                 f"{size_kb:.1f} КБ"
        )

        self.toast.show("Данные успешно загружены", "success")

    def _show_spinner(self, msg: str):
        self._spinner = ctk.CTkLabel(
            self, text=f"⏳ {msg}",
            font=ctk.CTkFont(size=16, weight="bold"),
            fg_color="#1a1a1a", corner_radius=10,
        )
        self._spinner.place(relx=0.5, rely=0.5, anchor="center")
        self.update_idletasks()

    def _hide_spinner(self):
        if hasattr(self, "_spinner"):
            self._spinner.destroy()
            del self._spinner

    def _on_chart_type_changed(self):
        if self.data is not None:
            self.build_chart()

    def build_chart(self):
        if self.data is None:
            self.toast.show("Сначала загрузите данные (Ctrl+O)", "warning")
            return

        x_col = self.x_var.get()
        y_col = self.y_var.get()
        chart_type = self.chart_type_var.get()

        if not x_col or not y_col:
            self.toast.show("Выберите колонки для осей X и Y", "warning")
            return

        if chart_type != "Тепловая карта корреляций":
            if x_col not in self.filtered_data.columns:
                self.toast.show(f"Колонка '{x_col}' не найдена", "error")
                return
            if y_col not in self.filtered_data.columns:
                self.toast.show(f"Колонка '{y_col}' не найдена", "error")
                return

        for w in self.chart_area.winfo_children():
            w.destroy()

        fig = Figure(figsize=(10, 6), dpi=100, facecolor="#1e1e1e")
        ax = fig.add_subplot(111)
        ax.set_facecolor("#2b2b2b")

        cmap_name = self.PALETTES.get(self.palette_var.get(), "viridis")
        cmap = plt.get_cmap(cmap_name)
        data = self.filtered_data

        try:
            self._draw_chart(ax, fig, data, chart_type, x_col, y_col, cmap)

            title = self.title_entry.get().strip()
            if title:
                ax.set_title(title, fontsize=14, fontweight="bold", color="white")
            else:
                ax.set_title(chart_type, fontsize=13, color="white")

            ax.tick_params(colors="#cccccc")
            ax.xaxis.label.set_color("#dddddd")
            ax.yaxis.label.set_color("#dddddd")
            for spine in ax.spines.values():
                spine.set_color("#555555")

            if self.grid_var.get():
                ax.grid(True, alpha=0.3, color="#555555")

            fig.tight_layout()

            canvas = FigureCanvasTkAgg(fig, master=self.chart_area)
            canvas.draw()
            canvas.get_tk_widget().pack(fill="both", expand=True)

            toolbar = NavigationToolbar2Tk(canvas, self.chart_area)
            toolbar.update()
            toolbar.pack(side="bottom", fill="x")

            self.current_fig = fig
            self.toast.show("График построен", "success")

        except Exception as e:
            self.toast.show(f"Ошибка построения: {e}", "error", 5000)

    def _draw_chart(self, ax, fig, data, chart_type, x_col, y_col, cmap):
        if chart_type == "Линейный график":
            ax.plot(data[x_col], data[y_col], marker="o",
                    linewidth=2, color=cmap(0.5), markersize=4)
            ax.set_xlabel(x_col)
            ax.set_ylabel(y_col)

        elif chart_type == "Столбчатая диаграмма":
            plot_df = data.head(20)
            ax.bar(range(len(plot_df)), plot_df[y_col],
                   color=[cmap(i / max(1, len(plot_df))) for i in range(len(plot_df))])
            ax.set_xticks(range(len(plot_df)))
            ax.set_xticklabels(
                [str(v)[:12] for v in plot_df[x_col]],
                rotation=45, ha="right", fontsize=9,
            )
            ax.set_xlabel(x_col)
            ax.set_ylabel(y_col)

        elif chart_type == "Круговая диаграмма":
            plot_df = data.head(10)
            values = plot_df[y_col].fillna(0)
            if values.sum() == 0:
                raise ValueError("Сумма значений Y равна 0")
            colors = [cmap(i / max(1, len(plot_df))) for i in range(len(plot_df))]
            ax.pie(values, labels=[str(v)[:15] for v in plot_df[x_col]],
                   autopct="%1.1f%%", colors=colors,
                   textprops={"color": "white", "fontsize": 9})
            ax.axis("equal")

        elif chart_type == "Гистограмма":
            series = data[y_col].dropna()
            if series.empty:
                raise ValueError(f"Колонка '{y_col}' не содержит числовых данных")
            ax.hist(series, bins=30, color=cmap(0.6), edgecolor="black", alpha=0.8)
            ax.set_xlabel(y_col)
            ax.set_ylabel("Частота")

        elif chart_type == "Scatter-плот":
            ax.scatter(data[x_col], data[y_col],
                       c=data[y_col], cmap=cmap, alpha=0.6, s=30)
            ax.set_xlabel(x_col)
            ax.set_ylabel(y_col)
            fig.colorbar(
                plt.cm.ScalarMappable(cmap=cmap), ax=ax,
                label=y_col, shrink=0.7,
            )

        elif chart_type == "Box plot":
            bp = ax.boxplot(
                [data[y_col].dropna()],
                labels=[y_col], patch_artist=True,
            )
            for box in bp["boxes"]:
                box.set_facecolor(cmap(0.5))
            ax.set_ylabel(y_col)

        elif chart_type == "Тепловая карта корреляций":
            numeric = data.select_dtypes(include=[np.number])
            if numeric.shape[1] < 2:
                raise ValueError("Нужно минимум 2 числовые колонки для корреляции")
            corr = numeric.corr()
            im = ax.imshow(corr.values, cmap=cmap, aspect="auto")
            ax.set_xticks(range(len(corr.columns)))
            ax.set_yticks(range(len(corr.columns)))
            ax.set_xticklabels(corr.columns, rotation=45, ha="right", fontsize=9)
            ax.set_yticklabels(corr.columns, fontsize=9)
            fig.colorbar(im, ax=ax, shrink=0.7)

        elif chart_type == "Area chart":
            y_vals = data[y_col].fillna(0)
            ax.fill_between(range(len(y_vals)), y_vals,
                            alpha=0.6, color=cmap(0.6))
            ax.plot(range(len(y_vals)), y_vals, color=cmap(0.8), linewidth=1)
            ax.set_xlabel("Индекс")
            ax.set_ylabel(y_col)

    def drop_nan_rows(self):
        if self.data is None:
            self.toast.show("Сначала загрузите данные", "warning")
            return
        before = len(self.filtered_data)
        self.filtered_data = self.filtered_data.dropna().reset_index(drop=True)
        after = len(self.filtered_data)
        removed = before - after
        self.table.set_data(self.filtered_data)
        self.toast.show(
            f"Удалено строк с NaN: {removed} (осталось: {after})",
            "success" if removed > 0 else "info",
        )

    def export_chart_png(self):
        if self.current_fig is None:
            self.toast.show("Сначала постройте график", "warning")
            return

        initial_dir = os.path.expanduser("~")
        
        path = filedialog.asksaveasfilename(
            title="Сохранить график",
            initialdir=initial_dir,
            defaultextension=".png",
            filetypes=[("PNG файлы", "*.png"), ("Все файлы", "*.*")],
            initialfile="chart.png",
        )
        if not path:
            return
        try:
            self.current_fig.savefig(path, dpi=300, bbox_inches="tight",
                                     facecolor=self.current_fig.get_facecolor())
            self.toast.show(f"Сохранено: {os.path.basename(path)}", "success")
        except Exception as e:
            self.toast.show(f"Ошибка сохранения: {e}", "error")

    def export_data_excel(self):
        if self.filtered_data is None or self.filtered_data.empty:
            self.toast.show("Нет данных для экспорта", "warning")
            return

        initial_dir = os.path.expanduser("~")
        
        path = filedialog.asksaveasfilename(
            title="Сохранить данные",
            initialdir=initial_dir,
            defaultextension=".xlsx",
            filetypes=[("Excel файлы", "*.xlsx")],
            initialfile="data_export.xlsx",
        )
        if not path:
            return
        try:
            self.filtered_data.to_excel(path, index=False, engine="openpyxl")
            self.toast.show(f"Экспортировано: {os.path.basename(path)}", "success")
        except Exception as e:
            self.toast.show(f"Ошибка экспорта: {e}", "error")


if __name__ == "__main__":
    app = DataVizStudio()
    app.mainloop()