"""Acha sozinho as CAMADAS de um vídeo de referência (o que anda junto) e as TROCAS de cena, com o tipo de cada uma.

    npm run camadas -- <ref.mp4> [--saida=<pasta>] [--min=15] [--rastreio=<camada>:<nome>,...] [--confere] [--so-trocas]

Nenhuma caixa é dada à mão. Milhares de pontos são seguidos de quadro em quadro (LK, ida e volta). Em cada par de quadros
um RANSAC em sequência separa os movimentos (translação + escala + giro): o que leva mais pontos é o fundo/câmera, os
seguintes são objetos com movimento próprio. Modelos de pares diferentes que dividem pontos viram a mesma camada (a
identidade atravessa buracos de até 6 quadros: borrão, sobreposição). Quem anda junto fica na mesma camada: texto preso
à parede anda com a parede, lâmpada anda com o corredor.

Troca de cena = os pontos não atravessam (menos de 35% sobrevivem). Salto de diferença com os pontos atravessando NÃO é
corte (câmera em degraus de 2 quadros, palavra que acende): sai só na contagem de "saltos sem corte". Tipo de cada troca,
quadro a quadro: clarão (quadro branco/preto), fusão (quadro = α·antes + (1−α)·depois), corte, troca em movimento.
É a FONTE ÚNICA das cenas do estudo: o `npm run estudo` e o `npm run decompor` leem as `cenas` daqui (cena nova começa no
`corte` de cada troca = o último quadro em que os pontos não atravessam).

Grava em referencias/<estilo>/analise/:
  camadas.json  {"video", "trocas": [{de, ate, corte, tipo, quebra}], "cenas": [[ini, fim]] (fim incluso, sem buraco),
                 "saltos_sem_corte": n,
                 "camadas": {id: {"papel": fundo|objeto, "de", "ate", "pontos", "caixa", "quadro", "q": {q: [x, y, s, g]},
                 "caixas": {q: [x, y, l, a]}}}}
                — "caixa"/"quadro"/"q" no MESMO formato do rastreio.json (RECRIAR.md §2): centro x, y em px da
                referência, escala 1 = tamanho no "quadro", giro em graus (+ = horário)
  CAMADAS.md    as trocas e as camadas em tabelas; com rastreio.json ao lado, a comparação com ele
--rastreio=c3:quadro,c7:foto  copia essas camadas para o rastreio.json com esses nomes (o que o caminhos/conferir leem).
--so-trocas   só as trocas e as cenas, em JSON na saída padrão (sem camadas nem arquivos — npm run ritmo, comparar).
--confere [--objetos=a,b]  só compara com o rastreio.json existente (ou só esses objetos) e sai com erro se algum ficar
              fora da tolerância do conferir (teste de regressão: npm test).
Não vê: objeto que nunca se mexe em cena parada, coisa que se deforma (fumaça, líquido), o nome e a função de cada camada.
"""
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")

args = [a for a in sys.argv[1:] if not a.startswith("--")]
opts = {a[2:].split("=")[0]: (a.split("=", 1)[1] if "=" in a else True) for a in sys.argv[1:] if a.startswith("--")}
if not args:
    sys.exit(__doc__)
video = Path(args[0]).resolve()
saida = Path(opts["saida"]).resolve() if "saida" in opts else video.parent.parent / "analise"
MIN = int(opts.get("min", 15))
LARG = 360  # largura de trabalho (px); tudo o que sai volta para px da referência

# ---------------------------------------------------------------- quadros
cap = cv2.VideoCapture(str(video))
W0, H0 = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
FPS = cap.get(cv2.CAP_PROP_FPS) or 30
S = W0 / LARG
ALT = int(round(H0 / S))
F = []
while True:
    ok, f = cap.read()
    if not ok:
        break
    F.append(cv2.cvtColor(cv2.resize(f, (LARG, ALT), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY))
N = len(F)
if N < 3:
    sys.exit("vídeo sem quadros")

LK = dict(winSize=(21, 21), maxLevel=3, criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01))


