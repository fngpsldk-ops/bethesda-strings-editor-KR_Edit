"""Minimal GPU utilization monitor for the status bar.

Reads from AMD sysfs (/sys/class/drm + hwmon) or NVIDIA nvidia-smi.
No external dependencies required — pure sysfs/subprocess.

AMD stats rely on Linux sysfs, so they're Linux-only.  NVIDIA stats come from
`nvidia-smi`, which ships with the driver on Windows and macOS as well, so
NVIDIA GPUs are covered on every platform.  When nothing is found the widget
hides itself.

Shows: GPU% · VRAMused/VRAMtotal · Temperature°C
Color: green < 50/70%/70°C · yellow < 80/90%/85°C · red above that.
Updates every 2 seconds via QTimer.  Hidden automatically if no GPU found.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThread, QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

logger = logging.getLogger(__name__)


# ── Data ──────────────────────────────────────────────────────────────────────

@dataclass
class GpuStats:
    utilization: int    # 0–100 %
    vram_used_mb: int   # MB
    vram_total_mb: int  # MB
    temperature: int    # °C; -1 = unavailable


# ── Backends ──────────────────────────────────────────────────────────────────

def _read_int(path: Path) -> Optional[int]:
    try:
        return int(path.read_text().strip())
    except BaseException:
        return None


def _find_amd_device() -> Optional[Path]:
    """Return the sysfs device path for the first AMDGPU card."""
    for card in sorted(Path("/sys/class/drm").glob("card[0-9]*")):
        busy = card / "device" / "gpu_busy_percent"
        if not busy.exists():
            continue
        # Confirm via hwmon name so we don't accidentally pick a display engine
        hwmon_root = card / "device" / "hwmon"
        if hwmon_root.exists():
            for hw in hwmon_root.iterdir():
                name_file = hw / "name"
                if name_file.exists() and name_file.read_text().strip() == "amdgpu":
                    return card / "device"
        # Fallback: gpu_busy_percent existing is AMD-specific
        return card / "device"
    return None


def _read_amd(dev: Path) -> Optional[GpuStats]:
    util       = _read_int(dev / "gpu_busy_percent")
    vram_used  = _read_int(dev / "mem_info_vram_used")
    vram_total = _read_int(dev / "mem_info_vram_total")
    if util is None or vram_used is None or vram_total is None:
        return None

    # Prefer junction temp (temp2) over edge (temp1) — closer to real die temp
    temp = -1
    hwmon_root = dev / "hwmon"
    if hwmon_root.exists():
        for hw in sorted(hwmon_root.iterdir()):
            for idx in (2, 1, 3):
                t = _read_int(hw / f"temp{idx}_input")
                if t is not None:
                    temp = t // 1000  # millidegrees → °C
                    break
            if temp != -1:
                break

    return GpuStats(
        utilization=util,
        vram_used_mb=vram_used  // (1024 * 1024),
        vram_total_mb=vram_total // (1024 * 1024),
        temperature=temp,
    )


def _read_nvidia() -> Optional[GpuStats]:
    # On a frozen/windowed build (no console of its own), spawning a console
    # child like nvidia-smi without suppressing its window makes Windows
    # allocate/tear down a console for it on every single call -- confirmed
    # to be slow enough, polled every 2s on the CALLING thread (see _poll()
    # below), to make the whole UI feel intermittently frozen. Same fix
    # already applied to ollama_control.py's restart-command launch; mirrored
    # here. stdin=DEVNULL for the same reason that fix uses it: a windowed
    # process has no console to inherit stdin from, so leaving it unset can
    # itself be a source of hangs on some systems.
    #
    # Belt-and-suspenders: creationflags=CREATE_NO_WINDOW alone has been
    # reported to still flash a console in some Windows 11 configurations
    # (notably when Windows Terminal is set as the default terminal app) --
    # explicitly setting STARTUPINFO with STARTF_USESHOWWINDOW/SW_HIDE is the
    # more universally-reliable second layer for this and costs nothing when
    # the simpler flag alone would already have worked.
    creationflags = 0
    startupinfo = None
    if sys.platform == "win32":
        creationflags = 0x08000000  # CREATE_NO_WINDOW
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0  # SW_HIDE
    try:
        r = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
            startupinfo=startupinfo,
        )
        if r.returncode != 0:
            return None
        parts = [p.strip() for p in r.stdout.strip().split(",")]
        if len(parts) < 4:
            return None
        return GpuStats(
            utilization=int(parts[0]),
            vram_used_mb=int(parts[1]),
            vram_total_mb=int(parts[2]),
            temperature=int(parts[3]),
        )
    except BaseException:
        return None


def read_gpu_stats() -> Optional[GpuStats]:
    """Return current GPU stats, or None if no supported GPU found.

    AMD is read from Linux sysfs (Linux-only); NVIDIA via nvidia-smi (all
    platforms).  Returns None when neither is present so the widget can hide.
    """
    if sys.platform == "linux":
        dev = _find_amd_device()
        if dev:
            return _read_amd(dev)
    return _read_nvidia()


# ── Widget ────────────────────────────────────────────────────────────────────

def _color_gpu(pct: int) -> str:
    if pct < 50:
        return "#4ade80"
    if pct < 80:
        return "#fbbf24"
    return "#f87171"


def _color_vram(used_mb: int, total_mb: int) -> str:
    if total_mb == 0:
        return "#6b7280"
    ratio = used_mb / total_mb
    if ratio < 0.70:
        return "#4ade80"
    if ratio < 0.90:
        return "#fbbf24"
    return "#f87171"


def _color_temp(t: int) -> str:
    if t < 0:
        return "#6b7280"
    if t < 70:
        return "#4ade80"
    if t < 85:
        return "#fbbf24"
    return "#f87171"

def _fmt_mb(mb: int) -> str:
    return f"{mb / 1024:.1f}G" if mb >= 1024 else f"{mb}M"


class _GpuPollThread(QThread):
    """Runs read_gpu_stats() off the main/UI thread.

    CREATE_NO_WINDOW (above) fixes the common case of nvidia-smi being slow
    specifically because Windows has to allocate/tear down a console for it
    on every call from a windowed (console-less) frozen build. But ANY
    source of per-call latency here -- antivirus scanning the freshly
    spawned process, driver query overhead, disk contention -- still blocks
    whichever thread calls read_gpu_stats(). At a 2-second poll interval,
    even occasional multi-hundred-ms stalls are a visible, recurring UI
    freeze if run on the main thread (confirmed: this was the exact
    "GPU polling makes the whole app intermittently unresponsive" bug from
    the very first test of a frozen build). Running it here instead means
    the worst nvidia-smi can do is make its OWN next poll late -- it can
    never block a button click, a keystroke, or anything else.
    """

    stats_ready = Signal(object)  # GpuStats | None

    def run(self) -> None:
        self.stats_ready.emit(read_gpu_stats())


class GpuMonitorWidget(QWidget):
    """Compact status-bar widget: GPU% · VRAM · Temp, updated every 2 s."""

    _POLL_MS = 2000

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 0, 2, 0)
        lay.setSpacing(0)

        self._lbl = QLabel()
        self._lbl.setStyleSheet("font-size: 11px;")
        lay.addWidget(self._lbl)

        # One-time synchronous probe at startup to decide whether a supported
        # GPU exists at all (hide the widget entirely if not). This runs once,
        # not on a 2s repeat, so it isn't the source of the recurring-freeze
        # bug above -- left synchronous to keep first-paint logic simple.
        stats = read_gpu_stats()
        if stats is None:
            self.setVisible(False)
            return

        self._apply(stats)

        self._poll_thread: Optional[_GpuPollThread] = None

        self._timer = QTimer(self)
        self._timer.setInterval(self._POLL_MS)
        self._timer.timeout.connect(self._poll)
        self._timer.start()

    def _poll(self) -> None:
        # Skip this tick if the previous poll is still in flight (a slow
        # nvidia-smi call delays its own next reading instead of stacking up
        # background threads or blocking anything).
        if self._poll_thread is not None and self._poll_thread.isRunning():
            return
        self._poll_thread = _GpuPollThread(self)
        self._poll_thread.stats_ready.connect(self._on_stats_ready)
        self._poll_thread.start()

    def _on_stats_ready(self, stats: Optional[GpuStats]) -> None:
        if stats:
            self._apply(stats)

    def _apply(self, s: GpuStats) -> None:
        gc = _color_gpu(s.utilization)
        vc = _color_vram(s.vram_used_mb, s.vram_total_mb)
        tc = _color_temp(s.temperature)

        used_str  = _fmt_mb(s.vram_used_mb)
        total_str = _fmt_mb(s.vram_total_mb)

        html = (
            f"<span style='color:{gc}'>GPU {s.utilization}%</span>"
            f"<span style='color:#555'> · </span>"
            f"<span style='color:{vc}'>{used_str}/{total_str}</span>"
        )
        if s.temperature >= 0:
            html += (
                f"<span style='color:#555'> · </span>"
                f"<span style='color:{tc}'>{s.temperature}°C</span>"
            )

        self._lbl.setText(html)
        self._lbl.setToolTip(
            f"GPU utilization:  {s.utilization}%\n"
            f"VRAM:             {used_str} / {total_str}\n"
            + (f"Temperature:      {s.temperature}°C" if s.temperature >= 0 else "")
        )
