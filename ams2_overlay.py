"""
AMS2 Telemetry Overlay
F6  = modo config (arrastar widgets)
F8  = fechar todos os overlays
"""

import ctypes
from ctypes import wintypes
import sys
import traceback
import os
import json
from collections import deque

from PyQt5.QtCore import Qt, QTimer, QPointF, QAbstractNativeEventFilter, QPoint
from PyQt5.QtGui import (
    QPainter, QColor, QFont, QPen, QBrush, QPainterPath
)
from PyQt5.QtWidgets import QApplication, QWidget, QSystemTrayIcon, QMenu, QAction

kernel32 = ctypes.windll.kernel32
user32   = ctypes.windll.user32

FILE_MAP_READ     = 0x0004
GWL_EXSTYLE       = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOPMOST     = 0x00000008

kernel32.OpenFileMappingW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.OpenFileMappingW.restype  = wintypes.HANDLE
kernel32.MapViewOfFile.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t
]
kernel32.MapViewOfFile.restype  = wintypes.LPVOID
kernel32.UnmapViewOfFile.argtypes = [wintypes.LPCVOID]
kernel32.UnmapViewOfFile.restype  = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype  = wintypes.BOOL

try:
    user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongPtrW.restype  = wintypes.LONG_PTR
    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG_PTR]
    user32.SetWindowLongPtrW.restype  = wintypes.LONG_PTR
except Exception:
    pass

MEM_NAMES = ["$pcars2$", "Global\\$pcars2$"]

OFF_THROTTLE = 6428
OFF_BRAKE    = 6432
OFF_STEERING = 6436
OFF_CLUTCH   = 6440
OFF_SPEED    = 6848
OFF_RPM      = 6852
OFF_MAX_RPM  = 6856
OFF_GEAR     = 6876
OFF_YAW_RATE = 748
OFF_LAT_G    = 760
OFF_LAST_LAP    = 6720
OFF_CURRENT_TIME = 6724
OFF_SPLIT_TIME  = 6736
OFF_BEST_LAP    = 6744

BG_DARK      = QColor(10, 10, 10, 200)
BG_PANEL     = QColor(12, 12, 12, 180)
BG_CONFIG    = QColor(20, 20, 30, 230)
C_THROTTLE   = QColor(0, 220, 50)
C_BRAKE      = QColor(255, 40, 40)
C_CLUTCH     = QColor(255, 180, 30)
C_STEERING   = QColor(100, 140, 180)
C_TEXT       = QColor(220, 220, 220, 220)
C_TEXT_DIM   = QColor(140, 140, 140, 160)
C_TEXT_HI    = QColor(255, 255, 255, 240)
C_GRID       = QColor(50, 50, 50, 120)
C_BORDER     = QColor(70, 70, 70, 150)
C_CONFIG     = QColor(255, 200, 50, 220)


def _read_float(address, offset=0):
    return ctypes.cast(
        ctypes.c_void_p(address + offset),
        ctypes.POINTER(ctypes.c_float)
    )[0]

def _read_int32(address, offset=0):
    return ctypes.cast(
        ctypes.c_void_p(address + offset),
        ctypes.POINTER(ctypes.c_int32)
    )[0]


# =====================================================================
#  CONFIG (persistencia de posicoes)
# =====================================================================

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "overlay_config.json")
_config_mode = False
_all_overlays = []


def _load_config():
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_config(cfg):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass


def _get_default_config():
    screen = QApplication.primaryScreen()
    if not screen:
        return {}
    sg = screen.geometry()
    return {
        "lap":    [sg.left(), sg.top()],
        "dash":   [sg.right() - 190, sg.bottom() - 150],
        "graph":  [sg.left() + (sg.width() - 560) // 2, sg.bottom() - 180],
        "pedals": [sg.left(), sg.bottom() - 160],
        "help":   [sg.left() + (sg.width() - 320) // 2, sg.top()],
        "hidden": [],
    }


def _get_hidden():
    cfg = _load_config()
    return cfg.get("hidden", [])


def _set_hidden(hidden_list):
    cfg = _load_config()
    cfg["hidden"] = hidden_list
    _save_config(cfg)


def _config_pos(widget_id):
    cfg = _load_config()
    defaults = _get_default_config()
    if widget_id in cfg:
        return cfg[widget_id]
    return defaults.get(widget_id, [100, 100])


def _set_click_through(widget, enabled):
    hwnd = int(widget.winId())
    try:
        cur = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    except AttributeError:
        cur = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    if enabled:
        new = cur | WS_EX_TRANSPARENT | WS_EX_TOPMOST
    else:
        new = (cur | WS_EX_TOPMOST) & ~WS_EX_TRANSPARENT
    try:
        user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, new)
    except AttributeError:
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, new)


