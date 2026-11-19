# SlideCast Studio — Direção Automática de Aula e Transições na Linha do Tempo

Este documento descreve a arquitetura, engine multimídia, modelo de dados, políticas de scaling e diretrizes de handoff para a direção automática de videoaulas no **SlideCast Studio**.

---

## 1. Visão Geral da Arquitetura

O SlideCast Studio oferece uma engine determinística de direção pedagógica para gravações de reuniões e aulas (Google Meet, Zoom, Teams, Webcams e Telas). O princípio fundamental da arquitetura baseia-se na **separação entre captura contínua e composição dirigida por linha do tempo**:

```
+-------------------------------------------------------------------------------+
|                             CAPTURA CONTÍNUA (AO VIVO)                        |
|                                                                               |
|  [Área A: Apresentação/Slides]  --> raw_presentation.mp4 (com áudio contínuo) |
|  [Área B: Vídeo do Professor]   --> raw_presenter.mp4                         |
|  [Marcadores de Início/Fim]     --> session.live_markers                      |
+-------------------------------------------------------------------------------+
                                      |
                                      v
+-------------------------------------------------------------------------------+
|                       LINHA DO TEMPO PEDAGÓGICA (SEMI-ABERTA)                 |
|                                                                               |
|  [00:00 -> 02:00]  Layout 1: Professor em Destaque (#10201E + Título da Aula) |
|  [02:00 -> 36:00]  Layout 2: Slides Grandes (~80%) + Professor Lateral (~20%)|
|  [36:00 -> 40:00]  Layout 1: Professor em Destaque (#10201E + Encerramento)  |
+-------------------------------------------------------------------------------+
                                      |
                                      v
+-------------------------------------------------------------------------------+
|                    COMPOSIÇÃO NÃO-DESTRUTIVA (FFMPEG FILTERGRAPH)             |
|                                                                               |
|  • Áudio mestre único contínuo (-map 0:a:0) sem drift, clicks ou interrupção. |
|  • Chaveamento exato frame-perfect via expressões enable='between(t, s, e)'.  |
|  • Re-renderizável infinitamente sem necessidade de regravar o conteúdo.      |
+-------------------------------------------------------------------------------+
```

---

## 2. Layouts Pedagógicos e Regra de Composição

### Layout 1: Professor em Destaque (`presenter_focus` / `centered_title_card`)
- **Quando ocorre:** Antes do início dos slides (abertura/introdução), em pausas/intervalos entre apresentações e no encerramento da aula.
- **Estrutura visual:**
  - **Fundo do Palco:** `#10201E` (Dark Teal Profundo / Stage Broadcast).
  - **Professor:** Centralizado horizontal e verticalmente.
  - **Cartão de Abertura:** Título da Aula renderizado na parte superior com tipografia broadcast e subtítulo institucional/professor na parte inferior.
  - **Textos Seguros:** Escrita via arquivos temporários UTF-8 (`drawtext=textfile=...`), eliminando problemas de escape com caracteres especiais, acentos e emojis.

### Layout 2: Slides Grandes + Professor na Lateral (`sidebar` / `overlay_pip`)
- **Quando ocorre:** Durante os intervalos em que os slides estão ativos (`[startMs, endMs)`).
- **Estrutura visual:**
  - **Apresentação Dominante:** Ocupa aproximadamente 80% da largura da tela (78% útil), com proporção original estritamente preservada (`force_original_aspect_ratio=decrease`).
  - **Professor na Lateral:** Ocupa aproximadamente 20% da largura (21% útil), alinhado ao centro, topo ou base conforme configuração pedagógica.
  - **Alternativa PiP:** Professor sobreposto no canto escolhido (inferior direito, superior direito, inferior esquerdo, superior esquerdo) com borda elegante.

---

## 3. Política de Nitidez e Scaling Honesto (`Honest Scaling Policy`)

Em aulas remotas (Google Meet / Zoom), o feed do professor frequentemente possui resolução menor (ex: 320x240, 480x360 ou thumbnail de grid). Esticar cegamente uma imagem de 320x240 para ocupar metade de uma tela 1080p resulta em borrão extremo, bordas pixeladas e aparência amadora.

O SlideCast adota a **Política de Scaling Honesto**:
1. **Detecção Automática:** A engine inspeciona as dimensões reais do vídeo do professor via `probe_video_dimensions()`.
2. **Limite de Ampliação (`presenter_scale_limit = 1.5`):**
   - Se a largura da fonte for menor que 480px (ex: 320x240), a escala máxima de ampliação no palco é limitada a `1.5 × prof_src_w` (ex: 480px).
   - O professor permanece no centro do palco elegante `#10201E`, mantendo nitidez, foco e aparência intencional de transmissão profissional.
