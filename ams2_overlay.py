"""
AMS2 Telemetry Overlay
Tecla F8 = fechar todos os overlays
"""

import ctypes
from ctypes import wintypes
import sys
import traceback
from collections import deque

from PyQt5.QtCore import Qt, QTimer, QPointF, QAbstractNativeEventFilter
from PyQt5.QtGui import (
    QPainter, QColor, QFont, QPen, QBrush
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
kernel32.GetLastError.restype = wintypes.DWORD

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

BG_DARK     = QColor(10, 10, 10, 200)
BG_PANEL    = QColor(12, 12, 12, 180)
C_THROTTLE  = QColor(0, 220, 50)
C_BRAKE     = QColor(255, 40, 40)
C_STEERING  = QColor(100, 140, 180)
C_TEXT      = QColor(220, 220, 220, 220)
C_TEXT_DIM  = QColor(140, 140, 140, 160)
C_TEXT_HI   = QColor(255, 255, 255, 240)
C_GRID      = QColor(50, 50, 50, 120)
C_BORDER    = QColor(70, 70, 70, 150)


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


class TelemetryReader:

    def __init__(self):
        self._h_map = None
        self.throttle = 0.0
        self.brake = 0.0
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
        self.steer_condition = "NEUTRAL"
        self._steer_history = deque(maxlen=30)

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
            self._detect_steer()
            self.connected = True
        except Exception:
            self.connected = False
        finally:
            kernel32.UnmapViewOfFile(p_buf)

    def _detect_steer(self):
        steer_abs = abs(self.steering)
        if steer_abs < 0.15 or self.speed < 3:
            self.steer_condition = "NEUTRAL"
            return
        ratio = abs(self.yaw_rate) / (self.speed + 0.5) / (steer_abs + 0.01)
        self._steer_history.append(ratio)
        if len(self._steer_history) < 10:
            self.steer_condition = "NEUTRAL"
            return
        avg = sum(self._steer_history) / len(self._steer_history)
        deviation = (ratio - avg) / (avg + 0.001)
        if deviation < -0.35:
            self.steer_condition = "UNDER"
        elif deviation > 0.35:
            self.steer_condition = "OVER"
        else:
            self.steer_condition = "NEUTRAL"

    def disconnect(self):
        if self._h_map:
            kernel32.CloseHandle(self._h_map)
            self._h_map = None
        self.connected = False


def _make_click_through(widget):
    hwnd = int(widget.winId())
    try:
        cur = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    except AttributeError:
        cur = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    new = cur | WS_EX_TRANSPARENT | WS_EX_TOPMOST
    try:
        user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, new)
    except AttributeError:
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, new)


class BaseOverlay(QWidget):
    def __init__(self, w, h, tel):
        super().__init__()
        self.tel = tel
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(w, h)
        self._timer = QTimer()
        self._timer.timeout.connect(self.update)
        self._timer.start(33)

    def showEvent(self, event):
        super().showEvent(event)
        _make_click_through(self)


class LapOverlay(BaseOverlay):
    def __init__(self, tel):
        super().__init__(240, 84, tel)
        screen = QApplication.primaryScreen()
        sg = screen.geometry()
        self.move(sg.left(), sg.top())

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        tel = self.tel

        p.setPen(Qt.NoPen)
        p.setBrush(BG_PANEL)
        p.drawRoundedRect(0, 0, w, h, 6, 6)

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


class DashOverlay(BaseOverlay):
    def __init__(self, tel):
        super().__init__(190, 150, tel)
        screen = QApplication.primaryScreen()
        sg = screen.geometry()
        self.move(sg.right() - self.width(), sg.bottom() - self.height())

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        tel = self.tel

        p.setPen(Qt.NoPen)
        p.setBrush(BG_PANEL)
        p.drawRoundedRect(0, 0, w, h, 10, 10)

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


HISTORY_SECONDS = 8
SAMPLE_RATE_HZ  = 30
MAX_SAMPLES     = HISTORY_SECONDS * SAMPLE_RATE_HZ


