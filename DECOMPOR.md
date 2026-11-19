# Decompor um vídeo — o que é cada coisa, em que camada fica e o que acontece com ela

Dono do método e do formato do `DECOMPOSICAO.md`. Vale para **qualquer** vídeo de referência, de qualquer segmento. É um
passo do estudo (`.claude/skills/estudar-video/SKILL.md` → 2c): o `npm run estudo` já roda o `camadas` e o `decompor`, e
termina no `referencias/<estilo>/DECOMPOSICAO.md` + os recortes separados em `assets/`.
O `DECOMPOSICAO.md` é o **quê** do vídeo (cenas, elementos, efeitos, peças, assets) e o que a recriação lê primeiro; o
`ESTUDO.md` é o **porquê** (conceito, DNA, leitura) e não repete nada daqui.

## 1. Asset × operação
- **Asset** = uma **coisa** que precisa existir (um arquivo ou um desenho): foto, render 3D, vídeo, fundo, personagem,
  objeto, ícone, logo, texto.
- **Operação** = o que **acontece** com a coisa: anima, revela, recebe efeito, é recortada (máscara) ou troca de cena (transição).
- **O teste é comparar o mesmo elemento em quadros diferentes:**
  - Ele mantém a forma e muda só posição, tamanho, giro, opacidade ou foco → é **um asset com animação**.
  - Ele muda **por dentro** (um traço que cresce, um texto que ganha letras, uma borda reta que anda) → é uma **revelação**:
    traço, digitação ou máscara.
  - A tela inteira muda e as duas cenas convivem alguns quadros → é **transição**. Se não convivem nem por um quadro, é corte.
  - Ele muda por dentro **sem** ninguém mexer nele (partículas, fumaça, filmagem) → é um **asset de vídeo**.
- **Pronto × código:** o que tem luz, sombra e textura de foto ou render **vem pronto** (vaga de imagem; a imagem da
  referência nunca vai ao ar). Traço fino, chapado, poucas cores, forma geométrica e texto → **desenhado em código**.

## 2. Tipos de asset e as pastas do estudo
`npm run decompor` separa os recortes em `referencias/<estilo>/assets/<pasta>/`:

| pasta | o que é | como a medida sugere (tipo provável) | o que só a leitura decide |
|---|---|---|---|
| `fundos/` | o que cobre a tela atrás de tudo numa cena | recorte > 50% da tela; 1 por cena (`cena<n>-q<q>.png`) + versão `limpo-aprox` (candidatos apagados) | foto × cor × textura; se anda com a câmera |
| `imagens/` | foto, render, ilustração, **logo do cliente** | o que não é texto, ícone nem vídeo | o que a imagem mostra; se é logo |
| `videos/` | o que se move por dentro: partículas, fumaça, filmagem | o recorte muda num trecho parado, mesmo descontando o próprio deslize | se é vídeo pronto ou efeito de código |
| `personagens/` | pessoa, mascote, figura com rosto | — (a medida não sabe o que é gente) | sempre a leitura |
| `objetos/` | coisa com corpo: produto, cartão, botão, moldura | — | sempre a leitura |
| `icones/` | símbolo de traço ou chapado, pequeno | < 6% da tela, pouca cor, borda fina, pouca tinta | se é ícone ou letra |
| `textos/` | palavra, frase, número | 5+ peças da mesma altura em linha, pouca tinta | o conteúdo (nunca vai ao vídeo novo) |
| `_descartados/` | não é elemento: borda, pedaço, ruído | — | `--descarta` |

`assets/` fica **fora do git** (é recorte de vídeo de terceiro, só para estudo). Para escolher ou pedir a imagem nova, o
que vale é a lista e as medidas do `DECOMPOSICAO.md`.

## 3. Operações e como cada uma aparece na medida
| família | operação | sinal no vídeo | quem mede |
|---|---|---|---|
| animação | `anda` · `escala` · `gira` | a caixa anda, cresce ou gira com o conteúdo igual | `camadas` (caminho por quadro) |
| animação | `aparece` · `some` | surge ou vai embora entre dois trechos parados | `decompor` (aparição) |
| animação | `flutua` | vaivém pequeno e contínuo | `camadas` + leitura |
| revelação | `traço` | a tinta cresce ao longo de um caminho fino, caixa fixa | leitura (quadros seguidos) |
| revelação | `digitação` · `palavra a palavra` | a tinta cresce da esquerda para a direita, em saltos de letra ou de palavra | leitura; o `estudo` vê a largura abrindo |
| revelação | `desfoque→nítido` | a nitidez sobe com a caixa fixa | leitura |
| revelação | `máscara/cortina` | borda reta que anda e corta o elemento | leitura |
| efeito | `vidro` (desfoca atrás) | dentro do cartão o fundo fica mais borrado que fora | leitura |
| efeito | brilho, grão, sombra, partículas | — | leitura |
| transição | `corte` | um pico isolado; os pontos não atravessam | `camadas` |
| transição | `clarão` · `pelo preto` | a luz sobe e desce, ou o quadro fica liso | `camadas` |
| transição | `fusão` | o quadro é a mistura do antes com o depois | `camadas` (com imagens paradas) |
| transição | `empurrão` | a tela inteira desliza junto | `camadas`: o fundo anda ~1 largura de tela |
| transição | `cor do fundo` · `troca sobreposta` | a cor anda aos poucos; elementos das duas cenas ao mesmo tempo | `camadas` (troca em movimento) + leitura |

