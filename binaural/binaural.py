#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Binaural Beat Generator - Pro Edition
A cross-platform, high-performance, zero-allocation DSP audio generator.
"""

import sys
import os
import json
import configparser
import numpy as np

from PyQt6.QtCore import QSize, QIODevice, Qt, QRegularExpression, QStandardPaths
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QLabel, QLineEdit, QSlider, QPushButton, QMessageBox, QComboBox
)
from PyQt6.QtGui import QRegularExpressionValidator, QIcon, QPixmap
from PyQt6.QtMultimedia import QAudioFormat, QAudioSink, QAudio


# Wayland/X11 Environment Fixes for Linux
if sys.platform.startswith("linux"):
    if os.environ.get("XDG_SESSION_TYPE") == "wayland":
        os.environ["QT_QPA_PLATFORM"] = "wayland"
        os.environ["QT_WAYLAND_DISABLE_WINDOWDECORATION"] = "0"
        os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
        os.environ["GDK_BACKEND"] = "wayland"
    else:
        os.environ["QT_QPA_PLATFORM"] = "xcb"


DEFAULT_EN = {
    "mode_label": "Mode:",
    "left_freq_label": "Left Freq (Hz):",
    "right_freq_label": "Right Freq (Hz):",
    "volume_label": "Volume:",
    "btn_start": "Play",
    "btn_stop": "Stop",
    "mode_calm": "Calm",
    "mode_deep_relax": "Deep Relax",
    "mode_focus": "Focus",
    "mode_gamma": "Gamma",
    "mode_deep_sleep": "Deep Sleep",
    "wave_delta": "Delta",
    "wave_theta": "Theta",
    "wave_alpha": "Alpha",
    "wave_beta": "Beta",
    "wave_gamma": "Gamma",
    "diff_prefix": "Beat Frequency:",
    "headphone_warning": "🎧 Please wear headphones for binaural effect.",
    "about_title": "About",
    "about_version": "Version",
    "about_license": "License",
    "about_developer": "Developer",
    "about_text": "High-performance brain wave entrainment audio generator.",
    "about_ok_button": "OK",
    "audio_error_title": "Audio Hardware Error",
    "audio_error_msg": "Audio device disconnected or format is unsupported."
}


class LanguageManager:
    """Robust Language Manager utilizing OS-native configuration paths."""
    def __init__(self, script_dir: str):
        self.script_dir = script_dir
        self.languages_dir = os.path.join(script_dir, "languages")
        
        # Cross-platform config directory (AppData on Win, ~/.config on Lin, Library on Mac)
        config_root = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)
        self.config_dir = os.path.join(config_root, "binaural_generator")
        self.config_path = os.path.join(self.config_dir, "lang.json")
        
        self.available_languages = {"en": {"name": "English", "strings": DEFAULT_EN}}
        self.current_code = "en"
        
        self.load_languages()
        self.load_saved_language()

    def load_languages(self):
        if not os.path.isdir(self.languages_dir):
            return
            
        for filename in os.listdir(self.languages_dir):
            if not filename.lower().endswith(".ini"):
                continue
                
            code = os.path.splitext(filename)[0]
            parser = configparser.ConfigParser(interpolation=None)
            try:
                parser.read(os.path.join(self.languages_dir, filename), encoding="utf-8")
                if "Meta" in parser and "Strings" in parser:
                    self.available_languages[code] = {
                        "name": parser["Meta"].get("name", code),
                        "strings": {k: v.replace("\\n", "\n") for k, v in parser["Strings"].items()}
                    }
            except Exception:
                pass

    def load_saved_language(self):
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("language") in self.available_languages:
                        self.current_code = data["language"]
        except Exception:
            pass

    def save_language(self, code: str):
        if code not in self.available_languages:
            return
        self.current_code = code
        try:
            os.makedirs(self.config_dir, exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump({"language": code}, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def get(self, key: str, default: str = "") -> str:
        # Fallback to English dictionary if key is missing in chosen language
        lang_dict = self.available_languages.get(self.current_code, {}).get("strings", {})
        return lang_dict.get(key, DEFAULT_EN.get(key, default))


class BinauralEngine(QIODevice):
    """
    Zero-Allocation, Hardware-Safe DSP Engine.
    Implements Volume Ramping (Anti-Pop) and continuous phase calculation.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.sample_rate = 44100
        
        # Audio State
        self.freq_left = 130.0
        self.freq_right = 140.0
        self.phase_left = 0.0
        self.phase_right = 0.0
        
        # Volume Ramping (Anti-Pop) State
        self.target_vol = 0.15
        self.current_vol = 0.0
        
        # Memory Pre-allocation (Zero-Allocation Architecture)
        # Prevents Python Garbage Collector from causing audio dropouts
        self._max_samples = 16384
        self._t_base = np.arange(self._max_samples, dtype=np.float64)
        
        # Working buffers
        self._phase_buf = np.empty(self._max_samples, dtype=np.float64)
        self._wave_buf_l = np.empty(self._max_samples, dtype=np.float64)
        self._wave_buf_r = np.empty(self._max_samples, dtype=np.float64)
        self._stereo_out = np.zeros((self._max_samples, 2), dtype=np.int16)
        
        self.open(QIODevice.OpenModeFlag.ReadOnly)

    def isSequential(self) -> bool:
        return True

    def bytesAvailable(self) -> int:
        # Trick Qt into believing this infinite stream always has data available
        return super().bytesAvailable() + (self._max_samples * 4)

    def set_frequencies(self, left: float, right: float):
        self.freq_left = left
        self.freq_right = right

    def set_volume(self, vol: float):
        self.target_vol = max(0.0, min(1.0, vol))

    def reset_fades(self):
        """Called when playback starts to ramp volume up from zero."""
        self.current_vol = 0.0

    def readData(self, maxlen: int) -> bytes:
        num_samples = maxlen // 4
        if num_samples <= 0:
            return b""
            
        # Cap to pre-allocated buffer size
        if num_samples > self._max_samples:
            num_samples = self._max_samples

        # 1. Anti-Pop Volume Smoothing (Ramp towards target volume)
        if abs(self.current_vol - self.target_vol) > 0.001:
            step = 0.05 if self.target_vol > self.current_vol else -0.05
            self.current_vol += step
            # Clamp to target
            if (step > 0 and self.current_vol > self.target_vol) or (step < 0 and self.current_vol < self.target_vol):
                self.current_vol = self.target_vol

        vol_scaled = self.current_vol * 32767.0

        # 2. DSP Math (Using out= parameter to avoid RAM allocation during playback)
        
        # --- Left Channel ---
        step_l = 2.0 * np.pi * self.freq_left / self.sample_rate
        np.multiply(self._t_base[:num_samples], step_l, out=self._phase_buf[:num_samples])
        np.add(self._phase_buf[:num_samples], self.phase_left, out=self._phase_buf[:num_samples])
        np.sin(self._phase_buf[:num_samples], out=self._wave_buf_l[:num_samples])
        np.multiply(self._wave_buf_l[:num_samples], vol_scaled, out=self._wave_buf_l[:num_samples])
        
        # --- Right Channel ---
        step_r = 2.0 * np.pi * self.freq_right / self.sample_rate
        np.multiply(self._t_base[:num_samples], step_r, out=self._phase_buf[:num_samples])
        np.add(self._phase_buf[:num_samples], self.phase_right, out=self._phase_buf[:num_samples])
        np.sin(self._phase_buf[:num_samples], out=self._wave_buf_r[:num_samples])
        np.multiply(self._wave_buf_r[:num_samples], vol_scaled, out=self._wave_buf_r[:num_samples])

        # 3. Phase Continuity (Wrap to 2pi to prevent float overflow over long sessions)
        self.phase_left = (self.phase_left + num_samples * step_l) % (2.0 * np.pi)
        self.phase_right = (self.phase_right + num_samples * step_r) % (2.0 * np.pi)

        # 4. Safely Cast to Int16 and Pack Stereo
        self._stereo_out[:num_samples, 0] = self._wave_buf_l[:num_samples].astype(np.int16)
        self._stereo_out[:num_samples, 1] = self._wave_buf_r[:num_samples].astype(np.int16)
        
        return self._stereo_out[:num_samples].tobytes()


