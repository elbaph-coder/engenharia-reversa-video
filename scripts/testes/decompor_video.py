"""Estudo sintético para o teste do `npm run decompor` (scripts/testes/decompor.test.mjs).
    python -P scripts/testes/decompor_video.py <pasta do estudo>
Cria <pasta>/fonte/ref.mp4 — 720×1280, 30 qps, 100 quadros, câmera parada:
  q0–59   fundo claro com textura; um bloco de texto (linhas de "letras") aparece em q20; um ícone de traço aparece em q40
  q60     corte seco para um fundo escuro com textura; um cartão claro aparece em q80
e <pasta>/verdade.json com as caixas (px da referência) e os quadros de entrada.
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np

pasta = Path(sys.argv[1])
(pasta / "fonte").mkdir(parents=True, exist_ok=True)
W, H, N = 720, 1280, 100
rng = np.random.default_rng(5)


def textura(base, var):
    t = cv2.GaussianBlur(rng.random((H // 8, W // 8)).astype(np.float32), (0, 0), 2)
    t = cv2.resize(t, (W, H), interpolation=cv2.INTER_CUBIC)
    return np.clip(base + var * (t - 0.5), 0, 255).astype(np.uint8)


claro, escuro = textura(215, 40), textura(45, 30)
texto = {"caixa": [120, 300, 480, 150], "q": 20}
icone = {"caixa": [280, 700, 160, 160], "q": 40}
cartao = {"caixa": [160, 500, 400, 300], "q": 80}
saida = cv2.VideoWriter(str(pasta / "fonte" / "ref.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), 30, (W, H))
for q in range(N):
    f = (claro if q < 60 else escuro).copy()
    if 20 <= q < 60:
        x, y, w, h = texto["caixa"]
        for linha in range(2):  # duas linhas de "letras": blocos escuros da altura da linha
            for k in range(11):
                cv2.rectangle(f, (x + 8 + k * 42, y + 15 + linha * 70), (x + 38 + k * 42, y + 65 + linha * 70), 30, 6)
    if 40 <= q < 60:
        x, y, w, h = icone["caixa"]
        cv2.circle(f, (x + 80, y + 80), 70, 20, 5)
        cv2.line(f, (x + 40, y + 80), (x + 120, y + 80), 20, 5)
    if q >= 80:
        x, y, w, h = cartao["caixa"]
        cv2.rectangle(f, (x, y), (x + w, y + h), 235, -1)
        cv2.rectangle(f, (x + 30, y + 40), (x + 200, y + 60), 120, -1)
    saida.write(cv2.cvtColor(f, cv2.COLOR_GRAY2BGR))
saida.release()
json.dump({"texto": texto, "icone": icone, "cartao": cartao, "corte": 60}, open(pasta / "verdade.json", "w"))