def segue(a, b, p):
    """p (n,1,2) do quadro a para o b; devolve (novos pontos, máscara dos que voltam ao lugar)"""
    n, st, _ = cv2.calcOpticalFlowPyrLK(F[a], F[b], p, None, **LK)
    v, st2, _ = cv2.calcOpticalFlowPyrLK(F[b], F[a], n, None, **LK)
    ok = (st.ravel() == 1) & (st2.ravel() == 1) & (np.abs(v - p).reshape(-1, 2).max(1) < 0.7)
    return n, ok


# ---------------------------------------------------------------- 1. trocas
pequeno = [cv2.resize(f, (90, int(90 * ALT / LARG)), interpolation=cv2.INTER_AREA).astype(np.float32) for f in F]
dif = np.array([0.0] + [float(np.abs(pequeno[i] - pequeno[i - 1]).mean()) for i in range(1, N)])
lum = np.array([float(f.mean()) for f in F])
desv = np.array([float(f.std()) for f in F])
liso = (desv < 12) & ((lum > 225) | (lum < 25))  # quadro branco ou preto (clarão, passagem pelo preto)
sobrevive = np.ones(N)
for i in range(1, N):
    p = cv2.goodFeaturesToTrack(F[i - 1], 300, 0.01, 6)
    if liso[i - 1] or liso[i]:
        sobrevive[i] = 0.0 if (liso[i - 1] != liso[i]) or p is None or len(p) < 20 else 1.0
        continue
    if p is None or len(p) < 20 or desv[i - 1] < 12 or desv[i] < 12:
        # fundo suave ou chapado (cor lisa, céu): nada para seguir (os "cantos" são ruído de compressão e não atravessam)
        # — quem decide é quanto da tela mudou: troca de cena muda quase tudo; elemento que aparece muda um pedaço
        sobrevive[i] = 0.0 if float((np.abs(pequeno[i] - pequeno[i - 1]) > 20).mean()) > 0.5 else 1.0
        continue
    _, ok = segue(i - 1, i, p.astype(np.float32))
    sobrevive[i] = float(ok.mean())
QUEBRA = 0.35
med = float(np.median(dif[1:]))
salto = dif > max(3 * med, 8)
quebra = sobrevive < QUEBRA
saltos_sem_corte = int((salto & ~quebra & ~liso).sum())


def fusao(a, b, k):
    """o quadro k é a mistura de a e b? devolve (α, erro médio)"""
    A, B, X = pequeno[a].ravel(), pequeno[b].ravel(), pequeno[k].ravel()
    d = A - B
    if float(np.dot(d, d)) < 1e-3:
        return 1.0, 99.0
    al = float(np.clip(np.dot(X - B, d) / np.dot(d, d), 0, 1))
    return al, float(np.abs(X - (al * A + (1 - al) * B)).mean())


marcas = [q for q in range(1, N) if quebra[q] or liso[q]]
grupos = []  # quebras a até 3 quadros uma da outra são um trecho só (fumaça emendada, cortes rápidos)
for q in marcas:
    if grupos and q - grupos[-1][1] <= 3:
        grupos[-1][1] = q
    else:
        grupos.append([q, q])
trocas = []
for de, ate in grupos:
    # a janela da troca: até onde a diferença segue alta em volta da quebra (no máx. 15 q de cada lado)
    a, b = de, ate
    while a - 1 > 0 and de - a < 15 and dif[a - 1] > 2 * med:
        a -= 1
    while b + 1 < N - 1 and b - ate < 15 and dif[b + 1] > 2 * med:
        b += 1
    A, B = max(a - 1, 0), min(b + 1, N - 1)
    nq = sum(1 for q in marcas if de <= q <= ate)
    # corte seco = um pico isolado; pico baixo no meio de diferença alta = troca com movimento (fusão de imagens que andam,
    # borrão que desliza): o pixel não separa as duas — conferir no recorte
    vizinhos = (dif[de - 1] + dif[min(de + 1, N - 1)]) / 2
    tipo = "corte" if ate == de and dif[de] > 2.5 * max(vizinhos, 1) else "troca em movimento (fusão ou borrão? conferir)"
    # fusão: o quadro do meio fica bem mais perto da mistura de A e B do que de qualquer um dos dois
    mist = []
    for k in range(A + 1, B):
        al, e = fusao(A, B, k)
        X = pequeno[k]
        perto = min(float(np.abs(X - pequeno[A]).mean()), float(np.abs(X - pequeno[B]).mean()))
        if 0.1 < al < 0.9 and e < 0.6 * perto:
            mist.append((k, al))
    pico = float(lum[a:b + 1].max()) - max(lum[A], lum[B])
    if liso[de:ate + 1].any():
        tipo = "clarão" if lum[de:ate + 1][liso[de:ate + 1]].mean() > 128 else "pelo preto"
    elif pico > 40:
        tipo = "clarão"
        claro = np.where(lum[a:b + 1] > max(lum[A], lum[B]) + 20)[0]
        a, b = a + int(claro[0]), a + int(claro[-1])
    elif len(mist) >= 3 and np.corrcoef([k for k, _ in mist], [x for _, x in mist])[0, 1] < -0.5:
        tipo = "fusão"
        a, b = mist[0][0], mist[-1][0]
    elif nq >= 3 and ate - de >= 4:
        tipo = "trecho sem rastro (fumaça, deformação ou cortes rápidos)"
    if tipo in ("corte", "trecho sem rastro (fumaça, deformação ou cortes rápidos)"):
        a, b = de, ate
    # corte = 1º quadro da cena nova: o último quadro do grupo em que os pontos não atravessam (depois dele, atravessam)
    trocas.append({"de": int(a), "ate": int(b), "corte": int(ate), "tipo": tipo, "quebra": True, "quebras": nq})