def _reset_config():
    if not _config_mode:
        return
    try:
        os.remove(CONFIG_FILE)
    except Exception:
        pass
    cfg = _get_default_config()
    for ov in _all_overlays:
        pos = cfg.get(ov._id, [100, 100])
        ov.move(pos[0], pos[1])


def _toggle_config():
    global _config_mode
    _config_mode = not _config_mode
    hidden = _get_hidden()
    for ov in _all_overlays:
        if _config_mode:
            _set_click_through(ov, False)
            ov.setWindowFlags(ov.windowFlags() | Qt.WindowStaysOnTopHint)
            ov.show()
        else:
            if ov._id in hidden:
                ov.hide()
                _set_click_through(ov, True)
            else:
                _set_click_through(ov, True)
        ov.update()
    if not _config_mode:
        cfg = _load_config()
        for ov in _all_overlays:
            cfg[ov._id] = [ov.x(), ov.y()]
        cfg["hidden"] = hidden
        _save_config(cfg)


# =====================================================================
#  TELEMETRY READER
# =====================================================================

class TelemetryReader:

    def __init__(self):
        self._h_map = None
        self.throttle = 0.0
        self.brake = 0.0
        self.clutch = 0.0
        self.steering = 0.0
        self.speed = 0.0
        self.rpm = 0.0
        self.max_rpm = 0.0
        self.gear = 0
        self.last_lap = 0.0
        self.current_time = 0.0
        self.split_time = 0.0
        self.best_lap = 0.0
        self.yaw_rate = 0.0
        self.lat_g = 0.0
        self.connected = False

    def connect(self):
        if self._h_map:
            self.disconnect()
        for name in MEM_NAMES:
            h = kernel32.OpenFileMappingW(FILE_MAP_READ, False, name)
            if h:
                self._h_map = h
                self.connected = True
                return True
        return False

    def update(self):
        if not self._h_map:
            self.connected = False
            return
        p_buf = kernel32.MapViewOfFile(self._h_map, FILE_MAP_READ, 0, 0, 0)
        if not p_buf:
            self.connected = False
            return
        try:
            self.throttle = max(0.0, min(1.0, _read_float(p_buf, OFF_THROTTLE)))
            self.brake    = max(0.0, min(1.0, _read_float(p_buf, OFF_BRAKE)))
            self.clutch   = max(0.0, min(1.0, _read_float(p_buf, OFF_CLUTCH)))
            self.steering = max(-1.0, min(1.0, _read_float(p_buf, OFF_STEERING)))
            self.speed    = max(0.0, _read_float(p_buf, OFF_SPEED))
            self.rpm      = max(0.0, _read_float(p_buf, OFF_RPM))
            self.max_rpm  = max(0.0, _read_float(p_buf, OFF_MAX_RPM))
            self.gear     = _read_int32(p_buf, OFF_GEAR)
            self.last_lap = _read_float(p_buf, OFF_LAST_LAP)
            self.current_time = _read_float(p_buf, OFF_CURRENT_TIME)
            self.split_time = _read_float(p_buf, OFF_SPLIT_TIME)
            self.best_lap = _read_float(p_buf, OFF_BEST_LAP)
            self.yaw_rate = _read_float(p_buf, OFF_YAW_RATE)
            self.lat_g    = _read_float(p_buf, OFF_LAT_G)
            self.connected = True
        except Exception:
            self.connected = False
        finally:
            kernel32.UnmapViewOfFile(p_buf)

    def disconnect(self):
        if self._h_map:
            kernel32.CloseHandle(self._h_map)
            self._h_map = None
        self.connected = False


