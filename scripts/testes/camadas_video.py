"""Vídeo sintético para o teste do `npm run camadas` (scripts/testes/camadas.test.mjs), com o movimento conhecido.
    python -P scripts/testes/camadas_video.py <saida.mp4> <verdade.json>
720×1280, 30 qps, 90 quadros:
  q0–44   fundo com textura andando para a esquerda (3 px/q) + um cartão com outra textura que desce (4 px/q) e gira
  q45     corte seco para outro fundo, que aproxima devagar (escala +0,4%/q)
  q66–68  clarão (3 quadros brancos), depois o fundo da 2ª cena de novo
verdade.json: as trocas e, por quadro, o centro do cartão e o deslocamento do fundo.
"""
import json
import math
import sys

import cv2
import numpy as np

W, H, N = 720, 1280, 90
rng = np.random.default_rng(3)


def textura(w, h, grao):
    t = cv2.GaussianBlur(rng.random((h // grao, w // grao)).astype(np.float32), (0, 0), 1.2)
    t = cv2.resize(t, (w, h), interpolation=cv2.INTER_CUBIC)
    return cv2.normalize(t, None, 30, 225, cv2.NORM_MINMAX).astype(np.uint8)


fundo1, fundo2 = textura(W + 400, H, 6), textura(W, H, 9)
cartao = textura(220, 300, 4)
cartao = cv2.rectangle(cartao, (0, 0), (219, 299), 255, 6)
saida = cv2.VideoWriter(sys.argv[1], cv2.VideoWriter_fourcc(*"mp4v"), 30, (W, H))
verdade = {"trocas": [{"tipo": "corte", "q": 45}, {"tipo": "clarão", "de": 66, "ate": 68}], "cartao": {}, "fundo": {}}
for q in range(N):
    if q < 45:
        dx = 3 * q
        f = fundo1[:, dx:dx + W].copy()
        cx, cy, g = 360, 420 + 4 * q, 0.4 * q
        M = cv2.getRotationMatrix2D((110, 150), -g, 1.0)  # −g: no OpenCV + é anti-horário
        M[:, 2] += [cx - 110, cy - 150]
        mask = cv2.warpAffine(np.full(cartao.shape, 255, np.uint8), M, (W, H))
        obj = cv2.warpAffine(cartao, M, (W, H))
        f[mask > 128] = obj[mask > 128]
        verdade["cartao"][q] = [cx, cy, 1.0, g]
        verdade["fundo"][q] = [-dx, 0]
    elif 66 <= q <= 68:
        f = np.full((H, W), 255, np.uint8)
    else:
        s = 1 + 0.004 * (q - 45)
        f = cv2.warpAffine(fundo2, cv2.getRotationMatrix2D((W / 2, H / 2), 0, s), (W, H), borderMode=cv2.BORDER_REFLECT)
    saida.write(cv2.cvtColor(f, cv2.COLOR_GRAY2BGR))
saida.release()
json.dump(verdade, open(sys.argv[2], "w"))
