// Teste do `npm run camadas` (scripts/camadas.py).
// 1. Vídeo sintético com o movimento conhecido (scripts/testes/camadas_video.py): corte seco, clarão, fundo que anda e um
//    cartão que desce girando — confere as trocas e o caminho das duas camadas.
//   node --test scripts/testes/   (npm test)
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import test from "node:test";
import assert from "node:assert/strict";

const raiz = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const py = (...a) => spawnSync("python", ["-P", ...a], { cwd: raiz, encoding: "utf8" });

test("camadas: vídeo sintético — trocas e caminhos conhecidos", () => {
  const d = mkdtempSync(join(tmpdir(), "camadas-"));
  const v = join(d, "v.mp4");
  let r = py("scripts/testes/camadas_video.py", v, join(d, "verdade.json"));
  assert.equal(r.status, 0, r.stderr);
  r = py("scripts/camadas.py", v, `--saida=${d}`);
  assert.equal(r.status, 0, r.stderr);
  const { trocas, camadas } = JSON.parse(readFileSync(join(d, "camadas.json"), "utf8"));

  assert.ok(trocas.some((t) => t.tipo === "corte" && Math.abs(t.de - 45) <= 1), JSON.stringify(trocas));
  assert.ok(trocas.some((t) => t.tipo === "clarão" && t.de >= 65 && t.de <= 67 && t.ate >= 67 && t.ate <= 70), JSON.stringify(trocas));
  assert.equal(trocas.length, 2, JSON.stringify(trocas));

  const lista = Object.values(camadas);
  const ponta = (c, q) => c.q[String(q)];
  const fundo = lista.find((c) => c.papel === "fundo" && c.de <= 2 && c.ate >= 43);
  assert.ok(fundo, "fundo da 1ª cena");
  const [a, b] = [ponta(fundo, fundo.de), ponta(fundo, 44)];
  assert.ok(Math.abs(b[0] - a[0] - -3 * (44 - fundo.de)) <= 4 && Math.abs(b[1] - a[1]) <= 3, `fundo anda ${b[0] - a[0]}, ${b[1] - a[1]}`);

  const cartao = lista.find((c) => c.papel === "objeto" && c.pontos >= 100 && c.de <= 2 && c.ate >= 43);
  assert.ok(cartao, "cartão como objeto");
  const [c0, c1] = [ponta(cartao, cartao.de), ponta(cartao, 44)];
  const n = 44 - cartao.de;
  assert.ok(Math.abs(c1[1] - c0[1] - 4 * n) <= 4 && Math.abs(c1[0] - c0[0]) <= 4, `cartão anda ${c1[0] - c0[0]}, ${c1[1] - c0[1]}`);
  assert.ok(Math.abs(c1[3] - c0[3] - 0.4 * n) <= 1, `cartão gira ${c1[3] - c0[3]}`);
  assert.ok(Math.abs(c1[2] / c0[2] - 1) <= 0.02, `cartão escala ${c1[2] / c0[2]}`);
});