limites = [0] + sorted({t["corte"] for t in trocas if 0 < t["corte"] < N}) + [N]
cenas = [[a, b - 1] for a, b in zip(limites, limites[1:])]
if "so-trocas" in opts:
    print(json.dumps({"quadros": N, "trocas": trocas, "cenas": cenas}, ensure_ascii=False))
    sys.exit(0)

cortes = sorted({t["ate"] + 1 for t in trocas if t["quebra"]} | {q for q in range(1, N) if quebra[q] or liso[q]})

# ---------------------------------------------------------------- 2. pontos seguidos
trilhas, nid = {}, 0  # id → {q: (x, y)} em px de trabalho
pts, ids = None, []
for q in range(N):
    if q in cortes:
        pts = None
    if liso[q]:
        pts = None
        continue
    if pts is None or len(ids) < 250 or q % 8 == 0:
        mask = np.full(F[q].shape, 255, np.uint8)
        if pts is None:
            pts, ids = np.zeros((0, 1, 2), np.float32), []
        else:
            for x, y in pts.reshape(-1, 2):
                cv2.circle(mask, (int(x), int(y)), 6, 0, -1)
        novos = cv2.goodFeaturesToTrack(F[q], 500, 0.01, 6, mask=mask)
        if novos is not None:
            pts = np.vstack([pts, novos.astype(np.float32)])
            ids += list(range(nid, nid + len(novos)))
            nid += len(novos)
    for p, k in zip(pts.reshape(-1, 2), ids):
        trilhas.setdefault(k, {})[q] = (float(p[0]), float(p[1]))
    if q + 1 >= N or (q + 1) in cortes or liso[q + 1] or not len(ids):
        pts = None
        continue
    nxt, ok = segue(q, q + 1, pts)
    pts, ids = nxt[ok], [k for k, b in zip(ids, ok) if b]


def ajusta(P0, P1, lim=0.8):
    M, inl = cv2.estimateAffinePartial2D(P0, P1, ransacReprojThreshold=lim, maxIters=800, confidence=0.995)
    return (None, None) if M is None else (M, inl.ravel().astype(bool))