class GraphOverlay(BaseOverlay):
    def __init__(self, tel):
        super().__init__(560, 180, tel)
        self.history = deque(maxlen=MAX_SAMPLES)
        screen = QApplication.primaryScreen()
        sg = screen.geometry()
        x = (sg.width() - self.width()) // 2
        y = sg.bottom() - self.height()
        self.move(sg.left() + x, y)
        self._tick_timer = QTimer()
        self._tick_timer.timeout.connect(self._tick)
        self._tick_timer.start(33)

    def _tick(self):
        if self.tel.connected:
            self.history.append((self.tel.throttle, self.tel.brake))
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        tel = self.tel

        p.setPen(Qt.NoPen)
        p.setBrush(BG_DARK)
        p.drawRoundedRect(0, 0, w, h, 8, 8)

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

        p.setPen(QPen(C_BORDER, 1))
        p.setBrush(QColor(15, 15, 15, 160))
        p.drawRoundedRect(sw_x, sw_top, sw_w, sw_bot - sw_top, 6, 6)

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

        cond = tel.steer_condition
        if cond != "NEUTRAL":
            is_under = cond == "UNDER"
            c_warn = QColor(255, 140, 30) if is_under else QColor(255, 50, 50)
            p.setPen(QPen(c_warn, 1))
            p.setBrush(QColor(c_warn.red(), c_warn.green(), c_warn.blue(), 60))
            ind_y = sw_bot - 24
            p.drawRoundedRect(sw_x + 6, ind_y, sw_w - 12, 18, 3, 3)
            p.setPen(c_warn)
            p.setFont(QFont("Segoe UI", 7, QFont.Bold))
            txt = "UNDER" if is_under else "OVER"
            p.drawText(sw_x, ind_y + 1, sw_w, 16, Qt.AlignCenter, txt)

        g_x     = 6
        g_w     = w - 120
        g_top   = 6
        g_bot   = h - 6
        g_left  = g_x + 36
        g_right = g_x + g_w - 4
        gw      = g_right - g_left
        gh      = g_bot - g_top

        p.setPen(QPen(C_BORDER, 1))
        p.setBrush(QColor(12, 12, 12, 150))
        p.drawRoundedRect(g_x, g_top, g_w, g_bot - g_top, 6, 6)

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

            pts_thr = [QPointF(x_for(i), g_bot - int(gh * self.history[i][0])) for i in range(n)]
            p.setPen(QPen(C_THROTTLE, 2))
            p.drawPolyline(pts_thr)

            pts_brk = [QPointF(x_for(i), g_bot - int(gh * self.history[i][1])) for i in range(n)]
            p.setPen(QPen(C_BRAKE, 2))
            p.drawPolyline(pts_brk)

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


WM_HOTKEY = 0x0312
MOD_NOREPEAT = 0x4000
VK_F8 = 0x77
HOTKEY_ID = 1

user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.RegisterHotKey.restype  = wintypes.BOOL
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype  = wintypes.BOOL


class HotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, callback):
        super().__init__()
        self._cb = callback
        ok = user32.RegisterHotKey(None, HOTKEY_ID, MOD_NOREPEAT, VK_F8)
        if not ok:
            print("[!] F8 ja esta em uso")

    def nativeEventFilter(self, event_type, message):
        msg = ctypes.cast(ctypes.c_void_p(int(message)), ctypes.POINTER(wintypes.MSG))
        if msg.contents.message == WM_HOTKEY and msg.contents.wParam == HOTKEY_ID:
            self._cb()
            return True, 0
        return False, 0

    def unregister(self):
        user32.UnregisterHotKey(None, HOTKEY_ID)


def criar_tray(app, overlays):
    def fechar():
        for ov in overlays:
            ov.close()
        app.quit()

    icon = app.style().standardIcon(app.style().SP_ComputerIcon)
    tray = QSystemTrayIcon(icon)
    tray.setToolTip("AMS2 Telemetry")
    menu = QMenu()
    acao = QAction("Sair")
    acao.triggered.connect(fechar)
    menu.addAction(acao)
    tray.setContextMenu(menu)
    tray.show()
    return tray


def main():
    try:
        app = QApplication(sys.argv)
        app.setQuitOnLastWindowClosed(False)

        tel = TelemetryReader()
        tel.connect()

        graph = GraphOverlay(tel)
        dash  = DashOverlay(tel)
        lap   = LapOverlay(tel)

        graph.show()
        dash.show()
        lap.show()

        overlays = [graph, dash, lap]
        tray_icon = criar_tray(app, overlays)

        def on_f8():
            for ov in overlays:
                ov.close()
            app.quit()

        hotkey_filter = HotkeyFilter(on_f8)
        app.installNativeEventFilter(hotkey_filter)
        tray_icon._unregister_hotkey = hotkey_filter.unregister

        def master_tick():
            if not tel.connected:
                tel.connect()
            tel.update()

        master_timer = QTimer()
        master_timer.timeout.connect(master_tick)
        master_timer.start(33)

        print("=" * 50)
        print("  AMS2 Telemetry Overlay iniciado")
        print("  F8 = fechar  |  Bandeja = Sair")
        print("=" * 50)

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
