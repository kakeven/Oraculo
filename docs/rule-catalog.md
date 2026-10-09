# Catálogo de regras por item

O objetivo final é um mestre de RPG por IA que lê as fichas, cria NPCs e conduz a campanha. Este catálogo é a camada de consulta das regras do livro. Ele não decide o resultado de uma ação nem altera a ficha.

## Primeiro índice de Mutantes & Malfeitores

`oraculo catalog-index mutantes-malfeitores` lê `processed/pages.jsonl` e escreve `processed/entities/catalog.jsonl` e `catalog_report.json`. Cada registro contém tipo, nome, subtipo, texto da seção, página e linha inicial/final do PDF, hash da fonte e `status: needs_review`.

| Tipo | O que representa | Quantidade inicial |
| --- | --- | ---: |
| `ability` | Uma das oito habilidades básicas | 8 |
| `skill` | Uma perícia nomeada | 16 |
| `advantage` | Uma vantagem nomeada | 74 |
| `effect` | Um efeito mecânico de poder | 40 |
| `power_example` | Um exemplo de poder construído com efeitos | 20 |
| `modifier_extra` | Um extra que modifica o custo ou uso de um efeito | 38 |
| `modifier_flaw` | Uma falha que limita um efeito | 22 |

Em Mutantes & Malfeitores, o nome narrativo de um poder na ficha não define sozinho sua mecânica. “Sopro congelante”, por exemplo, precisa apontar para um ou mais efeitos, suas graduações e modificadores. Os exemplos do livro não são uma lista fechada de poderes possíveis.

O catálogo lê as colunas esquerda e direita nesta ordem nas páginas de perícias, vantagens, extras e falhas. Nessas categorias, usa a fonte e o tamanho dos títulos do próprio PDF para identificar o início dos itens: perícias têm título maior; vantagens trazem o tipo na faixa; extras e falhas trazem o custo na faixa. Os extras e falhas aparecem como categorias separadas. O extrator não interpreta automaticamente custo, salvamento ou relações entre itens. Tabelas, caixas laterais e textos largos ainda podem precisar de ajuste humano; por isso os registros exigem revisão. Descritores, regras de combate e condições ainda precisam de índices próprios.

A revisão já encontrou casos em que o texto corrido e uma tabela apresentam valores diferentes. O índice conserva ambos para conferência humana e não escolhe automaticamente qual prevalece.

## Consulta

`oraculo catalog mutantes-malfeitores` mostra as contagens. Com uma pergunta, mostra os itens encontrados e as páginas. `--category skill` limita a uma categoria.

O comando `ask` verifica o hash do PDF, procura primeiro itens nomeados no catálogo e inclui apenas as regras estruturadas do piloto relacionadas à pergunta. Se não houver item ou regra correspondente, usa a busca de chunks. O texto enviado ao modelo é um recorte com fonte, não o catálogo inteiro. A recuperação por nome e aliases ainda é simples; perguntas por sinônimos ou pelo nome de um poder definido somente na ficha podem cair na busca geral.

## Próximas camadas

1. Revisar os limites e o conteúdo dos registros, sobretudo tabelas e seções longas.
2. Estruturar o procedimento mecânico de cada item: ação, alcance, teste, CD, efeitos, exceções e relações com outras regras, sempre ligado ao trecho do PDF.
3. Representar poderes de fichas como composições de efeitos, graduações, modificadores e descritores.
4. Recuperar conjuntamente regra geral, itens da ficha e estado da cena; deixar o backend validar e aplicar o resultado, e a IA narrá-lo.