# =====================================================================
#  BASE OVERLAY (com suporte a arrasto no modo config)
# =====================================================================

class BaseOverlay(QWidget):
    def __init__(self, w, h, tel, widget_id, draggable=True):
        super().__init__()
        self.tel = tel
        self._id = widget_id
        self._draggable = draggable
        self._dragging = False
        self._drag_start = QPoint()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(w, h)
        pos = _config_pos(widget_id)
        self.move(pos[0], pos[1])
        self._timer = QTimer()
        self._timer.timeout.connect(self.update)
        self._timer.start(33)
        _all_overlays.append(self)

    def showEvent(self, event):
        super().showEvent(event)
        _set_click_through(self, True)

    def mousePressEvent(self, event):
        if _config_mode and self._draggable and event.button() == Qt.LeftButton:
            self._dragging = True
            self._drag_start = event.globalPos() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if _config_mode and self._draggable and self._dragging:
            self.move(event.globalPos() - self._drag_start)

    def mouseReleaseEvent(self, event):
        if _config_mode and self._draggable and event.button() == Qt.LeftButton:
            self._dragging = False

    def closeEvent(self, event):
        self._timer.stop()
        super().closeEvent(event)


# =====================================================================
#  LAP OVERLAY
# =====================================================================

class LapOverlay(BaseOverlay):
    def __init__(self, tel):
        super().__init__(240, 84, tel, "lap")

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        tel = self.tel

        bg = BG_CONFIG if _config_mode else BG_PANEL
        border = C_CONFIG if _config_mode else C_BORDER
        p.setPen(QPen(border, 1))
        p.setBrush(bg)
        p.drawRoundedRect(0, 0, w, h, 6, 6)

        if _config_mode:
            p.setPen(C_CONFIG)
            p.setFont(QFont("Segoe UI", 9, QFont.Bold))
            p.drawText(0, 0, w, h, Qt.AlignCenter, "DRAG TO MOVE")
            p.end()
            return

        if not tel.connected:
            p.setPen(C_TEXT_DIM)
            p.setFont(QFont("Segoe UI", 8))
            p.drawText(0, 0, w, h, Qt.AlignCenter, "Aguardando...")
            p.end()
            return

        if tel.current_time > 0:
            m = int(tel.current_time // 60)
            s = tel.current_time % 60
            cur_txt = f"{m}:{s:06.3f}"
        else:
            cur_txt = "--:--.---"
        p.setFont(QFont("Segoe UI", 18, QFont.Bold))
        p.setPen(C_TEXT_HI)
        p.drawText(8, 0, w - 16, 28, Qt.AlignLeft | Qt.AlignVCenter, cur_txt)

        if tel.current_time > 0 and abs(tel.split_time) > 0.0001:
            delta = tel.split_time
            if delta > 0:
                delta_txt = f"+{delta:.3f}"
                delta_col = QColor(255, 80, 80)
            elif delta < 0:
                delta_txt = f"{delta:.3f}"
                delta_col = QColor(0, 220, 60)
            else:
                delta_txt = " 0.000"
                delta_col = C_TEXT
            p.setFont(QFont("Segoe UI", 13, QFont.Bold))
            p.setPen(delta_col)
            p.drawText(8, 28, w - 16, 24, Qt.AlignLeft | Qt.AlignVCenter, delta_txt)
        else:
            p.setFont(QFont("Segoe UI", 10))
            p.setPen(C_TEXT_DIM)
            p.drawText(8, 28, w - 16, 24, Qt.AlignLeft | Qt.AlignVCenter, "--.---")

        p.setFont(QFont("Segoe UI", 7))
        p.setPen(C_TEXT_DIM)
        p.drawText(10, 56, 50, 14, Qt.AlignLeft, "LAST")
        if tel.last_lap > 0:
            m = int(tel.last_lap // 60)
            s = tel.last_lap % 60
            last_txt = f"{m}:{s:06.3f}"
        else:
            last_txt = "--:--.---"
        p.setFont(QFont("Segoe UI", 11, QFont.Bold))
        p.setPen(C_TEXT)
        p.drawText(8, 56, w - 16, 22, Qt.AlignLeft | Qt.AlignVCenter, last_txt)

        p.end()


# =====================================================================
#  PEDALS OVERLAY (THR/BRK/CLT barras + porcentagem)
# =====================================================================

class PedalsOverlay(BaseOverlay):
    def __init__(self, tel):
        super().__init__(140, 160, tel, "pedals")

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        tel = self.tel

        bg = BG_CONFIG if _config_mode else BG_PANEL
        border = C_CONFIG if _config_mode else C_BORDER
        p.setPen(QPen(border, 1))
        p.setBrush(bg)
        p.drawRoundedRect(0, 0, w, h, 6, 6)

        if _config_mode:
            p.setPen(C_CONFIG)
            p.setFont(QFont("Segoe UI", 9, QFont.Bold))
            p.drawText(0, 0, w, h, Qt.AlignCenter, "DRAG TO MOVE")
            p.end()
            return

        if not tel.connected:
            p.setPen(C_TEXT_DIM)
            p.setFont(QFont("Segoe UI", 8))
            p.drawText(0, 0, w, h, Qt.AlignCenter, "...")
            p.end()
            return

        pedals = [
            ("THR", tel.throttle, C_THROTTLE),
            ("BRK", tel.brake,    C_BRAKE),
            ("CLT", tel.clutch,   C_CLUTCH),
        ]

        col_w = 38
        margin = 12
        top_y = 14
        bot_y = 26
        bar_w = 22
        bar_h = h - top_y - bot_y
        spacing = (w - margin * 2 - col_w * 3) // 2

        for i, (label, val, color) in enumerate(pedals):
            cx = margin + i * (col_w + spacing)

            p.setFont(QFont("Segoe UI", 7, QFont.Bold))
            p.setPen(C_TEXT_DIM)
            p.drawText(cx, 2, col_w, 12, Qt.AlignCenter, label)

            bx = cx + (col_w - bar_w) // 2
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(30, 30, 30, 220))
            p.drawRoundedRect(bx, top_y, bar_w, bar_h, 3, 3)

            if val > 0.001:
                fill = max(4, int(bar_h * val))
                p.setBrush(color)
                p.drawRoundedRect(bx, top_y + bar_h - fill, bar_w, fill, 3, 3)

            p.setPen(C_TEXT)
            p.setFont(QFont("Segoe UI", 7))
            p.drawText(cx, h - 22, col_w, 14, Qt.AlignCenter, f"{int(val*100)}%")

        p.end()


# =====================================================================
#  DASH OVERLAY
# =====================================================================

class DashOverlay(BaseOverlay):
    def __init__(self, tel):
        super().__init__(190, 150, tel, "dash")

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        tel = self.tel

        bg = BG_CONFIG if _config_mode else BG_PANEL
        border = C_CONFIG if _config_mode else C_BORDER
        p.setPen(QPen(border, 1))
        p.setBrush(bg)
        p.drawRoundedRect(0, 0, w, h, 10, 10)

        if _config_mode:
            p.setPen(C_CONFIG)
            p.setFont(QFont("Segoe UI", 9, QFont.Bold))
            p.drawText(0, 0, w, h, Qt.AlignCenter, "DRAG TO MOVE")
            p.end()
            return

        if not tel.connected:
            p.setPen(C_TEXT_DIM)
            p.setFont(QFont("Segoe UI", 8))
            p.drawText(0, 0, w, h, Qt.AlignCenter, "Aguardando...")
            p.end()
            return

        if tel.gear == -1:
            gtxt, gcol = "R", QColor(220, 60, 60)
        elif tel.gear == 0:
            gtxt, gcol = "N", C_TEXT_DIM
        else:
            gtxt, gcol = str(tel.gear), C_TEXT_HI
        p.setFont(QFont("Segoe UI", 40, QFont.Bold))
        p.setPen(gcol)
        p.drawText(0, 2, w, 50, Qt.AlignCenter, gtxt)

        speed_kmh = int(tel.speed * 3.6)
        p.setFont(QFont("Segoe UI", 22, QFont.Bold))
        p.setPen(C_TEXT_HI)
        p.drawText(0, 50, w, 72, Qt.AlignCenter, f"{speed_kmh}")
        p.setFont(QFont("Segoe UI", 7))
        p.setPen(C_TEXT_DIM)
        p.drawText(0, 100, w, 10, Qt.AlignCenter, "km/h")

        rpm_pct = tel.rpm / (tel.max_rpm + 1.0)
        rpm_pct = max(0.0, min(1.0, rpm_pct))
        bar_x, bar_y, bar_w, bar_h = 12, 114, w - 24, 16
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(30, 30, 30, 220))
        p.drawRoundedRect(bar_x, bar_y, bar_w, bar_h, 2, 2)
        fill = int(bar_w * rpm_pct)
        if fill > 0:
            if rpm_pct > 0.92:
                c = QColor(255, 20, 20)
            elif rpm_pct > 0.85:
                c = QColor(255, 220, 40)
            else:
                c = QColor(0, 220, 80)
            p.setBrush(c)
            p.drawRoundedRect(bar_x, bar_y, fill, bar_h, 2, 2)

        p.setFont(QFont("Segoe UI", 7))
        p.setPen(C_TEXT_DIM)
        p.drawText(0, bar_y + bar_h + 2, w, 12, Qt.AlignCenter, f"{int(tel.rpm)} rpm")

        p.end()