# ---------------------------------------------------------------- 3. camadas
BURACO = 6
camadas = []  # {"passos": {(q0, q1): M}, "ids": {q: set}, "fim": q, "vistos": set}
for q in range(N - 1):
    ks = [k for k, t in trilhas.items() if q in t and q + 1 in t]
    if len(ks) < MIN:
        continue
    P0 = np.float32([trilhas[k][q] for k in ks])
    P1 = np.float32([trilhas[k][q + 1] for k in ks])
    livres = np.ones(len(ks), bool)
    modelos = []
    for _ in range(4):
        if livres.sum() < MIN:
            break
        M, inl = ajusta(P0[livres], P1[livres])
        if M is None or inl.sum() < MIN:
            break
        idx = np.where(livres)[0][inl]
        # objeto de verdade é compacto: pontos espalhados pela tela inteira que sobram do fundo são ruído
        if modelos:
            P = P0[idx]
            if np.ptp(P[:, 0]) * np.ptp(P[:, 1]) > 0.6 * LARG * ALT and len(idx) < 0.15 * len(ks):
                livres[idx] = False
                continue
        modelos.append((M, {ks[i] for i in idx}))
        livres[idx] = False
    usadas = set()
    aqui = set(ks)
    for M, s in sorted(modelos, key=lambda m: -len(m[1])):
        cands = [(len(c["vistos"] & s), n) for n, c in enumerate(camadas)
                 if n not in usadas and q - c["fim"] <= BURACO and not any(cc > c["fim"] and cc <= q for cc in cortes)]
        comum, n = max(cands, default=(0, None))
        # continua a camada se boa parte do modelo veio dela OU se boa parte dela (dos pontos vivos) caiu neste modelo —
        # o 2º caso é o recomeço de pontos: muitos novos de uma vez não podem abrir outra camada
        vivos = len(camadas[n]["vistos"] & aqui) if n is not None else 0
        if n is None or comum < 8 or (comum < 0.25 * len(s) and comum < 0.5 * vivos):
            n = len(camadas)
            camadas.append({"passos": {}, "ids": {}, "fim": q, "vistos": set()})
        c = camadas[n]
        usadas.add(n)
        if c["ids"] and c["fim"] < q:  # buraco: liga o último quadro visto a este pelos pontos em comum
            ult = c["fim"]
            kk = [k for k in s if ult in trilhas[k] and q in trilhas[k]]
            if len(kk) >= 6:
                G, _ = ajusta(np.float32([trilhas[k][ult] for k in kk]), np.float32([trilhas[k][q] for k in kk]), 1.5)
                if G is not None:
                    c["passos"][(ult, q)] = G
        c["passos"][(q, q + 1)] = M
        c["ids"][q] = s
        c["ids"][q + 1] = c["ids"].get(q + 1, set()) | {k for k in s}
        c["vistos"] = (c["vistos"] | s) if q - c["fim"] <= 1 else s | c["vistos"]
        c["fim"] = q + 1


def anda_igual(A, B):
    """B anda com o movimento de A nos pares que os dois têm? (o RANSAC partiu um objeto em dois, ex.: entrada rápida
    com giro). Só vale se B se mexe de verdade nesses pares — duas coisas paradas não provam que andam juntas."""
    comuns = [k for k in A["passos"] if k in B["passos"] and k[1] - k[0] == 1]
    if len(comuns) < 2:
        return False
    err, mexe = [], []
    for q, q1 in comuns:
        kk = [k for k in B["ids"].get(q, ()) if q1 in trilhas[k]]
        if len(kk) < 6:
            continue
        P, Q = np.float32([trilhas[k][q] for k in kk]), np.float32([trilhas[k][q1] for k in kk])
        M = A["passos"][(q, q1)]
        err.append(float(np.median(np.hypot(*(P @ M[:, :2].T + M[:, 2] - Q).T))))
        mexe.append(float(np.median(np.hypot(*(Q - P).T))))
    return len(err) >= 2 and np.median(err) < 0.8 and np.median(mexe) > 1.5


juntou = True
while juntou:
    juntou = False
    for i in range(len(camadas)):
        for j in range(i + 1, len(camadas)):
            A, B = camadas[i], camadas[j]
            if anda_igual(A, B) or anda_igual(B, A):
                for k, M in B["passos"].items():
                    A["passos"].setdefault(k, M)
                for q, s in B["ids"].items():
                    A["ids"][q] = A["ids"].get(q, set()) | s
                del camadas[j]
                juntou = True
                break
        if juntou:
            break


def m3(M):
    return np.vstack([M, [0, 0, 1]])


