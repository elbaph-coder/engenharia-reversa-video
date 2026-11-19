"""Medidas prontas de um estudo (chamado pelo `npm run estudo`, depois do RESUMO.md) — o que antes se fazia olhando folhas
ou com numpy improvisado (skill estudar-video, passos 2, 4 e 5):

    python -P scripts/fichas.py <video> [--saida=<pasta analise>]   (sozinho: refaz só isto sobre um estudo já rodado)

Lê `analise/cenas.json` e `analise/medidas.json` e escreve:
  analise/fichas.json   textos · paleta · som · curvas (tudo abaixo, com todos os números)
  analise/RESUMO.md     seção "Medidas prontas" (entre <!-- fichas --> e <!-- /fichas -->, trocada a cada rodada)
  analise/olhar-NNN.jpg recorte pequeno (só a palavra, quadro a quadro) de cada ficha de texto com ⚠ — o único lugar
                        onde ainda vale abrir imagem

1. Fichas de texto: cada bloco de letras que entra responde as 4 perguntas (ordem das letras, borda × falta, embalo,
   tamanho) pelas caixas de tinta de cada letra (componentes conexos dentro da caixa do bloco), cada resposta com confiança.
   Entra = nasce no meio da cena, chega com corte que não é seco, ou (bloco `L<n>b`) já estava e volta a mudar de largura
   no quadro em que outra palavra nasce — a batida que o texto marca sem a imagem trocar (o camadas não corta ali).
2. Paleta por cena: k-means nas cores → hex com papel provável (fundo = maior área, texto = tinta dentro das caixas de
   letra, acento = cor saturada de pouca área).
3. Som: nível, RMS em janelas de 50 ms, ataques (derivada > média + 2·desvio), BPM aproximado, quedas, e quais cortes e
   entradas de texto caem num golpe.
4. Curvas: cada movimento de câmera e de bloco ajustado a Easing.bezier(4 números) e a spring(damping, stiffness, mass 1),
   com a fórmula pronta para colar no Remotion e o erro do ajuste.
"""
import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage
from scipy.optimize import least_squares

sys.stdout.reconfigure(encoding="utf-8")

DUVIDA = 0.6  # confiança abaixo disto vira "⚠ olhar"


hexa = lambda c: "#%02x%02x%02x" % tuple(int(round(min(255, max(0, v)))) for v in c)