# =====================================================================
#  GRAPH OVERLAY
# =====================================================================

# =====================================================================
#  HELP OVERLAY (legenda de teclas, topo central)
# =====================================================================

class HelpOverlay(BaseOverlay):
    def __init__(self, tel):
        super().__init__(320, 30, tel, "help", draggable=False)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        if not _config_mode:
            p.end()
            return

        p.setPen(Qt.NoPen)
        p.setBrush(QColor(10, 10, 10, 180))
        p.drawRoundedRect(0, 0, w, h, 5, 5)

        p.setFont(QFont("Segoe UI", 7))
        p.setPen(C_CONFIG)
        p.drawText(0, 0, w, h, Qt.AlignCenter, "Ctrl+F5 = reset   |   Ctrl+F6 = save")


# =====================================================================
#  GRAPH OVERLAY
# =====================================================================

HISTORY_SECONDS = 15#Quantos segundos de input sao registrados no grafico
SAMPLE_RATE_HZ  = 60
MAX_SAMPLES     = HISTORY_SECONDS * SAMPLE_RATE_HZ


class GraphOverlay(BaseOverlay):
    EMA_ALPHA = 0.35  # menor = mais suave (0.0 a 1.0)

    def __init__(self, tel):
        super().__init__(560, 180, tel, "graph")
        self.history = deque(maxlen=MAX_SAMPLES)
        self._s_thr = 0.0
        self._s_brk = 0.0
        self._tick_timer = QTimer()
        self._tick_timer.timeout.connect(self._tick)
        self._tick_timer.start(16)

    def _tick(self):
        if self.tel.connected:
            a = self.EMA_ALPHA
            self._s_thr = a * self.tel.throttle + (1 - a) * self._s_thr
            self._s_brk = a * self.tel.brake    + (1 - a) * self._s_brk
            self.history.append((self._s_thr, self._s_brk))
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        tel = self.tel

        bg = BG_CONFIG if _config_mode else BG_DARK
        border = C_CONFIG if _config_mode else C_BORDER
        p.setPen(QPen(border, 1))
        p.setBrush(bg)
        p.drawRoundedRect(0, 0, w, h, 8, 8)

        # linha divisoria entre grafico e volante
        p.setPen(QPen(C_BORDER, 1))
        p.drawLine(w - 110, 6, w - 110, h - 6)

        if _config_mode:
            p.setPen(C_CONFIG)
            p.setFont(QFont("Segoe UI", 10, QFont.Bold))
            p.drawText(0, 0, w, h, Qt.AlignCenter, "DRAG TO MOVE")
            p.end()
            return

        if not tel.connected:
            p.setPen(C_TEXT_DIM)
            p.setFont(QFont("Segoe UI", 8))
            p.drawText(0, 0, w, h, Qt.AlignCenter, "Aguardando...")
            p.end()
            return

        sw_x   = w - 110
        sw_w   = 100
        sw_top = 6
        sw_bot = h - 6
        sw_cx  = sw_x + sw_w // 2
        sw_cy  = sw_top + (sw_bot - sw_top) // 2
        sw_r   = 28

        angle_deg = tel.steering * 180
        p.save()
        p.translate(sw_cx, sw_cy)
        p.rotate(angle_deg)

        p.setPen(QPen(C_STEERING, 2))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(int(-sw_r), int(-sw_r), int(sw_r * 2), int(sw_r * 2))

        p.setPen(QPen(C_STEERING, 1))
        p.drawLine(0, 0, 0, -sw_r + 3)
        p.drawLine(0, 0, int(-sw_r * 0.6), int(sw_r * 0.4))
        p.drawLine(0, 0, int(sw_r * 0.6), int(sw_r * 0.4))

        p.setBrush(C_STEERING)
        p.setPen(Qt.NoPen)
        p.drawEllipse(-3, -3, 6, 6)

        p.setPen(QPen(QColor(255, 220, 50), 2))
        p.drawLine(0, -sw_r - 4, 0, -sw_r + 6)

        p.restore()

        g_x     = 6
        g_w     = w - 120
        g_top   = 6
        g_bot   = h - 6
        g_left  = g_x + 36
        g_right = g_x + g_w - 4
        gw      = g_right - g_left
        gh      = g_bot - g_top

        p.setPen(QPen(C_GRID, 1))
        for i in range(5):
            y = g_top + int(gh * i / 4)
            p.drawLine(g_left, y, g_right, y)

        sec = SAMPLE_RATE_HZ
        for i in range(0, len(self.history), sec):
            x = g_right - int(gw * i / MAX_SAMPLES)
            if x >= g_left:
                p.drawLine(x, g_top, x, g_bot)

        p.setPen(C_TEXT_DIM)
        p.setFont(QFont("Segoe UI", 7))
        for i, label in enumerate(["100", "75", "50", "25", "0"]):
            y = g_top + int(gh * i / 4)
            p.drawText(4, y - 5, 30, 12, Qt.AlignRight, label)

        n = len(self.history)
        if n >= 2:
            p.setBrush(Qt.NoBrush)
            def x_for(i):
                return g_right - int(gw * (n - 1 - i) / MAX_SAMPLES)

            def draw_smooth(painter, pen, values):
                if len(values) < 2:
                    return
                pts = [QPointF(x_for(i), g_bot - gh * values[i]) for i in range(n)]
                painter.setPen(pen)
                path = QPainterPath()
                path.moveTo(pts[0])
                for i in range(1, len(pts)):
                    p0, p1 = pts[i - 1], pts[i]
                    dx = (p1.x() - p0.x()) * 0.5
                    path.cubicTo(
                        QPointF(p0.x() + dx, p0.y()),
                        QPointF(p1.x() - dx, p1.y()),
                        p1
                    )
                painter.setBrush(Qt.NoBrush)
                painter.drawPath(path)

            thr_vals = [self.history[i][0] for i in range(n)]
            brk_vals = [self.history[i][1] for i in range(n)]

            draw_smooth(p, QPen(C_THROTTLE, 2), thr_vals)
            draw_smooth(p, QPen(C_BRAKE, 2), brk_vals)

        p.setFont(QFont("Segoe UI", 8, QFont.Bold))
        p.setPen(C_THROTTLE)
        p.drawText(g_left + 6, g_top + 14, 28, 12, Qt.AlignLeft, "THR")
        p.setPen(C_BRAKE)
        p.drawText(g_left + 40, g_top + 14, 28, 12, Qt.AlignLeft, "BRK")

        p.end()

    def closeEvent(self, event):
        self._tick_timer.stop()
        self._timer.stop()
        super().closeEvent(event)


