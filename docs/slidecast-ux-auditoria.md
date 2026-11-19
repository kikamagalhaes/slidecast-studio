# Auditoria UX/UI — SlideCast Desktop e landing

Data: 18/11/2026 (America/Sao_Paulo). Implementação em `codex/desktop-ux-landing`, worktree `slidecast-ux-ui`.

## Base e proveniência

Foram lidos integralmente, na ordem solicitada, `00-inventario-base.md`, `entrega-web-sem-ia.md`, `deploy-local-e-vps.md`, `01-auditoria-web-desktop.md` e `02-entrega-estudio-web-desktop.md`. Esses documentos registram entregas históricas; as verificações abaixo usam o código e a aplicação Qt atuais.

O checkout ativo é `slidecast-studio`; o antigo `VideosCreate` foi localizado apenas na lixeira. O aplicativo canônico abre por `main.py`, usando PySide6 e `app/ui/`. A implementação foi isolada em worktree. O motor multitrack do commit `32eb1b7` foi integrado, sem criar outro renderizador. Os commits de UI `9a3ac1c` e `3df68ea` passaram a compor a base durante o trabalho.

O desktop atual contém três slots de PDF, cenas, caneta, teleprompter, gravação, podcast e materiais. Não foi encontrado um fluxo desktop separado de Program/Preview/TAKE como o descrito para a web. A navegação real e seus recursos foram preservados, sem inventar controles de transmissão.

## Achados e correções

| Tela/componente | Problema e consequência | Risco | Solução implementada |
|---|---|---|---|
| Aplicação inteira | 356 estilos locais com cores fixas; a troca da paleta não alcançava filhos | Texto invisível e estado difícil de identificar | Tokens semânticos, QPalette, QSS global e `apply_style` reaplicado em tempo real |
| Home | Hierarquia fragmentada e estilos diferentes entre cartões | Dificuldade para escolher tarefa | Cartões numerados, títulos orientados à tarefa, tipografia comum e cabeçalho persistente |
| Navegação | Ações globais dispersas | Troca de tela durante captura ou trabalho não salvo | Seletor de tarefa e tema sempre disponíveis; bloqueio de saída durante gravação/processamento; editor preservado entre telas |
| Criar vídeo | Interface concentrada em PDF e um áudio | Novo contrato multimídia inacessível | Fonte PDF/MP4 explícita, prévia, propriedades, até quatro faixas e exportação no mesmo espaço |
| Importação | Arquivos inválidos poderiam substituir dados úteis | Perda de trabalho | Validação em QThread sobre cópia do projeto; alterações só aplicadas no sucesso |
| Faixas e duração | Ausência de visão temporal independente | Volume/posição e corte final difíceis de antecipar | Nome, volume, mute e início por faixa; timeline proporcional e aviso de corte; limite de quatro explicado |
| Prévia | Imagem estática não permite conferir a mixagem | Confundir thumbnail com resultado audiovisual | Rótulo explícito para imagem; prévia MP4 gerada pelo mesmo worker do render final e reproduzida pelo Qt |
| Projeto e exportação | Mudança de fonte e compatibilidade antiga exigem cuidado | Perder ajustes ou sobrescrever fonte | Confirmação, preservação de faixas, migração v1, guarda de alterações e bloqueio de sobrescrita das mídias de origem |
| Estúdio/teleprompter | Texto inverso sobre superfície clara e estilos herdados | Compromete leitura durante aula | Pares de cor corrigidos; seletor QFrame limitado ao próprio painel; conteúdo da cena separado do tema do operador |
| Campos e menus | Indicadores nativos desapareciam sob QSS | Combo/spin/checkbox sem indicação visual | Ícones SVG de ambos os temas, foco e estados disabled/seleção comuns |
| Notebook e escala | Conteúdo mínimo excessivo | Controles fora da janela | Rolagem nas telas e painel de faixas, splitters e zoom da timeline |
| Site | Estúdio web competia com a proposta desktop | Mensagem comercial ambígua | Landing em `/`; estúdio antigo atrás de `ENABLE_WEB_STUDIO`; APIs, contas e banco preservados |
| Compra/download | Stripe web não é licença desktop; pacotes antigos não contêm este editor | Oferta ou download enganoso | Estados “Em breve”; nenhum preço, checkout, suporte ou pacote inventado |

## Evidências visuais

As imagens foram capturadas de widgets Qt reais. As amostras são PDFs e WAVs de demonstração efetivamente importados pelo motor. Não são mockups do produto.

| Área | Antes | Claro | Escuro |
|---|---|---|---|
| Home | [Antes](evidencias/antes/home.png) | [Depois](evidencias/depois-claro/home.png) | [Depois](evidencias/depois-escuro/home.png) |
| Editor | [Antes](evidencias/antes/editor.png) | [Quatro faixas](evidencias/depois-claro/editor.png) | [Quatro faixas](evidencias/depois-escuro/editor.png) |
| Estúdio | [Antes](evidencias/antes/estudio.png) | [Depois](evidencias/depois-claro/estudio.png) | [Depois](evidencias/depois-escuro/estudio.png) |
| Podcast | [Antes](evidencias/antes/podcast.png) | [Depois](evidencias/depois-claro/podcast.png) | [Depois](evidencias/depois-escuro/podcast.png) |
| Modal | [Antes](evidencias/antes/dialogo.png) | [Claro](evidencias/depois-claro/dialogo.png) | [Escuro](evidencias/depois-escuro/dialogo.png) |

As pastas dos dois temas também incluem todas as etapas de aula, reunião, podcast e materiais, menus, seletor de arquivos Qt e modal com tema trocado enquanto aberto. A validação detalhada e suas limitações estão em [slidecast-ux-validacao.md](slidecast-ux-validacao.md).
