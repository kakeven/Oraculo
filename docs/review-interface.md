# Revisão local do catálogo

Execute `oraculo-review mutantes-malfeitores` na raiz do projeto. O servidor escolhe uma porta disponível em `127.0.0.1`, imprime o endereço e abre o navegador. Encerre com `Ctrl+C`. Não é necessário login ChatGPT para revisar o livro.

A lista permite filtrar por habilidade, perícia, vantagem, efeito, exemplo de poder, extra e falha, além de pendentes/aprovados. A leitura mostra o texto usado nas respostas, páginas e linhas, com link para a página no PDF local. Use **Editar texto** para remover trechos extras ou corrigir a extração e clique em **Salvar texto**. A edição passa a ser usada pelo `ask`; o texto extraído originalmente continua disponível para comparação e pode ser recuperado com **Restaurar original**. A edição fica em `processed/entities/catalog_edits.jsonl`, sem alterar o catálogo bruto. Uma reindexação da mesma extração preserva a edição; se o texto original, os limites ou o PDF mudarem, a edição antiga deixa de ser aplicada.

Ao aprovar, o sistema registra a decisão em `processed/entities/catalog_reviews.jsonl`. O registro tem data, ID do item, hash da fonte e impressão digital da versão efetiva do texto e de seus limites. Uma alteração do texto invalida a aprovação dessa versão; revise e aprove novamente. **Voltar para revisão** registra uma nova decisão e é reversível.

A aprovação significa que uma pessoa conferiu o trecho extraído e sua delimitação. Ela não aprova automaticamente o resumo de uma regra, uma fórmula mecânica ou uma mudança de estado de jogo. O `ask` inclui o estado `approved` ou `needs_review` no contexto do item encontrado.

## Limites e proteção local

- O servidor e o PDF são acessíveis apenas pela interface local `127.0.0.1`; não há exposição de rede pública ou CORS.
- O livro e o catálogo são dados locais privados. Nenhum token ChatGPT é usado ou enviado pelo servidor de revisão.
- A página usa texto sem HTML dinâmico, política de conteúdo restrita e cabeçalhos contra incorporação. Leituras da API exigem o token aleatório da sessão; gravações também exigem origem local e token. O token muda ao reiniciar o servidor.
- Os dados de revisão ficam no diretório `processed/`, ignorado pelo Git. Faça backup de `catalog_edits.jsonl` e `catalog_reviews.jsonl` junto com o catálogo e o PDF, pois eles contêm as edições e o histórico de aprovações.
- Este é um serviço pessoal local, sem contas ou autorização entre vários usuários. Antes de transformá-lo em serviço remoto, será necessário acrescentar autenticação por usuário, HTTPS, autorização por sistema/campanha, limites de requisições e uma política de backups.