def quadros(video, largura, altura):
    cmd = ["ffmpeg", "-v", "error", "-i", str(video), "-vf", f"scale={largura}:{altura}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    tam = largura * altura * 3
    while True:
        b = proc.stdout.read(tam)
        if len(b) < tam:
            break
        yield np.frombuffer(b, np.uint8).reshape(altura, largura, 3)
    proc.wait()


# ---------------------------------------------------------------- 4. curvas (usadas também pelas fichas)
def bezier_y(t, p):
    """Easing.bezier(x1, y1, x2, y2) do Remotion avaliado em t ∈ [0, 1]"""
    x1, y1, x2, y2 = p
    s = np.linspace(0, 1, 401)
    bx = 3 * (1 - s) ** 2 * s * x1 + 3 * (1 - s) * s ** 2 * x2 + s ** 3
    by = 3 * (1 - s) ** 2 * s * y1 + 3 * (1 - s) * s ** 2 * y2 + s ** 3
    return np.interp(t, bx, by)


def mola(f, fps, damping, stiffness, mass=1.0):
    """spring() do Remotion de 0 a 1 (sem durationInFrames) no quadro f — forma fechada da mesma conta que ele faz
    quadro a quadro (amortecimento < 1: oscila; ≥ 1: o Remotion usa a fórmula crítica)"""
    t = np.asarray(f, float) / fps
    w0 = np.sqrt(stiffness / mass)
    z = damping / (2 * np.sqrt(stiffness * mass))
    if z < 1:
        w1 = w0 * np.sqrt(1 - z * z)
        return 1 - np.exp(-z * w0 * t) * (np.cos(w1 * t) + z * w0 / w1 * np.sin(w1 * t))
    return 1 - np.exp(-w0 * t) * (1 + w0 * t)


def ajusta(vs, fps):
    """ajusta uma série (de v0 a v1) a bezier e a spring; devolve os dois com o erro (% da amplitude)"""
    v = np.asarray(vs, float)
    amp = v[-1] - v[0]
    n = len(v) - 1
    t = np.arange(n + 1) / n
    y = (v - v[0]) / amp
    melhor_b = None
    for p0 in ([0.25, 0.1, 0.25, 1], [0.42, 0, 1, 1], [0, 0, 0.58, 1], [0.42, 0, 0.58, 1], [0.33, 0.33, 0.67, 0.67], [0.2, 0.8, 0.2, 1]):
        r = least_squares(lambda p: bezier_y(t, p) - y, p0, bounds=([0, -1, 0, -1], [1, 2, 1, 2]))
        if melhor_b is None or r.cost < melhor_b.cost:
            melhor_b = r
    melhor_m = None
    for d0, k0 in ((10, 100), (20, 200), (30, 400), (8, 60), (15, 50)):
        r = least_squares(lambda p: mola(np.arange(n + 1), fps, np.exp(p[0]), np.exp(p[1])) - y, [np.log(d0), np.log(k0)],
                          bounds=([0, 0], [np.log(300), np.log(2000)]))
        if melhor_m is None or r.cost < melhor_m.cost:
            melhor_m = r
    eb = float(np.sqrt(np.mean(melhor_b.fun ** 2)))
    em = float(np.sqrt(np.mean(melhor_m.fun ** 2)))
    return ({"p": [round(float(x), 2) for x in melhor_b.x], "erro": round(100 * eb, 1), "erro_max": round(float(np.abs(melhor_b.fun).max() * abs(amp)), 2)},
            {"damping": round(float(np.exp(melhor_m.x[0])), 1), "stiffness": round(float(np.exp(melhor_m.x[1])), 1), "mass": 1,
             "erro": round(100 * em, 1), "erro_max": round(float(np.abs(melhor_m.fun).max() * abs(amp)), 2)})


def movimentos(vs, minimo, eps):
    """trechos (i0, i1) em que a série anda de um repouso a outro: mesma direção (1 quadro de pausa tolerado), passada do
    ponto que volta (quique/mola, amplitude menor) junta no mesmo movimento; pontas estendidas pelo resto da desaceleração"""
    v = np.asarray(vs, float)
    if len(v) < 4:
        return []
    v = ndimage.median_filter(v, 3, mode="nearest")
    d = np.diff(v)
    s = np.where(np.abs(d) > eps, np.sign(d), 0)
    runs, i = [], 0
    while i < len(s):
        if s[i] == 0:
            i += 1
            continue
        j = i
        while j + 1 < len(s) and (s[j + 1] == s[i] or (s[j + 1] == 0 and j + 2 < len(s) and s[j + 2] == s[i])):
            j += 1
        runs.append([i, j + 1, s[i]])
        i = j + 1
    for r in runs:  # estende pelo começo e pelo fim enquanto ainda anda um pouco na mesma direção
        while r[0] > 0 and np.sign(d[r[0] - 1]) == r[2] and abs(d[r[0] - 1]) > eps / 4:
            r[0] -= 1
        while r[1] < len(d) and np.sign(d[r[1]]) == r[2] and abs(d[r[1]]) > eps / 4:
            r[1] += 1
    out, k = [], 0
    while k < len(runs):
        i0, i1, sg = runs[k]
        amp = abs(v[i1] - v[i0])
        while k + 1 < len(runs) and runs[k + 1][0] - i1 <= 2 and runs[k + 1][2] != sg \
                and abs(v[runs[k + 1][1]] - v[runs[k + 1][0]]) < 0.6 * amp:
            k += 1
            amp, i1, sg = abs(v[runs[k][1]] - v[runs[k][0]]), runs[k][1], runs[k][2]
        if abs(v[i1] - v[i0]) >= minimo and i1 - i0 >= 5:
            out.append((i0, i1))
        k += 1
    return out


def num(x, casas=2):
    return f"{x:.{casas}f}".rstrip("0").rstrip(".") if casas else f"{x:.0f}"


def formula(c, fps):
    q0, q1, v0, v1 = c["q0"], c["q1"], c["de_valor"], c["ate_valor"]
    casas = 3 if c["medida"] in ("zoom", "espaço") else 1
    if c["melhor"] == "bezier":
        p = ", ".join(num(x) for x in c["bezier"]["p"])
        return (f"interpolate(q, [{q0}, {q1}], [{num(v0, casas)}, {num(v1, casas)}], {{easing: Easing.bezier({p}), "
                f"extrapolateLeft: \"clamp\", extrapolateRight: \"clamp\"}})")
    m = c["spring"]
    return (f"interpolate(spring({{frame: q - {q0}, fps: {num(fps, 3)}, config: {{damping: {num(m['damping'], 1)}, "
            f"stiffness: {num(m['stiffness'], 1)}, mass: 1}}}}), [0, 1], [{num(v0, casas)}, {num(v1, casas)}])")


def curvas(medidas, fps):
    """todos os movimentos de câmera e de bloco do medidas.json, cada um com a curva que melhor o descreve"""
    out = []
    uf, altura = medidas["largura"], medidas["altura"]
    for cm in medidas["cenas"]:
        series = []
        for k, cc in enumerate(cm["camera"]):
            if not cc.get("anda") or cc.get("liso"):
                continue
            se = cc.get("serie")
            if not se:  # estudo antigo, sem a série inteira: reconstrói pelos quadros-chave (curva menos fiel)
                qs = list(range(cc["q"][0], cc["q"][-1] + 1))
                se = {m: list(np.interp(qs, cc["q"], cc[m])) for m in ("x", "y", "zoom", "giro")}
            for m, minimo, eps in (("x", 4, 0.25), ("y", 4, 0.25), ("zoom", 0.04, 0.002), ("giro", 2, 0.15)):
                series.append((f"câmera{'' if not k else f' (trecho {k + 1})'}", m, cc["de"], se[m], minimo, eps))
        nl = ni = 0
        for b in cm["blocos"]:
            if len(b["quadros"]) < 5:
                continue
            if b["tipo"] == "letra":
                nl += 1
                nome = f"L{nl}"
            else:
                ni += 1
                nome = f"I{ni}"
            qd = b["quadros"]
            alt_med = float(np.median([x["alt"] for x in qd]))
            # bloco cortado pela borda (entrando/saindo): o centro sai da borda que não está cortada + tamanho de quando inteiro
            corta_x = lambda x: x["esq"] <= 0.5 or x["dir"] >= uf - 0.5
            corta_y = lambda x: x["topo"] <= 0.5 or x["topo"] + x["alt"] >= altura - 0.5
            inteiros_x = [x["dir"] - x["esq"] for x in qd if not corta_x(x)]
            inteiros_y = [x["alt"] for x in qd if not corta_y(x)]
            lw = float(np.median(inteiros_x)) if inteiros_x else None
            lh = float(np.median(inteiros_y)) if inteiros_y else None

            def cx(x):
                if lw and x["dir"] >= uf - 0.5 and x["esq"] > 0.5:
                    return x["esq"] + lw / 2
                if lw and x["esq"] <= 0.5 and x["dir"] < uf - 0.5:
                    return x["dir"] - lw / 2
                return (x["esq"] + x["dir"]) / 2

            def cy(x):
                if lh and x["topo"] + x["alt"] >= altura - 0.5 and x["topo"] > 0.5:
                    return x["topo"] + lh / 2
                if lh and x["topo"] <= 0.5 and x["topo"] + x["alt"] < altura - 0.5:
                    return x["topo"] + x["alt"] - lh / 2
                return x["topo"] + x["alt"] / 2

            if b["tipo"] == "letra" and lw:  # letra a letra a caixa cresce sem a palavra andar: só depois de inteira
                k0 = next((k for k, x in enumerate(qd) if corta_x(x) or x["dir"] - x["esq"] >= 0.9 * lw), 0)
                qd = qd[k0:]
                if len(qd) < 5:
                    continue
            for m, f in (("x", cx), ("y", cy), ("alt", lambda x: x["alt"])):
                if m == "alt" and any(corta_y(x) for x in qd):
                    continue
                minimo = max(4, 0.15 * alt_med) if m == "alt" else 4
                series.append((nome, m, qd[0]["q"], [f(x) for x in qd], minimo, 0.25))
        for quem, m, q_ini, vs, minimo, eps in series:
            for i0, i1 in movimentos(vs, minimo, eps):
                bz, sp = ajusta(vs[i0:i1 + 1], fps)
                c = {"cena": cm["n"], "quem": quem, "medida": m, "q0": q_ini + i0, "q1": q_ini + i1,
                     "de_valor": round(float(vs[i0]), 3), "ate_valor": round(float(vs[i1]), 3), "bezier": bz, "spring": sp,
                     "melhor": "bezier" if bz["erro"] <= sp["erro"] else "spring"}
                c["erro"] = min(bz["erro"], sp["erro"])
                c["formula"] = formula(c, fps)
                out.append(c)
    return out


# ---------------------------------------------------------------- 1. fichas de texto
def camera_em(cm, q):
    """(x, y, zoom) acumulados da câmera da cena no quadro q (desde o começo do trecho) ou None (parada/sem medida)"""
    for cc in cm["camera"]:
        if cc["de"] <= q <= cc["ate"] and cc.get("serie"):
            k = q - cc["de"]
            return cc["serie"]["x"][k], cc["serie"]["y"][k], cc["serie"]["zoom"][k], cc["de"]
    return None


def assentado(qd):
    """índice do quadro em que o bloco termina de entrar: o 1º em que largura e altura ficam 4 quadros sem mudar (letra a
    letra até 3 q por letra ainda conta como entrando; o zoom lento da câmera não). Não usa a maior largura: um zoom ou
    desfoque no fim da cena incha a caixa muito depois de a palavra ter entrado"""
    for k in range(len(qd) - 3):
        w = [x["dir"] - x["esq"] for x in qd[k:k + 4]]
        al = [x["alt"] for x in qd[k:k + 4]]
        if np.ptp(w) <= max(1.0, 0.02 * max(w)) and np.ptp(al) <= max(1.0, 0.03 * max(al)):
            return k
    return min(len(qd) - 1, 30)


def entradas(cenas_j, medidas):
    """blocos de letras que entram: nascem no meio da cena, ou com um corte que não é seco"""
    tipo_corte = {c["q"]: c["tipo"] for c in cenas_j["cortes"]}
    ini = {c["n"]: c["ini"] for c in cenas_j["cenas"]}
    out = []
    for cm in medidas["cenas"]:
        nl = 0
        letras = [b for b in cm["blocos"] if b["tipo"] == "letra"]
        for b in letras:
            nl += 1
            qd = b["quadros"]
            if len(qd) < 4:
                continue
            corte = tipo_corte.get(cm["ini"])
            if b["de"] <= 1 and (corte is None or corte == "seco"):
                continue  # já estava (ou chegou com corte seco): não é entrada
            # continuação de outro bloco que acabou de sumir no mesmo lugar (o rastreador partiu a trilha)
            q0 = qd[0]
            if any(o is not b and o["ate"] in (b["de"] - 1, b["de"] - 2) and abs(o["quadros"][-1]["topo"] - q0["topo"]) < 3
                   and min(o["quadros"][-1]["dir"], q0["dir"]) - max(o["quadros"][-1]["esq"], q0["esq"]) > 0 for o in letras):
                continue
            k = assentado(qd)
            out.append({"cena": cm["n"], "bloco": f"L{nl}", "de": b["de"], "abs": ini[cm["n"]] + b["de"], "assenta": k,
                        "quadros": qd[:k + 3], "trilha": qd[:40], "corte": corte if b["de"] <= 1 else None})
        # batida no meio da cena: quando uma palavra nasce, o bloco que já estava e começa a mudar ali (as letras se juntam
        # ou se afastam) faz uma entrada nova — é o "corte" que o texto marca sem a imagem trocar (o camadas não corta:
        # os pontos atravessam). Só largura: altura parada (zoom de câmera e fade mudam as duas, ou nenhuma)
        nascem = sorted({b["de"] for b in letras if b["de"] >= 2 and len(b["quadros"]) >= 3})
        nl = 0
        for b in letras:
            nl += 1
            qd = b["quadros"]
            for qn in nascem:
                if b["de"] > qn - 2:
                    continue
                i = next((k for k, x in enumerate(qd) if x["q"] == qn), None)
                if i is None or len(qd) - i < 4:
                    continue
                sub = qd[i:]
                k = assentado(sub)
                w0, wk = sub[0]["dir"] - sub[0]["esq"], sub[k]["dir"] - sub[k]["esq"]
                if k >= 2 and abs(wk - w0) > max(3.0, 0.06 * w0) and abs(sub[k]["alt"] - sub[0]["alt"]) <= max(1.0, 0.03 * sub[0]["alt"]):
                    out.append({"cena": cm["n"], "bloco": f"L{nl}b", "de": qn, "abs": ini[cm["n"]] + qn, "assenta": k,
                                "quadros": sub[:k + 3], "trilha": sub[:40], "corte": None})
                    break  # uma batida por bloco: a primeira em que ele volta a mudar
    return out


def tinta(crop, fundo, cor):
    """máscara do texto: o pixel já percorreu metade do caminho fundo → cor do texto (pega letras ainda acendendo)"""
    d = cor - fundo
    n2 = float(d @ d)
    if n2 < 900:  # texto quase da cor do fundo: não dá
        return None
    proj = ((crop.astype(float) - fundo) @ d) / n2
    m = proj >= 0.5
    return ndimage.binary_opening(m, np.ones((2, 2), bool)), float(np.percentile(proj, 99))


def pecas(m, alt_px):
    """letras: componentes conexos, juntando os que se sobrepõem na horizontal (pingo do i, acento); [(x0, x1, área, y0, y1)]"""
    if m is None:
        return []
    lab_, n = ndimage.label(m, np.ones((3, 3)))
    cs = []
    for sl, a in zip(ndimage.find_objects(lab_), ndimage.sum(m, lab_, range(1, n + 1))):
        if a >= max(4, 0.02 * alt_px * alt_px):
            cs.append([sl[1].start, sl[1].stop, float(a), sl[0].start, sl[0].stop])
    cs.sort()
    out = []
    for c in cs:
        if out and min(out[-1][1], c[1]) - max(out[-1][0], c[0]) > 0.5 * min(out[-1][1] - out[-1][0], c[1] - c[0]):
            o = out[-1]
            out[-1] = [min(o[0], c[0]), max(o[1], c[1]), o[2] + c[2], min(o[3], c[3]), max(o[4], c[4])]
        else:
            out.append(c)
    return out


def sobrepoe(c, velhos, dx, frac=0.3):
    """a letra c já existia (em velhos, deslocados de dx)?"""
    return any(min(c[1], v[1] + dx) - max(c[0], v[0] + dx) > frac * (c[1] - c[0]) for v in velhos)


def ficha(e, crops, regiao, uf, altura, AW, AH, cm, fps):
    """as 4 perguntas para cada palavra de uma entrada de texto. A caixa do estudo é uma LINHA: palavras que se juntam a
    ela depois (letras novas a um espaço de distância da tinta que já estava acesa) viram fichas próprias.
    Devolve [(respostas, k0, k1)] — k = índice nos quadros da entrada"""
    qd = e["quadros"]
    k_s = e["assenta"]
    x0r, y0r = regiao[0], regiao[1]
    px = AW / uf  # px da análise por unidade da folha
    alt_px = qd[k_s]["alt"] * px
    final = crops[k_s]
    fundo = np.median(np.concatenate([final[0], final[-1], final[:, 0], final[:, -1]]).astype(float), 0)
    s = qd[k_s]  # cor do texto: a tinta forte dentro da caixa assentada
    bx0, bx1 = int(s["esq"] * px) - x0r, int(s["dir"] * px) - x0r
    by0, by1 = int(s["topo"] / altura * AH) - y0r, int((s["topo"] + s["alt"]) / altura * AH) - y0r
    dentro = final[max(0, by0):max(1, by1), max(0, bx0):max(1, bx1)].reshape(-1, 3).astype(float)
    forte = dentro[np.abs(dentro - fundo).max(1) > 60] if len(dentro) else dentro
    if len(forte) < 10:
        nada = ("não medido (texto com pouco contraste)", 0.0)
        return [({"ordem": nada, "borda": nada, "embalo": nada, "tamanho": nada}, 0, k_s)]
    cor = np.median(forte, 0)
    tt = [tinta(c, fundo, cor) for c in crops]
    ps = [pecas(t[0] if t else None, alt_px) for t in tt]
    luz = [t[1] if t else 0.0 for t in tt]
    cxs = [((x["esq"] + x["dir"]) / 2) * px - x0r for x in qd]
    # deslocamento entre quadros seguidos: o que melhor casa as letras de um com as do outro (desconta o deslizar)
    dxs = [0.0]
    for k in range(1, len(ps)):
        a_, b_ = ps[k - 1], ps[k]
        cands = {0.0, cxs[k] - cxs[k - 1], (qd[k]["esq"] - qd[k - 1]["esq"]) * px, (qd[k]["dir"] - qd[k - 1]["dir"]) * px}
        casa = lambda dx: sum(sobrepoe(c, a_, dx, 0.5) for c in b_)
        dxs.append(max(sorted(cands, key=abs), key=casa) if a_ and b_ else cxs[k] - cxs[k - 1])
    alt_ref = float(np.median([c[4] - c[3] for c in ps[k_s]])) if ps[k_s] else alt_px
    cortes = []
    for k in range(1, k_s + 1):
        a_, b_ = ps[k - 1], ps[k]
        na_borda = qd[k]["esq"] <= 0.5 or qd[k]["dir"] >= uf - 0.5
        if not a_ or not b_ or luz[k - 1] < 0.85 * luz[k_s] or na_borda or abs(dxs[k]) > 0.3 * alt_ref:
            continue  # palavra andando ou entrando pela borda: letra nova longe é só o deslizar
        novos = [c for c in b_ if not sobrepoe(c, a_, dxs[k])]
        gap = min((min(max(0, c[0] - v[1] - dxs[k], v[0] + dxs[k] - c[1]) for v in a_) for c in novos), default=0)
        if novos and gap > 0.3 * alt_ref:
            cortes.append(k)
    segs = list(zip([0] + cortes, [c - 1 for c in cortes] + [k_s]))

    def outros(q0_, q1_, f):
        """mediana de uma medida dos OUTROS blocos da cena entre dois quadros (a câmera vista pelo resto)"""
        rs = []
        for o in cm["blocos"]:
            a_ = next((x for x in o["quadros"] if x["q"] == q0_), None)
            b_ = next((x for x in o["quadros"] if x["q"] == q1_), None)
            if a_ and b_ and o["de"] != e["de"]:
                rs.append(f(a_, b_))
        return float(np.median(rs)) if len(rs) >= 2 else None

    out = []
    for j, (a, b) in enumerate(segs):
        base = ps[a - 1] if j else []

        def sel(k, a=a, j=j, base=base):
            """letras desta palavra no quadro k (nas palavras que se juntam à linha: só as que não estavam lá antes)"""
            if not j:
                return ps[k]
            return [c for c in ps[k] if not sobrepoe(c, base, sum(dxs[a:k + 1]))]

        n_fin = len(sel(b))
        area = [sum(c[2] for c in sel(k)) for k in range(len(ps))]
        acesa = next((k for k in range(a, b + 1) if (area[k] >= 0.85 * area[b] if j else luz[k] >= 0.85 * luz[b])), b)
        resp = {}
        longe = None
        # 2. borda × falta
        if j:
            resp["borda"] = ("não — junta-se à linha já escrita, longe da borda", 0.85)
        else:
            q0 = qd[0]
            lados = [n for n, ok in (("esq", q0["esq"] <= 0.5), ("dir", q0["dir"] >= uf - 0.5), ("topo", q0["topo"] <= 0.5),
                                     ("baixo", q0["topo"] + q0["alt"] >= altura - 0.5)) if ok]
            if lados:
                lado = lados[0]
                anda = max({"esq": x["esq"] - q0["esq"], "dir": q0["dir"] - x["dir"], "topo": x["topo"] - q0["topo"],
                            "baixo": (q0["topo"] + q0["alt"]) - (x["topo"] + x["alt"])}[lado] for x in e["trilha"])
                longe = anda > 2
                resp["borda"] = (f"entra pela borda ({lado}): encosta nela no 1º quadro e se afasta {anda:.0f} un", 0.9) if longe else \
                    (f"encosta na borda ({lado}) e não se afasta — cortada pela borda ou é assim mesmo?", 0.4)
            else:
                primeiro = next((k for k in range(a, b + 1) if sel(k)), None)
                falta = False
                if primeiro is not None and 0 < len(sel(primeiro)) < n_fin and abs(sum(dxs[primeiro + 1:b + 1])) < 0.5 * alt_ref:
                    centros = [(c[0] + c[1]) / 2 for c in sel(b)]
                    idx = sorted({int(np.argmin([abs((c[0] + c[1]) / 2 - x) for x in centros])) for c in sel(primeiro)})
                    falta = len(idx) > 1 and idx[-1] - idx[0] + 1 > len(idx)
                resp["borda"] = ("faltam letras no meio no começo (aparecem fora de ordem)", 0.7) if falta else \
                    ("não — nada cortado pela borda, surge longe dela", 0.85 if n_fin >= 2 else 0.7)
        # 1. ordem: quadro a quadro, de que lado nasce cada letra nova
        votos = {"→": 0, "←": 0, "meio": 0}
        primeiro = next((k for k in range(a, b + 1) if sel(k)), a)
        for k in range(primeiro + 1, b + 1):
            velhos = sel(k - 1)
            if not velhos or len(sel(k)) <= len(velhos):
                continue  # só conta quando aparece letra (peças que piscam sobre foto não contam)
            for c in sel(k):
                if sobrepoe(c, velhos, dxs[k]):
                    continue
                lo, hi = min(v[0] for v in velhos) + dxs[k], max(v[1] for v in velhos) + dxs[k]
                votos["→" if c[0] >= hi - 2 else "←" if c[1] <= lo + 2 else "meio"] += 1
        total = sum(votos.values())
        inteira = len(sel(primeiro)) >= max(1, 0.8 * n_fin) and total < 2
        fade = f", acendendo em {acesa - primeiro + 1} q (fade)" if acesa > primeiro else ""
        if longe:
            resp["ordem"] = ("as letras aparecem conforme cruzam a borda (não se escrevem)", 0.8)
        elif n_fin <= 1:
            resp["ordem"] = ("uma peça só (letras coladas ou forma) — não dá para contar letras", 0.3)
        elif inteira:
            resp["ordem"] = ("a palavra inteira de uma vez (sem ordem de letras)" + fade, 0.85)
        elif total == 0:
            resp["ordem"] = ("não vi letras nascendo uma a uma", 0.4)
        else:
            dom = max(votos, key=votos.get)
            conf = votos[dom] / total * min(1.0, total / 2)
            nome = {"→": "esquerda→direita", "←": "direita→esquerda", "meio": "do meio / ao acaso"}[dom]
            resp["ordem"] = (f"uma a uma, {nome} — {votos['→']}→ {votos['←']}← {votos['meio']} meio", round(conf, 2))
        # 3. embalo: anda logo ao nascer? o corte de antes já vinha andando?
        if j:
            resp["embalo"] = (f"não — nasce em q{qd[a]['q']}, junto da linha", 0.85)
        else:
            ini = min(3, len(qd) - 1)
            bordas = [qd[ini][x] - qd[0][x] for x, lim in (("esq", lambda v: v <= 0.5), ("dir", lambda v: v >= uf - 0.5))
                      if not lim(qd[0][x]) and not lim(qd[ini][x])]
            v_ini = (min(bordas, key=abs) if bordas else (cxs[ini] - cxs[0]) / px) / max(1, ini)
            anda_txt = f"desliza {'→' if v_ini > 0 else '←'} {abs(v_ini):.1f} un/q ao nascer" if abs(v_ini) > 0.8 else "nasce parada"
            c0, c1 = camera_em(cm, qd[0]["q"]), camera_em(cm, qd[ini]["q"])
            if c0 and c1 and c0[3] == c1[3]:
                v_cam = (c1[0] - c0[0]) / max(1, ini)
            else:
                v_cam = outros(qd[0]["q"], qd[ini]["q"], lambda a_, b_: ((b_["esq"] + b_["dir"]) - (a_["esq"] + a_["dir"])) / 2 / max(1, ini))
            if abs(v_ini) > 0.8 and v_cam is not None and abs(v_cam - v_ini) < 0.8:
                anda_txt += " (junto com a câmera: presa à cena)"
            if e["corte"]:
                mesmo = ("→" in e["corte"] and v_ini > 0.8) or ("←" in e["corte"] and v_ini < -0.8)
                if e["corte"].startswith("com embalo") or (e["corte"].startswith("sai em movimento") and mesmo):
                    resp["embalo"] = (f"sim — continua o movimento do corte ({e['corte']}); {anda_txt}", 0.85 if mesmo else 0.6)
                else:
                    resp["embalo"] = (f"não — corte \"{e['corte']}\"; {anda_txt} por conta própria", 0.7)
            else:
                resp["embalo"] = (f"não — nasce em q{e['de']}, longe do corte; {anda_txt}", 0.9)
        # 4. tamanho: letras da palavra inteira E acesa (no fade a tinta cresce conforme clareia) × assentadas
        k_ref = next((k for k in range(acesa, b + 1) if len(sel(k)) >= max(1, 0.9 * n_fin)), None)
        partes, curva, duvida = [], None, False
        if k_ref is not None and sel(k_ref) and sel(b):
            # 1ª palavra: a caixa do estudo (estável sobre foto); palavra que se junta à linha: as letras novas
            H = (lambda k: qd[k]["alt"]) if not j else (lambda k: float(np.median([c[4] - c[3] for c in sel(k)])))
            r_alt = H(k_ref) / max(1e-3, H(b))
            z0, z1 = camera_em(cm, qd[k_ref]["q"]), camera_em(cm, qd[b]["q"])
            if z0 and z1 and z0[3] == z1[3]:
                r_cam = z0[2] / z1[2]
            else:
                r_cam = outros(qd[k_ref]["q"], qd[b]["q"], lambda a_, b_: (b_["alt"] and a_["alt"] / b_["alt"]) or 1.0)
            if r_cam and abs(r_cam - 1) > 0.03:
                if abs(r_alt / r_cam - 1) <= 0.08 and abs(r_alt - 1) > 0.08:
                    partes.append(f"só o zoom da câmera (×{r_cam:.2f}): a palavra não muda em relação à cena")
                r_alt /= r_cam
            if r_alt > 1.08:
                partes.append(f"chega maior e encolhe (altura ×{r_alt:.2f} → 1)")
            elif r_alt < 0.92:
                partes.append(f"cresce (altura ×{r_alt:.2f} → 1)")
            if k_ref < b and not longe:
                if not j:
                    e0, d0, e1, d1 = (qd[k_ref]["esq"] * px, qd[k_ref]["dir"] * px, qd[b]["esq"] * px, qd[b]["dir"] * px)
                else:
                    dx = sum(dxs[k_ref + 1:b + 1])
                    e0, d0 = min(c[0] for c in sel(k_ref)) + dx, max(c[1] for c in sel(k_ref)) + dx
                    e1, d1 = min(c[0] for c in sel(b)), max(c[1] for c in sel(b))
                r_w = (d0 - e0) / max(1e-3, d1 - e1) / (r_cam or 1.0)
                if abs(r_w - 1) > 0.08:
                    # os dois sentidos; e de onde vem a mudança: espaço entre as letras (letterSpacing) × a letra em si (scaleX)
                    abre = r_w < 1
                    if abre:
                        lado = "só para a direita" if abs(e1 - e0) < 2 and d1 - d0 > 2 else \
                            "só para a esquerda" if abs(d1 - d0) < 2 and e1 - e0 < -2 else "para os dois lados"
                    else:
                        lado = "em direção à direita (a borda direita fica parada)" if abs(d1 - d0) < 2 and e1 - e0 > 2 else \
                            "em direção à esquerda (a borda esquerda fica parada)" if abs(e1 - e0) < 2 and d1 - d0 < -2 else "para o centro"
                    l0, l1 = sel(k_ref), sel(b)
                    larg = lambda ls: float(np.median([c[1] - c[0] for c in ls]))
                    vao = lambda ls: float(np.mean([ls[i + 1][0] - ls[i][1] for i in range(len(ls) - 1)]))
                    r_l = larg(l0) / max(1e-3, larg(l1)) / (r_cam or 1.0) if len(l0) == len(l1) >= 2 else None
                    em = alt_ref / 0.7  # tamanho da fonte ≈ altura das maiúsculas ÷ 0,7
                    if r_l is not None and abs(r_l - 1) <= 0.06:
                        s0 = (vao(l0) - vao(l1)) / em
                        partes.append((f"letras chegam afastadas e se juntam {lado}" if not abre else f"letras chegam juntas e se afastam {lado}")
                                      + f" — espaço entre letras, não a letra (letterSpacing ≈ {s0:+.2f}em → 0; largura ×{r_w:.2f} → 1)")
                        # curva do espaço: todos os quadros com as mesmas letras, até assentar
                        ks = [k for k in range(k_ref, len(ps)) if len(sel(k)) == len(l1)]
                        serie = [(vao(sel(k)) - vao(l1)) / em for k in ks]
                        if len(ks) >= 4 and ks[-1] - ks[0] == len(ks) - 1 and abs(serie[0] - serie[-1]) >= 0.03:
                            bz, sp = ajusta(serie, fps)
                            c = {"medida": "espaço", "q0": qd[ks[0]]["q"], "q1": qd[ks[-1]]["q"], "de_valor": round(serie[0], 3),
                                 "ate_valor": round(serie[-1], 3), "bezier": bz, "spring": sp,
                                 "melhor": "bezier" if bz["erro"] <= sp["erro"] else "spring", "erro": min(bz["erro"], sp["erro"])}
                            c["formula"] = formula(c, fps)
                            curva = c
                    elif r_l is not None and abs(r_l - r_w) <= 0.1:
                        partes.append(f"nasce espremida e se abre {lado} — a letra se estica, não o espaço (scaleX ×{r_l:.2f} → 1)" if abre else
                                      f"nasce esticada e se estreita {lado} — a letra, não o espaço (scaleX ×{r_l:.2f} → 1)")
                    else:
                        partes.append((f"nasce espremida e se abre {lado}" if abre else f"nasce larga e se fecha {lado}")
                                      + f" (largura ×{r_w:.2f} → 1) — espaço ou letra esticada: não deu para separar")
                        duvida = True
        conf = 0.85 if k_ref is not None and b - k_ref >= 1 else 0.7 if k_ref is not None else 0.5
        if duvida:
            conf = 0.5
        if partes and partes[0].startswith("só o zoom") and len(partes) > 1:
            partes = partes[1:]
        resp["tamanho"] = ("; ".join(partes) if partes else "não muda ao entrar", conf) + (({"curva": curva},) if curva else ())
        out.append((resp, a, b))
    return out


def recorte(crops, rotulos, destino):
    """tira pequena só da palavra: até 10 quadros lado a lado, altura 90 px"""
    idx = np.unique(np.linspace(0, len(crops) - 1, min(10, len(crops))).round().astype(int))
    h = 90
    peds = []
    for i in idx:
        c = Image.fromarray(crops[i])
        w = max(1, int(c.width * h / c.height))
        peds.append((c.resize((w, h)), rotulos[i]))
    img = Image.new("RGB", (sum(p.width + 4 for p, _ in peds), h + 16), "#202020")
    d = ImageDraw.Draw(img)
    try:
        fonte = ImageFont.truetype("arialbd.ttf", 11)
    except OSError:
        fonte = ImageFont.load_default()
    x = 0
    for p, r in peds:
        img.paste(p, (x, 16))
        d.text((x + 2, 1), r, fill="yellow", font=fonte)
        x += p.width + 4
    img.save(destino, quality=88)


# ---------------------------------------------------------------- 2. paleta
def lab(px):
    return cv2.cvtColor(px.reshape(-1, 1, 3).astype(np.uint8), cv2.COLOR_RGB2LAB).reshape(-1, 3).astype(float)


def paleta(frames, caixas):
    """frames: quadros pequenos de uma cena; caixas: caixas de letra (frações) por quadro"""
    px = np.concatenate([f.reshape(-1, 3) for f in frames]).astype(np.float32)
    k = 5
    _, rot, cen = cv2.kmeans(px, k, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.5), 3, cv2.KMEANS_PP_CENTERS)
    rot = rot.ravel()
    area = np.bincount(rot, minlength=k) / len(rot)
    ordem = np.argsort(-area)
    fundo = cen[ordem[0]]
    L = lab(cen)
    chroma = np.hypot(L[:, 1] - 128, L[:, 2] - 128)
    # texto: tinta dentro das caixas de letra (o que difere do fundo)
    tinta_px = []
    for f, cx in zip(frames, caixas):
        h, w = f.shape[:2]
        for b in cx:
            sub = f[int(b["y"] * h):int((b["y"] + b["h"]) * h) + 1, int(b["x"] * w):int((b["x"] + b["w"]) * w) + 1].reshape(-1, 3)
            tinta_px.append(sub[np.abs(sub.astype(float) - fundo).max(1) > 60])
    tinta_px = np.concatenate(tinta_px) if tinta_px else np.zeros((0, 3))
    if len(tinta_px) >= 40:  # o miolo da letra: a metade mais longe do fundo
        dist = np.abs(tinta_px.astype(float) - fundo).max(1)
        tinta_px = tinta_px[dist >= np.median(dist)]
    texto = None
    if len(tinta_px) >= 20:
        if len(tinta_px) >= 60:  # duas cores na tinta (texto + destaque): fica a de mais pixels
            _, r2, c2 = cv2.kmeans(tinta_px.astype(np.float32), 2, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1), 2,
                                   cv2.KMEANS_PP_CENTERS)
            texto = c2[np.bincount(r2.ravel(), minlength=2).argmax()]
        else:
            texto = np.median(tinta_px, 0)
    # acento: pixels saturados que ocupam pouca área (somem no k-means geral)
    lp = lab(px)
    sat = (np.hypot(lp[:, 1] - 128, lp[:, 2] - 128) > 45) & (lp[:, 0] > 70)  # cor forte de verdade (sépia/marrom não passa)
    acento, acentos = None, []
    if 0.0005 < sat.mean() < 0.15:
        sp = px[sat]
        if texto is not None:  # o texto colorido não é acento
            sp = sp[np.abs(sp - texto).max(1) > 50]
        if len(sp) >= max(10, 0.0005 * len(px)):
            if len(sp) >= 60:  # até 3 cores saturadas; vale a que tem 15%+ dos pixels saturados
                _, r3, c3 = cv2.kmeans(sp.astype(np.float32), 3, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1), 2,
                                       cv2.KMEANS_PP_CENTERS)
                parte = np.bincount(r3.ravel(), minlength=3) / len(sp)
                acentos = [c3[i] for i in np.argsort(-parte) if parte[i] >= 0.15]
            else:
                acentos = [np.median(sp, 0)]
            acento = acentos[0]
    return {"fundo": hexa(fundo), "texto": hexa(texto) if texto is not None else None, "acento": hexa(acento) if acento is not None else None,
            "acentos": [hexa(a) for a in acentos],
            "acento_area": round(100 * float(sat.mean()), 2),
            "cores": [{"hex": hexa(cen[i]), "area": round(100 * float(area[i]), 1), "saturada": bool(chroma[i] > 30)} for i in ordem]}