# =====================================================================
#  HOTKEYS (F6 config, F8 quit)
# =====================================================================

WM_HOTKEY = 0x0312
MOD_NOREPEAT = 0x4000
MOD_CONTROL   = 0x0002
MOD_ALT       = 0x0001
MOD_SHIFT     = 0x0004

user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.RegisterHotKey.restype  = wintypes.BOOL
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype  = wintypes.BOOL


class HotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, hotkey_defs):
        super().__init__()
        self._cbs = {}
        for hid, vk, cb in hotkey_defs:
            self._cbs[hid] = cb
            ok = user32.RegisterHotKey(None, hid, MOD_NOREPEAT | MOD_CONTROL, vk)
            if not ok:
                print(f"[!] Hotkey Ctrl+F{hid} ja esta em uso")

    def nativeEventFilter(self, event_type, message):
        msg = ctypes.cast(ctypes.c_void_p(int(message)), ctypes.POINTER(wintypes.MSG))
        if msg.contents.message == WM_HOTKEY:
            hid = msg.contents.wParam
            if hid in self._cbs:
                self._cbs[hid]()
                return True, 0
        return False, 0

    def unregister(self):
        for hid in self._cbs:
            user32.UnregisterHotKey(None, hid)


# =====================================================================
#  SYSTEM TRAY
# =====================================================================