3. **Badge de Transparência:** Na interface de edição, uma tag informa o professor:
   > *"📐 Câmera do Professor: 320×240 px · Política de Nitidez: Ampliação contida em até 1.5× no palco #10201E (sem esticar ou pixelar)"*

---

## 4. Métodos para Definição dos Intervalos

A engine disponibiliza três métodos independentes e complementares:

### Método A: Entrada Manual de Tempos (Determinístico e Primário)
- Campos de texto `Início: mm:ss` e `Fim: mm:ss` (ou `hh:mm:ss`).
- Validação automática:
  - Formato de tempo válido (`parse_time_to_ms`).
  - `end_ms > start_ms`.
  - Proibição estrita de sobreposição de intervalos: se houver conflito com intervalo pré-existente, a interface emite alerta claro e bloqueia a adição.
  - Tabela com lista completa de intervalos e botão de remoção instantânea `🗑️ Remover`.

### Método B: Marcadores ao Vivo Durante a Gravação
- Durante a gravação, botões acessíveis permitem marcar o ritmo da aula em tempo real:
  - **`▶ Apresentação Começou`**: Registra timestamp atual como início do intervalo de slides.
  - **`⏹ Apresentação Terminou`**: Registra timestamp atual como encerramento do intervalo e gera um `PresentationInterval` com `origin="live_marker"`.
- **Fechamento Automático de Segurança:** Se a gravação for finalizada enquanto um intervalo de slides ainda estiver aberto, a engine automaticamente fecha o intervalo na duração final da gravação, evitando perda de dados.

### Método C: Sugestão por Heurística Local Offline (Opt-in e Não-Vinculante)
- Executa análise local no arquivo da apresentação (`detect_slide_intervals_heuristic`).
- Detecta períodos em preto ou estáticos e propõe intervalos candidatos.
- Nunca altera a linha do tempo sem confirmação explícita do professor via modal interativo.

---

## 5. Grafo de Filtros FFmpeg e Áudio Contínuo

O chaveamento de layouts e cartões de título é realizado dentro de um único grafo de filtros através do parâmetro `enable` do FFmpeg:

```bash
# Expressão de ativação dos slides:
enable='between(t, 2.0, 36.0) + between(t, 42.0, 58.0)'

# Expressão de ativação do professor em destaque:
enable='not(between(t, 2.0, 36.0) + between(t, 42.0, 58.0))'
```

### Por que esta abordagem é superior ao corte/concatenation?
- **Zero Audio Drift:** O áudio é mapeado diretamente do vídeo mestre (`-map 0:a:0 -c:a aac -b:a 192k`). Não há transição, junção nem remontagem de pacotes de áudio.
- **Transição Frame-Perfect:** O corte no vídeo ocorre no timestamp exato sem glitches de PTS, telas pretas ou congelamentos.
- **Performance:** Uma única passagem do FFmpeg realiza toda a renderização.

---

## 6. Handoff para Codex (Camada Visual & Estilos)

Os componentes foram desacoplados para que o time de UX/Codex possa personalizar a interface sem impactar a engine determinística:

| Componente | Arquivo | Responsabilidade |
|---|---|---|
| Engine de Linha do Tempo | [dual_region_recorder.py](file:///home/kika-magalhaes/Plataformas/slidecast/slidecast-studio/app/core/dual_region_recorder.py) | Modelos `PresentationInterval`, FFmpeg filtergraph, normalização, honest scaling. |
| Widget da Linha do Tempo | [class_timeline_widget.py](file:///home/kika-magalhaes/Plataformas/slidecast/slidecast-studio/app/ui/class_timeline_widget.py) | Régua de tempo, blocos coloridos, agulha playhead, hover tooltips, drag & seek. |
| View de Reunião e Aula | [record_meet_view.py](file:///home/kika-magalhaes/Plataformas/slidecast/slidecast-studio/app/ui/views/record_meet_view.py) | Telas de gravação ao vivo, botões de marcadores, tabela de intervalos e recomposição. |
| Paleta e Tokens | [styles.py](file:///home/kika-magalhaes/Plataformas/slidecast/slidecast-studio/app/ui/styles.py) | Tokens `@stage@`, `@stage_text@`, `@primary@`, `@focus@`, `@surface@`. |

### Onde o Codex pode customizar:
1. **Cores e Temas da Linha do Tempo:**
   Em `ClassTimelineWidget.paintEvent`, as cores dos blocos de slides (`#6366f1` / `#818cf8`), palco (`#10201E`) e agulha (`#f59e0b`) podem ser ajustadas dinamicamente via tokens de tema.
2. **Estilo da Tabela e Botões:**
   Em `RecordMeetView`, a tabela de intervalos e os botões de ação usam o sistema de estilos centralizado `apply_style()`.