## 4. Camadas, grupos e relações
- **Separar em camadas** o que se move de jeito diferente. O que **anda junto** é **um grupo** (cartão + ícone + texto) e
  vira um `<div>`/`<Camera>` no Remotion, com os membros parados dentro dele. O `camadas` mede isso: a mesma camada é a
  mesma transformação nos mesmos pontos.
- **Relações** (cada uma com a prova):
  - `sobre` / `atrás de`: quem cobre quem na área em que se cruzam.
  - `dentro de`: a caixa fica contida o tempo todo e anda junto.
  - `toca`: as bordas ficam encostadas por vários quadros.
  - `anda com`: a mesma camada.
  - `desfoca atrás`: é vidro.
  - `aponta para`: seta, olhar, gesto.
- **Ordem das camadas** = a ordem no JSX, de baixo para cima: fundo → atmosfera (bolhas, partículas) → cartões → conteúdo
  → enfeites por cima.

## 5. Evidência: O · H · +Q
Toda afirmação do `DECOMPOSICAO.md` leva uma marca:
- **[O] observado:** a medida mostrou (`camadas`, `decompor`, `estudo`) ou o quadro foi visto.
- **[H] hipótese de reconstrução:** é como se faria, mas não está provado (ex.: "vídeo pronto de partículas", "aproximação
  lenta da câmera" sem medida).
- **[+Q] precisa de mais quadros:** diz **quais** quadros (`q390–420`) e o que eles decidem.

O `decomposicao.json` guarda o mesmo em `status` (`hipotese` → `confirmado` / `rejeitado`) e `fonte` (`medida` · `modelo`).

## 6. Passo a passo (comandos a partir da raiz do repositório)
1. `npm run estudo -- referencias/<estilo>/fonte/<v>.mp4` — roda o `camadas` (as cenas e as trocas: a fonte única, a
   mesma do estudo e do decompor) e, no fim, o `decompor`.
2. O `decompor` (sozinho: `npm run decompor -- referencias/<estilo>`) acha os candidatos de três jeitos (o que aparece entre trechos parados; o
   que tem detalhe acima do fundo em cada trecho parado; as camadas com movimento próprio), dá o tipo provável, separa
   nas pastas e monta `assets/_folha.jpg`.
3. Abrir **uma** imagem, a `_folha.jpg` (ou a `_pendentes.jpg` nas rodadas seguintes), e classificar:
   - `--classifica=e3:objetos,e7:textos`
   - `--descarta=e9,e12`
   - `--acrescenta="objetos:66:230,370,260,640:implante"` para o que a medida perdeu (pasta:quadro:x,y,larg,alt em px da
     referência:nome; vários separados por `;`)
   A classificação fica gravada e volta a cada nova rodada.
4. Para as dúvidas, uma tira pequena dos quadros da dúvida (`ffmpeg … select=…,tile=`), nunca a folha inteira.
5. Escrever o `DECOMPOSICAO.md` (formato abaixo). O vídeo não é recriado aqui: a recriação é outra sessão.

## 7. Formato do `DECOMPOSICAO.md`
1. Cabeçalho: vídeo, ficha, comandos rodados, quantos quadros foram vistos; "copiamos a linguagem, nunca a marca".
2. **Cenas e trocas:** tabela `cena | quadros | fundo | troca para a próxima (tipo) | marca`.
3. **Ficha de cada cena** (as que não são repetição; as repetidas só "= cena N") — `tempo · fala que a dispara`, e:
   **entrada** (como cada elemento chega, de onde, quantos quadros) · **durante** (o que se mexe, inclusive cópias pequenas e
   enfeites; algo fica parado?) · **trocas dentro da cena** (como uma palavra vira outra) · **saída e passagem** (tipo do
   corte no `RESUMO.md` + o que se vê na folha de corte) · **intenção** (função/emoção com o vocabulário) · em cena com texto
   que entra, as respostas das 4 perguntas da skill (ordem, borda × falta, embalo, tamanho).
4. **Elementos por cena:** tabela `elemento (id) | trecho | tipo/pasta | função | relações | operações | marca`.
5. **Grupos e ordem das camadas** por cena.
6. **Catálogo de efeitos** — cada operação achada, sem repetir, da mais usada à menos: **nome** (descritivo em português;
   termo em inglês se houver) · família (§3) · **o que faz** · **passo a passo** quadro a quadro (o que muda: posição, tamanho,
   espaçamento, cor, recorte; aceleração/freio) · duração · **exemplos** (cena e tempo de cada vez) · peça que recria.
7. **Peças e assets para a recriação:**
   - peças: para cada efeito do catálogo, onde já existe na sua ferramenta (biblioteca própria, pacotes oficiais, terceiros),
     ou "falta — construir" com a assinatura proposta (`<Nome props={...} />`); primeiro o que mais carrega o estilo. Não é
     a lista de efeitos obrigatórios de um vídeo novo: só "ao pé da letra" esta lista vira o roteiro de efeitos;
   - assets: o que vem pronto (vaga: o que mostrar, tamanho), o que é código, o que é do cliente.
8. **Dúvidas (+Q):** os quadros e o que cada um decide.