def criar_tray(app, overlays):
    def fechar():
        for ov in overlays:
            ov.close()
        app.quit()

    icon = app.style().standardIcon(app.style().SP_ComputerIcon)
    tray = QSystemTrayIcon(icon)
    tray.setToolTip("AMS2 Telemetry")
    menu = QMenu()
    tray._menu = menu
    tray._actions = []

    tray._actions.append(menu.addAction("Widgets:"))

    hidden = _get_hidden()
    widget_names = {"lap": "Lap Times", "dash": "Dash", "graph": "Graph", "pedals": "Pedals"}

    def make_toggle(wid):
        def toggle(checked):
            h = _get_hidden()
            ov = next((o for o in overlays if o._id == wid), None)
            if not checked:
                if wid not in h:
                    h.append(wid)
                if ov:
                    ov.hide()
            else:
                if wid in h:
                    h.remove(wid)
                if ov and not _config_mode:
                    ov.show()
            _set_hidden(h)
        return toggle

    for wid, name in widget_names.items():
        act = QAction(name)
        act.setCheckable(True)
        act.setChecked(wid not in hidden)
        act.triggered.connect(make_toggle(wid))
        menu.addAction(act)
        tray._actions.append(act)

    menu.addSeparator()
    acao = QAction("Sair")
    acao.triggered.connect(fechar)
    menu.addAction(acao)
    tray._actions.append(acao)

    tray.setContextMenu(menu)
    tray.show()
    return tray