def poses(c):
    """transformação acumulada de cada quadro da camada: T[q] leva o 1º quadro ao q"""
    chegam = {}  # quadro → [(de onde, M)]; o passo de 1 quadro vale mais que o que pula um buraco
    for (a, b), M in c["passos"].items():
        chegam.setdefault(b, []).append((a, M))
    qs = sorted({a for a, _ in c["passos"]} | set(chegam))
    if not qs:
        return {}
    T = {qs[0]: np.eye(3)}
    for b in qs[1:]:
        de = [(a, M) for a, M in chegam.get(b, ()) if a in T]
        if de:
            a, M = max(de, key=lambda x: x[0])
            T[b] = m3(M) @ T[a]
    # encadear passo a passo acumula erro (~10 px em 20 q): onde há pontos em comum com o quadro de referência (o de
    # mais pontos), a pose sai direto dele; o encadeado só preenche os quadros sem pontos em comum suficientes
    r = max(T, key=lambda q: len(c["ids"].get(q, ())))
    base = list(c["ids"][r])
    R = {}
    for q in T:
        kk = [k for k in base if q in trilhas[k]]
        # só com uma boa parte dos pontos da camada nesse quadro: poucos pontos em comum podem ser de outra coisa
        if len(kk) >= max(MIN, 0.3 * len(c["ids"].get(q, ()))):
            M, _ = ajusta(np.float32([trilhas[k][r] for k in kk]), np.float32([trilhas[k][q] for k in kk]), 1.0)
            if M is not None:
                R[q] = m3(M)
    if not R:
        return T
    for q in sorted(T):
        if q not in R:
            p = min(R, key=lambda k: abs(k - q))
            R[q] = T[q] @ np.linalg.inv(T[p]) @ R[p]
    return {q: R[q] @ T[r] for q in T}


def escala_giro(T):
    return math.hypot(T[0, 0], T[1, 0]), math.degrees(math.atan2(T[1, 0], T[0, 0]))