# ---------------------------------------------------------------- 3. som
def som(video, eventos, fps):
    """eventos: [(tempo s, rótulo)] — diz quais caem num golpe"""
    tem = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", str(video)],
                         capture_output=True, text=True).stdout.strip()
    if not tem:
        return None
    sr = 8000
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"], capture_output=True).stdout
    a = np.frombuffer(raw, np.int16).astype(np.float32) / 32768
    if len(a) < sr // 2:
        return None
    jan, passo = int(0.05 * sr), int(0.01 * sr)
    n = 1 + (len(a) - jan) // passo
    idx = np.arange(jan)[None, :] + passo * np.arange(n)[:, None]
    rms = np.sqrt((a[idx] ** 2).mean(1) + 1e-12)
    db = 20 * np.log10(rms + 1e-9)
    tempo = (np.arange(n) * passo + jan / 2) / sr
    nivel = float(20 * np.log10(np.sqrt((a ** 2).mean()) + 1e-9))
    pico = float(20 * np.log10(np.abs(a).max() + 1e-9))
    env = np.maximum(0, np.diff(rms, prepend=rms[0]))
    lim = env.mean() + 2 * env.std()
    golpes = []
    for i in range(1, n - 1):
        if env[i] > lim and env[i] >= env[i - 1] and env[i] >= env[i + 1] and (not golpes or tempo[i] - golpes[-1] > 0.1):
            golpes.append(float(tempo[i] + jan / 2 / sr))  # o ataque está na borda da frente da janela que mais subiu
    # BPM: autocorrelação do envelope de ataques entre 60 e 180 golpes/min
    e = env - env.mean()
    ac = np.correlate(e, e, "full")[n - 1:]
    bpm, conf = None, 0.0
    l0, l1 = int(60 / 180 / 0.01), int(60 / 60 / 0.01)
    if ac[0] > 0 and l1 < n:
        lag = l0 + int(np.argmax(ac[l0:l1 + 1]))
        bpm, conf = round(60 / (lag * 0.01), 1), round(float(ac[lag] / ac[0]), 2)
    # quedas: trechos de ≥ 0,3 s 10 dB abaixo da mediana (a trilha baixa)
    med = float(np.median(db))
    baixo = db < med - 10
    quedas, i = [], 0
    while i < n:
        if baixo[i]:
            j = i
            while j + 1 < n and baixo[j + 1]:
                j += 1
            if tempo[j] - tempo[i] >= 0.3:
                quedas.append({"de": round(float(tempo[i]), 2), "ate": round(float(tempo[j]), 2), "db": round(float(db[i:j + 1].mean()), 1)})
            i = j + 1
        else:
            i += 1
    tol = max(0.07, 1.5 / fps)
    batem = []
    for t, rot in eventos:
        g = min(golpes, key=lambda x: abs(x - t), default=None)
        batem.append({"t": round(t, 2), "o_que": rot, "golpe": None if g is None else round(g, 2),
                      "no_golpe": g is not None and abs(g - t) <= tol})
    return {"nivel_db": round(nivel, 1), "pico_db": round(pico, 1), "mediana_db": round(med, 1), "golpes": [round(g, 2) for g in golpes],
            "bpm": bpm, "bpm_confianca": conf, "quedas": quedas, "tolerancia_s": round(tol, 3), "eventos": batem,
            "rms_50ms": {"passo_s": 0.01, "db": [round(float(x), 1) for x in db[::5]], "passo_amostra_s": 0.05}}


