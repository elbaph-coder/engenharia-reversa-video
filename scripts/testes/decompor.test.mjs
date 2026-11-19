// Teste do `npm run decompor` (scripts/decompor.py) num estudo sintético (scripts/testes/decompor_video.py): câmera
// parada, texto que aparece em q20, ícone em q40, corte em q60, cartão em q80. Confere as cenas, que cada elemento vira
// candidato com a caixa e o quadro de entrada certos, as pastas criadas, o --classifica (move o arquivo) e que a
// classificação sobrevive a uma nova rodada.
//   node --test scripts/testes/   (npm test)
import { existsSync, mkdtempSync, readFileSync, readdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import test from "node:test";
import assert from "node:assert/strict";

const raiz = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const py = (...a) => spawnSync("python", ["-P", ...a], { cwd: raiz, encoding: "utf8" });

const iou = (a, b) => {
  const x0 = Math.max(a[0], b[0]), y0 = Math.max(a[1], b[1]);
  const x1 = Math.min(a[0] + a[2], b[0] + b[2]), y1 = Math.min(a[1] + a[3], b[1] + b[3]);
  const i = Math.max(0, x1 - x0) * Math.max(0, y1 - y0);
  return i / (a[2] * a[3] + b[2] * b[3] - i);
};

test("decompor: estudo sintético — cenas, candidatos, pastas e classificação", () => {
  const d = mkdtempSync(join(tmpdir(), "decompor-"));
  let r = py("scripts/testes/decompor_video.py", d);
  assert.equal(r.status, 0, r.stderr);
  r = py("scripts/decompor.py", d);
  assert.equal(r.status, 0, r.stderr);
  const verdade = JSON.parse(readFileSync(join(d, "verdade.json"), "utf8"));
  const ler = () => JSON.parse(readFileSync(join(d, "analise", "decomposicao.json"), "utf8"));
  let dados = ler();

  assert.equal(dados.cenas.length, 2, JSON.stringify(dados.cenas));
  assert.ok(Math.abs(dados.cenas[1][0] - verdade.corte) <= 6, JSON.stringify(dados.cenas));
  for (const p of ["fundos", "imagens", "videos", "personagens", "objetos", "icones", "textos", "_descartados"])
    assert.ok(existsSync(join(d, "assets", p)), `pasta ${p}`);
  assert.ok(existsSync(join(d, "assets", "_folha.jpg")));
  assert.ok(readdirSync(join(d, "assets", "fundos")).some((f) => f.startsWith("cena2-")), "fundo da cena 2");

  const acha = (v) =>
    Object.entries(dados.elementos).find(([, e]) => iou(e.caixa, v.caixa) > 0.5 && Math.abs(e.de - v.q) <= 8);
  for (const nome of ["texto", "icone", "cartao"]) assert.ok(acha(verdade[nome]), `${nome} achado: ${JSON.stringify(Object.values(dados.elementos).map((e) => [e.caixa, e.de]))}`);
  assert.equal(acha(verdade.texto)[1].tipo, "texto");

  const [id] = acha(verdade.cartao);
  r = py("scripts/decompor.py", d, `--classifica=${id}:objetos`);
  assert.equal(r.status, 0, r.stderr);
  dados = ler();
  assert.equal(dados.elementos[id].pasta, "objetos");
  assert.ok(existsSync(join(d, dados.elementos[id].arquivo)));

  r = py("scripts/decompor.py", d); // rodar de novo mantém o que foi classificado
  assert.equal(r.status, 0, r.stderr);
  dados = ler();
  const [, cartao] = acha(verdade.cartao);
  assert.equal(cartao.pasta, "objetos");
  assert.equal(cartao.status, "confirmado");
});
