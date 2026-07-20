# Binaural-Beat-Generator (Pro Edition)

A high-performance, cross-platform binaural audio simulator utilizing a Zero-Allocation DSP Engine.

This program was developed to simulate the effects of specific sound frequencies on the human brain. By playing slightly different sine wave frequencies into the left and right ears, a third, perceived frequency equal to the difference between the two (e.g. a 10 Hz Alpha wave) is created in the brain.

This method is based on scientific research (Heinrich Wilhelm Dove, 1839, and modern EEG studies) exploring the synchronization of brainwaves, increasing focus, reducing stress, and promoting deep relaxation.

## 🚀 Pro Edition Features

Unlike standard audio players, this fork has been deeply optimized for true Digital Signal Processing (DSP) standards:

*   **⚡ Zero-Allocation DSP Engine:** Uses advanced NumPy vectorization (`out=` parameters) with pre-allocated memory buffers. This bypasses the Python Garbage Collector, ensuring 0% RAM leakage and microsecond-level, stutter-free continuous audio.
*   **🔊 Hardware Anti-Pop Ramping:** Implements logarithmic volume ramping when starting or stopping playback. This prevents sudden DC-offset spikes (the "pop" or "click" sound) and protects your hardware/ears.
*   **🛡️ Asynchronous Audio Polling:** Real-time Qt6 hardware state listeners instantly detect if your audio device drops out (e.g., Bluetooth headphones disconnecting) and stops playback safely.
*   **🌍 True Cross-Platform:** Originally for Debian, now perfectly native on Windows, macOS, and Linux (with advanced Wayland & X11 environment detection). Configuration files are now securely saved in OS-native paths via `QStandardPaths`.
*   **🛡️ Bulletproof UI:** Strict Regex validators prevent crashes from invalid float inputs (unlimited decimals supported natively).

## 📸 Screenshots

<img width="430" height="354" alt="Screenshot 1" src="https://github.com/user-attachments/assets/7a64f778-b59e-418b-ac24-14c8152ecfa5" />
<img width="430" height="354" alt="Screenshot 2" src="https://github.com/user-attachments/assets/ea829182-af3e-4fcb-8257-38ee2d53d33b" />

*(🎧 Note: You MUST wear stereo headphones to experience the binaural effect.)*

## 🛠️ Installation & Requirements

This software requires **Python 3**, **PyQt6** for the GUI/Audio sink, and **NumPy** for the DSP engine.

1. Clone the repository:
   ```bash
   git clone https://github.com/MustafaKoca9/Binaural-Beat-Generator.git
   cd Binaural-Beat-Generator