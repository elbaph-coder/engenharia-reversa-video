"""Rastreia uma imagem (foto, quadro, recorte, cenário) quadro a quadro num vídeo de referência → analise/rastreio.json.

    npm run rastreio -- <ref.mp4> <nome> --quadro=<q> --caixa=x,y,larg,alt [--de=<q>] [--ate=<q>] [--min=12]

A imagem é o recorte `caixa` (px da referência) no quadro `quadro`. Em cada quadro de `de` a `ate`, acha os mesmos pontos
(SIFT) e calcula a pose do recorte: centro x, y (px da referência), escala (1 = tamanho no quadro do recorte) e giro em
graus (+ = horário, como o rotate do CSS). Compara sempre com o recorte (não com o quadro anterior): não acumula erro.
Quadro com menos de `min` pontos que batem (corte, borrão, a imagem saiu da tela) fica de fora e aparece na lista "sem".

Grava em referencias/<estilo>/analise/rastreio.json ({"objetos": {nome: {"caixa", "quadro", "q": {q: [x, y, s, g]}}}}),
o formato que o `npm run conferir` lê. Rodar de novo com o mesmo nome substitui aquele objeto.
Para escolher a caixa: posições das folhas × 3 (folha de 240 de largura para vídeo de 720) ou o `analise/medidas.md`.
"""
import json
import math
import os
import sys

import cv2
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")

args = [a for a in sys.argv[1:] if not a.startswith("--")]
opts = {a[2:].split("=")[0]: a.split("=", 1)[1] if "=" in a else True for a in sys.argv[1:] if a.startswith("--")}
if len(args) < 2 or "quadro" not in opts or "caixa" not in opts:
    sys.exit(__doc__)
ref, nome = args[0], args[1]
q0 = int(opts["quadro"])
bx, by, bw, bh = (int(float(v)) for v in opts["caixa"].split(","))
MIN = int(opts.get("min", 12))

cap = cv2.VideoCapture(ref)
N = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
de, ate = int(opts.get("de", q0)), int(opts.get("ate", N - 1))
quadros = {}
for q in range(min(de, q0), max(ate, q0) + 1):
    cap.set(cv2.CAP_PROP_POS_FRAMES, q)
    ok, f = cap.read()
    if ok:
        quadros[q] = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)

sift = cv2.SIFT_create(nfeatures=3000)
mask = np.zeros_like(quadros[q0])
mask[by:by + bh, bx:bx + bw] = 255
kt, dt = sift.detectAndCompute(quadros[q0], mask)
if dt is None or len(kt) < MIN:
    sys.exit(f"recorte com poucos pontos ({0 if dt is None else len(kt)}): escolha uma caixa com mais textura")
cx, cy = bx + bw / 2, by + bh / 2
bf = cv2.BFMatcher()
res, sem, pontos = {}, [], {}
for q in range(de, ate + 1):
    if q not in quadros:
        sem.append(q)
        continue
    kf, df = sift.detectAndCompute(quadros[q], None)
    if df is None or len(kf) < MIN:
        sem.append(q)
        continue
    bons = [m for m, n in (p for p in bf.knnMatch(dt, df, k=2) if len(p) == 2) if m.distance < 0.75 * n.distance]
    if len(bons) < MIN:
        sem.append(q)
        continue
    A, inl = cv2.estimateAffinePartial2D(np.float32([kt[m.queryIdx].pt for m in bons]),
                                         np.float32([kf[m.trainIdx].pt for m in bons]), method=cv2.RANSAC, ransacReprojThreshold=4)
    if A is None or int(inl.sum()) < MIN:
        sem.append(q)
        continue
    s = math.hypot(A[0, 0], A[1, 0])
    if not 0.33 < s < 3:  # ajuste degenerado (poucos pontos espalhados num canto): não é a imagem
        sem.append(q)
        continue
    g = math.degrees(math.atan2(A[1, 0], A[0, 0]))
    x, y = A @ np.array([cx, cy, 1.0])
    res[str(q)] = [round(float(x), 1), round(float(y), 1), round(s, 4), round(g, 2)]
    pontos[q] = int(inl.sum())

saida = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(ref))), "analise", "rastreio.json")
dados = json.load(open(saida, encoding="utf8")) if os.path.exists(saida) else {"objetos": {}}
dados["objetos"][nome] = {"caixa": [bx, by, bw, bh], "quadro": q0, "q": res}
json.dump(dados, open(saida, "w", encoding="utf8"), ensure_ascii=False)


def faixas(qs):
    out = []
    for q in qs:
        if out and q == out[-1][1] + 1:
            out[-1][1] = q
        else:
            out.append([q, q])
    return ", ".join(f"{a}–{b}" if a != b else str(a) for a, b in out) or "—"


print(f"✔ {nome}: {len(res)}/{ate - de + 1} quadros rastreados → {saida}")
print(f"  sem: {faixas(sem)}")
if res:
    qs = sorted(int(q) for q in res)
    print(f"  pontos que batem: mín {min(pontos.values())} · mediana {int(np.median(list(pontos.values())))}")
    for q in qs[:: max(1, len(qs) // 8)] + [qs[-1]]:
        x, y, s, g = res[str(q)]
        print(f"  q{q}: x {x:.0f} y {y:.0f} escala {s:.3f} giro {g:+.1f}°")
