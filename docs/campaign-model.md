# Modelo de campanha: estado atual e direção

O objetivo descrito no [README](../README.md) é um Mestre de RPG por IA com um motor de regras, campanhas persistentes e um backend que valida ações antes de gravá-las. Este banco é um protótipo local dessa memória de campanha, **não** o banco final do produto. O documento original de concepção permanece apenas na máquina do autor.

## Protótipo local

- SQLite guarda campanhas, elementos do mundo, sessões, eventos ordenados e propostas da IA. O livro processado continua em arquivos separados.
- `campaign_entities` guarda propriedades variáveis em JSON. `npc_profiles` identifica quais personagens são NPCs e guarda a personalidade em JSON, separada dos dados gerais do personagem. As chaves sugeridas são `traits`, `motivations`, `goals`, `voice`, `fears` e `secrets`; o formato final será definido com exemplos reais de NPCs e de sistemas.
- `ai_proposals` guarda saídas propostas, modelo e referências. Aceitar uma proposta registra a revisão; aplicar mudanças ao mundo ainda exige comandos validados do backend.
- `campaign_events` guarda acontecimentos em ordem. As decisões do grupo e consequências podem ser recuperadas para dar contexto à IA. Ainda faltam resumos de longo prazo, vínculo entre entidades e regras de atualização do estado.
- O arquivo `data/campaigns/oraculo.sqlite3` é privado. A CLI atual não implementa usuários nem autorização por jogador; portanto não deve ser exposta como serviço.

## Diferenças para o produto descrito no resumo

| Tema | Protótipo | Direção do produto |
| --- | --- | --- |
| Persistência | SQLite local | PostgreSQL com JSONB e tabelas relacionais |
| Sistema e livro | Um slug na campanha e arquivos processados | Entidades distintas para livros, versões e pacotes de sistema com proveniência |
| Personagens | Entidades genéricas e perfil de NPC | Tipos e schemas definidos pelo sistema, fichas e inventários |
| Regras | Sem execução | Motor determinístico validando ações antes de mudar o estado |
| IA | Propostas persistidas para revisão | Interpretação, narração e condução das sessões, com backend responsável pelo estado |
| Custos | Sem medição | Medição por cliente, campanha e sessão de tokens, modelo, custo e RAG |

## Próxima fatia de implementação

Usar um NPC e uma ação real de Mutantes & Malfeitores como exemplo. Definir os campos de personalidade, o que os jogadores podem ver e como o NPC reage a eventos. Depois construir um comando de ação estruturada que valide regras e grave a consequência, seguido da narração da IA. Isso permite testar a fronteira entre narrativa e estado antes de ampliar o modelo.