final = []  # (camada interna, saída) — só as que duram 10+ quadros ligados
for c in camadas:
    T = poses(c)
    qs = sorted(T)
    if len(qs) < 10:
        continue
    c["T"] = T
    cnt = {q: len(c["ids"].get(q, ())) for q in qs}
    ref = max(qs, key=lambda q: cnt[q])
    P = np.array([trilhas[k][ref] for k in c["ids"][ref]]) * S
    x0, y0 = np.percentile(P[:, 0], 2), np.percentile(P[:, 1], 2)
    x1, y1 = np.percentile(P[:, 0], 98), np.percentile(P[:, 1], 98)
    cx, cy = (x0 + x1) / 2 / S, (y0 + y1) / 2 / S
    Ti = np.linalg.inv(T[ref])
    sr, gr = escala_giro(T[ref])
    q_ = {}
    for q in qs:
        R = T[q] @ Ti
        x, y = (R @ [cx, cy, 1.0])[:2] * S
        s, g = escala_giro(R)
        q_[str(q)] = [round(float(x), 1), round(float(y), 1), round(s, 4), round(g, 2)]
    caixas = {}
    for q in qs[:: max(1, len(qs) // 12)] + [qs[-1]]:
        if c["ids"].get(q):
            Pq = np.array([trilhas[k][q] for k in c["ids"][q]]) * S
            caixas[str(q)] = [int(np.percentile(Pq[:, 0], 2)), int(np.percentile(Pq[:, 1], 2)),
                              int(np.percentile(Pq[:, 0], 98) - np.percentile(Pq[:, 0], 2)),
                              int(np.percentile(Pq[:, 1], 98) - np.percentile(Pq[:, 1], 2))]
    final.append((c, {
        "de": qs[0], "ate": qs[-1], "pontos": int(np.median(list(cnt.values()))),
        "caixa": [int(x0), int(y0), int(x1 - x0), int(y1 - y0)], "quadro": int(ref), "q": q_, "caixas": caixas}))
final.sort(key=lambda f: (f[1]["de"], -f[1]["pontos"]))
camadas_out = {f"c{n}": sc for n, (_, sc) in enumerate(final)}
interno = {f"c{n}": c for n, (c, _) in enumerate(final)}

# papel: em cada quadro, a camada com mais pontos é o fundo; a que é fundo na maior parte da vida é "fundo"
ids_por_q = {}
for cid, c in interno.items():
    for q, s in c["ids"].items():
        ids_por_q.setdefault(q, []).append((len(s), cid))
for cid, sc in camadas_out.items():
    vida = [q for q in range(sc["de"], sc["ate"] + 1) if q in ids_por_q]
    fundo = sum(1 for q in vida if max(ids_por_q[q])[1] == cid)
    sc["papel"] = "fundo" if vida and fundo >= 0.5 * len(vida) else "objeto"
    sc["pequena"] = sc["pontos"] < 30  # poucos pontos: borda de outra camada ou ruído — conferir antes de usar

# ---------------------------------------------------------------- 4. comparação com o rastreio.json (se houver)
def compara(rast):
    """para cada objeto do rastreio: a camada que leva os pontos da caixa dele e o erro do caminho"""
    linhas = []
    for nome, o in rast.items():
        bx, by, bw, bh = o["caixa"]
        q0 = o["quadro"]
        rq = {int(k): v for k, v in o["q"].items()}
        melhor = None
        for cid, c in interno.items():
            qq = min(c["ids"], key=lambda k: abs(k - q0))
            if abs(qq - q0) > 3:
                continue
            P = np.array([trilhas[k][qq] for k in c["ids"][qq]]) * S
            den = ((P[:, 0] > bx) & (P[:, 0] < bx + bw) & (P[:, 1] > by) & (P[:, 1] < by + bh))
            # nota: quantos pontos da camada caem na caixa (não a fração — o fundo grande também tem pontos lá)
            nota = int(den.sum()) * (0.5 + den.mean())
            if melhor is None or nota > melhor[0]:
                melhor = (nota, cid, c, float(den.mean()))
        if not melhor:
            linhas.append({"objeto": nome, "camada": None})
            continue
        _, cid, c, frac = melhor
        T = c["T"]
        ancora = min(T, key=lambda k: abs(k - q0))
        if q0 not in rq:
            linhas.append({"objeto": nome, "camada": cid})
            continue
        x, y, s0, g0 = rq[q0]
        Ti = np.linalg.inv(T[ancora])
        err, errs, errg, pior = [], [], [], []
        for q, (rx, ry, rs, rg) in rq.items():
            if q not in T or not rs:
                continue  # rastreio sem escala nesse quadro
            R = T[q] @ Ti
            px, py = (R @ [x / S, y / S, 1.0])[:2] * S
            s, g = escala_giro(R)
            err.append(math.hypot(px - rx, py - ry))
            pior.append((err[-1], q))
            errs.append(abs(s * s0 - rs) / rs * 100)
            errg.append(abs(g + g0 - rg))
        linhas.append({"objeto": nome, "camada": cid, "dentro": frac, "cobre": len(err) / len(rq),
                       "pos": float(np.median(err)) if err else None, "pos90": float(np.percentile(err, 90)) if err else None,
                       "piores": [q for _, q in sorted(pior, reverse=True)[:5]],
                       "esc": float(np.median(errs)) if errs else None, "giro": float(np.median(errg)) if errg else None})
    return linhas


rpath = saida / "rastreio.json"
rast = json.load(open(rpath, encoding="utf8"))["objetos"] if rpath.exists() else {}
if "objetos" in opts:  # --objetos=a,b: só esses (os outros do rastreio ficam de fora da comparação)
    rast = {k: v for k, v in rast.items() if k in str(opts["objetos"]).split(",")}
comp = compara(rast) if rast else []
TOL_POS, TOL_ESC, COBRE = 9.0, 2.5, 0.6  # as tolerâncias do conferir (RECRIAR.md §4)


def ok(l):
    return l.get("camada") and l["cobre"] >= COBRE and l["pos"] is not None and l["pos"] <= TOL_POS and l["esc"] <= TOL_ESC


# ---------------------------------------------------------------- 5. saída
def fx(v, f="{:.1f}"):
    return "—" if v is None else f.format(v)


if "confere" in opts:
    for l in comp:
        print(f"{'✔' if ok(l) else '✘'} {l['objeto']}: camada {l.get('camada')} · cobre {fx(l.get('cobre'), '{:.0%}')} · "
              f"posição {fx(l.get('pos'))} px (p90 {fx(l.get('pos90'), '{:.0f}')}) · escala {fx(l.get('esc'))}% · giro {fx(l.get('giro'))}°")
    sys.exit(0 if comp and all(ok(l) for l in comp) else 1)

saida.mkdir(parents=True, exist_ok=True)
dados = {"video": {"arquivo": video.name, "w": W0, "h": H0, "qps": FPS, "quadros": N},
         "trocas": trocas, "cenas": cenas, "saltos_sem_corte": saltos_sem_corte, "camadas": camadas_out}
json.dump(dados, open(saida / "camadas.json", "w", encoding="utf8"), ensure_ascii=False)

md = [f"# Camadas — {video.name}", "",
      f"Gerado por `npm run camadas` (não editar). {W0}×{H0}, {FPS:g} qps, {N} quadros. Camada = o que anda junto; "
      "`fundo` = leva mais pontos na maior parte da vida (câmera/cenário), `objeto` = movimento próprio. Posições em px da "
      "referência; caminho completo em `camadas.json` (formato do `rastreio.json`). Não vê: objeto parado em cena parada, "
      "fumaça/deformação, nome e função (isso é leitura).", "",
      "## Trocas", "", "| quadros | tipo | cena nova começa em |", "|---|---|---|"]
md += [f"| q{t['de']}–q{t['ate']} | {t['tipo']} | q{t['corte']} |" for t in trocas]
md += ["", "Cenas (fonte única do estudo e do decompor): " + " · ".join(f"C{k + 1} q{a}–{b}" for k, (a, b) in enumerate(cenas)) + "."]
md += ["", f"Saltos sem corte (diferença alta, pontos atravessam — degraus, palavra que acende): **{saltos_sem_corte}**.", "",
       "## Camadas", "", "| id | quadros | papel | pontos | caixa no q de referência | anda | escala | giro |", "|---|---|---|---|---|---|---|---|"]
for cid, c in camadas_out.items():
    qs = sorted(int(k) for k in c["q"])
    a, b = c["q"][str(qs[0])], c["q"][str(qs[-1])]
    md.append(f"| {cid} | q{c['de']}–q{c['ate']} | {c['papel']}{' (pequena: borda ou ruído?)' if c['pequena'] else ''} | {c['pontos']} | q{c['quadro']}: {c['caixa']} | "
              f"{math.hypot(b[0] - a[0], b[1] - a[1]):.0f} px | ×{b[2] / a[2]:.2f} | {b[3] - a[3]:+.1f}° |")
if comp:
    md += ["", "## × rastreio.json (feito à mão)", "",
           f"Tolerância do `conferir`: posição {TOL_POS:g} px, escala {TOL_ESC:g}%; cobre ≥ {COBRE:.0%} dos quadros rastreados.", "",
           "| objeto | camada | cobre | posição (mediana · p90) | escala | giro | |", "|---|---|---|---|---|---|---|"]
    for l in comp:
        md.append(f"| {l['objeto']} | {l.get('camada') or '—'} | {fx(l.get('cobre'), '{:.0%}')} | {fx(l.get('pos'))} · "
                  f"{fx(l.get('pos90'), '{:.0f}')} px | {fx(l.get('esc'))}% | {fx(l.get('giro'))}° | {'✔' if ok(l) else '⚠'} |")
(saida / "CAMADAS.md").write_text("\n".join(md) + "\n", encoding="utf8")

if "rastreio" in opts:
    r = json.load(open(rpath, encoding="utf8")) if rpath.exists() else {"objetos": {}}
    for par in str(opts["rastreio"]).split(","):
        cid, nome = par.split(":")
        c = camadas_out[cid]
        r["objetos"][nome] = {"caixa": c["caixa"], "quadro": c["quadro"], "q": c["q"], "origem": f"camadas {cid}"}
        print(f"  → rastreio.json: {nome} = {cid}")
    json.dump(r, open(rpath, "w", encoding="utf8"), ensure_ascii=False)

print(f"✔ {N} quadros · {len(trocas)} trocas · {saltos_sem_corte} saltos sem corte · {len(camadas_out)} camadas → {saida / 'CAMADAS.md'}")
for t in trocas:
    print(f"  troca q{t['de']}–q{t['ate']}: {t['tipo']}")
for cid, c in camadas_out.items():
    print(f"  {cid}: q{c['de']}–q{c['ate']} {c['papel']} · {c['pontos']} pontos · caixa q{c['quadro']} {c['caixa']}")
for l in comp:
    print(f"  {'✔' if ok(l) else '⚠'} {l['objeto']} × {l.get('camada')}: cobre {fx(l.get('cobre'), '{:.0%}')} · "
          f"posição {fx(l.get('pos'))} px (p90 {fx(l.get('pos90'), '{:.0f}')}) · escala {fx(l.get('esc'))}% · giro {fx(l.get('giro'))}°")
