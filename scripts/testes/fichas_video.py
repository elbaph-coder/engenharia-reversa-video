"""Vídeo sintético para o teste das medidas prontas do `npm run estudo` (scripts/testes/fichas.test.mjs).
    python -P scripts/testes/fichas_video.py <pasta do estudo>
Cria <pasta>/fonte/ref.mp4 — 720×1280, 30 qps, 90 quadros (3 s), com áudio:
  q0–44   fundo escuro; "PALAVRA" branca nasce letra a letra, esquerda→direita, a partir de q10 (uma a cada 2 q), parada;
          quadradinho vermelho (acento) no canto; "JUNTA" nasce inteira em q22 com as letras afastadas (+36 px entre elas)
          e se junta até q28, borda direita parada; "ESTICA" nasce inteira em q24 espremida (scaleX 0,6) e se abre até q30
          para os dois lados
  q45     corte seco para fundo creme; "ENTRA" escura entra pela borda direita em q50 e desliza até x=150 em q70 com
          Easing.bezier(0.2, 0.8, 0.2, 1); cartão azul desce de y=1000 a y=800 a partir de q55 com spring(damping 12,
          stiffness 150, mass 1)
  áudio   um estalo a cada 0,5 s (120 BPM) desde 0 s — o corte (1,5 s) cai num golpe
e <pasta>/verdade.json com o que o teste espera.
"""
import json
import subprocess
import sys
import wave
from pathlib import Path

import cv2
import numpy as np

pasta = Path(sys.argv[1])
(pasta / "fonte").mkdir(parents=True, exist_ok=True)
W, H, N, FPS = 720, 1280, 90, 30
FONTE = cv2.FONT_HERSHEY_DUPLEX
ESCURO, CREME = (46, 30, 30), (205, 225, 235)  # BGR
VERMELHO, AZUL = (30, 30, 220), (200, 80, 40)


def bezier(t, x1, y1, x2, y2):
    s = np.linspace(0, 1, 2001)
    bx = 3 * (1 - s) ** 2 * s * x1 + 3 * (1 - s) * s ** 2 * x2 + s ** 3
    by = 3 * (1 - s) ** 2 * s * y1 + 3 * (1 - s) * s ** 2 * y2 + s ** 3
    return float(np.interp(t, bx, by))


def junta(f, q):
    """JUNTA letra por letra, borda direita em x=630, espaço extra entre letras de 36 px (q22) a 0 (q28)"""
    extra = 36 * (1 - min(1, (q - 22) / 6)) ** 2
    ws = [cv2.getTextSize(c, FONTE, 2, 6)[0][0] for c in "JUNTA"]
    x = 630 - sum(ws) - 4 * extra
    for c, w in zip("JUNTA", ws):
        cv2.putText(f, c, (int(round(x)), 760), FONTE, 2, (240, 240, 240), 6, cv2.LINE_AA)
        x += w + extra


def estica(f, q):
    """ESTICA desenhada inteira e espremida na horizontal (scaleX 0,6 em q24 → 1 em q30), centro em x=360"""
    (w, h), base = cv2.getTextSize("ESTICA", FONTE, 2, 6)
    img = np.zeros((h + base + 12, w + 12, 3), np.uint8)
    cv2.putText(img, "ESTICA", (6, h + 6), FONTE, 2, (240, 240, 240), 6, cv2.LINE_AA)
    sx = 0.6 + 0.4 * min(1, (q - 24) / 6)
    img = cv2.resize(img, (max(1, int(round(img.shape[1] * sx))), img.shape[0]), interpolation=cv2.INTER_AREA)
    x0, y0 = 360 - img.shape[1] // 2, 900
    roi = f[y0:y0 + img.shape[0], x0:x0 + img.shape[1]]
    np.maximum(roi, img, out=roi)


def mola(f, d=12, k=150):
    t = f / FPS
    w0, z = np.sqrt(k), d / (2 * np.sqrt(k))
    w1 = w0 * np.sqrt(1 - z * z)
    return 1 - np.exp(-z * w0 * t) * (np.cos(w1 * t) + z * w0 / w1 * np.sin(w1 * t))


tmp = pasta / "fonte" / "_v.mp4"
saida = cv2.VideoWriter(str(tmp), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
for q in range(N):
    if q < 45:
        f = np.full((H, W, 3), ESCURO, np.uint8)
        cv2.rectangle(f, (600, 1100), (650, 1150), VERMELHO, -1)
        if q >= 10:
            cv2.putText(f, "PALAVRA"[:min(7, (q - 10) // 2 + 1)], (90, 500), FONTE, 3, (240, 240, 240), 8, cv2.LINE_AA)
        if q >= 22:
            junta(f, q)
        if q >= 24:
            estica(f, q)
    else:
        f = np.full((H, W, 3), CREME, np.uint8)
        if q >= 50:
            x = 600 + (150 - 600) * bezier(min(1, (q - 50) / 20), 0.2, 0.8, 0.2, 1)
            cv2.putText(f, "ENTRA", (int(round(x)), 400), FONTE, 3, (30, 30, 30), 8, cv2.LINE_AA)
        y = 1000 + (800 - 1000) * (mola(q - 55) if q >= 55 else 0)
        cv2.rectangle(f, (210, int(round(y))), (510, int(round(y)) + 200), AZUL, -1)
    saida.write(f)
saida.release()

sr = 22050
a = 0.02 * np.sin(2 * np.pi * 110 * np.arange(int(sr * N / FPS)) / sr)  # fundo baixo
rng = np.random.default_rng(1)
for k in range(6):
    i = int(k * 0.5 * sr)
    n = int(0.03 * sr)
    a[i:i + n] += 0.7 * rng.standard_normal(n) * np.exp(-np.arange(n) / (0.006 * sr))
wav = pasta / "fonte" / "_a.wav"
with wave.open(str(wav), "wb") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(sr)
    w.writeframes((np.clip(a, -1, 1) * 32767).astype(np.int16).tobytes())
subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(tmp), "-i", str(wav), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "16",
                "-c:a", "aac", "-shortest", str(pasta / "fonte" / "ref.mp4")], check=True)
tmp.unlink()
wav.unlink()
json.dump({"corte": 45, "corte_s": 1.5, "bpm": 120, "fundo_a": "#1e1e2e", "acento_a": "#dc1e1e", "texto_b": "#1e1e1e",
           "bezier": [0.2, 0.8, 0.2, 1], "spring": {"damping": 12, "stiffness": 150}}, open(pasta / "verdade.json", "w"))
