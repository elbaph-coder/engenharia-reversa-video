"""Análise quadro a quadro de um vídeo de referência (passo 2 da skill estudar-video).

    npm run estudo -- referencias/<estilo>/fonte/<video>.mp4                → modo econômico (padrão)
    npm run estudo -- referencias/<estilo>/fonte/<video>.mp4 --completo     → folhas de todas as cenas e de todos os cortes
    opções: --sem-fala (não transcreve) · --saida=<pasta> (padrão: referencias/<estilo>/analise/)
           --so-medidas (só medidas.md/json: sem folhas, resumo nem fala — usado pelo npm run comparar)
           --so-movimento (só imprime cortes/min, movimento médio e % parados em JSON — usado pelo npm run ritmo)
           --so-fonte (só põe a fonte do carimbo em fonte/f.ttf — para o nível rápido, que não roda o estudo)

Cenas: vêm do `npm run camadas` (scripts/camadas.py, rodado antes de medir → analise/camadas.json + CAMADAS.md) — a
fonte única das fronteiras de cena, a mesma do decompor. Aqui se mede só o tipo de MOVIMENTO de cada corte; o tipo da
troca (corte, clarão, fusão, pelo preto…) vem do camadas e sai junto. No fim roda o `npm run decompor` (assets/ +
analise/decomposicao.json) e põe a fonte do carimbo em fonte/f.ttf se faltar.

Lê TODOS os quadros (nada de 1 a cada 4) e gera, sem ninguém olhar nada ainda:
  analise/RESUMO.md     cenas (entre cortes) com movimento medido, eventos (elemento entra/sai, desliza, letras abrem/
                        fecham, cresce, pico de 1–2 q, deriva lenta, cópias pequenas que deslizam), repetições (refrão),
                        tipo de cada corte (seco / com embalo / entra pela borda), a cobertura das folhas (o que ficou de
                        fora — eventos fora tem que ser 0) e a lista de folhas para ver — é por ele que se começa
  analise/cenas.json    os mesmos dados + caixa de cada bloco de texto em cada quadro
  analise/medidas.md    por cena: câmera (fluxo óptico: x, y, zoom, giro; saltos = cortes de aproximação), letras e
                        imagens (fotos, objetos, papéis) separadas — "⚠ conferir na folha" onde a separação ficou em
                        dúvida; em fundo liso a câmera sai das letras —, em quadros-chave já no formato L(q, [...], [...]),
                        nas unidades da folha: recriar sem medir nas folhas à mão (medidas.json: os mesmos + todos os quadros)
  analise/cenas-NNN.jpg quadros das cenas, grandes; cenas seguidas dividem a folha (borda vermelha = começo de cena,
                        rótulo C<n>); no econômico: todos na entrada, na saída e em volta de cada evento, 1 a cada 4 no resto
  analise/corte-NNN.jpg 6 quadros antes e 6 depois de um corte
  analise/rastros-NNN.jpg  uma imagem por cena estudada com todos os quadros sobrepostos, cor = tempo (azul → vermelho):
                        mostra o movimento numa imagem só (direção, freio/aceleração, espalhar, entrar pela borda)
  analise/setas-NNN.jpg setas de movimento (fluxo óptico) num momento de movimento lento/médio de cada cena
  RESUMO.md → "Narração por cena": cada bloco de texto acompanhado e descrito em palavras (entra, desliza, abre, some)
  analise/fichas.json   + seção "Medidas prontas" no RESUMO.md (scripts/fichas.py): as 4 perguntas de cada entrada de texto
                        com confiança, paleta por cena com papel, som (golpes, BPM, quedas, o que cai no golpe) e a curva de
                        cada movimento (Easing.bezier / spring prontos para colar); olhar-NNN.jpg = recorte só onde há ⚠
  fonte/fala.txt        transcrição palavra por palavra (faster-whisper medium, idioma automático) — fora do git; antes, um
                        detector de voz (VAD, < 1 s) pula o medium quando o áudio é só música; se a fala sair só "Music"/
                        vazia, o fala.txt diz "sem fala"
Econômico: folhas só das cenas com ação que não são repetição e só dos cortes que não são secos. Completo: tudo.
As medidas mostram ONDE olhar; o entendimento vem de ler as folhas.
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage
import cv2

sys.stdout.reconfigure(encoding="utf-8")

args = [a for a in sys.argv[1:] if not a.startswith("--")]
opts = {a[2:].split("=")[0]: (a.split("=", 1)[1] if "=" in a else True) for a in sys.argv[1:] if a.startswith("--")}
if not args:
    sys.exit(__doc__)
video = Path(args[0]).resolve()
completo = bool(opts.get("completo"))
saida = Path(opts["saida"]).resolve() if "saida" in opts else (video.parent.parent / "analise")
so_medidas = bool(opts.get("so-medidas"))
so_movimento = bool(opts.get("so-movimento"))

# fonte do carimbo (rótulos das folhas; F=fonte/f.ttf no ffmpeg — caminho com "C:" quebra o filtro drawtext)
SISTEMA = [Path("C:/Windows/Fonts/arialbd.ttf"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")]
carimbo = video.parent / "f.ttf"
if video.parent.name == "fonte" and not carimbo.exists():
    origem = next((f for f in SISTEMA if f.exists()), None)
    if origem:
        carimbo.write_bytes(origem.read_bytes())
if not carimbo.exists():
    carimbo = next((f for f in SISTEMA if f.exists()), None)
if opts.get("so-fonte"):
    sys.exit(f"✔ fonte do carimbo: {carimbo}" if carimbo else "✘ sem fonte do sistema para copiar")
if not so_movimento:
    saida.mkdir(parents=True, exist_ok=True)
for velho in [] if (so_medidas or so_movimento) else list(saida.glob("cena*.jpg")) + list(saida.glob("corte-*.jpg")) + list(saida.glob("rastros-*.jpg")) + list(saida.glob("setas-*.jpg")):
    velho.unlink()

# ---------------------------------------------------------------- ficha técnica
p = json.loads(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                               "stream=width,height,r_frame_rate:format=duration", "-of", "json", str(video)],
                              capture_output=True, text=True).stdout)
W0, H0 = p["streams"][0]["width"], p["streams"][0]["height"]
n_, d_ = map(int, p["streams"][0]["r_frame_rate"].split("/"))
FPS = n_ / d_
DUR = float(p["format"]["duration"])

AW = 640  # largura da análise (alta o bastante para medir as cópias pequenas do texto)
AH = int(round(H0 * AW / W0 / 4) * 4)
TW = 368 if W0 >= H0 else 240  # largura de cada quadro nas folhas
TH = int(round(H0 * TW / W0 / 2) * 2)


def quadros(largura, altura):
    cmd = ["ffmpeg", "-v", "error", "-i", str(video), "-vf", f"scale={largura}:{altura}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    tam = largura * altura * 3
    while True:
        b = proc.stdout.read(tam)
        if len(b) < tam:
            break
        yield np.frombuffer(b, np.uint8).reshape(altura, largura, 3)
    proc.wait()


hexa = lambda c: "#%02x%02x%02x" % tuple(int(v) for v in c)


def rgb(h):
    return np.array([int(h[k:k + 2], 16) for k in (1, 3, 5)])

# ---------------------------------------------------------------- passo 1: medir cada quadro
print(f"▶ {video.name}: {W0}×{H0}, {FPS:g} qps, {DUR:.1f} s — medindo todos os quadros…")
med = []  # por quadro: dif, fundo, blocos
cam = []  # por quadro: movimento da imagem desde o anterior (tx, ty em fração da largura; escala; giro em graus)


def camera(a, b):
    """movimento de câmera entre dois quadros pequenos: fluxo óptico + ajuste robusto de translação, escala e giro
    (o fundo manda; o que se mexe sozinho — texto, objeto — sai como resíduo)"""
    fl = cv2.calcOpticalFlowFarneback(a.astype(np.uint8), b.astype(np.uint8), None, 0.5, 3, 15, 3, 5, 1.2, 0)
    h, w = a.shape
    ys, xs = np.mgrid[2:h:4, 2:w:4]
    u, v = fl[ys, xs, 0].ravel(), fl[ys, xs, 1].ravel()
    x, y = (xs.ravel() - w / 2), (ys.ravel() - h / 2)
    # textura: só pontos com contraste (fundo chapado não diz nada sobre a câmera)
    gy, gx = np.gradient(a)
    ok = (np.hypot(gx, gy)[ys, xs].ravel() > 3)
    if ok.mean() < 0.08:
        return None  # fundo liso (preto, céu, cor chapada): não há o que medir
    tex = ok.copy()
    for _ in range(3):
        A = np.zeros((2 * ok.sum(), 4))
        A[0::2] = np.c_[x[ok], -y[ok], np.ones(ok.sum()), np.zeros(ok.sum())]
        A[1::2] = np.c_[y[ok], x[ok], np.zeros(ok.sum()), np.ones(ok.sum())]
        rhs = np.empty(2 * ok.sum())
        rhs[0::2], rhs[1::2] = u[ok], v[ok]
        sol = np.linalg.lstsq(A, rhs, rcond=None)[0]
        res = np.hypot(sol[0] * x - sol[1] * y + sol[2] - u, sol[1] * x + sol[0] * y + sol[3] - v)
        lim = np.percentile(res[ok], 70)
        ok = ok & (res <= max(lim, 0.3))
        if ok.sum() < 40:
            break
    # confiança: a maior parte do que tem textura anda junto? (senão o "movimento" é de objetos soltos, não da câmera)
    if (res[tex] < 0.6).mean() < 0.5:
        return None
    return (float(sol[2] / w), float(sol[3] / w), float(1 + sol[0]), float(np.degrees(sol[1])))


def parece_letra(dentro):
    """o bloco parece texto? várias peças (letras) quase da altura da linha, sem encher a caixa; foto/forma/papel não.
    Devolve (é letra?, motivo da dúvida ou None) — dúvida = alguma medida perto do limite da decisão"""
    hh, ww = dentro.shape
    cheio = float(dentro.mean())
    duvida = []
    lab, n = ndimage.label(dentro)
    if n == 0:
        return False, None
    alturas = [sl[0].stop - sl[0].start for sl in ndimage.find_objects(lab)]
    altas = sum(1 for a in alturas if a >= 0.45 * hh)
    com_letras = 3 <= n <= 40 and altas >= 3  # estrutura de texto: várias peças da altura da linha
    if hh > AH * 0.22 or ww < hh * 0.35 or cheio > 0.7:
        # imagem — só é dúvida se, mesmo assim, tem cara de linha de letras (palavra gigante, letra grossa colada)
        if com_letras and hh <= 0.35 * AH and cheio <= 0.85:
            duvida.append("palavra gigante ou letra grossa colada?" if hh > AH * 0.22 else "letras coladas enchendo a caixa (ou etiqueta)?")
        return False, (duvida[0] if duvida else None)
    letra = n <= 40 and (altas >= 2 or (n == 1 and cheio < 0.5 and ww < hh * 1.2))
    if letra and cheio < 0.12:
        duvida.append("traços finos e ralos (desenho, ícones, grade?)")
    if not letra and com_letras:
        duvida.append("várias peças da altura da linha (texto colado?)")
    return letra, (duvida[0] if duvida else None)
mini = []  # 32×18 cinza, para achar cenas repetidas
ant = None
kern = np.ones((3, max(3, AW // 40)), bool)  # junta letras numa palavra/linha
area_min = AW * AH * 0.0006
for f in quadros(AW, AH):
    g = f.mean(2)
    pequeno = g.reshape(AH // 4, 4, AW // 4, 4).mean((1, 3))  # 160 px: o grão some
    dif = float(np.abs(pequeno - ant).mean()) if ant is not None else 0.0
    cam.append(camera(ant, pequeno) if ant is not None and not so_movimento else None)
    ant = pequeno
    q = (f // 32).astype(np.int32)
    chave = q[..., 0] * 64 + q[..., 1] * 8 + q[..., 2]
    vals, cont = np.unique(chave, return_counts=True)
    k = vals[cont.argmax()]
    fundo = f[chave == k].mean(0)
    # texto = muito diferente do fundo em algum canal (manchas cinza da textura e grão não passam); tira pontinhos de meio-tom
    mask = np.abs(f.astype(np.int16) - fundo).max(2) > 110
    mask = ndimage.binary_opening(mask, np.ones((3, 3), bool))
    rot, n = ndimage.label(ndimage.binary_dilation(mask, kern))
    blocos = []
    for i, sl in enumerate(ndimage.find_objects(rot)):
        dentro = mask[sl] & (rot[sl] == i + 1)
        a = int(dentro.sum())
        if a < area_min:
            continue
        cor = np.median(f[sl][dentro], 0)
        y0, y1, x0, x1 = sl[0].start, sl[0].stop, sl[1].start, sl[1].stop
        blocos.append({"x": round(x0 / AW, 3), "y": round(y0 / AH, 3), "w": round((x1 - x0) / AW, 3), "h": round((y1 - y0) / AH, 3),
                       "area": a, "cor": hexa(cor), **dict(zip(("letra", "duvida"), parece_letra(dentro)))})
    # letras muito espaçadas (T H A T) viram blocos separados: junta o que está na mesma linha e perto (até 4× a altura)
    juntou = True
    while juntou:
        juntou = False
        for i in range(len(blocos)):
            for j in range(i + 1, len(blocos)):
                a_, b_ = blocos[i], blocos[j]
                ha, hb = a_["h"] * AH, b_["h"] * AH
                vert = min(a_["y"] + a_["h"], b_["y"] + b_["h"]) - max(a_["y"], b_["y"])
                gap = max(a_["x"], b_["x"]) - min(a_["x"] + a_["w"], b_["x"] + b_["w"])
                mesma_cor = np.abs(rgb(a_["cor"]) - rgb(b_["cor"])).max() < 120  # letras da mesma palavra têm a mesma cor
                if mesma_cor and vert * AH > 0.6 * min(ha, hb) and 0.6 < ha / max(hb, 1) < 1.7 and gap * AW < 4 * max(ha, hb):
                    x0, y0 = min(a_["x"], b_["x"]), min(a_["y"], b_["y"])
                    x1, y1 = max(a_["x"] + a_["w"], b_["x"] + b_["w"]), max(a_["y"] + a_["h"], b_["y"] + b_["h"])
                    cor = a_["cor"] if a_["area"] >= b_["area"] else b_["cor"]
                    blocos[i] = {"x": round(x0, 3), "y": round(y0, 3), "w": round(x1 - x0, 3), "h": round(y1 - y0, 3),
                                 "area": a_["area"] + b_["area"], "cor": cor, "letra": a_["letra"] and b_["letra"],
                                 "duvida": a_.get("duvida") or b_.get("duvida")}
                    del blocos[j]
                    juntou = True
                    break
            if juntou:
                break
    blocos.sort(key=lambda b: -b["area"])
    med.append({"dif": round(dif, 2), "fundo": hexa(fundo), "blocos": blocos[:8]})
    mini.append(np.asarray(Image.fromarray(g.astype(np.uint8)).resize((32, 18)), np.float32))
N = len(med)

# ---------------------------------------------------------------- passo 2: cortes e cenas (do camadas: fonte única)
PARADO = 0.8
_cam = [sys.executable, "-P", str(Path(__file__).with_name("camadas.py")), str(video)]
if so_movimento or so_medidas:
    trocas = json.loads(subprocess.run(_cam + ["--so-trocas"], capture_output=True, text=True, encoding="utf-8", check=True).stdout)["trocas"]
else:
    subprocess.run(_cam + [f"--saida={saida}"], check=True, stdout=subprocess.DEVNULL)
    trocas = json.load(open(saida / "camadas.json", encoding="utf-8"))["trocas"]
troca_de = {t["corte"]: t for t in trocas if 0 < t["corte"] < N}
cortes = sorted(troca_de)
limites = [0] + cortes + [N]
cenas = [{"n": k + 1, "ini": a, "fim": b} for k, (a, b) in enumerate(zip(limites, limites[1:])) if b > a]
if so_movimento:
    _difs = [m["dif"] for i, m in enumerate(med[1:], 1) if i not in set(cortes)]
    print(json.dumps({"cortes_por_min": round(len(cortes) / (DUR / 60), 1), "cena_media_s": round(DUR / len(cenas), 2),
                      "movimento_medio": round(float(np.mean(_difs)), 2), "quadros_parados_pct": round(100 * float(np.mean([d < PARADO for d in _difs])), 1)}))
    sys.exit(0)

seg = lambda q: q / FPS


def principal(i):
    b = med[i]["blocos"]
    return b[0] if b else None


def mexe(i0, i1):
    """quanto o bloco principal andou/mudou de largura entre dois quadros (fração da largura)"""
    p0, p1 = principal(i0), principal(i1)
    if not (p0 and p1):
        return 0.0
    return max(abs((p1["x"] + p1["w"] / 2) - (p0["x"] + p0["w"] / 2)), abs(p1["w"] - p0["w"]), abs(p1["y"] - p0["y"]))


def fim_parado(i, fim):
    """último quadro do trecho parado que começa em i: imagem quase igual E o texto principal no mesmo lugar"""
    j = i
    while j + 1 < fim and med[j + 1]["dif"] < PARADO and mexe(i, j + 1) < 0.006:
        j += 1
    return j


def pequenos_andam(i):
    """deslocamento horizontal mediano das cópias pequenas (blocos 2..N) entre i-1 e i, casadas pelo centro mais perto"""
    a_, b_ = med[i - 1]["blocos"][1:], med[i]["blocos"][1:]
    dx = []
    for p in b_:
        cx, cy = p["x"] + p["w"] / 2, p["y"] + p["h"] / 2
        melhor = min(a_, key=lambda o: abs(o["x"] + o["w"] / 2 - cx) + abs(o["y"] + o["h"] / 2 - cy), default=None)
        if melhor and abs(melhor["y"] + melhor["h"] / 2 - cy) < 0.03 and abs(melhor["x"] + melhor["w"] / 2 - cx) < 0.1                 and 0.7 < p["h"] / max(melhor["h"], 1e-3) < 1.4:
            dx.append(cx - (melhor["x"] + melhor["w"] / 2))
    return float(np.median(dx)) if len(dx) >= 2 else 0.0


for c in cenas:
    a, b = c["ini"], c["fim"]
    difs = [med[i]["dif"] for i in range(a + 1, b)]
    c["dur"] = b - a
    c["fundo"] = max(set(med[i]["fundo"] for i in range(a, b)), key=[med[i]["fundo"] for i in range(a, b)].count)
    c["mov"] = round(float(np.mean(difs)), 2) if difs else 0.0
    c["parados"] = round(100 * float(np.mean([d < PARADO for d in difs])), 0) if difs else 100.0
    # eventos: nº de blocos muda; o principal desliza, cresce/encolhe (letras abrindo/fechando ou escala)
    ev = []
    nb_ant = len(med[a]["blocos"])
    for i in range(a + 1, b):
        nb = len(med[i]["blocos"])
        dura = i + 1 < b and len(med[i + 1]["blocos"]) == nb
        if nb != nb_ant and dura:
            ev.append((i, f"{'+' if nb > nb_ant else '−'}{abs(nb - nb_ant)} bloco(s) ({nb_ant}→{nb})"))
            nb_ant = nb
    trilha = [(i, principal(i)) for i in range(a, b) if principal(i)]
    run = None
    for (i0, p0), (i1, p1) in zip(trilha, trilha[1:]):
        if i1 != i0 + 1 or abs(p1["area"] - p0["area"]) > 0.5 * max(p0["area"], 1):
            continue  # o "principal" trocou de bloco
        cx = (p1["x"] + p1["w"] / 2) - (p0["x"] + p0["w"] / 2)
        dw = p1["w"] - p0["w"]
        tipo = "→" if cx > 0.004 else "←" if cx < -0.004 else None
        abre = "abre/cresce" if dw > 0.006 else "fecha/encolhe" if dw < -0.006 else None
        sig = (tipo, abre)
        if run and run["sig"] == sig and run["fim"] == i0:
            run["fim"] = i1
            run["dx"] += cx
            run["dw"] += dw
        else:
            if run and run["sig"] != (None, None) and run["fim"] - run["ini"] >= 2:
                ev.append((run["ini"], run))
            run = {"sig": sig, "ini": i0, "fim": i1, "dx": cx, "dw": dw}
    if run and run["sig"] != (None, None) and run["fim"] - run["ini"] >= 2:
        ev.append((run["ini"], run))
    c["corridas"] = [(e["ini"], e["fim"], e["dx"], e["dw"]) for _, e in ev if isinstance(e, dict)]
    # picos: algo rápido (1–2 quadros) — rasgo, piscada, inversão
    for i in range(a + 1, b):
        viz = [med[k]["dif"] for k in range(max(a + 1, i - 4), min(b, i + 5)) if k != i]
        if viz and med[i]["dif"] > max(4.0, 3 * float(np.median(viz))):
            ev.append((i, "pico: mudança rápida (1–2 q) — ver na folha"))
    # deriva lenta: imagem quase igual, mas o texto anda devagar (o "nunca para")
    i = a
    while i < b:
        j = i
        while j + 1 < b and med[j + 1]["dif"] < PARADO:
            j += 1
        if j - i >= 2 and mexe(i, j) >= 0.006:
            p0, p1 = principal(i), principal(j)
            dx = (p1["x"] + p1["w"] / 2) - (p0["x"] + p0["w"] / 2)
            dw = p1["w"] - p0["w"]
            ev.append((i, f"deriva lenta até q{j - a}: {'→' if dx > 0 else '←'} {abs(dx) * 100:.1f}%, largura {dw * 100:+.1f}%"))
        i = j + 1 if j > i else i + 1
    # cópias pequenas que deslizam (imitam a principal ou não)
    corrida, ini_c = 0, None
    for i in range(a + 1, b + 1):
        v = pequenos_andam(i) if i < b else 0.0
        sinal = 1 if v > 0.004 else -1 if v < -0.004 else 0
        if sinal and sinal == corrida:
            continue
        if corrida and i - ini_c >= 2:
            ev.append((ini_c, f"cópias pequenas deslizam {'→' if corrida > 0 else '←'} até q{i - 1 - a}"))
        corrida, ini_c = sinal, i
    c["q_eventos"] = [i for i, _ in ev]
    textos = []
    for i, e in sorted(ev, key=lambda x: x[0]):
        if isinstance(e, str):
            textos.append(f"q{i - a}: {e}")
        else:
            partes = []
            if e["sig"][0]:
                partes.append(f"desliza {e['sig'][0]} {abs(e['dx']) * 100:.0f}% da largura")
            if e["sig"][1]:
                partes.append(f"largura {e['dw'] * 100:+.0f}% ({e['sig'][1]})")
            textos.append(f"q{e['ini'] - a}–q{e['fim'] - a}: principal " + ", ".join(partes))
    c["eventos"] = textos
    # repetição: mesma duração (±3 q) e mesmos quadros pequenos no começo, meio e fim
    c["repete"] = None
    for o in cenas:
        if o["n"] >= c["n"]:
            break
        if abs(o["dur"] - c["dur"]) <= 3 and c["dur"] > 4:
            pares = [(o["ini"] + int(f * (o["dur"] - 1)), a + int(f * (c["dur"] - 1))) for f in (0.15, 0.5, 0.85)]
            if np.mean([np.abs(mini[x] - mini[y]).mean() for x, y in pares]) < 7:
                c["repete"] = o["repete"] or o["n"]
                break
    c["acao"] = c["dur"] > 3 and (c["parados"] < 90 or len(textos) > 0)

# narração: acompanha TODOS os blocos de texto da cena (não só o principal) e descreve cada um em palavras
def nome_cor(h):
    r, g, b = rgb(h)
    if r > 150 and g < 90 and b < 90:
        return "vermelho"
    if max(r, g, b) < 70:
        return "preto"
    if min(r, g, b) > 190:
        return "branco"
    return f"cinza/{h}"


def onde(cx, cy):
    return ("esq" if cx < 0.33 else "centro" if cx < 0.67 else "dir") + "/" + ("alto" if cy < 0.33 else "meio" if cy < 0.67 else "baixo")


def narrar(c):
    a, b = c["ini"], c["fim"]
    trilhas = []
    for i in range(a, b):
        livres = [t for t in trilhas if t["fim"] == i - 1]
        for bl in med[i]["blocos"]:
            cx, cy = bl["x"] + bl["w"] / 2, bl["y"] + bl["h"] / 2
            melhor, dist = None, 1e9
            for t in livres:
                u = t["blocos"][-1]
                ux, uy = u["x"] + u["w"] / 2, u["y"] + u["h"] / 2
                d = abs(ux - cx) + abs(uy - cy)
                if d < dist and abs(uy - cy) < 0.06 and abs(ux - cx) < 0.15 + u["w"] / 2 and 0.6 < bl["h"] / max(u["h"], 1e-3) < 1.6 \
                        and np.abs(rgb(u["cor"]) - rgb(bl["cor"])).max() < 120:
                    melhor, dist = t, d
            if melhor:
                melhor["blocos"].append(bl)
                melhor["qs"].append(i)
                melhor["fim"] = i
                livres.remove(melhor)
            else:
                trilhas.append({"ini": i, "fim": i, "blocos": [bl], "qs": [i]})
    c["trilhas"] = trilhas
    frases = []
    for t in sorted(trilhas, key=lambda t: -max(x["area"] for x in t["blocos"]))[:8]:
        n = len(t["blocos"])
        if n < 3:
            continue
        p0, p1 = t["blocos"][0], t["blocos"][-1]
        tam = max(x["h"] for x in t["blocos"])
        porte = "grande" if tam > 0.25 else "médio" if tam > 0.08 else "pequeno"
        borda0 = p0["x"] < 0.02 and "esq" or p0["x"] + p0["w"] > 0.98 and "dir" or None
        borda1 = p1["x"] < 0.02 and "esq" or p1["x"] + p1["w"] > 0.98 and "dir" or None
        partes = [f"{porte} {nome_cor(p0['cor'])}"]
        partes.append(("já está" if t["ini"] == a else f"aparece em q{t['ini'] - a}") + (f" entrando pela borda {borda0}" if borda0 and p0["w"] < 0.95 else "")
                      + f" ({onde(p0['x'] + p0['w'] / 2, p0['y'] + p0['h'] / 2)})")
        dx = (p1["x"] + p1["w"] / 2) - (p0["x"] + p0["w"] / 2)
        dy = (p1["y"] + p1["h"] / 2) - (p0["y"] + p0["h"] / 2)
        dw = p1["w"] - p0["w"]
        dl, dr = p1["x"] - p0["x"], (p1["x"] + p1["w"]) - (p0["x"] + p0["w"])
        if abs(dx) > 0.02:
            # velocidade no primeiro terço × no último terço do trajeto
            cxs = [x["x"] + x["w"] / 2 for x in t["blocos"]]
            k3 = max(1, n // 3)
            v1 = abs(cxs[k3] - cxs[0]) / k3
            v2 = abs(cxs[-1] - cxs[-1 - k3]) / k3
            ritmo = " freando" if v2 < 0.6 * v1 else " acelerando" if v2 > 1.6 * v1 else ""
            passos = [abs(b2 - a2) for a2, b2 in zip(cxs, cxs[1:])]
            if len(passos) >= 6 and np.mean(passos[-3:]) > 2.5 * max(np.median(passos), 1e-4):
                ritmo += " e dispara no fim"
            partes.append(f"desliza {'→' if dx > 0 else '←'} {abs(dx) * 100:.0f}%{ritmo}")
        if abs(dy) > 0.03:
            partes.append(f"{'desce' if dy > 0 else 'sobe'} {abs(dy) * 100:.0f}%")
        if abs(dw) > 0.02:
            lado = " só para a direita" if abs(dl) < 0.01 and dr > 0.02 else " só para a esquerda" if abs(dr) < 0.01 and dl < -0.02 else ""
            partes.append(f"{'abre/cresce' if dw > 0 else 'fecha/encolhe'} {abs(dw) * 100:.0f}%{lado if dw > 0 else ''}")
        if abs(dl) > 0.02 and abs(dr) < 0.01 and dw < 0:
            partes.append("perde a parte da esquerda (comida pela esquerda?)")
        partes.append((f"some em q{t['fim'] - a}" if t["fim"] < b - 1 else "fica até o fim") + (f" saindo pela borda {borda1}" if borda1 and p1["w"] < 0.95 else ""))
        frases.append(" · ".join(partes))
    return frases


for c in cenas:
    c["narracao"] = narrar(c)

# tipo de cada corte: o movimento atravessa o corte?
def vel(i0, i1, borda_dir=False):
    """deslocamento médio por quadro do bloco principal (centro, ou borda direita/esquerda que mais anda)"""
    v = []
    for i in range(i0, i1):
        p0, p1 = principal(i), principal(i + 1)
        if not (p0 and p1):
            continue
        sobrepoe = min(p0["y"] + p0["h"], p1["y"] + p1["h"]) - max(p0["y"], p1["y"]) > 0.5 * min(p0["h"], p1["h"])
        if not sobrepoe:
            continue
        esq, dirx = p1["x"] - p0["x"], (p1["x"] + p1["w"]) - (p0["x"] + p0["w"])
        v.append(dirx if abs(dirx) > abs(esq) else esq)  # a borda que mais anda (letras abrindo para um lado contam)
    return float(np.median(v)) if len(v) >= 2 else 0.0


corte_info = []
for k, q in enumerate(cortes):
    antes, depois = vel(max(0, q - 5), q - 1), vel(q, min(N - 1, q + 4))
    p = principal(q)
    borda = p and (p["x"] < 0.02 or p["x"] + p["w"] > 0.98) and p["w"] < 0.95
    LIM = 0.01  # 1% da largura por quadro
    if abs(antes) > LIM and abs(depois) > LIM and np.sign(antes) == np.sign(depois):
        tipo = f"com embalo {'→' if depois > 0 else '←'}"
    elif borda and abs(depois) > LIM:
        tipo = f"entra pela borda {'→' if depois > 0 else '←'}"
    elif abs(antes) > LIM:
        tipo = f"sai em movimento {'→' if antes > 0 else '←'}"
    elif abs(depois) > LIM:
        tipo = f"entra em movimento {'→' if depois > 0 else '←'}"
    else:
        tipo = "seco"
    cena_dep = next(c for c in cenas if c["ini"] == q)
    tr = troca_de[q]
    corte_info.append({"n": k + 1, "q": q, "t": round(seg(q), 2), "tipo": tipo, "troca": tr["tipo"], "de": tr["de"], "ate": tr["ate"],
                       "repete": cena_dep["repete"] is not None})

# ---------------------------------------------------------------- medidas de cada bloco (para recriar sem medir à mão)
# unidades da folha: a largura de um quadro das folhas (TW) — as mesmas que se leem nas folhas; topo e altura do bloco
# (≈ topo e altura da maiúscula). Só os quadros-chave: onde a trajetória muda (simplificação com tolerância de 1 unidade).
UF = TW


def chaves(series, tol=1.0):
    """índices onde alguma das séries muda de rumo (Ramer–Douglas–Peucker em cada série, unidos)"""
    n = len(series[0])
    marca = {0, n - 1}

    def rdp(v, i0, i1):
        if i1 - i0 < 2:
            return
        a, b = v[i0], v[i1]
        pior, k = 0.0, None
        for i in range(i0 + 1, i1):
            esperado = a + (b - a) * (i - i0) / (i1 - i0)
            d = abs(v[i] - esperado)
            if d > pior:
                pior, k = d, i
        if pior > tol:
            marca.add(k)
            rdp(v, i0, k)
            rdp(v, k, i1)

    for v in series:
        rdp(v, 0, n - 1)
    return sorted(marca)


TOL_CHAVE = 1.5  # unidades da folha (~1,5 = 7 px em 1080): o caminho entre os quadros-chave nunca se afasta mais que isso


def chaves_max(series, tol=TOL_CHAVE):
    """quadros-chave por erro, não por quantidade: tantos quantos o movimento pedir para o caminho traçado ficar a até `tol`
    do real — ruído menor que isso some; voltas, quiques e "respiração" maiores que isso ficam"""
    return chaves(series, tol)


def kserie(b, f, casas=1):
    """uma medida de um bloco com os seus próprios quadros-chave (por erro), no formato do código"""
    qs = [x["q"] for x in b["quadros"]]
    vs = [f(x) for x in b["quadros"]]
    ks = chaves([vs], TOL_CHAVE)
    return kq([qs[k] for k in ks], [vs[k] for k in ks], casas)


def kq(qs, vs, casas=1):
    """quadros-chave no formato do código: L(q, [quadros], [valores]) — caminho liso (@/pecas/movimento)"""
    f = (lambda v: f"{v:.{casas}f}".rstrip("0").rstrip(".") if casas else f"{v:.0f}")
    return f"L(q, [{', '.join(str(q) for q in qs)}], [{', '.join(f(v) for v in vs)}])"


medidas = {"unidade": f"1 = 1/{UF} da largura (folha {UF}×{round(H0 * UF / W0)})", "largura": UF, "altura": round(H0 * UF / W0, 1),
           "fps": round(FPS, 3), "quadros": N, "cortes": cortes, "cenas": []}
for c in cenas:
    blocos_c = []
    r = H0 * UF / W0
    for t in sorted(c["trilhas"], key=lambda t: -max(x["area"] for x in t["blocos"])):
        if len(t["blocos"]) < 2 or len(blocos_c) >= 14:
            continue
        votos = sum(b.get("letra", False) for b in t["blocos"]) / len(t["blocos"])
        letra = votos >= 0.5
        motivos = [b["duvida"] for b in t["blocos"] if b.get("duvida")]
        curto = len(t["blocos"]) < 4  # 2–3 quadros: resto de transição, não vale abrir folha por isso
        duvida = None if curto else ("ora parece letra, ora imagem" if 0.3 < votos < 0.7 else
                                     max(set(motivos), key=motivos.count) if len(motivos) >= 0.4 * len(t["blocos"]) else None)
        t["letra"] = letra
        esq = [round(b["x"] * UF, 1) for b in t["blocos"]]
        dir_ = [round((b["x"] + b["w"]) * UF, 1) for b in t["blocos"]]
        topo = [round(b["y"] * r, 1) for b in t["blocos"]]
        alt = [round(b["h"] * r, 1) for b in t["blocos"]]
        ks = chaves_max([esq, dir_, topo, alt])
        blocos_c.append({"tipo": "letra" if letra else "imagem", "duvida": duvida, "cor": nome_cor(t["blocos"][0]["cor"]), "hex": t["blocos"][0]["cor"],
                         "de": t["ini"] - c["ini"], "ate": t["fim"] - c["ini"],
                         "chaves": [{"q": t["qs"][k] - c["ini"], "esq": esq[k], "dir": dir_[k], "topo": topo[k], "alt": alt[k]} for k in ks],
                         "quadros": [{"q": q - c["ini"], "esq": e, "dir": d, "topo": tp, "alt": a}
                                     for q, e, d, tp, a in zip(t["qs"], esq, dir_, topo, alt)]})
    # câmera da cena: movimento acumulado da imagem (o conteúdo anda x, y; zoom; giro), sem o quadro do corte; um salto
    # grande dentro da cena (corte de aproximação, troca de enquadramento) abre um trecho novo, que recomeça do zero
    trechos, ini_t = [], c["ini"]
    for i in range(c["ini"] + 1, c["fim"]):
        viz = [med[k]["dif"] for k in range(max(c["ini"] + 1, i - 3), min(c["fim"], i + 4)) if k != i]
        salto = med[i]["dif"] > 14 and (not viz or med[i]["dif"] > 2.0 * float(np.median(viz)))  # pico isolado, não pan rápido
        if salto and i - ini_t >= 3 and c["fim"] - i >= 3:
            trechos.append((ini_t, i))
            ini_t = i
    trechos.append((ini_t, c["fim"]))
    def pelas_letras(t0, t1):
        """fundo liso: a câmera tirada das letras — se 2+ linhas de texto andam/encolhem juntas entre dois quadros, é a câmera
        (uma linha sozinha andando pode ser só o texto se mexendo: não conta)"""
        trs = [t for t in c["trilhas"] if t.get("letra")]
        por_q = [{id(t): t["blocos"][t["qs"].index(i)] for t in trs if i in t["qs"]} for i in range(t0, t1)]
        C = np.array([UF / 2, r / 2])
        movs = [None]
        for k in range(1, len(por_q)):
            a_, b_ = por_q[k - 1], por_q[k]
            comuns = [(a_[x], b_[x]) for x in a_ if x in b_]
            if len(comuns) < 2:
                movs.append(None)
                continue
            esc = np.array([bb["h"] / max(aa["h"], 1e-4) for aa, bb in comuns])
            sc = float(np.median(esc))
            ts = np.array([np.array([bb["x"] * UF, bb["y"] * r]) - C - sc * (np.array([aa["x"] * UF, aa["y"] * r]) - C) for aa, bb in comuns])
            t_ = np.median(ts, 0)
            juntas = np.abs(esc - sc).max() < 0.03 and np.abs(ts - t_).max() < 2.0
            movs.append((float(t_[0] / UF), float(t_[1] / UF), sc, 0.0) if juntas else None)
        return movs

    def acumula(movs):
        X, Y, Z, R = [0.0], [0.0], [1.0], [0.0]
        ultimo, faltou = (0.0, 0.0, 1.0, 0.0), 0
        for m in movs[1:]:
            # quadro sem medida confiável: repete o último movimento por até 2 quadros (a câmera não para de repente)
            if m is None:
                faltou += 1
            else:
                ultimo, faltou = m, 0
            tx, ty, sc, gr = ultimo if (m is not None or faltou <= 2) else (0.0, 0.0, 1.0, 0.0)
            X.append(X[-1] + tx * UF)
            Y.append(Y[-1] + ty * UF)
            Z.append(Z[-1] * sc)
            R.append(R[-1] + gr)
        return X, Y, Z, R

    camc = []
    for t0, t1 in trechos:
        movs = [None] + [cam[i] for i in range(t0 + 1, t1)]
        lisos = sum(m is None for m in movs[1:])
        liso = lisos > 0.5 * max(1, t1 - t0 - 1)
        fonte_cam = "fundo"
        if liso:
            ml = pelas_letras(t0, t1)
            if sum(m is not None for m in ml[1:]) >= 0.5 * max(1, t1 - t0 - 1):
                movs, liso, fonte_cam = ml, False, "letras"
        X, Y, Z, R = acumula(movs)
        kc = chaves_max([X, Y, [z * 100 for z in Z], R])  # zoom ×100: tolerância de 0,015 no zoom e 1,5° no giro
        anda = len(X) > 2 and (max(np.ptp(X), np.ptp(Y)) > 3 or np.ptp(Z) > 0.03 or np.ptp(R) > 1.5)
        camc.append({"de": t0 - c["ini"], "ate": t1 - 1 - c["ini"], "anda": bool(anda), "liso": liso, "fonte": fonte_cam, "q": [k + t0 - c["ini"] for k in kc],
                     "x": [round(X[k], 1) for k in kc], "y": [round(Y[k], 1) for k in kc],
                     "zoom": [round(Z[k], 3) for k in kc], "giro": [round(R[k], 1) for k in kc],
                     "serie": {"x": [round(v, 2) for v in X], "y": [round(v, 2) for v in Y], "zoom": [round(v, 4) for v in Z],
                               "giro": [round(v, 2) for v in R]} if anda and not liso else None})
    medidas["cenas"].append({"n": c["n"], "ini": c["ini"], "fim": c["fim"], "dur": c["dur"], "fundo": c["fundo"],
                             "fundo_nome": nome_cor(c["fundo"]), "camera": camc, "blocos": blocos_c})
    c.pop("trilhas", None)
json.dump(medidas, open(saida / "medidas.json", "w", encoding="utf-8"), ensure_ascii=False)
M = [f"# Medidas — {video.name}", "",
     f"Gerado por `npm run estudo`. Unidade: {medidas['unidade']} — as mesmas das folhas; q = quadro desde o início da cena. "
     "Para recriar **sem abrir as folhas**: cada linha já vem no formato do código (`K` de `@/pecas/medida-folha`).", "",
     "- **Câmera**: quanto a imagem inteira anda (x, y em unidades: + = para a direita/para baixo), zoom (1 = igual) e giro (graus),",
     "  acumulados desde o começo do trecho. É o `translate/scale/rotate` do contêiner da cena. \"parada\" = anda menos de 3 unidades.",
     "  Quadros-chave por erro: o caminho traçado entre eles fica a até 1,5 unidade (~7 px) do real — voltas, quiques e",
     "  \"respiração\" maiores que isso aparecem; tremida menor some. Cada medida tem os seus próprios quadros.",
     "  Um salto dentro da cena (corte de aproximação, novo enquadramento) abre outro trecho, que recomeça do zero.",
     "- **Letras**: blocos que parecem texto (várias letras da altura da linha). `esq`/`dir` = bordas, `topo`/`alt` ≈ topo e",
     "  altura da maiúscula. Palavra que nasce já é um bloco novo (veja `de`). Posições já incluem o movimento da câmera.",
     "- **Imagens**: fotos, objetos, papéis, cartões (o detector não distingue estes entre si): centro e tamanho.",
     "- **⚠ conferir na folha**: a separação letra × imagem ficou perto do limite (palavra gigante, letra grossa colada, etiqueta,",
     "  desenho de traço fino). Blocos de 2–3 quadros não são marcados (resto de transição). Só nesses blocos (e nas cenas de câmera \"não dá para medir\") abra a folha da cena.",
     "- Fundo liso (preto, céu, cor chapada): a câmera sai **das letras** quando 2+ linhas andam ou encolhem juntas.",
     "- Desconfie de bloco com `alt` muito maior que os vizinhos (duas linhas coladas viram um bloco) e de letra muito",
     "  espaçada (pode virar várias). Só nesses casos abra a folha daquela cena.", ""]
for cm in medidas["cenas"]:
    M.append(f"## C{cm['n']} · q{cm['ini']}–{cm['fim'] - 1} ({cm['dur']} q, {seg(cm['ini']):.2f}–{seg(cm['fim']):.2f} s) · fundo {cm['fundo_nome']}")
    for k, cc in enumerate(cm["camera"]):
        rot = f"Câmera q{cc['de']}–{cc['ate']}" + (" (salto: novo enquadramento)" if k else "") + (" — medida pelas letras (fundo liso: 2+ linhas andando juntas)" if cc.get("fonte") == "letras" else "")
        if cc["liso"]:
            M.append(f"- {rot}: não dá para medir (fundo liso ou só objetos soltos se mexendo) — veja o movimento nas letras e imagens")
        elif cc["anda"]:
            M.append(f"- {rot}: x {kq(cc['q'], cc['x'])} · y {kq(cc['q'], cc['y'])} · zoom {kq(cc['q'], cc['zoom'], 3)} · giro {kq(cc['q'], cc['giro'])}")
        else:
            M.append(f"- {rot}: parada")
    for tipo, rot in (("letra", "L"), ("imagem", "I")):
        k = 0
        for b in cm["blocos"]:
            if b["tipo"] != tipo:
                continue
            k += 1
            alts = [x["alt"] for x in b["quadros"]]
            aviso = f" · ⚠ conferir na folha: {b['duvida']}" if b.get("duvida") else ""
            if tipo == "letra":
                M.append(f"- {rot}{k} {b['cor']} · q{b['de']}–{b['ate']} · alt≈{np.median(alts):.0f} · "
                         f"esq {kserie(b, lambda x: x['esq'])} · dir {kserie(b, lambda x: x['dir'])} · topo {kserie(b, lambda x: x['topo'])}"
                         + (f" · alt {kserie(b, lambda x: x['alt'])}" if np.ptp(alts) > 2 else "") + aviso)
            else:
                M.append(f"- {rot}{k} {b['cor']} · q{b['de']}–{b['ate']} · centro x {kserie(b, lambda x: (x['esq'] + x['dir']) / 2)} · "
                         f"y {kserie(b, lambda x: x['topo'] + x['alt'] / 2)} · larg {kserie(b, lambda x: x['dir'] - x['esq'])} · alt {kserie(b, lambda x: x['alt'])}" + aviso)
    M.append("")
(saida / "medidas.md").write_text("\n".join(M), encoding="utf-8", newline="\n")
print(f"✔ {saida / 'medidas.md'} (câmera, letras e imagens de cada cena, prontos para o código) + medidas.json")
if so_medidas:
    sys.exit(0)

# ---------------------------------------------------------------- passo 3: o que vira folha
folhas = {}  # nome → lista de (quadro, rótulo)
for c in cenas:
    if not completo and (not c["acao"] or c["repete"]):
        continue
    perto = set(range(c["ini"], min(c["fim"], c["ini"] + 6))) | set(range(max(c["ini"], c["fim"] - 5), c["fim"]))
    for q in c["q_eventos"]:
        perto |= set(range(max(c["ini"], q - 2), min(c["fim"], q + 3)))
    grupo, i = [], c["ini"]
    while i < c["fim"]:
        j = fim_parado(i, c["fim"])
        if j - i >= 2:  # trecho parado de verdade (imagem e texto) vira um quadro só
            grupo.append((i, f"C{c['n']} {seg(i):.2f}s q{i - c['ini']}–{j - c['ini']} parado"))
            i = j + 1
            continue
        if completo or i in perto or (i - c["ini"]) % 4 == 0:
            grupo.append((i, f"C{c['n']} {seg(i):.2f}s q{i - c['ini']}"))
        i += 1
    folhas[f"cena-{c['n']:03d}"] = grupo
for ci in corte_info:
    if not completo and ((ci["troca"] == "corte" and not ci["tipo"].startswith(("com embalo", "entra pela borda"))) or ci["repete"]):
        continue  # econômico: corte seco simples não vira folha; clarão, fusão, troca em movimento e embalo viram
    q = ci["q"]
    # 6 quadros antes e depois do corte, ou a troca inteira (fusão, clarão) com 3 de folga, o que for maior (até 24)
    i0, i1 = max(0, min(q - 6, ci["de"] - 3)), min(N, max(q + 6, ci["ate"] + 4))
    i0, i1 = max(i0, q - 12), min(i1, q + 12)
    folhas[f"corte-{ci['n']:03d}"] = [(i, f"{seg(i):.2f}s {'antes' if i < q else 'depois'}") for i in range(i0, i1)]

# cobertura: o que as folhas das cenas estudadas NÃO mostram
mostra, junta = set(), set()
for nome, itens in folhas.items():
    if nome.startswith("cena-"):
        c = cenas[int(nome[5:]) - 1]
        for q, rot in itens:
            mostra.add(q)
            if "parado" in rot:
                junta |= set(range(q, fim_parado(q, c["fim"]) + 1))
estudadas = [i for c in cenas if f"cena-{c['n']:03d}" in folhas for i in range(c["ini"], c["fim"])]
fora = [i for i in estudadas if i not in mostra and i not in junta]
picos_fora = [i for i in fora for c in cenas if c["ini"] <= i < c["fim"] and i in c["q_eventos"]]
cobertura = {"quadros_estudados": len(estudadas), "mostrados": len(mostra), "juntados_parados": len(junta) - len(mostra & junta),
             "fora": len(fora), "fora_com_mudanca": sum(1 for i in fora if med[i]["dif"] >= 1.5), "eventos_fora": len(picos_fora)}

COLS = 4 if W0 >= H0 else 6
LIN_MAX = 4 if W0 >= H0 else 2
POR = COLS * LIN_MAX
paginas = []  # (arquivo, [(quadro, rótulo)])
# cenas: seguidas na mesma folha (uma cena só quebra de folha se não couber inteira numa folha nova)
fila, nomes, k = [], [], 0
def fecha():
    global fila, nomes, k
    if fila:
        k += 1
        paginas.append((f"cenas-{k:03d}.jpg", fila))
        nomes_folha[f"cenas-{k:03d}.jpg"] = nomes
    fila, nomes = [], []
nomes_folha = {}
for nome, itens in folhas.items():
    if not nome.startswith("cena-"):
        continue
    if len(fila) + len(itens) > POR and len(itens) <= POR:
        fecha()
    while itens:
        cabe = POR - len(fila)
        fila += itens[:cabe]
        nomes.append(nome)
        itens = itens[cabe:]
        if len(fila) == POR:
            fecha()
fecha()
for nome, itens in folhas.items():
    if nome.startswith("corte-"):
        paginas.append((f"{nome}.jpg", itens))
cena_folhas = {}
for arq, ns in nomes_folha.items():
    for n_ in ns:
        cena_folhas.setdefault(n_, []).append(arq)

precisa = {}
for pi, (_, itens) in enumerate(paginas):
    for slot, (q, _) in enumerate(itens):
        precisa.setdefault(q, []).append((pi, slot))
try:
    fonte = ImageFont.truetype(str(carimbo), 14)
except (OSError, TypeError):
    fonte = ImageFont.load_default()
abertas, faltam = {}, {pi: len(it) for pi, (_, it) in enumerate(paginas)}

# rastro de cada cena estudada (cores = tempo) e setas num momento de movimento lento/médio
estudadas_n = [int(n[5:]) for n in folhas if n.startswith("cena-")]
cena_de = np.zeros(N, int)
for c in cenas:
    cena_de[c["ini"]:c["fim"]] = c["n"]
POR_R = COLS * LIN_MAX
rastro_arq = {n: f"rastros-{k // POR_R + 1:03d}.jpg" for k, n in enumerate(estudadas_n)}
rastro_slot = {n: k % POR_R for k, n in enumerate(estudadas_n)}
setas_q = {}
for n in estudadas_n:
    c = cenas[n - 1]
    for i0, i1, dx, dw in c["corridas"]:
        v = max(abs(dx), abs(dw)) / max(1, i1 - i0)
        if 0.002 < v < 0.02 and i1 - i0 >= 3 and (i0 + i1) // 2 + 2 < c["fim"]:
            setas_q[n] = (i0 + i1) // 2
            break
POR_S = 8
setas_arq = {n: f"setas-{k // POR_S + 1:03d}.jpg" for k, n in enumerate(setas_q)}
setas_slot = {n: k % POR_S for k, n in enumerate(setas_q)}
acum, pags_extra, guarda = {}, {}, {}
tot_r = {a_: sum(1 for v in rastro_arq.values() if v == a_) for a_ in set(rastro_arq.values())}
tot_s = {a_: sum(1 for v in setas_arq.values() if v == a_) for a_ in set(setas_arq.values())}
feitos = {}


def cor_tempo(k):
    hsv = np.uint8([[[int(120 * (1 - k)), 255, 255]]])
    return cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB)[0, 0]


def cola(arq, slot, tile, rot, total, cols):
    if arq not in pags_extra:
        lin = (total + cols - 1) // cols
        pags_extra[arq] = Image.new("RGB", (cols * TW, lin * TH), "#202020")
    img = pags_extra[arq]
    x, y = (slot % cols) * TW, (slot // cols) * TH
    img.paste(tile, (x, y))
    d = ImageDraw.Draw(img)
    d.rectangle([x, y, x + 8 + 8 * len(rot), y + 18], fill="black")
    d.text((x + 3, y + 1), rot, fill="yellow", font=fonte)
    feitos[arq] = feitos.get(arq, 0) + 1
    if feitos[arq] == total:
        img.save(saida / arq, quality=85)
        del pags_extra[arq]


def setas_img(f0, f1):
    a_, b_ = cv2.cvtColor(f0, cv2.COLOR_RGB2GRAY), cv2.cvtColor(f1, cv2.COLOR_RGB2GRAY)
    flow = cv2.calcOpticalFlowFarneback(a_, b_, None, 0.5, 3, 15, 3, 5, 1.1, 0)
    out = Image.fromarray((f1.astype(np.float32) * 0.55).astype(np.uint8))
    d = ImageDraw.Draw(out)
    G = 12
    for yy in range(G // 2, TH, G):
        for xx in range(G // 2, TW, G):
            dx, dy = flow[yy, xx]
            m = (dx * dx + dy * dy) ** 0.5
            if m < 0.6:
                continue
            x2, y2 = xx + dx * 3, yy + dy * 3
            d.line([(xx, yy), (x2, y2)], fill=(255, 230, 0), width=1)
            ang = np.arctan2(dy, dx)
            for s_ in (0.8, -0.8):
                d.line([(x2, y2), (x2 - 4 * np.cos(ang + s_), y2 - 4 * np.sin(ang + s_))], fill=(255, 230, 0), width=1)
    return out

print(f"▶ {len(cenas)} cenas, {len(cortes)} cortes — montando {len(paginas)} folha(s)…")
for q, f in enumerate(quadros(TW, TH)):
    for pi, slot in precisa.get(q, []):
        arq, itens = paginas[pi]
        if pi not in abertas:
            lin = (len(itens) + COLS - 1) // COLS
            abertas[pi] = Image.new("RGB", (COLS * TW, lin * TH), "#202020")
        img = abertas[pi]
        x, y = (slot % COLS) * TW, (slot // COLS) * TH
        img.paste(Image.fromarray(f), (x, y))
        d = ImageDraw.Draw(img)
        rot = itens[slot][1]
        if rot.startswith("C") and (slot == 0 or itens[slot - 1][1].split()[0] != rot.split()[0]):
            d.rectangle([x, y, x + TW - 1, y + TH - 1], outline="#ff3030", width=3)
        d.rectangle([x, y, x + 8 + 8 * len(rot), y + 18], fill="black")
        d.text((x + 3, y + 1), rot, fill="yellow", font=fonte)
        faltam[pi] -= 1
        if faltam[pi] == 0:
            img.save(saida / arq, quality=85)
            del abertas[pi]
    n = int(cena_de[q])
    if n in rastro_arq:
        c = cenas[n - 1]
        if n not in acum:
            acum[n] = (np.zeros((TH, TW, 3), np.uint8), np.zeros((TH, TW), bool), rgb(c["fundo"]))
        cor_acc, msk, fundo_c = acum[n]
        m = np.abs(f.astype(np.int16) - fundo_c).max(2) > 110
        m = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_OPEN, np.ones((2, 2), np.uint8)).astype(bool)
        cor_acc[m] = cor_tempo((q - c["ini"]) / max(1, c["dur"] - 1))
        msk |= m
        if q == c["fim"] - 1:
            base = (f.astype(np.float32) * 0.25 + 40).astype(np.uint8)
            base[msk] = cor_acc[msk]
            cola(rastro_arq[n], rastro_slot[n], Image.fromarray(base), f"C{n} rastro {seg(c['ini']):.2f}–{seg(c['fim']):.2f}s",
                 tot_r[rastro_arq[n]], COLS)
            del acum[n]
    if n in setas_q:
        q0 = setas_q[n]
        if q == q0:
            guarda[n] = f.copy()
        elif q == q0 + 2 and n in guarda:
            cola(setas_arq[n], setas_slot[n], setas_img(guarda.pop(n), f), f"C{n} setas {seg(q0):.2f}s→+2q", tot_s[setas_arq[n]], 4)

# ---------------------------------------------------------------- passo 4: resumo
difs = [m["dif"] for i, m in enumerate(med[1:], 1) if i not in set(cortes)]
geral = {
    "quadros": N, "fps": round(FPS, 3), "duracao": round(DUR, 2), "tamanho": f"{W0}x{H0}",
    "cortes_por_min": round(len(cortes) / (DUR / 60), 1),
    "cena_media_s": round(float(np.mean([c["dur"] for c in cenas])) / FPS, 2),
    "movimento_medio": round(float(np.mean(difs)), 2),
    "quadros_parados_pct": round(100 * float(np.mean([d < PARADO for d in difs])), 1),
}
json.dump({"geral": geral, "cobertura": cobertura, "cenas": cenas, "cortes": corte_info, "quadros": med}, open(saida / "cenas.json", "w", encoding="utf-8"),
          ensure_ascii=False)

L = [f"# Análise quadro a quadro — {video.name}", "",
     f"Gerado por `npm run estudo` ({'completo' if completo else 'econômico'}). {W0}×{H0}, {FPS:g} qps, {DUR:.1f} s, {N} quadros.", "",
     "## Medidas gerais (compare com o nosso vídeo: `npm run estudo -- <nosso.mp4> --sem-fala`)", "",
     f"- cortes por minuto: **{geral['cortes_por_min']}** · cena média: **{geral['cena_media_s']} s**",
     f"- movimento médio entre quadros (sem cortes): **{geral['movimento_medio']}** · quadros quase parados: **{geral['quadros_parados_pct']}%**",
     "", f"**Cobertura das folhas** ({'completo' if completo else 'econômico'}): de {cobertura['quadros_estudados']} quadros das cenas "
     f"estudadas, {cobertura['mostrados']} aparecem um a um, {cobertura['juntados_parados']} estão em trechos parados de verdade "
     f"(imagem e texto) e {cobertura['fora']} ficam de fora ({cobertura['fora_com_mudanca']} com mudança — passos intermediários de um "
     f"movimento contínuo); eventos fora das folhas: **{cobertura['eventos_fora']}**. Cenas repetidas e sem ação não têm folha.",
     "", "## Cortes", "",
     "Fronteiras e tipo da troca: `npm run camadas` (analise/CAMADAS.md — a mesma fonte do decompor). Movimento: o bloco de "
     "texto principal atravessa o corte?", "",
     "| # | tempo | troca | movimento | folha |", "|---|---|---|---|---|"]
for ci in corte_info:
    nome = f"corte-{ci['n']:03d}"
    tem = any(a.startswith(nome) for a, _ in paginas)
    janela = f" q{ci['de']}–{ci['ate']}" if ci["ate"] > ci["de"] else ""
    L.append(f"| {ci['n']} | {ci['t']:.2f} s | {ci['troca']}{janela} | {ci['tipo']}{' (repetição)' if ci['repete'] else ''} | {nome + '.jpg' if tem else '—'} |")
L += ["", "## Cenas", "",
      "Fundo = cor mais comum; mov = diferença média entre quadros; parados = % de quadros sem mudança; eventos em quadros (q) "
      "desde o início da cena, sobre o bloco de texto principal.", "",
      "| # | tempo | dur | fundo | mov | parados | eventos | repete | folha |", "|---|---|---|---|---|---|---|---|---|"]
for c in cenas:
    nome = f"cena-{c['n']:03d}"
    fol = ", ".join(sorted(set(cena_folhas.get(nome, [])))) or "—"
    ev = "<br>".join(c["eventos"][:6]) + (f"<br>… +{len(c['eventos']) - 6}" if len(c["eventos"]) > 6 else "")
    L.append(f"| {c['n']} | {seg(c['ini']):.2f}–{seg(c['fim']):.2f} s | {c['dur']} q | {c['fundo']} | {c['mov']} | {c['parados']:.0f}% | "
             f"{ev or '—'} | {'cena ' + str(c['repete']) if c['repete'] else ''} | {fol} |")
L += ["", "## Narração por cena (todos os blocos de texto, medidos)", "",
      "Cada linha é um bloco acompanhado quadro a quadro: tamanho e cor · como aparece (e onde) · o que faz · como sai. "
      "Rastro = todos os quadros da cena sobrepostos, cor = tempo (azul começo → vermelho fim): borrão colorido = movimento, "
      "degradê que se aperta no vermelho = freando, que se abre = acelerando, nítido = parado.", ""]
for n in estudadas_n:
    c = cenas[n - 1]
    extra = f" · rastro: {rastro_arq[n]}" + (f" · setas: {setas_arq[n]}" if n in setas_arq else "")
    L.append(f"**C{n}** ({seg(c['ini']):.2f}–{seg(c['fim']):.2f} s){extra}")
    L += [f"- {fr}" for fr in c["narracao"]] or ["- (nenhum bloco acompanhado por 3+ quadros)"]
    L.append("")
extras = sorted(set(rastro_arq.values())) + sorted(set(setas_arq.values()))
L += ["", f"**Folhas para ler ({len(paginas)} + {len(extras)} de rastros/setas):** comece pelos rastros (o movimento de cada cena "
      f"numa imagem), depois as folhas das cenas com mais eventos e os cortes que não são secos.", ""]
(saida / "RESUMO.md").write_text("\n".join(L), encoding="utf-8", newline="\n")
print(f"✔ {saida / 'RESUMO.md'} · {len(paginas)} folha(s) + {len(extras)} de rastros/setas")

# ---------------------------------------------------------------- passo 4b: medidas prontas (fichas de texto, paleta, som, curvas)
subprocess.run([sys.executable, "-P", str(Path(__file__).with_name("fichas.py")), str(video), f"--saida={saida}"], check=True)

# ---------------------------------------------------------------- passo 4c: decompor (candidatos de elementos, mesmas cenas)
subprocess.run([sys.executable, "-P", str(Path(__file__).with_name("decompor.py")), str(video), f"--saida={saida}"], check=True)

# ---------------------------------------------------------------- passo 5: fala
if not opts.get("sem-fala"):
    tem_audio = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0",
                                str(video)], capture_output=True, text=True).stdout.strip()
    if not tem_audio:
        print("  (sem faixa de áudio)")
    else:
        from faster_whisper.vad import VadOptions, get_speech_timestamps

        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
                             capture_output=True).stdout
        a = np.frombuffer(raw, np.int16).astype(np.float32) / 32768
        destino = video.parent / "fala.txt"
        # detector de voz (Silero, < 1 s): só música dá ~0 s de voz — aí nem carrega o medium (que "ouve" Music, Thanks for watching)
        voz_s = sum(x["end"] - x["start"] for x in get_speech_timestamps(a, VadOptions(threshold=0.5))) / 16000
        if voz_s < 0.5:
            destino.write_text(f"sem fala: o detector de voz achou {voz_s:.1f} s de voz em {len(a) / 16000:.1f} s de áudio (só música/efeitos)"
                               " — transcrição pulada\n", encoding="utf-8")
            print(f"  (sem voz no áudio: {voz_s:.1f} s — transcrição pulada) → {destino}")
        else:
            print(f"▶ transcrevendo a faixa de áudio ({voz_s:.1f} s de voz; faster-whisper medium, idioma automático)…")
            from faster_whisper import WhisperModel

            modelo = WhisperModel("medium", device="cpu", compute_type="int8")
            segs, info = modelo.transcribe(a, word_timestamps=True, condition_on_previous_text=False)
            linhas = [f"idioma: {info.language} ({info.language_probability:.0%})"]
            for s in segs:
                linhas.append(f"[{s.start:6.2f}-{s.end:6.2f}] {s.text.strip()}")
                linhas.append("   " + " ".join(f"{w.word.strip()}@{w.start:.2f}" for w in s.words))
            # o que o whisper escreve quando só há música: "Music", "MÚSICA", "[Música]", "♪", vazio
            limpa = lambda t: t.strip(" .,!?♪♫[]()-").lower()
            textos = [l.split("] ", 1)[1] for l in linhas if l.startswith("[")]
            if all(limpa(t) in ("", "music", "música", "musica", "musique") for t in textos):
                linhas.insert(0, f"sem fala: a transcrição só achou música ({', '.join(textos) or 'nada'}) — trate o vídeo como só visual")
            destino.write_text("\n".join(linhas), encoding="utf-8")
            voz = 0 if linhas[0].startswith("sem fala") else len(textos)
            print(f"✔ {destino} — {voz} trecho(s) de fala" + ("" if voz else " (só música: sem fala)"))
