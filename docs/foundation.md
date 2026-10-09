# Fronteiras e segurança do protótipo

Este registro descreve o comportamento atual do projeto local. Ele não autoriza a exposição do servidor de revisão na internet.

| Tema | Decisão atual |
| --- | --- |
| Interface pública | Nenhuma. A interface de revisão escuta somente em `127.0.0.1` e serve ao usuário da máquina. |
| Dados | Livros e texto extraído podem ser protegidos por direitos autorais; fichas, campanhas e perfis de NPC podem conter dados privados. Tudo fica em `data/`, ignorado pelo Git. |
| Autenticação | A revisão local usa token de sessão e verificação de origem para gravações; isso não substitui autenticação entre usuários. O login opcional do Oráculo usa OAuth com PKCE e guarda tokens via DPAPI do usuário Windows. |
| Autorização | A CLI de campanhas é pessoal e não possui contas de jogadores nem separação de permissões por campanha. Não deve ser colocada atrás de uma API pública sem um novo desenho de autorização. |
| Entrada não confiável | PDF, conteúdo extraído, respostas de modelo e parâmetros HTTP são dados não confiáveis. O processador limita tamanho e páginas do PDF; a revisão valida método, origem, token, tipo, tamanho e campos das mutações. |
| Persistência | SQLite usa consultas parametrizadas e chaves estrangeiras. Edições e aprovações do catálogo são registros separados, ligados à versão do conteúdo. |
| Saída e navegador | A interface mostra texto extraído com `textContent`, usa CSP restrita e cabeçalhos contra incorporação. O PDF local é servido para consulta do usuário pela mesma interface. |
| Rede | Ingestão, indexação, busca e banco são locais. `ask` e a extração via API exigem uma opção explícita antes de enviar trechos selecionados ao serviço de IA. Instalação e modelos de embeddings podem acessar a rede. |
| Segredos | Credenciais não ficam no código, no README nem no Git. `data/`, `.env*` e formatos de chave são ignorados. O verificador `scripts/check_publication.py` inspeciona arquivos candidatos ao commit. |
| Logs | O callback OAuth não registra URLs com códigos de autorização. O servidor de revisão não registra requisições; comandos podem mostrar resumos e erros sem despejar tokens. |
| Recuperação | O dono do PDF guarda seu próprio original. Backup de `data/auth/` não é portátil entre usuários Windows; campanhas SQLite e decisões de revisão precisam de backup local se forem importantes. |

## Antes de qualquer hospedagem

- Projetar autenticação por usuário, autorização por campanha e visibilidade real de dados de mestre/jogador.
- Colocar um proxy HTTPS à frente das rotas públicas, definir cookies e proteção CSRF, CORS restrito, limites de requisição e de upload.
- Manter banco, livros e administração em rede privada; definir isolamento e retenção de arquivos.
- Definir injeção de segredos, rotação, logs sem dados sensíveis, backups testados e monitoramento.
- Revisar contra OWASP ASVS e Top 10 e repetir a varredura de dependências atualizadas.

## Verificações antes do primeiro commit público

1. `python scripts/check_publication.py` deve passar.
2. `git status --short --untracked-files=all` deve mostrar apenas código e documentação destinada ao público.
3. `git check-ignore -v` deve confirmar a exclusão do PDF, de `data/` e dos arquivos locais do piloto.
4. A suíte `pytest` deve passar. Uma revisão humana do diff continua necessária, pois padrões automáticos não detectam todo segredo ou conteúdo protegido.