# =====================================================================
#  MAIN
# =====================================================================

def main():
    try:
        app = QApplication(sys.argv)
        app.setQuitOnLastWindowClosed(False)

        tel = TelemetryReader()
        tel.connect()

        graph = GraphOverlay(tel)
        dash  = DashOverlay(tel)
        lap   = LapOverlay(tel)
        ped   = PedalsOverlay(tel)
        help  = HelpOverlay(tel)

        overlays = [graph, dash, lap, ped, help]

        hidden = _get_hidden()
        for ov in overlays:
            if ov._id not in hidden:
                ov.show()
            else:
                ov.hide()

        tray_icon = criar_tray(app, overlays)

        def on_f8():
            for ov in overlays:
                ov.close()
            app.quit()

        hotkey_defs = [
            (1, 0x77, on_f8),          # F8 = quit
            (2, 0x75, _toggle_config),  # F6 = config
            (3, 0x74, _reset_config),   # F5 = reset positions
        ]
        hotkey_filter = HotkeyFilter(hotkey_defs)
        app.installNativeEventFilter(hotkey_filter)
        tray_icon._unregister_hotkey = hotkey_filter.unregister

        def master_tick():
            if not tel.connected:
                tel.connect()
            tel.update()

        master_timer = QTimer()
        master_timer.timeout.connect(master_tick)
        master_timer.start(33)

        print("=" * 55)
        print("  AMS2 Telemetry Overlay iniciado")
        print("  Ctrl+F6 = modo config (arrastar widgets)")
        print("  Ctrl+F5 = reset posicoes (durante config)")
        print("  Ctrl+F8 = fechar  |  Bandeja = Sair")
        print("=" * 55)

        ret = app.exec_()
        master_timer.stop()
        hotkey_filter.unregister()
        tel.disconnect()
        sys.exit(ret)

    except Exception as e:
        print(f"\n[ERRO FATAL] {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
