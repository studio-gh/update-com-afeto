# Update com Afeto · Intelligence Desk

Este repositório contém a primeira versão publicável do site do **Update com Afeto**. A página inicial é um Intelligence Desk responsivo; a saída A4 aparece pelo botão **Imprimir** do navegador.

## O que já está incluído
- `index.html`: protótipo aprovado como ponto de partida visual.
- `data/sources.json`: as 12 fontes oficiais da Série A e seis candidatas da Série B, claramente separadas.
- `data/latest.json`: contrato inicial para a edição atual.
- `data/editions/`: arquivo de edições por data.
- `.github/workflows/pages.yml`: publicação automática no GitHub Pages quando houver push na branch principal.

## Publicar no GitHub Pages
1. Envie todos os arquivos e pastas deste ZIP para a raiz do repositório `studio-gh/update-com-afeto` (ou o nome que você criou).
2. No GitHub, abra **Settings → Pages**.
3. Em **Build and deployment**, escolha **GitHub Actions**.
4. Abra **Actions** e confirme que o workflow **Deploy to GitHub Pages** terminou com sucesso.
5. A URL do site aparecerá em **Settings → Pages**.

## Importante sobre a edição inicial
O HTML preserva o protótipo editorial e os cards usados na demonstração. Os títulos, datas e links dessas matérias ainda precisam de uma auditoria de publicação. O arquivo `data/latest.json` está marcado como `prototype` e não deve ser tratado como uma edição validada.

## Atualização diária: estado atual
A publicação do site está automatizada após cada push, mas a **curadoria diária ainda não está ligada**. Não queremos fingir que uma edição foi apurada quando as fontes, as datas ou os links não foram verificados. O workflow `.github/workflows/daily-edition.yml` pesquisa as 12 fontes da Série A, valida URLs e datas nas páginas originais, usa `OPENAI_API_KEY` para seleção editorial e atualiza `data/latest.json` + arquivo datado. A rotina é agendada para 08:07 em `America/Sao_Paulo` e também pode ser executada manualmente em Actions. A chave nunca deve entrar no HTML nem no repositório.

## Regras editoriais
- Exatamente 10 matérias por edição.
- Janela de publicação: últimos 7 dias corridos, incluindo a data da edição.
- No máximo 2 matérias por fonte e pelo menos 6 fontes distintas.
- Links diretos para a matéria, com data e fonte verificáveis.
- Não inventar títulos, datas, resumos ou URLs.
- Se a validação não encontrar 10 matérias elegíveis, não publicar silenciosamente uma edição incompleta.
- Série A é oficial. Série B permanece candidata até aprovação explícita da Dani.
- Foco: publicidade, campanhas, branding, experiências de marca, estratégia/negócios, comportamento e cultura digital, com humanidade e empatia como lentes editoriais.

## Rotina sugerida
- Edição diária desejada: 08:00, horário de Brasília (`America/Sao_Paulo`).
- O agendamento da curadoria será configurado na etapa do pipeline diário; o workflow diário está configurado para 08:07, horário de Brasília; a primeira execução precisa terminar com sucesso antes de considerar a edição automatizada validada.
