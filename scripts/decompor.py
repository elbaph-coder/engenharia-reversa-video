"""Decompõe um vídeo de referência em ELEMENTOS candidatos e separa os recortes em pastas por tipo (passo "decompor" da
skill estudar-video; método e vocabulário: DECOMPOR.md).

    npm run decompor -- referencias/<estilo>                     → acha os candidatos e monta assets/ + decomposicao.json
    npm run decompor -- referencias/<estilo>/fonte/<v>.mp4 --saida=<pasta>   → outro vídeo/pasta (o npm run estudo chama
                         assim no fim); assets/ fica ao lado da pasta se ela se chama "analise", senão dentro dela
    npm run decompor -- referencias/<estilo> --classifica=e3:personagens,e7:objetos   → o modelo/usuário confirma o tipo
    npm run decompor -- referencias/<estilo> --descarta=e9,e12                        → não é elemento (ruído, borda)
    npm run decompor -- referencias/<estilo> --acrescenta="objetos:40:250,380,220,520:implante"   → o que a medida perdeu
                         (pasta:quadro:x,y,larg,alt em px da ref[:nome]; vários separados por ";"; fica gravado)

Lê fonte/*.mp4 (o 1º) e analise/camadas.json (roda o `npm run camadas` se faltar). As CENAS e as trocas vêm só do
camadas — a mesma fonte do `npm run estudo`, então as cenas daqui são as dele. Acha candidatos de três jeitos:
  1. APARIÇÃO — entre dois trechos parados seguidos ("platôs"), o que mudou (depois de alinhar a câmera) é um elemento que
     entrou, saiu ou mudou; se mudou quase a tela toda, é troca de cena e o platô novo vira um FUNDO.
  2. DESTAQUE — no 1º platô de cada cena, o que tem detalhe muito acima do fundo desfocado em volta (texto, ícone, objeto
     nítido sobre fundo suave) — pega o que já está na tela quando a cena começa.
  3. CAMADA — cada objeto com movimento próprio do camadas.json, recortado no quadro de referência dele.
Cada candidato ganha um TIPO PROVÁVEL por medida (fundo, video, texto, icone, imagem) e vai para assets/<pasta>/; "personagens"
e "objetos" só por --classifica (a medida não sabe o que é uma pessoa). Fundo de cena sai também "limpo" (aprox.: os
candidatos daquele platô apagados com inpaint).

Grava:
  assets/{fundos,imagens,videos,personagens,objetos,icones,textos,_descartados}/<id>.png + assets/_folha.jpg (todos os
  candidatos numa folha só, com id e tipo — para classificar abrindo UMA imagem) + assets/_pendentes.jpg (só os que ainda
  não foram classificados nem descartados — nas rodadas seguintes, abra esta). assets/ fica FORA do git (recorte de vídeo
  de terceiro: só estudo, nunca vai para o vídeo).
  analise/decomposicao.json  {"video", "plato": [[de, ate]], "trocas" (do camadas), "cenas": [[ini, fim]] (do camadas), "elementos": {id: {tipo, status, fonte,
  pasta, arquivo, de, ate, caixa [x, y, l, a] px da ref, origem, operacoes: [{tipo, de, ate, status, fonte, ...}],
  nome, funcao, relacoes, hipoteses}}} — nome/função/relações/hipóteses ficam vazios para a leitura (DECOMPOR.md §4).
Rodar de novo refaz os candidatos e mantém o que já foi classificado/descartado (casado pela caixa e pelo trecho).
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.stdout.reconfigure(encoding="utf-8")
args = [a for a in sys.argv[1:] if not a.startswith("--")]
opts = {a[2:].split("=")[0]: (a.split("=", 1)[1] if "=" in a else True) for a in sys.argv[1:] if a.startswith("--")}
if not args:
    sys.exit(__doc__)
alvo = Path(args[0]).resolve()
estudo = alvo.parent.parent if alvo.is_file() else alvo
PASTAS = ["fundos", "imagens", "videos", "personagens", "objetos", "icones", "textos", "_descartados"]
# tipo (singular) de cada pasta — "imagens" vira "imagem", não "imagen"
TIPO = {"fundos": "fundo", "imagens": "imagem", "videos": "video", "personagens": "personagem", "objetos": "objeto",
        "icones": "icone", "textos": "texto"}
analise = Path(opts["saida"]).resolve() if "saida" in opts else estudo / "analise"
assets = analise.parent / "assets" if analise.name == "analise" else analise / "assets"
jpath = analise / "decomposicao.json"


def mover(dados, pares, destino=None):
    for par in pares:
        eid, pasta = (par.split(":") + [destino])[:2] if destino is None else (par, destino)
        e = dados["elementos"].get(eid)
        if not e or pasta not in PASTAS:
            sys.exit(f"✘ {par}: id desconhecido ou pasta fora de {PASTAS}")
        novo = assets / pasta / Path(e["arquivo"]).name
        if (assets.parent / e["arquivo"]).exists():
            shutil.move(assets.parent / e["arquivo"], novo)
        e.update(pasta=pasta, arquivo=str(novo.relative_to(assets.parent)).replace("\\", "/"), fonte="modelo",
                 status="rejeitado" if pasta == "_descartados" else "confirmado",
                 tipo=e["tipo"] if pasta == "_descartados" else TIPO[pasta])
        print(f"  {eid} → {pasta}")


def acrescentados():
    """elementos que a medida não achou e o modelo/usuário apontou (--acrescenta), guardados para as próximas rodadas"""
    return json.load(open(jpath, encoding="utf8")).get("acrescentados", []) if jpath.exists() else []


if "classifica" in opts or "descarta" in opts:
    dados = json.load(open(jpath, encoding="utf8"))
    if "classifica" in opts:
        mover(dados, str(opts["classifica"]).split(","))
    if "descarta" in opts:
        mover(dados, str(opts["descarta"]).split(","), "_descartados")
    json.dump(dados, open(jpath, "w", encoding="utf8"), ensure_ascii=False, indent=1)
    if "acrescenta" not in opts:
        sys.exit(0)
    # com --acrescenta na mesma chamada: segue para a rodada completa (a classificação acima é mantida por ela)

videos = [alvo] if alvo.is_file() else sorted((estudo / "fonte").glob("*.mp4"))
if not videos:
    sys.exit(f"sem vídeo em {estudo / 'fonte'}")
video = videos[0]
cap = cv2.VideoCapture(str(video))
W0, H0 = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
FPS = cap.get(cv2.CAP_PROP_FPS) or 30
CHEIO = []  # quadros em cor, metade do tamanho (memória: 600 q de 360×640 ≈ 400 MB)
while True:
    ok, f = cap.read()
    if not ok:
        break
    CHEIO.append(cv2.resize(f, (W0 // 2, H0 // 2), interpolation=cv2.INTER_AREA))
N = len(CHEIO)
S = 2.0  # px da ref por px de trabalho
h, w = CHEIO[0].shape[:2]
CINZA = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in CHEIO]
peq = [cv2.resize(g, (90, int(90 * h / w)), interpolation=cv2.INTER_AREA).astype(np.float32) for g in CINZA]
dif = np.array([0.0] + [float(np.abs(peq[i] - peq[i - 1]).mean()) for i in range(1, N)])
AREA = w * h

def alinha(a, b):
    """leva o quadro b para a geometria do a (câmera que andou); (M, fração de pontos que batem) ou (None, 0)"""
    (ka, da), (kb, db) = ORB[a], ORB[b]
    if da is None or db is None or len(ka) < 30 or len(kb) < 30:
        return None, 0.0
    m = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(db, da)
    if len(m) < 30:
        return None, 0.0
    M, inl = cv2.estimateAffinePartial2D(np.float32([kb[x.queryIdx].pt for x in m]), np.float32([ka[x.trainIdx].pt for x in m]),
                                         ransacReprojThreshold=2.0)
    return (None, 0.0) if M is None else (M, float(inl.mean()))


def mudou(a, b):
    """máscara do que mudou de a para b depois de descontar a câmera (o que só andou junto com a tela não conta)"""
    M, conf = alinha(a, b)
    gb = CINZA[b] if M is None or conf < 0.4 else cv2.warpAffine(CINZA[b], M, (w, h), borderMode=cv2.BORDER_REPLICATE)
    return (cv2.absdiff(cv2.GaussianBlur(CINZA[a], (5, 5), 0), cv2.GaussianBlur(gb, (5, 5), 0)) > 22).astype(np.uint8) * 255, gb


# ---------------------------------------------------------------- platôs (trechos parados); trocas e cenas do camadas
# curva de mudança: fração da tela que muda em 6 quadros, com a câmera descontada (bolha que flutua ou fundo que desliza
# devagar mudam pouca área). Platô = < 3 % por 6+ quadros.
ORB = [cv2.ORB_create(1500).detectAndCompute(g, None) for g in CINZA]
PASSO, JAN = 3, 6
curva = {q: float(mudou(q, q + JAN)[0].mean() / 255) for q in range(0, N - JAN, PASSO)}


def trechos(cond):
    out, run = [], []
    for q in sorted(curva) + [None]:
        if q is not None and cond(curva[q]):
            run.append(q)
            continue
        if run:
            out.append([run[0], min(run[-1] + JAN, N - 1), len(run)])
        run = []
    return out


def picos(lim_alto):
    """platô = trechos abaixo de 3 %; dentro dele, um pico pequeno (ícone que acende: < 3 % da tela, mas bem acima do
    mexido de fundo daquele trecho — bolha, grão) também separa dois platôs"""
    calmo = [q for q in sorted(curva) if curva[q] < lim_alto]
    med = float(np.median([curva[q] for q in calmo])) if calmo else 0.0
    return lambda v: v < lim_alto and v <= max(0.004, 3 * med)


plato = [[a, b] for a, b, n in trechos(picos(0.03)) if n >= 2]
cpath = analise / "camadas.json"
camadas = json.load(open(cpath, encoding="utf8")) if cpath.exists() else {}
if "cenas" not in camadas:  # sem camadas.json (ou de antes das cenas): roda o camadas — a fonte única das cenas
    subprocess.run([sys.executable, "-P", str(Path(__file__).with_name("camadas.py")), str(video), f"--saida={analise}"],
                   check=True, stdout=subprocess.DEVNULL)
    camadas = json.load(open(cpath, encoding="utf8"))
trocas = camadas["trocas"]
cortes = sorted({t["de"] for t in trocas} | {t["corte"] for t in trocas})


def regioes(mask, area_min=0.0015):
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))  # 5×5 apaga ícone de traço fino
    n, lab, st, _ = cv2.connectedComponentsWithStats(mask)
    return [tuple(int(v) for v in st[k, :4]) for k in range(1, n) if st[k, 4] > area_min * AREA]


def tipo_provavel(q, x, y, bw, bh, de, ate):
    """o que o recorte parece ser, por medida (DECOMPOR.md §2): fundo · video · texto · icone · imagem"""
    if bw * bh > 0.5 * AREA:
        return "fundo"
    c = CHEIO[q][y:y + bh, x:x + bw]
    g = CINZA[q][y:y + bh, x:x + bw]
    # vídeo: o recorte muda por dentro num trecho em que a tela está parada (partículas, fumaça, filmagem)
    meu = next((p for p in plato if p[0] <= q <= p[1]), None)  # só o platô do próprio quadro: noutro o elemento nem está
    qs = list(range(meu[0], meu[1] + 1))[:30] if meu else []
    if len(qs) >= 8 and bw > 12 and bh > 12:
        # descontando o deslize do próprio recorte (cartão que desce devagar não é vídeo): alinha cada quadro ao 1º
        base = CINZA[qs[0]][y:y + bh, x:x + bw].astype(np.float32)
        pilha = []
        for k in qs:
            g_ = CINZA[k][y:y + bh, x:x + bw].astype(np.float32)
            (dx, dy), _ = cv2.phaseCorrelate(base, g_)
            pilha.append(cv2.warpAffine(g_, np.float32([[1, 0, -dx], [0, 1, -dy]]), (bw, bh), borderMode=cv2.BORDER_REPLICATE))
        if float(np.stack(pilha)[:, 4:-4, 4:-4].std(0).mean()) > 8:
            return "video"
    bordas = cv2.Canny(g, 60, 160) > 0
    cor = float(np.std(c.astype(np.float32), axis=2).mean())  # 0 = cinza; alto = colorido
    # tinta = o que foge muito do tom do próprio recorte (o Otsu partia em dois um fundo com textura)
    bi = (np.abs(g.astype(np.int16) - int(np.median(g))) > 40).astype(np.uint8) * 255
    n, _, st, _ = cv2.connectedComponentsWithStats(bi)
    alt = st[1:, 3] if n > 1 else np.array([])
    pecas = alt[(alt > 4) & (alt < 0.9 * bh)]
    if len(pecas) >= 5 and np.std(pecas) < 0.6 * np.mean(pecas) and bi.mean() / 255 < 0.55 and bh < 0.25 * h:
        return "texto"
    if bw * bh < 0.06 * AREA and cor < 18 and bordas.mean() > 0.06 and bi.mean() / 255 < 0.35:
        return "icone"
    return "imagem"


cands = []  # {de, ate, caixa (trabalho), q, origem, op}
cenas = []
for k in range(1, len(plato)):
    a, b = plato[k - 1], plato[k]
    qa, qb = (a[0] + a[1]) // 2, (b[0] + b[1]) // 2
    mask, gb = mudou(qa, qb)
    if mask.mean() / 255 > 0.45 or any(a[1] < c <= b[0] for c in cortes):
        continue  # mudou quase tudo: o que está no platô novo sai pelo destaque
    for x, y, bw, bh in regioes(mask):
        # entrou (está no b) ou saiu (estava no a)? o lado com mais detalhe na região é onde o elemento está
        da = float(cv2.Laplacian(CINZA[qa][y:y + bh, x:x + bw], cv2.CV_32F).var())
        db = float(cv2.Laplacian(gb[y:y + bh, x:x + bw], cv2.CV_32F).var())
        entra = db >= da
        cands.append({"de": a[1] + 1 if entra else a[0], "ate": b[1] if entra else a[1], "q": qb if entra else qa,
                      "caixa": (x, y, bw, bh), "origem": f"aparição entre os platôs q{a[1]}→q{b[0]}",
                      "op": {"tipo": "aparece" if entra else "some", "de": a[1] + 1, "ate": b[0], "status": "observado",
                             "fonte": "medida"}})
# cenas: as do camadas (as mesmas do estudo); a janela de cada troca (fusão, clarão) está em "trocas"
cenas = [[a, min(b, N - 1)] for a, b in camadas["cenas"] if a < N]

# destaque: em cada platô, o que tem detalhe muito acima da vizinhança desfocada (pega o que já está na tela)
for p in plato:
    q = (p[0] + p[1]) // 2
    g = CINZA[q].astype(np.float32)
    det = np.abs(g - cv2.GaussianBlur(g, (0, 0), 6))
    mask = (det > max(18, np.percentile(det, 97))).astype(np.uint8) * 255
    mask = cv2.dilate(mask, np.ones((9, 9), np.uint8))
    for x, y, bw, bh in regioes(mask, 0.002):
        if bw * bh > 0.6 * AREA:
            continue
        cands.append({"de": p[0], "ate": p[1], "q": q, "caixa": (x, y, bw, bh), "origem": f"destaque no platô q{p[0]}–q{p[1]}",
                      "op": {"tipo": "presente", "de": p[0], "ate": p[1], "status": "observado", "fonte": "medida"}})

# acrescentados à mão: --acrescenta=pasta:q:x,y,l,a[:nome] (px da ref); ficam gravados e voltam a cada rodada
manuais = acrescentados()
if "acrescenta" in opts:
    for item in str(opts["acrescenta"]).split(";"):
        partes = item.split(":")
        if len(partes) < 3 or partes[0] not in PASTAS:
            sys.exit(f"✘ --acrescenta={item}: use pasta:q:x,y,l,a[:nome] (pastas: {PASTAS})")
        manuais.append({"pasta": partes[0], "q": int(partes[1]), "caixa": [int(v) for v in partes[2].split(",")],
                        "nome": partes[3] if len(partes) > 3 else ""})
for m_ in manuais:
    x, y, bw, bh = (int(v / S) for v in m_["caixa"])
    cands.append({"de": m_["q"], "ate": m_["q"], "q": m_["q"], "caixa": (x, y, bw, bh), "origem": "acrescentado (modelo)",
                  "manual": m_, "op": {"tipo": "presente", "de": m_["q"], "ate": m_["q"], "status": "observado", "fonte": "modelo"}})

# camadas com movimento próprio
for cid, c in (camadas.get("camadas") or {}).items():
    if c["papel"] != "objeto" or c.get("pequena"):
        continue
    x, y, bw, bh = (int(v / S) for v in c["caixa"])
    qs = sorted(int(k) for k in c["q"])
    a_, b_ = c["q"][str(qs[0])], c["q"][str(qs[-1])]
    cands.append({"de": c["de"], "ate": c["ate"], "q": c["quadro"], "caixa": (x, y, bw, bh), "origem": f"camada {cid}",
                  "op": {"tipo": "anda", "de": c["de"], "ate": c["ate"], "status": "observado", "fonte": "medida",
                         "dx": round(b_[0] - a_[0]), "dy": round(b_[1] - a_[1]), "escala": round(b_[2] / a_[2], 3),
                         "giro": round(b_[3] - a_[3], 1)}})


# junta candidatos que são o mesmo elemento (caixas que quase coincidem, trechos que se tocam)
def iou(p, q):
    x0, y0 = max(p[0], q[0]), max(p[1], q[1])
    x1, y1 = min(p[0] + p[2], q[0] + q[2]), min(p[1] + p[3], q[1] + q[3])
    i_ = max(0, x1 - x0) * max(0, y1 - y0)
    return i_ / (p[2] * p[3] + q[2] * q[3] - i_ + 1e-6)


elementos = []
for c in sorted(cands, key=lambda c: c["de"]):
    par = next((e for e in elementos if iou(e["caixa"], c["caixa"]) > 0.6 and c["de"] <= e["ate"] + 15), None)
    if par:
        par["ate"] = max(par["ate"], c["ate"])
        par["ops"].append(c["op"])
        par["origens"].append(c["origem"])
        par["manual"] = par.get("manual") or c.get("manual")
    else:
        elementos.append({**c, "ops": [c["op"]], "origens": [c["origem"]]})
# a saída (some) de um elemento que entrou antes fecha o trecho dele
for e in elementos:
    sai = [o for o in e["ops"] if o["tipo"] == "some"]
    if sai:
        e["ate"] = max(o["ate"] for o in sai)

# ---------------------------------------------------------------- recortes, fundos e folha
antigo = json.load(open(jpath, encoding="utf8"))["elementos"] if jpath.exists() else {}
for p in PASTAS:
    (assets / p).mkdir(parents=True, exist_ok=True)
    for f in list((assets / p).glob("e*.png")) + list((assets / p).glob("cena*.png")):
        f.unlink()
saida = {}
for n, e in enumerate(elementos):
    x, y, bw, bh = e["caixa"]
    tipo = tipo_provavel(e["q"], x, y, bw, bh, e["de"], e["ate"])
    caixa_ref = [int(x * S), int(y * S), int(bw * S), int(bh * S)]
    eid = f"e{n}"
    velho = next((v for v in antigo.values() if v.get("status") in ("confirmado", "rejeitado")
                  and iou(v["caixa"], caixa_ref) > 0.6 and abs(v["de"] - e["de"]) <= 10), None)
    man = e.get("manual")
    if man and not velho:
        velho = {"pasta": man["pasta"], "tipo": TIPO.get(man["pasta"], "descartado"),
                 "status": "confirmado", "fonte": "modelo", "nome": man["nome"]}
    pasta = velho["pasta"] if velho else {"fundo": "fundos", "video": "videos", "texto": "textos", "icone": "icones"}.get(tipo, "imagens")
    arq = assets / pasta / f"{eid}.png"
    m = 6
    crop = cv2.resize(CHEIO[e["q"]], (W0, H0))[max(0, int(y * S) - m):int((y + bh) * S) + m, max(0, int(x * S) - m):int((x + bw) * S) + m]
    cv2.imwrite(str(arq), crop)
    saida[eid] = {
        "tipo": TIPO.get(velho["pasta"], velho["tipo"]) if velho else tipo, "status": velho["status"] if velho else "hipotese",
        "fonte": velho["fonte"] if velho else "medida", "pasta": pasta, "arquivo": str(arq.relative_to(assets.parent)).replace("\\", "/"),
        "de": int(e["de"]), "ate": int(e["ate"]), "quadro": int(e["q"]), "caixa": caixa_ref, "origem": e["origens"],
        "operacoes": e["ops"], "nome": (velho or {}).get("nome", ""), "funcao": (velho or {}).get("funcao", ""),
        "relacoes": (velho or {}).get("relacoes", []), "hipoteses": (velho or {}).get("hipoteses", [])}

fundos = []
# fundo de cada cena: o 1º platô inteiro + versão limpa aproximada (candidatos daquele platô apagados)
for k, (c0, c1) in enumerate(cenas):
    p = next((pp for pp in plato if c0 <= pp[0] <= c1), None)
    if not p:
        continue
    q = (p[0] + p[1]) // 2
    quadro = cv2.resize(CHEIO[q], (W0, H0))
    cv2.imwrite(str(assets / "fundos" / f"cena{k + 1}-q{q}.png"), quadro)
    fundos.append({"cena": k + 1, "de": c0, "ate": c1, "quadro": q, "arquivo": f"assets/fundos/cena{k + 1}-q{q}.png"})
    buraco = np.zeros((H0, W0), np.uint8)
    for e in saida.values():
        if e["de"] <= q <= e["ate"] and e["pasta"] != "fundos":
            x, y, bw, bh = e["caixa"]
            buraco[max(0, y - 8):y + bh + 8, max(0, x - 8):x + bw + 8] = 255
    if buraco.mean() / 255 < 0.6:
        limpo = cv2.inpaint(cv2.resize(quadro, (W0 // 2, H0 // 2)), cv2.resize(buraco, (W0 // 2, H0 // 2)), 9, cv2.INPAINT_TELEA)
        cv2.imwrite(str(assets / "fundos" / f"cena{k + 1}-q{q}-limpo-aprox.png"), cv2.resize(limpo, (W0, H0)))
        fundos[-1]["limpo"] = f"assets/fundos/cena{k + 1}-q{q}-limpo-aprox.png"

# folha: todos os candidatos com id e tipo (para classificar abrindo uma imagem só)
T = 150
fonte = video.parent / "f.ttf"
try:
    ft = ImageFont.truetype(str(fonte), 14) if fonte.exists() else ImageFont.load_default()
except OSError:
    ft = ImageFont.load_default()
def folha_de(ids, arq):
    cols = 8
    folha = Image.new("RGB", (cols * T, max(1, -(-len(ids) // cols)) * (T + 20)), (40, 40, 40))
    dr = ImageDraw.Draw(folha)
    for n, eid in enumerate(ids):
        e = saida[eid]
        im = Image.open(assets.parent / e["arquivo"]).convert("RGB")
        im.thumbnail((T - 6, T - 6))
        cx, cy = (n % cols) * T, (n // cols) * (T + 20)
        folha.paste(im, (cx + (T - im.width) // 2, cy + 20 + (T - 6 - im.height) // 2))
        dr.text((cx + 3, cy + 2), f"{eid} {e['tipo']} q{e['de']}-{e['ate']}", fill=(255, 220, 0), font=ft)
    folha.save(assets / arq, quality=80)


folha_de(list(saida), "_folha.jpg")
pendentes = [k for k, e in saida.items() if e["status"] == "hipotese"]
if pendentes:  # só o que ainda não foi classificado nem descartado: abrir esta, não a folha inteira, nas rodadas seguintes
    folha_de(pendentes, "_pendentes.jpg")
elif (assets / "_pendentes.jpg").exists():
    (assets / "_pendentes.jpg").unlink()

dados = {"video": {"arquivo": video.name, "w": W0, "h": H0, "qps": FPS, "quadros": N},
         "plato": plato, "trocas": trocas, "acrescentados": manuais, "cenas": cenas, "fundos": fundos,
         "elementos": saida}
analise.mkdir(parents=True, exist_ok=True)
json.dump(dados, open(jpath, "w", encoding="utf8"), ensure_ascii=False, indent=1)
cont = {p: sum(1 for e in saida.values() if e["pasta"] == p) for p in PASTAS}
print(f"✔ {N} quadros · {len(plato)} platôs · {len(cenas)} cenas ({', '.join(f'q{a}–{b}' for a, b in cenas)}) · {len(saida)} candidatos → {assets}")
print("  " + " · ".join(f"{p} {n}" for p, n in cont.items() if n))
print(f"  folha para classificar: {assets / ('_pendentes.jpg' if pendentes else '_folha.jpg')} "
      f"({len(pendentes)} sem classificar) · dados: {jpath}")
