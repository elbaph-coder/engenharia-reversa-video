"""Golpes de uma música: os instantes em que o som bate (bumbo, caixa, palma), com a força de cada um.

Serve para pôr efeitos na batida real (clarão, pulso, corte) em vez de numa grade de BPM.
  python scripts/golpes.py <audio> [--saida=<json>] [--min=0.25] [--sens=1.5]
Saída (JSON): { "duracao": s, "golpes": [[t, forca], ...] } — t em s, forca 0..1 (1 = o mais forte da música).
Também imprime a sonoridade por trecho de 5 s (para achar intro, partes e o fim do som).
Método: ffmpeg → mono 22 050 Hz; fluxo espectral nas graves+médias (≤ 4 kHz); pico acima da média móvel × sens,
separados por pelo menos `--min` s.
"""
import json
import subprocess
import sys

import numpy as np
from scipy.signal import find_peaks

args = [a for a in sys.argv[1:] if not a.startswith("--")]
opts = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
if not args:
    sys.exit(__doc__)
SR = 22050
bruto = subprocess.run(
    ["ffmpeg", "-v", "error", "-i", args[0], "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"], capture_output=True, check=True
).stdout
x = np.frombuffer(bruto, np.float32)
dur = len(x) / SR

HOP, N = 256, 1024
quadros = np.lib.stride_tricks.sliding_window_view(x, N)[::HOP] * np.hanning(N)
mag = np.abs(np.fft.rfft(quadros, axis=1))[:, : int(4000 / (SR / N))]
fluxo = np.maximum(np.diff(np.log1p(mag), axis=0), 0).sum(axis=1)
fluxo = np.concatenate([[0], fluxo])
tq = np.arange(len(fluxo)) * HOP / SR

media = np.convolve(fluxo, np.ones(43) / 43, mode="same")  # ~0,5 s
sens = float(opts.get("sens", 1.5))
picos, _ = find_peaks(fluxo, height=media * sens, distance=max(1, int(float(opts.get("min", 0.25)) * SR / HOP)))
forca = fluxo[picos] / np.percentile(fluxo[picos], 98)
golpes = [[round(float(tq[p]), 3), round(float(min(1, f)), 3)] for p, f in zip(picos, forca)]

blocos = x[: len(x) // (SR * 5) * SR * 5].reshape(-1, SR * 5)
rms = np.sqrt((blocos**2).mean(axis=1))
print(f"duração {dur:.2f} s · {len(golpes)} golpes · intervalo mediano {np.median(np.diff([g[0] for g in golpes])):.3f} s")
print("sonoridade (dB) a cada 5 s:", " ".join(f"{i*5}:{20*np.log10(r+1e-9):.0f}" for i, r in enumerate(rms)))
saida = opts.get("saida")
if saida:
    with open(saida, "w", encoding="utf-8") as f:
        json.dump({"duracao": round(dur, 3), "golpes": golpes}, f)
    print("salvo em", saida)
