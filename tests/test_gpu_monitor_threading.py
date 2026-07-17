"""Regression test: the GPU monitor status-bar widget was blocking the main
UI thread every 2 seconds by calling nvidia-smi synchronously via
subprocess.run() inside a QTimer callback. On a frozen (PyInstaller,
windowed/console-less) build, Windows has to allocate/tear down a console
for the nvidia-smi child process on every call since the parent has none of
its own -- this was slow enough, at a 2-second poll interval, to make the
whole app feel intermittently unresponsive/frozen (confirmed: this is the
exact bug reported from the very first test of a built .exe).

Two fixes, mirroring the same pattern already applied to
gui/ollama_control.py's restart-command launch:
  1. CREATE_NO_WINDOW + stdin=DEVNULL on the nvidia-smi subprocess call.
  2. The repeating poll now runs on a background QThread instead of the
     main thread, so even a slow/stalled nvidia-smi call (antivirus
     scanning, driver query overhead, disk contention -- anything CREATE_NO_
     WINDOW doesn't fix) can only delay its own next reading, never block
     a keystroke or button click.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).parent.parent))

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

import gui.gpu_monitor as gm  # noqa: E402


def test_nvidia_smi_call_suppresses_console_on_windows():
    captured = {}

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        class R:
            returncode = 0
            stdout = "10, 1000, 16000, 45\n"
        return R()

    with patch.object(gm.subprocess, "run", fake_run), \
         patch.object(gm.sys, "platform", "win32"):
        stats = gm._read_nvidia()

    assert captured["creationflags"] == 0x08000000  # CREATE_NO_WINDOW
    assert captured["stdin"] == gm.subprocess.DEVNULL
    assert stats == gm.GpuStats(10, 1000, 16000, 45)


def test_nvidia_smi_call_uses_no_special_flags_off_windows():
    captured = {}

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        class R:
            returncode = 0
            stdout = "10, 1000, 16000, 45\n"
        return R()

    with patch.object(gm.subprocess, "run", fake_run), \
         patch.object(gm.sys, "platform", "linux"):
        gm._read_nvidia()

    assert captured["creationflags"] == 0


def test_repeated_polling_runs_off_the_main_thread():
    with patch.object(gm, "read_gpu_stats", return_value=gm.GpuStats(10, 1000, 16000, 45)):
        widget = gm.GpuMonitorWidget()

    thread_ids = []

    def slow_read():
        thread_ids.append(threading.get_ident())
        time.sleep(0.2)
        return gm.GpuStats(20, 2000, 16000, 50)

    main_thread_id = threading.get_ident()
    with patch.object(gm, "read_gpu_stats", side_effect=slow_read):
        widget._poll()
        t0 = time.time()
        while widget._poll_thread.isRunning() and time.time() - t0 < 2:
            app.processEvents()
            time.sleep(0.01)
        app.processEvents()

    assert thread_ids, "read_gpu_stats was never called"
    assert thread_ids[0] != main_thread_id


def test_overlapping_poll_is_skipped_not_stacked():
    with patch.object(gm, "read_gpu_stats", return_value=gm.GpuStats(10, 1000, 16000, 45)):
        widget = gm.GpuMonitorWidget()

    class _StillRunning:
        def isRunning(self):
            return True

    sentinel = _StillRunning()
    widget._poll_thread = sentinel
    widget._poll()
    assert widget._poll_thread is sentinel  # no new thread was started


def test_stats_ready_updates_label_text():
    with patch.object(gm, "read_gpu_stats", return_value=gm.GpuStats(10, 1000, 16000, 45)):
        widget = gm.GpuMonitorWidget()

    widget._on_stats_ready(gm.GpuStats(77, 15000, 16000, 80))
    assert "77%" in widget._lbl.text()


def test_widget_hides_when_no_gpu_detected():
    with patch.object(gm, "read_gpu_stats", return_value=None):
        widget = gm.GpuMonitorWidget()
    assert widget.isVisible() is False