# ---------------------------------------------------------------- tudo
def medir(video, saida):
    video, saida = Path(video), Path(saida)
    cj = json.load(open(saida / "cenas.json", encoding="utf-8"))
    mj = json.load(open(saida / "medidas.json", encoding="utf-8"))
    fps = cj["geral"]["fps"]
    W0, H0 = map(int, cj["geral"]["tamanho"].split("x"))
    AW = 640
    AH = int(round(H0 * AW / W0 / 4) * 4)
    uf, altura = mj["largura"], mj["altura"]
    N = cj["geral"]["quadros"]
    for velho in saida.glob("olhar-*.jpg"):
        velho.unlink()

    ents = entradas(cj, mj)
    # região de recorte de cada entrada (px da análise) e quadros que ela precisa
    pede = {}
    for e in ents:
        qd = e["quadros"]
        x0 = min(x["esq"] for x in qd) / uf * AW
        x1 = max(x["dir"] for x in qd) / uf * AW
        y0 = min(x["topo"] for x in qd) / altura * AH
        y1 = max(x["topo"] + x["alt"] for x in qd) / altura * AH
        m = 0.3 * (y1 - y0)
        e["regiao"] = [int(max(0, x0 - m)), int(max(0, y0 - m)), int(min(AW, x1 + m)), int(min(AH, y1 + m))]
        e["crops"] = [None] * len(qd)
        cena_ini = next(c["ini"] for c in cj["cenas"] if c["n"] == e["cena"])
        for k, x in enumerate(qd):
            pede.setdefault(cena_ini + x["q"], []).append((e, k))
    # paleta: 1 quadro a cada ~0,5 s da cena (3 a 12) — cor que só passa um pouco (etiqueta, clarão) também conta
    pal_q = {}
    for c in cj["cenas"]:
        n_ = int(min(12, max(3, (c["fim"] - c["ini"]) / (fps / 2))))
        for f_ in np.linspace(0.1, 0.9, n_):
            pal_q.setdefault(c["ini"] + int(f_ * (c["fim"] - c["ini"] - 1)), set()).add(c["n"])
    pal_f = {}
    PW = 160
    PH = int(round(H0 * PW / W0))
    for q, f in enumerate(quadros(video, AW, AH)):
        for e, k in pede.get(q, []):
            x0, y0, x1, y1 = e["regiao"]
            e["crops"][k] = f[y0:y1, x0:x1].copy()
        if q in pal_q:
            pal_f[q] = cv2.resize(f, (PW, PH), interpolation=cv2.INTER_AREA)

    textos = []
    for e in ents:
        if any(c is None for c in e["crops"]) or e["regiao"][2] - e["regiao"][0] < 4 or e["regiao"][3] - e["regiao"][1] < 4:
            continue
        cm = next(c for c in mj["cenas"] if c["n"] == e["cena"])
        palavras = ficha(e, e["crops"], e["regiao"], uf, altura, AW, AH, cm, fps)
        for j, (resp, a, b) in enumerate(palavras):
            qa = e["quadros"][a]["q"]
            f = {"cena": e["cena"], "bloco": e["bloco"] + (f".{j + 1}" if len(palavras) > 1 else ""), "q": qa,
                 "t": round((e["abs"] + qa - e["de"]) / fps, 2), "assenta_em": e["quadros"][b]["q"],
                 # caixa do bloco já assentado (esq, topo, dir, base, na unidade do medidas.md): o que identifica o bloco
                 # de uma rodada para outra (o gabarito procura por tempo + caixa, não pelo nome L1/L2)
                 "caixa": [round(e["quadros"][b][k], 1) for k in ("esq", "topo", "dir")] + [round(e["quadros"][b]["topo"] + e["quadros"][b]["alt"], 1)],
                 **{k: {"resposta": v[0], "confianca": v[1], **(v[2] if len(v) > 2 else {})} for k, v in resp.items()}}
            duv = [k for k, v in resp.items() if v[1] < DUVIDA]
            if duv:
                arq = f"olhar-{len([t for t in textos if t.get('olhar')]) + 1:03d}.jpg"
                fim = min(len(e["crops"]), b + 3)
                recorte(e["crops"][max(0, a - 1):fim], [f"q{x['q']}" for x in e["quadros"][max(0, a - 1):fim]], saida / arq)
                f["olhar"] = {"arquivo": arq, "perguntas": duv}
            textos.append(f)

    pal = []
    for c in cj["cenas"]:
        qs = [q for q, ns in pal_q.items() if c["n"] in ns and q in pal_f]
        if not qs:
            continue
        caixas = [[b for b in cj["quadros"][q]["blocos"] if b.get("letra")] for q in qs]
        pal.append({"cena": c["n"], **paleta([pal_f[q] for q in qs], caixas)})

    eventos = [(c["t"], f"corte {c['n']} ({c['tipo']})") for c in cj["cortes"]] + \
              [(t["t"], f"entra texto C{t['cena']} {t['bloco']}") for t in textos]
    sm = som(video, sorted(eventos), fps)
    cv_ = curvas(mj, fps)
    for t in textos:  # espaço entre letras (letterSpacing, em) medido nas fichas
        if t["tamanho"].get("curva"):
            cv_.append({"cena": t["cena"], "quem": t["bloco"], **t["tamanho"].pop("curva")})
    sem = [c["n"] for c in mj["cenas"] if c["dur"] >= fps / 2 and not any(b["tipo"] == "letra" and len(b["quadros"]) >= 4 for b in c["blocos"])]
    dados = {"fps": fps, "unidade": mj["unidade"], "textos": textos, "cenas_sem_letras": sem, "paleta": pal, "som": sm, "curvas": cv_}
    json.dump(dados, open(saida / "fichas.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    escreve_resumo(saida, dados)
    return dados


def escreve_resumo(saida, d):
    fps = d["fps"]
    L = ["<!-- fichas -->", "## Medidas prontas (fichas de texto, paleta, som, curvas)", "",
         "Gerado por `npm run estudo` (`scripts/fichas.py`; números completos em `fichas.json`). **Só abra imagem onde houver ⚠** — "
         "e então só o recorte `olhar-NNN.jpg` indicado, não a folha inteira.", "",
         "### Fichas de texto (as 4 perguntas)", ""]
    if d["textos"]:
        L += ["Cada entrada de bloco de letras; (n%) = confiança da medida. q = quadro desde o início da cena.", "",
              "| cena | bloco | q | ordem | borda × falta | embalo | tamanho | ⚠ olhar |", "|---|---|---|---|---|---|---|---|"]
        for t in d["textos"]:
            cel = lambda k: f"{t[k]['resposta']} ({t[k]['confianca'] * 100:.0f}%)"
            ol = f"{t['olhar']['arquivo']}: {', '.join(t['olhar']['perguntas'])}" if t.get("olhar") else "—"
            L.append(f"| C{t['cena']} | {t['bloco']} | q{t['q']}→{t['assenta_em']} | {cel('ordem')} | {cel('borda')} | {cel('embalo')} | {cel('tamanho')} | {ol} |")
    else:
        L.append("Nenhum bloco de letras entrando (o texto já está nas cenas desde o corte, ou não há texto).")
    if d.get("cenas_sem_letras"):
        L += ["", f"⚠ Cenas de 0,5 s+ sem nenhum bloco de letras medido: {', '.join(f'C{n}' for n in d['cenas_sem_letras'])}. Se a fala ou "
              "o rastro mostram texto nelas, ele ficou fundido com a imagem (texto sobre foto/textura) — só nessas cenas responda as 4 "
              "perguntas na folha."]
    L += ["", "### Paleta por cena", "", "Papel provável: fundo = maior área · texto = tinta dentro das caixas de letra · "
          "acento = cor saturada de pouca área (% da tela).", "",
          "| cena | fundo | texto | acento | cores (área) |", "|---|---|---|---|---|"]
    for p in d["paleta"]:
        ac = f"{' · '.join(p['acentos'])} ({p['acento_area']}%)" if p["acento"] else "—"
        L.append(f"| C{p['cena']} | {p['fundo']} | {p['texto'] or '—'} | {ac} | " + " · ".join(f"{c['hex']} {c['area']:.0f}%" for c in p["cores"]) + " |")
    L += ["", "### Som", ""]
    s = d["som"]
    if not s:
        L.append("Sem faixa de áudio: tudo é visual.")
    else:
        bpm = (f"**~{s['bpm']:g} BPM** (confiança {s['bpm_confianca']:.2f}" + (" — baixa: ritmo irregular ou narração, não use como grade)" if s["bpm_confianca"] < 0.3 else ")")) if s["bpm"] else "sem BPM"
        L.append(f"- nível médio **{s['nivel_db']} dB** · pico {s['pico_db']} dB · mediana das janelas de 50 ms {s['mediana_db']} dB · {bpm}")
        L.append(f"- golpes (ataques, s): {' · '.join(f'{g:.2f}' for g in s['golpes']) or '—'}")
        L.append("- quedas (≥ 0,3 s, 10 dB abaixo da mediana): " + (" · ".join(f"{q['de']:.2f}–{q['ate']:.2f} s ({q['db']} dB)" for q in s["quedas"]) or "nenhuma"))
        no = [e for e in s["eventos"] if e["no_golpe"]]
        L.append(f"- no golpe (±{s['tolerancia_s'] * 1000:.0f} ms): **{len(no)} de {len(s['eventos'])}** eventos — "
                 + ("; ".join(f"{e['o_que']} {e['t']:.2f} s" for e in no) or "nenhum"))
    L += ["", "### Curvas dos movimentos", "",
          "Cada movimento (câmera: x, y, zoom, giro; blocos L/I do `medidas.md`: centro x, centro y, altura; espaço = letterSpacing em em, das fichas) ajustado a "
          "`Easing.bezier` e a `spring` (mass 1, fps da referência). Valores nas unidades do `medidas.md`; q = quadro da cena. "
          "erro = desvio médio em % do percurso (o outro ajuste entre parênteses). Erro > 8%: movimento composto — use o "
          "`L(...)` do `medidas.md`.", "",
          "| cena | quem | medida | q | curva (colar no Remotion) | erro |", "|---|---|---|---|---|---|"]
    for c in sorted(d["curvas"], key=lambda c: (c["cena"], c["q0"]))[:60]:
        outro = c["spring"]["erro"] if c["melhor"] == "bezier" else c["bezier"]["erro"]
        aviso = " ⚠ composto" if c["erro"] > 8 else ""
        L.append(f"| C{c['cena']} | {c['quem']} | {c['medida']} | q{c['q0']}–{c['q1']} | `{c['formula']}` | {c['erro']}% ({outro}%){aviso} |")
    if len(d["curvas"]) > 60:
        L.append(f"| … | +{len(d['curvas']) - 60} em `fichas.json` | | | | |")
    L.append("<!-- /fichas -->")
    resumo = saida / "RESUMO.md"
    txt = resumo.read_text(encoding="utf-8") if resumo.exists() else ""
    if "<!-- fichas -->" in txt:
        txt = txt[:txt.index("<!-- fichas -->")] + txt[txt.index("<!-- /fichas -->") + len("<!-- /fichas -->"):].lstrip("\n")
    txt = txt.rstrip("\n") + "\n\n" + "\n".join(L) + "\n"
    resumo.write_text(txt, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    opts = {a[2:].split("=")[0]: (a.split("=", 1)[1] if "=" in a else True) for a in sys.argv[1:] if a.startswith("--")}
    if not args:
        sys.exit(__doc__)
    v = Path(args[0]).resolve()
    s = Path(opts["saida"]).resolve() if "saida" in opts else v.parent.parent / "analise"
    d = medir(v, s)
    n_ol = sum(1 for t in d["textos"] if t.get("olhar"))
    print(f"✔ {s / 'fichas.json'} — {len(d['textos'])} ficha(s) de texto ({n_ol} com ⚠ olhar), paleta de {len(d['paleta'])} cena(s), "
          f"{'sem áudio' if not d['som'] else str(len(d['som']['golpes'])) + ' golpe(s)'}, {len(d['curvas'])} curva(s)")
