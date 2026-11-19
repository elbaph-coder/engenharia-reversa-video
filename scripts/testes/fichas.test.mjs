// Teste das medidas prontas do `npm run estudo` (scripts/fichas.py) num vídeo sintético (scripts/testes/fichas_video.py):
// palavra que nasce letra a letra no lugar, letras afastadas que se juntam, palavra espremida que se abre,
// palavra que entra pela borda com Easing.bezier, cartão que desce com spring,
// paleta conhecida e estalos a 120 BPM. Confere as 4 perguntas de cada entrada de texto, a paleta com papel, o som
// (BPM, golpes, corte no golpe) e as curvas (tipo e parâmetros recuperados).
//   node --test scripts/testes/   (npm test)
import { existsSync, mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import test from "node:test";
import assert from "node:assert/strict";

const raiz = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const py = (...a) => spawnSync("python", ["-P", ...a], { cwd: raiz, encoding: "utf8" });
const perto = (h1, h2, tol) => {
  const c = (h) => [1, 3, 5].map((k) => parseInt(h.slice(k, k + 2), 16));
  const [a, b] = [c(h1), c(h2)];
  return Math.max(...a.map((v, i) => Math.abs(v - b[i]))) <= tol;
};

test("estudo: fichas de texto, paleta, som e curvas num vídeo sintético", { timeout: 180000 }, () => {
  const d = mkdtempSync(join(tmpdir(), "fichas-"));
  let r = py("scripts/testes/fichas_video.py", d);
  assert.equal(r.status, 0, r.stderr);
  r = py("scripts/estudo.py", join(d, "fonte", "ref.mp4"), "--sem-fala");
  assert.equal(r.status, 0, r.stderr);
  const v = JSON.parse(readFileSync(join(d, "verdade.json"), "utf8"));
  const f = JSON.parse(readFileSync(join(d, "analise", "fichas.json"), "utf8"));
  const resumo = readFileSync(join(d, "analise", "RESUMO.md"), "utf8");
  assert.ok(resumo.includes("<!-- fichas -->") && resumo.includes("### Curvas dos movimentos"));

  // 1. fichas de texto
  const c1 = f.textos.filter((t) => t.cena === 1).sort((a, b) => a.q - b.q);
  const [t1, tj, te] = c1;
  const t2 = f.textos.find((t) => t.cena === 2);
  assert.ok(t1 && t2, JSON.stringify(f.textos));
  assert.match(t1.ordem.resposta, /esquerda→direita/);
  assert.ok(t1.ordem.confianca >= 0.6);
  assert.match(t1.borda.resposta, /^não/);
  assert.match(t1.embalo.resposta, /nasce parada/);
  assert.match(t1.tamanho.resposta, /não muda/);
  // letras que chegam afastadas e se juntam (espaço) × palavra espremida que se abre (a letra)
  assert.ok(tj && te, JSON.stringify(c1));
  assert.match(tj.tamanho.resposta, /letras chegam afastadas e se juntam em direção à direita/);
  assert.match(tj.tamanho.resposta, /letterSpacing/);
  assert.match(te.tamanho.resposta, /nasce espremida e se abre para os dois lados — a letra se estica/);
  const esp = f.curvas.find((c) => c.cena === 1 && c.quem === tj.bloco && c.medida === "espaço");
  assert.ok(esp && esp.de_valor > 0.1 && Math.abs(esp.ate_valor) < 0.03 && esp.erro < 3, JSON.stringify(esp));
  assert.match(t2.borda.resposta, /entra pela borda \(dir\)/);
  assert.match(t2.embalo.resposta, /desliza ←/);
  assert.match(t2.tamanho.resposta, /não muda/);
  for (const t of f.textos) if (t.olhar) assert.ok(existsSync(join(d, "analise", t.olhar.arquivo)));

  // 2. paleta
  const [p1, p2] = f.paleta;
  assert.ok(perto(p1.fundo, v.fundo_a, 12), p1.fundo);
  assert.ok(p1.acento && perto(p1.acento, v.acento_a, 25), String(p1.acento));
  assert.ok(perto(p1.texto, "#f0f0f0", 25), p1.texto);
  assert.ok(perto(p2.texto, v.texto_b, 25), p2.texto);

  // 3. som
  assert.ok(Math.abs(f.som.bpm - v.bpm) <= 4, String(f.som.bpm));
  assert.ok(f.som.golpes.some((g) => Math.abs(g - 1.0) < 0.04), JSON.stringify(f.som.golpes));
  const corte = f.som.eventos.find((e) => e.o_que.startsWith("corte 1"));
  assert.ok(corte && corte.no_golpe, JSON.stringify(f.som.eventos));

  // 4. curvas
  const desliza = f.curvas.find((c) => c.cena === 2 && c.quem.startsWith("L") && c.medida === "x");
  assert.ok(desliza, JSON.stringify(f.curvas));
  assert.equal(desliza.melhor, "bezier");
  assert.ok(desliza.erro < 3);
  desliza.bezier.p.forEach((x, i) => assert.ok(Math.abs(x - v.bezier[i]) < 0.12, JSON.stringify(desliza.bezier)));
  assert.match(desliza.formula, /Easing\.bezier\(/);
  const mola = f.curvas.find((c) => c.cena === 2 && c.quem.startsWith("I") && c.medida === "y");
  assert.ok(mola, JSON.stringify(f.curvas));
  assert.equal(mola.melhor, "spring");
  assert.ok(Math.abs(mola.spring.damping - v.spring.damping) / v.spring.damping < 0.2, JSON.stringify(mola.spring));
  assert.ok(Math.abs(mola.spring.stiffness - v.spring.stiffness) / v.spring.stiffness < 0.2, JSON.stringify(mola.spring));
  assert.match(mola.formula, /spring\(\{frame: q - \d+/);
  assert.ok(!f.curvas.some((c) => c.cena === 1 && c.quem === t1.bloco), "letra a letra não é movimento");
});
