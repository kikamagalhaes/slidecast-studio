# Sistema de design — SlideCast Studio

## Direção

Estúdio de criação com superfícies claras quentes, verde profundo para ações e tipografia legível. O escuro preserva a mesma hierarquia e dimensões. Cores de slides, desenhos, câmera e artes pertencem ao conteúdo; não são recoloridas pelo tema da interface.

## Tokens reais

Fonte: `app/ui/styles.py`. A tabela documenta os tokens usados em produção do código desktop.

| Papel | Claro | Escuro |
|---|---|---|
| Fundo `bg` | #F3EEE2 | #101A19 |
| Painel `surface` | #FFFDF7 | #192725 |
| Superfície alternativa | #EAE5D9 | #233532 |
| Campo `field` | #FFFFFF | #14211F |
| Elevado `elevated` | #FFFDF7 | #263A36 |
| Texto | #1B2A28 | #F3F1E8 |
| Texto secundário | #43564F | #C5D5CE |
| Texto discreto | #59665F | #ADBCB5 |
| Desabilitado | #546059 | #9EADA6 |
| Borda | #CCC6B8 | #3F5550 |
| Borda essencial | #807F72 | #7D9690 |
| Ação primária | #0E4A4A | #98D8C4 |
| Texto sobre ação | #FFFFFF | #102A23 |
| Foco/alerta | #8F5D14 / #85421D | #F5C783 |
| Sucesso | #226336 | #A3DBAB |
| Erro | #A52222 | #FFB7AA |
| Faixa 1 | #0E6562 | #A0DCD0 |
| Faixa 2 | #6A4698 | #CEBAF0 |
| Faixa 3 | #985022 | #F2C590 |
| Faixa 4 | #355E91 | #ACCBF4 |
| Palco do conteúdo | #10201E | #10201E |

Espaçamentos: 4, 8, 12, 16, 24 e 32 px. Raios: 6, 8, 12 e 16 px. Fonte de interface: Segoe UI, Noto Sans ou DejaVu Sans conforme disponibilidade. Corpo 13 px; títulos de seção 17 px; título principal 28 px. Campos e botões têm padding e altura mínima compartilhados. Na web, títulos editoriais serifados diferenciam apresentação comercial e operação.

## Arquitetura Qt

`ThemeManager` aplica estilo Fusion, QPalette e QSS à QApplication. A escolha fica em `QSettings("SlideCast", "Studio")`, chave `appearance/theme`. A alteração é imediata e emite sinal para widgets desenhados com QPainter.

Estilos específicos devem usar `apply_style(widget, "... @surface@ ... @text@ ...")`. Essa função mantém os templates em registro fraco e os recompõe após troca de tema. Não usar cores de interface fixas em novos `setStyleSheet`. A compatibilidade com telas antigas normaliza pares de foreground/background e restringe seletores QFrame ao painel raiz, evitando bordas em todos os labels.

Classes compartilhadas: `title`, `section-title`, `muted`, `card`, `menu-card`, `track`, `primary`, `danger`, `badge`, `badge-success` e `badge-warning`. Os SVGs de check e chevrons estão em `app/ui/assets` e foram incluídos no spec PyInstaller.

`AudioTrackWidget` mantém o mesmo modelo de volume (0–200%), mute e offset; `AudioTimeline` desenha os blocos na escala do vídeo. Cor nunca identifica sozinha uma faixa: há número, nome e valores. A timeline não inventa forma de onda. Texto de bloco curto pode ser recortado visualmente; os dados completos permanecem nos controles da faixa.

## Legibilidade e interação

O teste `test_theme_contrast_tokens` verifica as combinações de texto/estado/faixa sobre superfícies e ações com alvo mínimo 4,5:1. Durante a validação, o token disabled claro foi escurecido após falhar esse critério. Bordas decorativas suaves não substituem foco/seleção; indicadores essenciais usam borda forte e cores próprias.

O foco usa borda visível; Tab/Shift+Tab navegam pelos controles Qt, Enter/Espaço acionam os controles adequados. Ctrl+O e Ctrl+S atuam no editor. Os campos de faixa têm nomes acessíveis; nomes longos usam elisão e tooltip. A troca de tema não reconstrói o projeto nem altera o frame exportado.

Menus, listas, tabelas, abas, progressos, sliders, diálogos e seletores Qt compartilham os mesmos estados. O seletor nativo do sistema operacional pode ter aparência distinta; a evidência inclui o seletor Qt não nativo. A certificação visual de Windows e de leitores de tela ainda requer ambiente real.

## Landing

Implementação em `frontend/src/landing.tsx` e `landing.css`, sem fontes remotas ou rastreadores adicionados. HTML semântico com skip link, landmarks, títulos, tabela com cabeçalhos e FAQ via `details/summary`. Imagens reais otimizadas, dimensões explícitas e lazy loading abaixo da dobra. Âncoras conduzem a seções reais; nenhuma ação de compra/download simula disponibilidade.

## Refino visual de 19/11/2026

Estilos sem seletor são restritos ao widget alvo por `slidecastStyle`, evitando que bordas dos painéis desenhem molduras nos labels, radios e campos filhos. As bordas decorativas passaram a 1 px; foco de teclado e seleção permanecem distintos. Botões comuns têm alvo de aproximadamente 44 px e ações da home 48 px, com largura apropriada ao rótulo. Cartões da home não esticam seus botões em barras finas. Teleprompter recebeu mais espaço, leitura sem contorno interno e controles maiores. Blocos da timeline usam preenchimento suave e borda discreta.

Capturas revisadas: `docs/evidencias/refino-claro` e `refino-escuro`. O teste `test_panel_border_does_not_frame_child_labels` verifica o resultado renderizado do escopo das bordas.
