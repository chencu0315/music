from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import time
from dataclasses import dataclass


PYTHON_DIR = Path(sys.executable).resolve().parent
os.environ.setdefault("TCL_LIBRARY", str(PYTHON_DIR / "tcl" / "tcl8.6"))
os.environ.setdefault("TK_LIBRARY", str(PYTHON_DIR / "tcl" / "tk8.6"))


import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

from audio_backend import AudioClip, AudioFormatError, format_seconds, parse_time_text


try:
    import winsound
except ImportError:  # pragma: no cover
    winsound = None


ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


BG_MAIN = "#1a1b26"
PANEL_BG = "#24283b"
PANEL_BG_ALT = "#1d2132"
PANEL_BG_SOFT = "#171b29"
BORDER = "#343a55"
TEXT_MAIN = "#ecf0ff"
TEXT_MUTED = "#8b93b7"
ACCENT = "#00d0bf"
ACCENT_2 = "#00e5ff"
ACCENT_FILL = "#0f6760"
ACTIVE_TOOL_BG = "#183640"
HOVER_BG = "#2a3148"

RULER_TIMES = ["00:00", "00:15", "00:30", "00:45", "01:00", "01:15"]
PLACEHOLDER_PEAKS = [
    0.24,
    0.56,
    0.34,
    0.68,
    0.44,
    0.76,
    0.30,
    0.60,
    0.48,
    0.72,
    0.28,
    0.58,
    0.40,
    0.80,
    0.36,
    0.66,
    0.32,
    0.84,
    0.46,
    0.63,
    0.26,
    0.75,
    0.42,
    0.70,
    0.31,
    0.59,
    0.38,
    0.78,
    0.45,
    0.62,
    0.27,
    0.54,
]


@dataclass
class EditorState:
    clip: AudioClip | None
    selection_start: float
    selection_end: float
    is_dirty: bool


class AudioEditorApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()

        self.title("轻量级音频编辑器")
        self.geometry("1024x768")
        self.minsize(980, 720)
        self.configure(fg_color=BG_MAIN)

        self.clip: AudioClip | None = None
        self.selection_start_sec = 12.4
        self.selection_end_sec = 38.9

        self.undo_stack: list[EditorState] = []
        self.redo_stack: list[EditorState] = []

        self.file_summary_var = tk.StringVar(
            value="当前工程：未加载音频文件 · 当前已支持 WAV/MP3 导入导出、真实波形、播放、剪切与导出"
        )
        self.panel_subtitle_var = tk.StringVar(
            value="后续可在这里查看真实波形；当前默认显示连续波形占位示意"
        )
        self.status_var = tk.StringVar(value="最近动作：等待操作")
        self.start_time_var = tk.StringVar(value=format_seconds(self.selection_start_sec))
        self.end_time_var = tk.StringVar(value=format_seconds(self.selection_end_sec))
        self.play_time_var = tk.StringVar(value="00:12.4 - 00:38.9 / --:--")

        self.sidebar_buttons: dict[str, ctk.CTkButton] = {}
        self.ruler_labels: list[ctk.CTkLabel] = []
        self.wave_canvas: tk.Canvas | None = None
        self.play_button: ctk.CTkButton | None = None

        self._wave_redraw_job: str | None = None
        self._last_wave_size: tuple[int, int] = (0, 0)
        self._preview_file_path: Path | None = None
        self._playback_finish_job: str | None = None
        self._playback_progress_job: str | None = None
        self._playback_started_at: float | None = None
        self._playback_range: tuple[float, float] | None = None
        self._playhead_sec: float | None = None
        self._is_playing = False
        self._is_dirty = False
        self._selection_dragging = False
        self._selection_anchor_sec = 0.0
        self._selection_drag_mode: str | None = None
        self._handle_tolerance_px = 10

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build_top_bar()
        self._build_main_area()
        self._build_bottom_bar()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(120, self._maximize_window)

    def _maximize_window(self) -> None:
        try:
            self.state("zoomed")
        except tk.TclError:
            screen_w = self.winfo_screenwidth()
            screen_h = self.winfo_screenheight()
            self.geometry(f"{screen_w}x{screen_h}+0+0")

    def _build_top_bar(self) -> None:
        top_bar = ctk.CTkFrame(
            self,
            height=68,
            fg_color=PANEL_BG,
            corner_radius=0,
            border_width=1,
            border_color=BORDER,
        )
        top_bar.grid(row=0, column=0, sticky="ew")
        top_bar.grid_propagate(False)
        top_bar.grid_columnconfigure(1, weight=1)

        brand_frame = ctk.CTkFrame(top_bar, fg_color="transparent")
        brand_frame.grid(row=0, column=0, padx=(22, 16), pady=10, sticky="w")

        title_row = ctk.CTkFrame(brand_frame, fg_color="transparent")
        title_row.grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            title_row,
            text="●",
            text_color=ACCENT_2,
            font=ctk.CTkFont(size=14, weight="bold"),
        ).grid(row=0, column=0, padx=(0, 8))

        ctk.CTkLabel(
            title_row,
            text="轻量级音频编辑器",
            text_color=TEXT_MAIN,
            font=ctk.CTkFont(size=18, weight="bold"),
        ).grid(row=0, column=1, sticky="w")

        ctk.CTkLabel(
            brand_frame,
            text="CustomTkinter · 第一阶段后端已接入",
            text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=12),
        ).grid(row=1, column=0, sticky="w", padx=(22, 0))

        summary_frame = ctk.CTkFrame(
            top_bar,
            fg_color=PANEL_BG_ALT,
            corner_radius=14,
            border_width=1,
            border_color=BORDER,
        )
        summary_frame.grid(row=0, column=1, padx=8, pady=12, sticky="ew")
        summary_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            summary_frame,
            text=" 文件操作 ",
            text_color=ACCENT_2,
            fg_color="#162736",
            corner_radius=999,
            font=ctk.CTkFont(size=12, weight="bold"),
        ).grid(row=0, column=0, padx=(12, 10), pady=10)

        ctk.CTkLabel(
            summary_frame,
            textvariable=self.file_summary_var,
            text_color=TEXT_MUTED,
            anchor="w",
            font=ctk.CTkFont(size=12),
        ).grid(row=0, column=1, padx=(0, 14), pady=10, sticky="ew")

        ctk.CTkButton(
            top_bar,
            text="导入音频",
            command=self.handle_import_audio,
            height=42,
            corner_radius=12,
            fg_color=ACCENT,
            hover_color=ACCENT_2,
            text_color="#04161a",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).grid(row=0, column=2, padx=(12, 22), pady=12, sticky="e")

    def _build_main_area(self) -> None:
        main_area = ctk.CTkFrame(self, fg_color=BG_MAIN, corner_radius=0)
        main_area.grid(row=1, column=0, sticky="nsew")
        main_area.grid_columnconfigure(1, weight=1)
        main_area.grid_rowconfigure(0, weight=1)

        self._build_sidebar(main_area)
        self._build_workspace(main_area)

    def _build_sidebar(self, parent: ctk.CTkFrame) -> None:
        sidebar = ctk.CTkFrame(
            parent,
            width=156,
            fg_color=PANEL_BG,
            corner_radius=0,
            border_width=1,
            border_color=BORDER,
        )
        sidebar.grid(row=0, column=0, sticky="nsw")
        sidebar.grid_propagate(False)
        sidebar.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            sidebar,
            text="主编辑入口",
            text_color=TEXT_MUTED,
            anchor="w",
            font=ctk.CTkFont(size=12),
        ).grid(row=0, column=0, padx=14, pady=(18, 10), sticky="ew")

        tool_specs = [
            ("import", "导入音频", self.handle_import_audio),
            ("volume", "调整音量", self.handle_volume_adjust),
            ("speed", "变速", self.handle_speed_change),
            ("merge", "合并音频", self.handle_merge_audio),
        ]

        for row_index, (tool_key, label, command) in enumerate(tool_specs, start=1):
            button = ctk.CTkButton(
                sidebar,
                text=label,
                command=command,
                height=52,
                corner_radius=14,
                anchor="w",
                border_width=1,
                border_color=BORDER,
                fg_color=PANEL_BG_ALT,
                hover_color=HOVER_BG,
                text_color=TEXT_MAIN,
                font=ctk.CTkFont(size=14, weight="bold"),
            )
            button.grid(row=row_index, column=0, padx=12, pady=6, sticky="ew")
            self.sidebar_buttons[tool_key] = button

        self._set_active_tool("import")

    def _build_workspace(self, parent: ctk.CTkFrame) -> None:
        workspace = ctk.CTkFrame(parent, fg_color=BG_MAIN, corner_radius=0)
        workspace.grid(row=0, column=1, padx=22, pady=22, sticky="nsew")
        workspace.grid_rowconfigure(0, weight=1)
        workspace.grid_columnconfigure(0, weight=1)

        panel = ctk.CTkFrame(
            workspace,
            fg_color=PANEL_BG_ALT,
            corner_radius=20,
            border_width=1,
            border_color=BORDER,
        )
        panel.grid(row=0, column=0, sticky="nsew")
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_rowconfigure(2, weight=1)

        header = ctk.CTkFrame(panel, fg_color="transparent")
        header.grid(row=0, column=0, padx=20, pady=(18, 12), sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        title_group = ctk.CTkFrame(header, fg_color="transparent")
        title_group.grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            title_group,
            text="波形视图编辑区域",
            text_color=TEXT_MAIN,
            font=ctk.CTkFont(size=18, weight="bold"),
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            title_group,
            textvariable=self.panel_subtitle_var,
            text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=12),
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        ctk.CTkLabel(
            header,
            text="中央波形区会随着窗口尺寸自适应扩展",
            text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=12),
        ).grid(row=0, column=1, sticky="e")

        ruler = ctk.CTkFrame(panel, fg_color="transparent")
        ruler.grid(row=1, column=0, padx=20, sticky="ew")
        self.ruler_labels.clear()
        for index, tick in enumerate(RULER_TIMES):
            ruler.grid_columnconfigure(index, weight=1)
            label = ctk.CTkLabel(
                ruler,
                text=tick,
                text_color=TEXT_MUTED,
                font=ctk.CTkFont(size=12),
            )
            label.grid(row=0, column=index, sticky="w")
            self.ruler_labels.append(label)

        canvas_frame = ctk.CTkFrame(
            panel,
            fg_color=PANEL_BG_SOFT,
            corner_radius=18,
            border_width=1,
            border_color=BORDER,
        )
        canvas_frame.grid(row=2, column=0, padx=20, pady=16, sticky="nsew")
        canvas_frame.grid_rowconfigure(0, weight=1)
        canvas_frame.grid_columnconfigure(0, weight=1)

        self.wave_canvas = tk.Canvas(
            canvas_frame,
            bg=PANEL_BG_SOFT,
            highlightthickness=0,
            bd=0,
            relief="flat",
            cursor="crosshair",
        )
        self.wave_canvas.grid(row=0, column=0, sticky="nsew", padx=1, pady=1)
        self.wave_canvas.bind("<Configure>", self._schedule_wave_redraw)
        self.wave_canvas.bind("<Motion>", self._on_wave_canvas_motion)
        self.wave_canvas.bind("<Button-1>", self._on_wave_canvas_press)
        self.wave_canvas.bind("<B1-Motion>", self._on_wave_canvas_drag)
        self.wave_canvas.bind("<ButtonRelease-1>", self._on_wave_canvas_release)
        self.wave_canvas.bind("<Double-Button-1>", self._on_wave_canvas_double_click)

        footer = ctk.CTkFrame(panel, fg_color="transparent")
        footer.grid(row=3, column=0, padx=20, pady=(0, 16), sticky="ew")
        footer.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            footer,
            text="提示：当前支持 WAV/MP3 导入导出；真实波形、修剪导出、剪切、手柄拖拽与撤销/重做已可使用。",
            text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=12),
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            footer,
            textvariable=self.status_var,
            text_color=TEXT_MUTED,
            anchor="e",
            font=ctk.CTkFont(size=12),
        ).grid(row=0, column=1, sticky="e")

    def _build_bottom_bar(self) -> None:
        bottom_bar = ctk.CTkFrame(
            self,
            height=104,
            fg_color=PANEL_BG,
            corner_radius=0,
            border_width=1,
            border_color=BORDER,
        )
        bottom_bar.grid(row=2, column=0, sticky="ew")
        bottom_bar.grid_propagate(False)
        bottom_bar.grid_columnconfigure(1, weight=1)

        play_group = ctk.CTkFrame(bottom_bar, fg_color="transparent")
        play_group.grid(row=0, column=0, padx=(22, 14), pady=16, sticky="w")

        self.play_button = ctk.CTkButton(
            play_group,
            text="播放",
            command=self.handle_play,
            width=54,
            height=54,
            corner_radius=27,
            fg_color=ACCENT,
            hover_color=ACCENT_2,
            text_color="#021316",
            font=ctk.CTkFont(size=14, weight="bold"),
        )
        self.play_button.grid(row=0, column=0, rowspan=2, sticky="w")

        ctk.CTkLabel(
            play_group,
            text="预览播放",
            text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=12),
        ).grid(row=0, column=1, padx=(12, 0), sticky="sw")

        ctk.CTkLabel(
            play_group,
            textvariable=self.play_time_var,
            text_color=TEXT_MAIN,
            font=ctk.CTkFont(size=15, weight="bold"),
        ).grid(row=1, column=1, padx=(12, 0), sticky="nw")

        center_controls = ctk.CTkFrame(bottom_bar, fg_color="transparent")
        center_controls.grid(row=0, column=1, padx=10, pady=16)

        time_group = ctk.CTkFrame(center_controls, fg_color="transparent")
        time_group.grid(row=0, column=0, padx=(0, 18))

        start_entry = self._create_time_chip(time_group, "起始时间", self.start_time_var)
        start_entry.grid(row=0, column=0, padx=(0, 10))

        end_entry = self._create_time_chip(time_group, "结束时间", self.end_time_var)
        end_entry.grid(row=0, column=1)

        edit_group = ctk.CTkFrame(center_controls, fg_color="transparent")
        edit_group.grid(row=0, column=1)

        edit_actions = [
            ("剪切", self.handle_cut),
            ("分割", self.handle_split),
            ("撤销", self.handle_undo),
            ("重做", self.handle_redo),
        ]

        for index, (label, command) in enumerate(edit_actions):
            ctk.CTkButton(
                edit_group,
                text=label,
                command=command,
                height=36,
                width=74,
                corner_radius=12,
                fg_color=PANEL_BG_ALT,
                hover_color=HOVER_BG,
                border_width=1,
                border_color=BORDER,
                text_color=TEXT_MAIN,
                font=ctk.CTkFont(size=13),
            ).grid(row=0, column=index, padx=5)

        ctk.CTkButton(
            bottom_bar,
            text="导出保存",
            command=self.handle_export,
            height=42,
            width=132,
            corner_radius=12,
            fg_color=ACCENT,
            hover_color=ACCENT_2,
            text_color="#04161a",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).grid(row=0, column=2, padx=(14, 22), pady=16, sticky="e")

    def _create_time_chip(
        self,
        parent: ctk.CTkFrame,
        label_text: str,
        variable: tk.StringVar,
    ) -> ctk.CTkFrame:
        chip = ctk.CTkFrame(
            parent,
            fg_color=PANEL_BG_ALT,
            corner_radius=14,
            border_width=1,
            border_color=BORDER,
        )

        ctk.CTkLabel(
            chip,
            text=label_text,
            text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=12),
        ).grid(row=0, column=0, padx=(12, 8), pady=8)

        entry = ctk.CTkEntry(
            chip,
            textvariable=variable,
            width=108,
            height=34,
            fg_color="#111523",
            border_color=BORDER,
            text_color=TEXT_MAIN,
        )
        entry.grid(row=0, column=1, padx=(0, 10), pady=8)
        entry.bind("<Return>", self._on_time_entry_confirm)
        entry.bind("<FocusOut>", self._on_time_entry_blur)
        return chip

    def _set_active_tool(self, tool_key: str) -> None:
        for current_key, button in self.sidebar_buttons.items():
            is_active = current_key == tool_key
            button.configure(
                fg_color=ACTIVE_TOOL_BG if is_active else PANEL_BG_ALT,
                hover_color=ACTIVE_TOOL_BG if is_active else HOVER_BG,
                border_color=ACCENT_2 if is_active else BORDER,
            )

    def _snapshot_state(self) -> EditorState:
        return EditorState(
            clip=self.clip.clone() if self.clip else None,
            selection_start=self.selection_start_sec,
            selection_end=self.selection_end_sec,
            is_dirty=self._is_dirty,
        )

    def _push_undo_state(self) -> None:
        self.undo_stack.append(self._snapshot_state())
        if len(self.undo_stack) > 20:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def _restore_state(self, state: EditorState) -> None:
        self._stop_preview()
        self.clip = state.clip.clone() if state.clip else None
        self.selection_start_sec = state.selection_start
        self.selection_end_sec = state.selection_end
        self._is_dirty = state.is_dirty
        self._refresh_clip_view()

    def _mark_dirty(self) -> None:
        self._is_dirty = True

    def _refresh_clip_view(self) -> None:
        if self.clip is None:
            self.selection_start_sec = 12.4
            self.selection_end_sec = 38.9
            self._playhead_sec = None
            self.file_summary_var.set(
                "当前工程：未加载音频文件 · 当前已支持 WAV/MP3 导入导出、真实波形、播放、剪切与导出"
            )
            self.panel_subtitle_var.set("后续可在这里查看真实波形；当前默认显示连续波形占位示意")
        else:
            duration_text = format_seconds(self.clip.duration)
            dirty_flag = " · 已编辑" if self._is_dirty else ""
            self.file_summary_var.set(
                f"当前文件：{self.clip.display_name}{dirty_flag} · {self.clip.channel_label} · "
                f"{self.clip.sample_rate} Hz · {self.clip.bit_depth} bit · {duration_text}"
            )
            self.panel_subtitle_var.set(
                f"已加载真实波形：{self.clip.display_name} · 总时长 {duration_text}"
            )
            self.selection_start_sec = max(0.0, min(self.selection_start_sec, self.clip.duration))
            self.selection_end_sec = max(self.selection_start_sec, min(self.selection_end_sec, self.clip.duration))
            if not self._is_playing:
                self._playhead_sec = None

        self.start_time_var.set(format_seconds(self.selection_start_sec))
        self.end_time_var.set(format_seconds(self.selection_end_sec))
        self._update_ruler_labels()
        self._update_play_time()
        self._schedule_wave_redraw()

    def _update_play_time(self) -> None:
        if self.clip is None:
            self.play_time_var.set(
                f"{format_seconds(self.selection_start_sec)} - {format_seconds(self.selection_end_sec)} / --:--"
            )
            return

        self.play_time_var.set(
            f"{format_seconds(self.selection_start_sec)} - {format_seconds(self.selection_end_sec)} / "
            f"{format_seconds(self.clip.duration)}"
        )

    def _update_ruler_labels(self) -> None:
        if not self.ruler_labels:
            return

        if self.clip is None or self.clip.duration <= 0:
            for label, tick in zip(self.ruler_labels, RULER_TIMES):
                label.configure(text=tick)
            return

        last_index = max(len(self.ruler_labels) - 1, 1)
        for index, label in enumerate(self.ruler_labels):
            seconds = self.clip.duration * index / last_index
            label.configure(text=format_seconds(seconds))

    def _wave_usable_width(self, width: int) -> tuple[float, float]:
        padding_x = 32.0
        usable_width = max(width - padding_x * 2, 1.0)
        return padding_x, usable_width

    def _canvas_time_from_x(self, x: float) -> float | None:
        if self.clip is None or self.wave_canvas is None or self.clip.duration <= 0:
            return None

        width = self.wave_canvas.winfo_width()
        padding_x, usable_width = self._wave_usable_width(width)
        clamped_x = max(padding_x, min(width - padding_x, x))
        ratio = (clamped_x - padding_x) / usable_width
        return ratio * self.clip.duration

    def _canvas_x_from_time(self, seconds: float, width: int) -> float:
        padding_x, usable_width = self._wave_usable_width(width)
        if self.clip is None or self.clip.duration <= 0:
            return padding_x
        ratio = max(0.0, min(1.0, seconds / self.clip.duration))
        return padding_x + usable_width * ratio

    def _log_action(self, message: str) -> None:
        print(message)
        self.status_var.set(f"最近动作：{message}")

    def _show_error(self, title: str, message: str) -> None:
        messagebox.showerror(title, message)
        self._log_action(f"错误：{message}")

    def _on_time_entry_confirm(self, _event: tk.Event) -> None:
        self._apply_time_entries(show_error=True)

    def _on_time_entry_blur(self, _event: tk.Event) -> None:
        self._apply_time_entries(show_error=False)

    def _apply_time_entries(self, show_error: bool) -> bool:
        try:
            start = parse_time_text(self.start_time_var.get())
            end = parse_time_text(self.end_time_var.get())

            if self.clip is not None:
                duration = self.clip.duration
                start = max(0.0, min(start, duration))
                end = max(0.0, min(end, duration))

            if end < start:
                raise ValueError("结束时间不能早于起始时间")

            self.selection_start_sec = start
            self.selection_end_sec = end
            self.start_time_var.set(format_seconds(start))
            self.end_time_var.set(format_seconds(end))
            self._update_play_time()
            self._schedule_wave_redraw()
            return True
        except Exception as exc:  # noqa: BLE001
            self.start_time_var.set(format_seconds(self.selection_start_sec))
            self.end_time_var.set(format_seconds(self.selection_end_sec))
            if show_error:
                self._show_error("时间输入无效", str(exc))
            return False

    def _set_selection(self, start_sec: float, end_sec: float, *, announce: bool = False) -> None:
        if self.clip is not None:
            duration = self.clip.duration
            start_sec = max(0.0, min(start_sec, duration))
            end_sec = max(0.0, min(end_sec, duration))

        self.selection_start_sec = min(start_sec, end_sec)
        self.selection_end_sec = max(start_sec, end_sec)
        self.start_time_var.set(format_seconds(self.selection_start_sec))
        self.end_time_var.set(format_seconds(self.selection_end_sec))
        self._update_play_time()
        self._schedule_wave_redraw()

        if announce:
            self._log_action(
                f"更新选区：{format_seconds(self.selection_start_sec)} - {format_seconds(self.selection_end_sec)}"
            )

    def _on_wave_canvas_press(self, event: tk.Event) -> None:
        current_time = self._canvas_time_from_x(event.x)
        if current_time is None:
            return

        self._stop_preview()
        self._selection_dragging = True
        handle_mode = self._handle_hit_test(event.x)
        if handle_mode == "left":
            self._selection_drag_mode = "left_handle"
            self.status_var.set(f"正在调整左边界：{format_seconds(self.selection_start_sec)}")
            return

        if handle_mode == "right":
            self._selection_drag_mode = "right_handle"
            self.status_var.set(f"正在调整右边界：{format_seconds(self.selection_end_sec)}")
            return

        self._selection_drag_mode = "new_selection"
        self._selection_anchor_sec = current_time
        self._set_selection(current_time, current_time, announce=False)
        self.status_var.set(f"正在拖拽选区：{format_seconds(current_time)}")

    def _on_wave_canvas_drag(self, event: tk.Event) -> None:
        if not self._selection_dragging:
            return

        current_time = self._canvas_time_from_x(event.x)
        if current_time is None:
            return

        min_gap = 0.01
        if self.clip is not None and self.clip.sample_rate > 0:
            min_gap = max(min_gap, 1 / self.clip.sample_rate)

        if self._selection_drag_mode == "left_handle":
            new_start = min(current_time, self.selection_end_sec - min_gap)
            self._set_selection(new_start, self.selection_end_sec, announce=False)
            self.status_var.set(
                f"正在调整左边界：{format_seconds(self.selection_start_sec)} - {format_seconds(self.selection_end_sec)}"
            )
            return

        if self._selection_drag_mode == "right_handle":
            new_end = max(current_time, self.selection_start_sec + min_gap)
            self._set_selection(self.selection_start_sec, new_end, announce=False)
            self.status_var.set(
                f"正在调整右边界：{format_seconds(self.selection_start_sec)} - {format_seconds(self.selection_end_sec)}"
            )
            return

        self._set_selection(self._selection_anchor_sec, current_time, announce=False)
        self.status_var.set(
            f"正在拖拽选区：{format_seconds(self.selection_start_sec)} - {format_seconds(self.selection_end_sec)}"
        )

    def _on_wave_canvas_release(self, event: tk.Event) -> None:
        if not self._selection_dragging:
            return

        self._selection_dragging = False
        current_time = self._canvas_time_from_x(event.x)
        drag_mode = self._selection_drag_mode
        self._selection_drag_mode = None
        if current_time is None:
            self._refresh_clip_view()
            return

        if drag_mode == "left_handle":
            self._set_selection(self.selection_start_sec, self.selection_end_sec, announce=True)
            self._update_wave_cursor(event.x)
            return

        if drag_mode == "right_handle":
            self._set_selection(self.selection_start_sec, self.selection_end_sec, announce=True)
            self._update_wave_cursor(event.x)
            return

        if abs(current_time - self._selection_anchor_sec) < 0.01 and self.clip is not None:
            delta = min(0.25, max(self.clip.duration, 0.05))
            if current_time >= self.clip.duration:
                self._set_selection(max(0.0, current_time - delta), current_time, announce=True)
            else:
                end_time = min(self.clip.duration, current_time + delta)
                self._set_selection(current_time, end_time, announce=True)
        else:
            self._set_selection(self._selection_anchor_sec, current_time, announce=True)

        self._update_wave_cursor(event.x)

    def _on_wave_canvas_double_click(self, _event: tk.Event) -> None:
        if self.clip is None:
            return
        self._stop_preview()
        self._set_selection(0.0, self.clip.duration, announce=True)

    def _on_wave_canvas_motion(self, event: tk.Event) -> None:
        if self._selection_dragging:
            return
        self._update_wave_cursor(event.x)

    def _schedule_wave_redraw(self, _event: tk.Event | None = None) -> None:
        if self.wave_canvas is None:
            return

        size = (self.wave_canvas.winfo_width(), self.wave_canvas.winfo_height())
        size_changed = size != self._last_wave_size
        self._last_wave_size = size

        if _event is not None and not size_changed and self._wave_redraw_job is None:
            return

        if self._wave_redraw_job is not None:
            self.after_cancel(self._wave_redraw_job)

        delay = 24 if _event is not None else 1
        self._wave_redraw_job = self.after(delay, self._redraw_wave_canvas)

    def _build_wave_points(
        self,
        width: int,
        height: int,
        peaks: list[float],
    ) -> tuple[list[float], list[float], list[float]]:
        padding_x = 32
        padding_y = 24
        mid_y = height / 2
        amplitude_height = min(height * 0.34, mid_y - padding_y)
        usable_width = max(width - padding_x * 2, 1)
        step = usable_width / max(len(peaks) - 1, 1)

        upper_points: list[float] = []
        lower_points: list[float] = []
        lower_pairs: list[tuple[float, float]] = []

        for index, peak in enumerate(peaks):
            x = padding_x + index * step
            upper_y = mid_y - amplitude_height * peak
            lower_y = mid_y + amplitude_height * peak
            upper_points.extend([x, upper_y])
            lower_points.extend([x, lower_y])
            lower_pairs.append((x, lower_y))

        polygon_points: list[float] = [padding_x, mid_y, *upper_points, padding_x + step * (len(peaks) - 1), mid_y]
        for x, y in reversed(lower_pairs):
            polygon_points.extend([x, y])
        return polygon_points, upper_points, lower_points

    def _current_peaks(self, width: int) -> list[float]:
        if self.clip is None or self.clip.frame_count == 0:
            return PLACEHOLDER_PEAKS
        point_count = max(80, min(220, width // 5))
        return self.clip.get_waveform_peaks(point_count)

    def _selection_pixels(self, width: int, height: int) -> tuple[float, float, float, float]:
        padding_x = 32
        selection_top = height * 0.16
        selection_bottom = height * 0.84
        usable_width = max(width - padding_x * 2, 1)

        if self.clip is None or self.clip.duration <= 0:
            left = padding_x + usable_width * 0.18
            right = padding_x + usable_width * 0.78
        else:
            start_ratio = self.selection_start_sec / self.clip.duration
            end_ratio = self.selection_end_sec / self.clip.duration if self.clip.duration else start_ratio
            left = padding_x + usable_width * start_ratio
            right = padding_x + usable_width * end_ratio

        if right - left < 4:
            right = min(width - padding_x, left + 4)
            left = max(padding_x, right - 4)
        return left, right, selection_top, selection_bottom

    def _handle_hit_test(self, x: float) -> str | None:
        if self.wave_canvas is None:
            return None

        width = self.wave_canvas.winfo_width()
        height = self.wave_canvas.winfo_height()
        left, right, _, _ = self._selection_pixels(width, height)
        if abs(x - left) <= self._handle_tolerance_px:
            return "left"
        if abs(x - right) <= self._handle_tolerance_px:
            return "right"
        return None

    def _update_wave_cursor(self, x: float | None = None) -> None:
        if self.wave_canvas is None:
            return

        if x is not None and self._handle_hit_test(x) is not None:
            self.wave_canvas.configure(cursor="sb_h_double_arrow")
        else:
            self.wave_canvas.configure(cursor="crosshair")

    def _redraw_wave_canvas(self) -> None:
        self._wave_redraw_job = None
        if self.wave_canvas is None:
            return

        width = self.wave_canvas.winfo_width()
        height = self.wave_canvas.winfo_height()
        if width < 20 or height < 20:
            return

        self.wave_canvas.delete("all")

        grid_color = "#23293d"
        mid_line_color = "#214149"
        selection_mask = "#101523"
        vertical_lines = 8
        horizontal_lines = 5

        for index in range(vertical_lines + 1):
            x = width * index / vertical_lines
            self.wave_canvas.create_line(x, 0, x, height, fill=grid_color, width=1)

        for index in range(horizontal_lines + 1):
            y = height * index / horizontal_lines
            self.wave_canvas.create_line(0, y, width, y, fill=grid_color, width=1)

        mid_y = height / 2
        self.wave_canvas.create_line(0, mid_y, width, mid_y, fill=mid_line_color, width=2)

        peaks = self._current_peaks(width)
        polygon_points, upper_points, lower_points = self._build_wave_points(width, height, peaks)

        self.wave_canvas.create_polygon(
            polygon_points,
            fill=ACCENT_FILL,
            outline="",
            smooth=True,
            splinesteps=24,
        )
        self.wave_canvas.create_line(
            upper_points,
            fill=ACCENT_2,
            width=2,
            smooth=True,
            splinesteps=24,
        )
        self.wave_canvas.create_line(
            lower_points,
            fill=ACCENT_2,
            width=2,
            smooth=True,
            splinesteps=24,
        )

        selection_left, selection_right, selection_top, selection_bottom = self._selection_pixels(width, height)
        if selection_left > 2:
            self.wave_canvas.create_rectangle(
                0,
                0,
                selection_left,
                height,
                outline="",
                fill=selection_mask,
                stipple="gray50",
            )
        if selection_right < width - 2:
            self.wave_canvas.create_rectangle(
                selection_right,
                0,
                width,
                height,
                outline="",
                fill=selection_mask,
                stipple="gray50",
            )

        self.wave_canvas.create_rectangle(
            selection_left,
            selection_top,
            selection_right,
            selection_bottom,
            outline=ACCENT_2,
            width=2,
        )
        self.wave_canvas.create_line(
            selection_left,
            selection_top,
            selection_left,
            selection_bottom,
            fill=ACCENT,
            width=4,
        )
        self.wave_canvas.create_line(
            selection_right,
            selection_top,
            selection_right,
            selection_bottom,
            fill=ACCENT_2,
            width=4,
        )

        handle_top = (selection_top + selection_bottom) / 2 - 20
        handle_bottom = (selection_top + selection_bottom) / 2 + 20
        for handle_x, handle_color in ((selection_left, ACCENT), (selection_right, ACCENT_2)):
            self.wave_canvas.create_rectangle(
                handle_x - 5,
                handle_top,
                handle_x + 5,
                handle_bottom,
                fill=handle_color,
                outline="",
            )
            self.wave_canvas.create_line(
                handle_x,
                handle_top + 7,
                handle_x,
                handle_bottom - 7,
                fill="#091114",
                width=2,
            )

        indicator_time = self._playhead_sec if self._playhead_sec is not None else self.selection_start_sec
        indicator_x = self._canvas_x_from_time(indicator_time, width)
        self.wave_canvas.create_line(
            indicator_x,
            12,
            indicator_x,
            height - 12,
            fill="#7ef9ff",
            width=2,
        )
        self.wave_canvas.create_oval(
            indicator_x - 5,
            8,
            indicator_x + 5,
            18,
            fill="#7ef9ff",
            outline="",
        )

        self.wave_canvas.create_text(
            selection_left + 10,
            selection_top - 18,
            text=f"起点 {format_seconds(self.selection_start_sec)}",
            fill=ACCENT_2,
            anchor="w",
            font=("Segoe UI", 10, "bold"),
        )
        self.wave_canvas.create_text(
            selection_right - 10,
            selection_top - 18,
            text=f"终点 {format_seconds(self.selection_end_sec)}",
            fill=ACCENT_2,
            anchor="e",
            font=("Segoe UI", 10, "bold"),
        )

        if self.clip is None:
            self.wave_canvas.create_text(
                width / 2,
                height / 2,
                text="音频波形显示区域（导入 WAV 后显示真实连续波形）",
                fill=TEXT_MAIN,
                font=("Segoe UI", 18, "bold"),
            )
        else:
            self.wave_canvas.create_text(
                20,
                height - 18,
                text=f"已加载：{self.clip.display_name} · 当前指示 {format_seconds(indicator_time)}",
                fill=TEXT_MUTED,
                anchor="w",
                font=("Segoe UI", 10),
            )

    def _validate_selection(self, require_non_empty: bool = True) -> tuple[int, int]:
        if self.clip is None:
            raise ValueError("请先导入 WAV 或 MP3 音频文件")

        if not self._apply_time_entries(show_error=False):
            raise ValueError("起始时间或结束时间无效")

        start_frame = self.clip.time_to_frame(self.selection_start_sec)
        end_frame = self.clip.time_to_frame(self.selection_end_sec)

        if require_non_empty and end_frame <= start_frame:
            raise ValueError("请选择有效的时间区间")

        return start_frame, end_frame

    def _ensure_preview_file(self) -> Path:
        if self._preview_file_path is None:
            temp_dir = Path(tempfile.gettempdir()) / "music_editor_preview"
            temp_dir.mkdir(parents=True, exist_ok=True)
            self._preview_file_path = temp_dir / "preview.wav"
        return self._preview_file_path

    def _update_playback_progress(self) -> None:
        self._playback_progress_job = None
        if not self._is_playing or self._playback_started_at is None or self._playback_range is None:
            return

        start_sec, end_sec = self._playback_range
        elapsed = time.perf_counter() - self._playback_started_at
        current_sec = min(end_sec, start_sec + elapsed)
        self._playhead_sec = current_sec

        if self.clip is not None:
            self.play_time_var.set(
                f"播放 {format_seconds(current_sec)} / {format_seconds(self.clip.duration)}"
            )

        self._schedule_wave_redraw()

        if current_sec >= end_sec:
            self._finish_preview()
            return

        self._playback_progress_job = self.after(33, self._update_playback_progress)

    def _stop_preview(self) -> None:
        if self._playback_finish_job is not None:
            self.after_cancel(self._playback_finish_job)
            self._playback_finish_job = None

        if self._playback_progress_job is not None:
            self.after_cancel(self._playback_progress_job)
            self._playback_progress_job = None

        if winsound is not None:
            winsound.PlaySound(None, winsound.SND_PURGE)

        self._is_playing = False
        self._playback_started_at = None
        self._playback_range = None
        self._playhead_sec = None
        if self.play_button is not None:
            self.play_button.configure(text="播放")
        self._update_play_time()
        self._schedule_wave_redraw()

    def _finish_preview(self) -> None:
        self._playback_finish_job = None
        self._playback_progress_job = None
        self._is_playing = False
        self._playback_started_at = None
        self._playback_range = None
        self._playhead_sec = None
        if self.play_button is not None:
            self.play_button.configure(text="播放")
        self._update_play_time()
        self._schedule_wave_redraw()

    def _on_close(self) -> None:
        self._stop_preview()
        if self._preview_file_path and self._preview_file_path.exists():
            try:
                self._preview_file_path.unlink()
            except OSError:
                pass
        self.destroy()

    def handle_import_audio(self) -> None:
        self._set_active_tool("import")
        file_path = filedialog.askopenfilename(
            title="选择音频文件",
            filetypes=[("支持的音频", "*.wav *.mp3"), ("WAV 音频", "*.wav"), ("MP3 音频", "*.mp3"), ("所有文件", "*.*")],
        )
        if not file_path:
            return

        try:
            new_clip = AudioClip.from_file(file_path)
        except AudioFormatError as exc:
            self._show_error("导入失败", str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            self._show_error("导入失败", f"读取音频时发生错误：{exc}")
            return

        if self.clip is not None:
            self._push_undo_state()

        self._stop_preview()
        self.clip = new_clip
        self.selection_start_sec = 0.0
        self.selection_end_sec = self.clip.duration
        self._is_dirty = False
        self._refresh_clip_view()
        self._log_action(f"触发：导入音频 {self.clip.display_name}")

    def handle_volume_adjust(self) -> None:
        self._set_active_tool("volume")
        if self.clip is None:
            self._show_error("无法调整音量", "请先导入 WAV 或 MP3 音频文件")
            return

        dialog = ctk.CTkInputDialog(
            title="调整音量",
            text="请输入音量倍数，例如 0.8 / 1.2 / 1.5：",
        )
        value = dialog.get_input()
        if value is None:
            return

        try:
            factor = float(value)
            self._push_undo_state()
            self.clip = self.clip.apply_volume(factor)
        except Exception as exc:  # noqa: BLE001
            self._show_error("音量调整失败", str(exc))
            return

        self._mark_dirty()
        self._refresh_clip_view()
        self._log_action(f"触发：调整音量 × {factor:g}")

    def handle_speed_change(self) -> None:
        self._set_active_tool("speed")
        if self.clip is None:
            self._show_error("无法变速", "请先导入 WAV 或 MP3 音频文件")
            return

        dialog = ctk.CTkInputDialog(
            title="变速",
            text="请输入变速倍数，例如 0.8 / 1.2 / 1.5：",
        )
        value = dialog.get_input()
        if value is None:
            return

        try:
            factor = float(value)
            self._push_undo_state()
            self.clip = self.clip.change_speed(factor)
        except Exception as exc:  # noqa: BLE001
            self._show_error("变速失败", str(exc))
            return

        self._mark_dirty()
        self.selection_end_sec = min(self.selection_end_sec, self.clip.duration)
        self.selection_start_sec = min(self.selection_start_sec, self.selection_end_sec)
        self._refresh_clip_view()
        self._log_action(f"触发：变速 × {factor:g}")

    def handle_merge_audio(self) -> None:
        self._set_active_tool("merge")
        if self.clip is None:
            self._show_error("无法合并", "请先导入一段基础音频")
            return

        file_path = filedialog.askopenfilename(
            title="选择要合并的音频文件",
            filetypes=[("支持的音频", "*.wav *.mp3"), ("WAV 音频", "*.wav"), ("MP3 音频", "*.mp3"), ("所有文件", "*.*")],
        )
        if not file_path:
            return

        try:
            other_clip = AudioClip.from_file(file_path)
            self._push_undo_state()
            self.clip = self.clip.merge(other_clip)
        except Exception as exc:  # noqa: BLE001
            self._show_error("合并失败", str(exc))
            return

        self._mark_dirty()
        self.selection_start_sec = 0.0
        self.selection_end_sec = self.clip.duration
        self._refresh_clip_view()
        self._log_action(f"触发：合并音频 {Path(file_path).name}")

    def handle_play(self) -> None:
        if winsound is None:
            self._show_error("无法播放", "当前平台不支持 winsound 播放")
            return

        if self._is_playing:
            self._stop_preview()
            self._log_action("触发：停止预览")
            return

        try:
            start_frame, end_frame = self._validate_selection(require_non_empty=True)
            assert self.clip is not None
            preview_path = self._ensure_preview_file()
            self.clip.export_wav(preview_path, start_frame, end_frame)
            winsound.PlaySound(
                str(preview_path),
                winsound.SND_ASYNC | winsound.SND_FILENAME | winsound.SND_NODEFAULT,
            )
        except Exception as exc:  # noqa: BLE001
            self._show_error("播放失败", str(exc))
            return

        preview_duration = max(self.selection_end_sec - self.selection_start_sec, 0.1)
        self._is_playing = True
        self._playback_started_at = time.perf_counter()
        self._playback_range = (self.selection_start_sec, self.selection_end_sec)
        self._playhead_sec = self.selection_start_sec
        if self.play_button is not None:
            self.play_button.configure(text="停止")
        self._playback_finish_job = self.after(int(preview_duration * 1000) + 120, self._finish_preview)
        self._playback_progress_job = self.after(33, self._update_playback_progress)
        self._log_action("触发：播放预览")

    def handle_cut(self) -> None:
        try:
            start_frame, end_frame = self._validate_selection(require_non_empty=True)
            assert self.clip is not None
        except Exception as exc:  # noqa: BLE001
            self._show_error("剪切失败", str(exc))
            return

        self._push_undo_state()
        self._stop_preview()
        self.clip = self.clip.cut_frames(start_frame, end_frame)
        self._mark_dirty()
        self.selection_start_sec = 0.0
        self.selection_end_sec = self.clip.duration
        self._refresh_clip_view()
        self._log_action("触发：剪切音频片段")

    def handle_split(self) -> None:
        try:
            start_frame, end_frame = self._validate_selection(require_non_empty=True)
            assert self.clip is not None
        except Exception as exc:  # noqa: BLE001
            self._show_error("分割失败", str(exc))
            return

        self._push_undo_state()
        self._stop_preview()
        self.clip = self.clip.slice_frames(start_frame, end_frame)
        self._mark_dirty()
        self.selection_start_sec = 0.0
        self.selection_end_sec = self.clip.duration
        self._refresh_clip_view()
        self._log_action("触发：提取选中音频片段")

    def handle_undo(self) -> None:
        if not self.undo_stack:
            self._log_action("触发：撤销操作（无可撤销历史）")
            return

        self.redo_stack.append(self._snapshot_state())
        state = self.undo_stack.pop()
        self._restore_state(state)
        self._log_action("触发：撤销操作")

    def handle_redo(self) -> None:
        if not self.redo_stack:
            self._log_action("触发：重做操作（无可重做历史）")
            return

        self.undo_stack.append(self._snapshot_state())
        state = self.redo_stack.pop()
        self._restore_state(state)
        self._log_action("触发：重做操作")

    def handle_export(self) -> None:
        try:
            start_frame, end_frame = self._validate_selection(require_non_empty=True)
            assert self.clip is not None
        except Exception as exc:  # noqa: BLE001
            self._show_error("导出失败", str(exc))
            return

        default_name = Path(self.clip.display_name).stem if self.clip else "audio_clip"
        file_path = filedialog.asksaveasfilename(
            title="导出修剪后的音频文件",
            defaultextension=".wav",
            initialfile=f"{default_name}_export.wav",
            filetypes=[("WAV 音频", "*.wav"), ("MP3 音频", "*.mp3")],
        )
        if not file_path:
            return

        try:
            self.clip.export(file_path, start_frame, end_frame)
        except Exception as exc:  # noqa: BLE001
            self._show_error("导出失败", f"写入文件时发生错误：{exc}")
            return

        self._log_action(f"触发：导出保存 {Path(file_path).name}")


if __name__ == "__main__":
    app = AudioEditorApp()
    app.mainloop()
