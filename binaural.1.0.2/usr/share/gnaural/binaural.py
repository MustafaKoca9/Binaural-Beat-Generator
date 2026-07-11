#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import math
import struct
import os
import json
import configparser
from PyQt6.QtCore import QSize, QByteArray, QBuffer, QIODevice, Qt, QThread
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QLabel, QLineEdit, QSlider, QPushButton, QMessageBox, QComboBox
)
from PyQt6.QtGui import QIntValidator, QIcon, QPixmap
from PyQt6.QtMultimedia import QAudioFormat, QAudioOutput


# Gnome ve Wayland ortamlarında kararlı Qt6 çalışması için gelişmiş yapılandırma
if os.environ.get("XDG_SESSION_TYPE") == "wayland":
    os.environ["QT_QPA_PLATFORM"] = "wayland"
    os.environ["QT_WAYLAND_DISABLE_WINDOWDECORATION"] = "0"
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
    os.environ["GDK_BACKEND"] = "wayland"
else:
    os.environ["QT_QPA_PLATFORM"] = "xcb"

class LanguageManager:
    """
    Program dilini yönetir: script dizinindeki languages/ klasöründeki .ini
    dosyalarını okur, seçili dili ~/.config/binaural/lang.json içinde saklar.
    """

    def __init__(self, script_dir):
        self.script_dir = script_dir
        self.languages_dir = os.path.join(script_dir, "languages")
        self.config_dir = os.path.join(os.path.expanduser("~"), ".config", "binaural")
        self.config_path = os.path.join(self.config_dir, "lang.json")

        self.available_languages = {}  # {"tr": {"name": "Türkçe", "strings": {...}}, ...}
        self.current_code = "en"

        self.load_languages()
        self.load_saved_language()

    def load_languages(self):
        self.available_languages = {}
        if not os.path.isdir(self.languages_dir):
            return

        for filename in os.listdir(self.languages_dir):
            if not filename.lower().endswith(".ini"):
                continue

            code = os.path.splitext(filename)[0]
            filepath = os.path.join(self.languages_dir, filename)

            parser = configparser.ConfigParser(interpolation=None)
            try:
                parser.read(filepath, encoding="utf-8")
            except Exception:
                continue

            if "Meta" not in parser or "Strings" not in parser:
                continue

            name = parser["Meta"].get("name", code)
            strings = {
                key: value.replace("\\n", "\n")
                for key, value in parser["Strings"].items()
            }

            self.available_languages[code] = {
                "name": name,
                "strings": strings
            }

    def load_saved_language(self):
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                saved_code = data.get("language")
                if saved_code in self.available_languages:
                    self.current_code = saved_code
                    return
        except Exception:
            pass

        # Kayıtlı ayar yoksa ya da geçersizse: İngilizce'yi öntanımlı yap
        if "en" in self.available_languages:
            self.current_code = "en"
        elif self.available_languages:
            self.current_code = next(iter(self.available_languages))

    def save_language(self, code):
        self.current_code = code
        try:
            os.makedirs(self.config_dir, exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump({"language": code}, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def get(self, key, default=""):
        lang_data = self.available_languages.get(self.current_code)
        if lang_data:
            value = lang_data["strings"].get(key)
            if value is not None:
                return value
        return default


class BinauralWorker(QThread):
    def __init__(self, audio_format):
        super().__init__()
        self.audio_format = audio_format
        self.sample_rate = audio_format.sampleRate()
        self.freq_left = 130.0
        self.freq_right = 140.0
        
        # Hedef ses seviyesi ve anlık ses seviyesi (Ramp mekanizması için)
        self.target_volume = 0.15
        self.current_volume = 0.0
        
        self.phase_left = 0.0
        self.phase_right = 0.0
        self.running = False

    def set_frequencies(self, left, right):
        self.freq_left = float(left)
        self.freq_right = float(right)

    def set_volume(self, vol):
        self.target_volume = float(vol)

    def stop_worker(self):
        # Sesi yumuşakça sıfıra çekelim
        self.target_volume = 0.0
        # Ramp mekanizmasının sesi sıfırlaması için döngüye zaman tanıyalım
        self.msleep(30)
        # Döngüyü kırıp thread'i sonlandıralım
        self.running = False
        self.wait()

    def run(self):
        from PyQt6.QtMultimedia import QAudioSink, QMediaDevices
        
        current_device = QMediaDevices.defaultAudioOutput()
        audio_sink = QAudioSink(current_device, self.audio_format)
        
        # Donanım tampon boyutunu küçük tutarak gecikmeyi azaltalım (örn: 0.1 saniye)
        audio_sink.setBufferSize(int(self.sample_rate * 0.1 * 4))
        
        io_device = audio_sink.start()
        if not io_device:
            return

        self.running = True
        
        while self.running:
            # Ses kartı tamponundaki boş alanı bayt cinsinden alalım
            free_bytes = audio_sink.bytesFree()
            
            # Eğer tampon zaten doluysa bekleyip döngüye devam edelim
            if free_bytes < 1024:
                self.msleep(10)
                continue
                
            # Boş alanı 4 baytlık (Sol 16bit + Sağ 16bit) örneklere hizalayalım
            num_samples = free_bytes // 4
            
            data = bytearray()
            for _ in range(num_samples):
                # Ses seviyesini yumuşakça yaklaştırıyoruz (Ramp)
                if self.current_volume < self.target_volume:
                    self.current_volume += 0.001
                    if self.current_volume > self.target_volume:
                        self.current_volume = self.target_volume
                elif self.current_volume > self.target_volume:
                    self.current_volume -= 0.001
                    if self.current_volume < self.target_volume:
                        self.current_volume = self.target_volume

                # Sol kanal sinüs hesabı
                val_left = math.sin(self.phase_left) * self.current_volume * 32000
                self.phase_left += 2 * math.pi * self.freq_left / self.sample_rate
                if self.phase_left >= 2 * math.pi:
                    self.phase_left -= 2 * math.pi
                    
                # Sağ kanal sinüs hesabı
                val_right = math.sin(self.phase_right) * self.current_volume * 32000
                self.phase_right += 2 * math.pi * self.freq_right / self.sample_rate
                if self.phase_right >= 2 * math.pi:
                    self.phase_right -= 2 * math.pi

                v_l = max(-32768, min(32767, int(val_left)))
                v_r = max(-32768, min(32767, int(val_right)))
                data.extend(struct.pack('<hh', v_l, v_r))
            
            if io_device.isOpen() and io_device.isWritable():
                io_device.write(bytes(data))
            
            self.msleep(10)
            
        audio_sink.stop()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        
        # Logo dosyası yolu tanımlaması
        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        self.logo_path = os.path.join(self.script_dir, "brain.png")
        
        # Pencere ikonu ayarı
        if os.path.exists(self.logo_path):
            self.setWindowIcon(QIcon(self.logo_path))
            
        self.setWindowTitle("Binaural Beat Generator")
        self.setFixedSize(QSize(420, 320))
        
        # Qt'nin tercih ettiğimiz Fusion stilini uygulayalım
        QApplication.setStyle("Fusion")
        
        # Dil yöneticisi (languages/ dizinini okur, lang.json'u yükler)
        self.lang = LanguageManager(self.script_dir)
        
        # Audio ayarları
        self.audio_format = QAudioFormat()
        self.audio_format.setSampleRate(44100)
        self.audio_format.setChannelCount(2)
        self.audio_format.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        
        self.worker = None
        self.is_playing = False
        
        # Mod verileri artık dil bağımsız ID'ler ile tutuluyor.
        # Görünen isimler dil dosyalarındaki mode_xxx anahtarlarından geliyor.
        self.mode_ids = ["calm", "deep_relax", "focus", "gamma", "deep_sleep"]
        self.modes = {
            "calm": {"left": "130", "right": "140"},
            "deep_relax": {"left": "130", "right": "136"},
            "focus": {"left": "130", "right": "150"},
            "gamma": {"left": "130", "right": "170"},
            "deep_sleep": {"left": "130", "right": "132.5"}
        }
        self.init_ui()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # Dil Seçimi, Logo ve Hakkında Alanı (üst satır)
        top_layout = QHBoxLayout()
        
        self.lang_combo = QComboBox()
        for code, data in self.lang.available_languages.items():
            self.lang_combo.addItem(data["name"], code)
        current_index = self.lang_combo.findData(self.lang.current_code)
        if current_index >= 0:
            self.lang_combo.setCurrentIndex(current_index)
        top_layout.addWidget(self.lang_combo)
        
        top_layout.addStretch()
        
        if os.path.exists(self.logo_path):
            self.logo_label = QLabel()
            pixmap = QPixmap(self.logo_path).scaled(100, 100, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.logo_label.setPixmap(pixmap)
            self.logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            top_layout.addWidget(self.logo_label)
            
        top_layout.addStretch()
        
        # Hakkında Linki - bu etiket her dilde "About" olarak sabit kalır, çeviriye dahil değildir.
        self.about_label = QLabel("<a href='#'>About</a>")
        self.about_label.setOpenExternalLinks(False)
        self.about_label.linkActivated.connect(self.show_about_dialog)
        top_layout.addWidget(self.about_label)
        
        main_layout.addLayout(top_layout)
        
        # Mod Seçim Alanı
        mode_layout = QHBoxLayout()
        self.mode_label = QLabel()
        self.mode_combo = QComboBox()
        mode_layout.addWidget(self.mode_label)
        mode_layout.addWidget(self.mode_combo)
        main_layout.addLayout(mode_layout)
        
        # Frekans Girişleri (Sol - Sağ)
        freq_layout = QHBoxLayout()
        
        # Sadece tam sayı girişine izin verelim (Güvenli aralık 20-20000 Hz)
        validator = QIntValidator(20, 20000, self)
        
        # Sol Kanal UI
        left_box = QVBoxLayout()
        self.left_label = QLabel()
        self.left_input = QLineEdit("130")
        self.left_input.setValidator(validator)
        left_box.addWidget(self.left_label)
        left_box.addWidget(self.left_input)
        
        # Sağ Kanal UI
        right_box = QVBoxLayout()
        self.right_label = QLabel()
        self.right_input = QLineEdit("140")
        self.right_input.setValidator(validator)
        right_box.addWidget(self.right_label)
        right_box.addWidget(self.right_input)
        
        freq_layout.addLayout(left_box)
        freq_layout.addLayout(right_box)
        main_layout.addLayout(freq_layout)
        
        # Fark Bilgisi Ekranı
        self.diff_label = QLabel()
        self.diff_label.setStyleSheet("font-weight: bold; color: #00a8e8; margin-top: 10px;")
        main_layout.addWidget(self.diff_label)
        
        # Ses Sürgüsü (Volume)
        vol_layout = QHBoxLayout()
        self.vol_label = QLabel()
        self.vol_slider = QSlider()
        self.vol_slider.setOrientation(self.vol_slider.orientation().Horizontal)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(15)
        vol_layout.addWidget(self.vol_label)
        vol_layout.addWidget(self.vol_slider)
        main_layout.addLayout(vol_layout)
        
        # Oynat / Durdur Butonu
        self.btn_play = QPushButton()
        self.btn_play.setFixedHeight(40)
        main_layout.addWidget(self.btn_play)
        
        # Sinyaller ve Slotlar
        self.left_input.textChanged.connect(self.update_frequencies)
        self.right_input.textChanged.connect(self.update_frequencies)
        self.vol_slider.valueChanged.connect(self.update_volume)
        self.btn_play.clicked.connect(self.toggle_playback)
        self.mode_combo.currentIndexChanged.connect(self.apply_mode_selection)
        self.lang_combo.currentIndexChanged.connect(self.change_language)
        
        # Metinleri aktif dile göre doldur (mod combo dahil)
        self.retranslate_ui()
        
        # İlk değerleri motora gönder
        self.update_frequencies()
        self.update_volume()

    def retranslate_ui(self):
        # Sabit kalan öğeler (pencere başlığı, "About" linki) burada değiştirilmez.
        self.mode_label.setText(self.lang.get("mode_label"))
        self.left_label.setText(self.lang.get("left_freq_label"))
        self.right_label.setText(self.lang.get("right_freq_label"))
        self.vol_label.setText(self.lang.get("volume_label"))
        self.btn_play.setText(self.lang.get("btn_stop") if self.is_playing else self.lang.get("btn_start"))
        
        # Mod combo içeriğini, seçili öğeyi koruyarak yeniden doldur
        current_mode_id = self.mode_combo.currentData()
        self.mode_combo.blockSignals(True)
        self.mode_combo.clear()
        for mode_id in self.mode_ids:
            display_text = self.lang.get(f"mode_{mode_id}")
            self.mode_combo.addItem(display_text, mode_id)
        if current_mode_id is not None:
            idx = self.mode_combo.findData(current_mode_id)
            if idx >= 0:
                self.mode_combo.setCurrentIndex(idx)
        self.mode_combo.blockSignals(False)
        
        # Fark etiketini güncel dile göre yeniden hesapla
        self.update_frequencies()

    def change_language(self, index):
        code = self.lang_combo.itemData(index)
        if not code:
            return
        self.lang.save_language(code)
        self.retranslate_ui()

    def apply_mode_selection(self, index):
        mode_id = self.mode_combo.itemData(index)
        if mode_id in self.modes:
            freq_data = self.modes[mode_id]
            # Sinyal döngüsünü engellemek için anlık olarak textChanged sinyallerini bloklayalım
            self.left_input.blockSignals(True)
            self.right_input.blockSignals(True)
            
            self.left_input.setText(freq_data["left"])
            self.right_input.setText(freq_data["right"])
            
            self.left_input.blockSignals(False)
            self.right_input.blockSignals(False)
            
            # Değişiklikleri motora işlet ve etiketi güncelle
            self.update_frequencies()

    def toggle_playback(self):
        if not self.is_playing:
            # Oynatmayı başlat: Yeni bir Worker Thread yaratıyoruz
            self.worker = BinauralWorker(self.audio_format)
            
            # İlk frekans ve ses değerlerini gönderiyoruz
            self.update_frequencies()
            self.update_volume()
            
            self.worker.start()
            self.btn_play.setText(self.lang.get("btn_stop"))
            self.is_playing = True
        else:
            # Oynatmayı durdur: Arka plan thread'ini yumuşakça kapatıyoruz
            if self.worker and self.worker.isRunning():
                self.worker.stop_worker()
                self.worker = None
            self.btn_play.setText(self.lang.get("btn_start"))
            self.is_playing = False

    def update_frequencies(self):
        left_text = self.left_input.text()
        right_text = self.right_input.text()
        
        fl = float(left_text) if left_text else 0.0
        fr = float(right_text) if right_text else 0.0
        
        # Eğer arka planda motor aktifse değerleri canlı olarak gönder
        if self.worker:
            self.worker.set_frequencies(fl, fr)
        
        diff = abs(fl - fr)
        wave_type = ""
        if 0.5 <= diff < 4: wave_type = f" (Delta - {self.lang.get('wave_delta')})"
        elif 4 <= diff < 8: wave_type = f" (Theta - {self.lang.get('wave_theta')})"
        elif 8 <= diff < 12: wave_type = f" (Alfa - {self.lang.get('wave_alpha')})"
        elif 12 <= diff <= 30: wave_type = f" (Beta - {self.lang.get('wave_beta')})"
        elif diff > 30: wave_type = f" (Gamma - {self.lang.get('wave_gamma')})"
        
        prefix = self.lang.get("diff_prefix")
        self.diff_label.setText(f"{prefix} {diff:.1f} Hz{wave_type}")

    def update_volume(self):
        val = self.vol_slider.value() / 100.0
        if self.worker:
            self.worker.set_volume(val)

    def show_about_dialog(self):
        about_box = QMessageBox(self)
        about_box.setWindowTitle(self.lang.get("about_title"))
        
        # Yeni eklenen meta bilgiler ve mevcut açıklama metni birleştiriliyor
        about_details = (
            f"{self.lang.get('about_version')}: 1.0.2\n"
            f"{self.lang.get('about_license')}: GNU GPLv3\n"
            f"GUI/UX: Python Qt6\n"
            f"{self.lang.get('about_developer')}: A. Serhat KILIÇOĞLU (shampuan)\n"
            f"Github: www.github.com/shampuan\n\n"
            f"{self.lang.get('about_text')}"
        )
        
        about_box.setText(about_details)
        
        if os.path.exists(self.logo_path):
            about_box.setIconPixmap(QPixmap(self.logo_path).scaled(48, 48, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            
        # Standart Tamam butonu
        about_box.setStandardButtons(QMessageBox.StandardButton.Ok)
        ok_button = about_box.button(QMessageBox.StandardButton.Ok)
        if ok_button:
            ok_button.setText(self.lang.get("about_ok_button"))
            
        about_box.exec()
        
    def closeEvent(self, event):
        # Program kapatılırken ses motoru aktifse önce onu temiz bir şekilde durduruyoruz
        if self.worker and self.worker.isRunning():
            self.worker.stop_worker()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