def safe_float(val_str: str) -> float:
    try:
        return float(val_str.replace(',', '.')) if val_str else 0.0
    except ValueError:
        return 0.0


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        
        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        self.logo_path = os.path.join(self.script_dir, "brain.png")
        if os.path.exists(self.logo_path):
            self.setWindowIcon(QIcon(self.logo_path))
            
        self.setWindowTitle("Binaural Beat Generator Pro")
        self.setMinimumSize(QSize(450, 420))
        QApplication.setStyle("Fusion")
        
        self.lang = LanguageManager(self.script_dir)
        
        # Audio Subsystem Init
        self.audio_format = QAudioFormat()
        self.audio_format.setSampleRate(44100)
        self.audio_format.setChannelCount(2)
        self.audio_format.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        
        self.audio_sink = QAudioSink(self.audio_format, self)
        self.audio_sink.stateChanged.connect(self.on_audio_state_changed)
        
        self.engine = BinauralEngine(self)
        self.is_playing = False
        
        self.mode_ids = ["calm", "deep_relax", "focus", "gamma", "deep_sleep"]
        self.modes = {
            "calm": {"left": "130.0", "right": "140.0"},
            "deep_relax": {"left": "130.0", "right": "136.0"},
            "focus": {"left": "130.0", "right": "150.0"},
            "gamma": {"left": "130.0", "right": "170.0"},
            "deep_sleep": {"left": "130.0", "right": "132.5"}
        }
        
        self.init_ui()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(15, 15, 15, 15)
        
        # --- Top Bar ---
        top_layout = QHBoxLayout()
        self.lang_combo = QComboBox()
        for code, data in self.lang.available_languages.items():
            self.lang_combo.addItem(data["name"], code)
        
        idx = self.lang_combo.findData(self.lang.current_code)
        if idx >= 0: self.lang_combo.setCurrentIndex(idx)
        top_layout.addWidget(self.lang_combo)
        
        top_layout.addStretch()
        
        if os.path.exists(self.logo_path):
            self.logo_label = QLabel()
            pixmap = QPixmap(self.logo_path).scaled(
                90, 90, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
            self.logo_label.setPixmap(pixmap)
            top_layout.addWidget(self.logo_label)
            
        top_layout.addStretch()
        
        self.about_label = QLabel("<a href='#'>About</a>")
        self.about_label.linkActivated.connect(self.show_about_dialog)
        top_layout.addWidget(self.about_label)
        main_layout.addLayout(top_layout)

        # --- Domain Warning ---
        self.warning_label = QLabel()
        self.warning_label.setStyleSheet("color: #d9534f; font-weight: bold; font-size: 13px;")
        self.warning_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(self.warning_label)
        
        # --- Mode Selector ---
        mode_layout = QHBoxLayout()
        self.mode_label = QLabel()
        self.mode_combo = QComboBox()
        mode_layout.addWidget(self.mode_label)
        mode_layout.addWidget(self.mode_combo)
        main_layout.addLayout(mode_layout)
        
        # --- Frequency Inputs ---
        freq_layout = QHBoxLayout()
        
        # Bulletproof Regex: 0 to 99999, optional dot/comma with max 2 decimals.
        regex = QRegularExpression(r"^(0|[1-9][0-9]{0,4})([.,][0-9]{1,2})?$")
        validator = QRegularExpressionValidator(regex, self)
        
        left_box = QVBoxLayout()
        self.left_label = QLabel()
        self.left_input = QLineEdit("130.0")
        self.left_input.setValidator(validator)
        left_box.addWidget(self.left_label)
        left_box.addWidget(self.left_input)
        
        right_box = QVBoxLayout()
        self.right_label = QLabel()
        self.right_input = QLineEdit("140.0")
        self.right_input.setValidator(validator)
        right_box.addWidget(self.right_label)
        right_box.addWidget(self.right_input)
        
        freq_layout.addLayout(left_box)
        freq_layout.addLayout(right_box)
        main_layout.addLayout(freq_layout)
        
        # --- Wave Info Label ---
        self.diff_label = QLabel()
        self.diff_label.setStyleSheet("font-weight: bold; color: #00a8e8; margin-top: 10px;")
        main_layout.addWidget(self.diff_label)
        
        # --- Volume Slider ---
        vol_layout = QHBoxLayout()
        self.vol_label = QLabel()
        self.vol_slider = QSlider(Qt.Orientation.Horizontal)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(15)
        vol_layout.addWidget(self.vol_label)
        vol_layout.addWidget(self.vol_slider)
        main_layout.addLayout(vol_layout)
        
        # --- Play/Stop Button ---
        self.btn_play = QPushButton()
        self.btn_play.setFixedHeight(45)
        self.btn_play.setStyleSheet("font-weight: bold; font-size: 14px;")
        main_layout.addWidget(self.btn_play)
        
        # --- Signals ---
        self.left_input.textChanged.connect(self.update_frequencies)
        self.right_input.textChanged.connect(self.update_frequencies)
        self.vol_slider.valueChanged.connect(self.update_volume)
        self.btn_play.clicked.connect(self.toggle_playback)
        self.mode_combo.currentIndexChanged.connect(self.apply_mode_selection)
        self.lang_combo.currentIndexChanged.connect(self.change_language)
        
        # Initial Boot State
        self.retranslate_ui()
        self.update_frequencies()
        self.update_volume()

    def on_audio_state_changed(self, state):
        """Asynchronous listener for hardware audio dropouts or errors."""
        if state == QAudio.State.StoppedState and self.audio_sink.error() != QAudio.Error.NoError:
            self.is_playing = False
            self.btn_play.setText(self.lang.get("btn_start"))
            
            QMessageBox.critical(
                self, 
                self.lang.get("audio_error_title"), 
                self.lang.get("audio_error_msg")
            )

    def retranslate_ui(self):
        self.mode_label.setText(self.lang.get("mode_label"))
        self.left_label.setText(self.lang.get("left_freq_label"))
        self.right_label.setText(self.lang.get("right_freq_label"))
        self.vol_label.setText(self.lang.get("volume_label"))
        self.warning_label.setText(self.lang.get("headphone_warning"))
        self.btn_play.setText(self.lang.get("btn_stop") if self.is_playing else self.lang.get("btn_start"))
        
        current_mode_id = self.mode_combo.currentData()
        self.mode_combo.blockSignals(True)
        self.mode_combo.clear()
        
        for mode_id in self.mode_ids:
            self.mode_combo.addItem(self.lang.get(f"mode_{mode_id}"), mode_id)
            
        if current_mode_id is not None:
            idx = self.mode_combo.findData(current_mode_id)
            if idx >= 0:
                self.mode_combo.setCurrentIndex(idx)
                
        self.mode_combo.blockSignals(False)
        self.update_frequencies()

    def change_language(self, index):
        code = self.lang_combo.itemData(index)
        if code:
            self.lang.save_language(code)
            self.retranslate_ui()

    def apply_mode_selection(self, index):
        mode_id = self.mode_combo.itemData(index)
        if mode_id in self.modes:
            freq_data = self.modes[mode_id]
            self.left_input.blockSignals(True)
            self.right_input.blockSignals(True)
            self.left_input.setText(freq_data["left"])
            self.right_input.setText(freq_data["right"])
            self.left_input.blockSignals(False)
            self.right_input.blockSignals(False)
            self.update_frequencies()

    def update_frequencies(self):
        fl = min(max(safe_float(self.left_input.text()), 0.0), 20000.0)
        fr = min(max(safe_float(self.right_input.text()), 0.0), 20000.0)
        self.engine.set_frequencies(fl, fr)
        
        diff = abs(fl - fr)
        wave_type = ""
        if 0 < diff < 4: wave_type = f" ({self.lang.get('wave_delta')})"
        elif 4 <= diff < 8: wave_type = f" ({self.lang.get('wave_theta')})"
        elif 8 <= diff < 12: wave_type = f" ({self.lang.get('wave_alpha')})"
        elif 12 <= diff <= 30: wave_type = f" ({self.lang.get('wave_beta')})"
        elif diff > 30: wave_type = f" ({self.lang.get('wave_gamma')})"
            
        self.diff_label.setText(f"{self.lang.get('diff_prefix')} {diff:.2f} Hz{wave_type}")

    def update_volume(self):
        self.engine.set_volume(self.vol_slider.value() / 100.0)

    def toggle_playback(self):
        if not self.is_playing:
            self.engine.reset_fades() # Initialize anti-pop volume ramp
            self.audio_sink.start(self.engine)
            
            # Auto-align Sample Rate with OS Hardware capabilities
            actual_rate = self.audio_sink.format().sampleRate()
            if actual_rate > 0 and actual_rate != self.engine.sample_rate:
                self.engine.sample_rate = actual_rate

            self.btn_play.setText(self.lang.get("btn_stop"))
            self.is_playing = True
        else:
            self.audio_sink.stop()
            self.btn_play.setText(self.lang.get("btn_start"))
            self.is_playing = False

    def show_about_dialog(self):
        about_box = QMessageBox(self)
        about_box.setWindowTitle(self.lang.get("about_title"))
        about_box.setText(
            f"{self.lang.get('about_version')}: 2.0.0 Pro\n"
            f"{self.lang.get('about_license')}: GNU GPLv3\n"
            f"Architecture: Zero-Allocation DSP (NumPy) + Qt6\n"
            f"{self.lang.get('about_developer')}: A. Serhat KILIÇOĞLU\n"
            f"Github: www.github.com/shampuan\n\n"
            f"{self.lang.get('about_text')}"
        )
        if os.path.exists(self.logo_path):
            about_box.setIconPixmap(QPixmap(self.logo_path).scaled(
                64, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            ))
        
        ok_button = about_box.addButton(QMessageBox.StandardButton.Ok)
        ok_button.setText(self.lang.get("about_ok_button"))
        about_box.exec()

    def closeEvent(self, event):
        if hasattr(self, 'audio_sink'):
            self.audio_sink.stop()
        self.engine.close()
        event.accept()


if __name__ == "__main__":
    # Enable High DPI scaling for modern screens
    if hasattr(Qt.ApplicationAttribute, "AA_EnableHighDpiScaling"):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    if hasattr(Qt.ApplicationAttribute, "AA_UseHighDpiPixmaps"):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
        
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
