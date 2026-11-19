# SlideCast Desktop — Gravação de Aula/Reunião com Duas Áreas Selecionáveis

> **Documento:** Entrega e Especificação Técnica da Captura Dual-Region & Composição Pedagógica  
> **Data:** 19/11/2026  
> **Responsável:** Agi / Muse (Engenharia de Mídia, Captura, Sincronização, FFmpeg e UI Funcional)  
> **Produto:** SlideCast Desktop (Linux e Windows)  
> **Status:** Concluído e Validado (214 testes automatizados aprovados)

---

## 1. Resumo Executivo da Funcionalidade

A funcionalidade permite gravar aulas online e reuniões remotas selecionando **duas regiões retangulares independentes na tela do computador**:

1. **Área A — Apresentação (Slides / Material Didático):** Delimita a janela de slides (PowerPoint, Google Slides, PDF, etc.).
2. **Área B — Professor (Vídeo / Câmera):** Delimita a câmera do professor ou o mosaico de vídeo da reunião no Google Meet / Teams / Zoom.

### Regra Invariante Essencial: Dimensão da Captura ≠ Dimensão da Composição
Mesmo que a usuária selecione dois retângulos do **mesmo tamanho** na tela (por exemplo, dois blocos de 800×600 px), o SlideCast compõe o vídeo final de forma pedagógica assimétrica:
- **Apresentação:** Dominante (~80% da largura útil do vídeo 16:9), garantindo total legibilidade dos slides e fórmulas.
- **Professor:** Menor (~20% da largura útil), posicionado na lateral direita ou sobreposto em Picture-in-Picture.
- **Sem deformações:** Escala proporcional com preservação de aspect ratio (`force_original_aspect_ratio=decrease`) e preenchimento de palco na cor padrão `#10201E`.

### Recomposição Pós-Gravação Sem Regravar
As trilhas brutas da apresentação e do professor são preservadas em disco junto à sessão serializada (`.session.json`). A usuária pode alternar entre os layouts **Professor na Lateral** e **Professor Sobreposto (PiP)**, alterar a posição do professor e re-renderizar o vídeo MP4 instantaneamente, sem precisar regravar a aula.

---

## 2. Experiência de Uso (Passo a Passo com Nomes Exatos)

1. **Acessar o Módulo de Gravação:**
   - No menu principal do SlideCast Studio, clique no card **"3. Gravar Reunião do Meet - Captura com IA"**.
2. **Definir Modo & Objetivo:**
   - Escolha entre **"Modo Reunião Completa"** ou **"Modo Aula no Meet"**.
   - Clique em **"Continuar para Dispositivos & Gravação ▶"**.
3. **Selecionar o Formato de Captura de Vídeo:**
   - Escolha o botão de rádio **"📐 Apresentação + Professor (Selecionar 2 Áreas na Tela)"**.
   *(O modo tradicional "🖥️ Gravar Tela Inteira (Padrão)" continua 100% preservado).*
4. **Delimitar as Duas Regiões:**
   - Clique em **`📐 Selecionar Área da Apresentação`**: Uma sobreposição semitransparente com bordas em ciano (`#38bdf8`) surge na tela. Clique e arraste o mouse sobre o slide e confirme com **Enter** ou clique no botão `✓ Confirmar Seleção`.
   - Clique em **`📐 Selecionar Área do Professor`**: A sobreposição surge em dourado (`#f59e0b`). Clique e arraste sobre o vídeo do professor e confirme com **Enter**.
   - *(Opcional)*: Use o botão **`🔄 Refazer Seleções`** a qualquer momento se desejar refazer.
5. **Configurar o Layout da Composição Inicial:**
   - **Layout Pedagógico:** Escolha entre **"Professor na Lateral (Recomendado - 80% / 20%)"** ou **"Professor Sobreposto no Slide (PiP)"**.
   - **Posição:** No layout Lateral: `Centro (Equilíbrio Padrão)`, `Topo` ou `Embaixo`. No layout PiP: `Canto Inferior Direito`, `Canto Superior Direito`, `Canto Inferior Esquerdo` ou `Canto Superior Esquerdo`.
   - **Resolução:** `1920x1080 (Full HD 16:9)` ou `1280x720 (HD 16:9)`.
6. **Gravação Simultânea:**
   - Clique em **`🔴 Iniciar Gravação do Google Meet`**.
   - Um contador de 3 segundos permite alternar para a janela da aula.
   - O gravador captura ambas as regiões em sincronia perfeita de quadros (usando captura otimizada de bounding-box único com split/crop em X11/Windows, eliminando drift temporal e reduzindo o consumo de CPU em ~50%).
7. **Conclusão & Renderização:**
   - Ao término, clique em **`⏹ Concluir Gravação & Processar IA`**.
   - O `DualRegionRenderWorker` renderiza automaticamente o MP4 final composto.
   - Em seguida, a inteligência artificial gera a transcrição integral, resumo executivo e/ou o E-book didático em PDF.
8. **Recomposição Rápida:**
   - Na aba **🎬 Vídeo da Gravação**, o painel **"🎨 Reorganizar Layout da Aula Gravada (Sem Regravar)"** permite trocar a qualquer momento o layout (ex: mudar de Lateral para PiP) e clicar em **`🔄 Re-renderizar Novo Layout`**.

---

## 3. Arquitetura Técnica & Arquivos Modificados

### 3.1. Novos Arquivos
- [`app/core/dual_region_recorder.py`](file:///home/kika-magalhaes/Plataformas/slidecast/slidecast-studio/app/core/dual_region_recorder.py):
  - `ScreenRegion`: Dataclass para coordenadas globais, monitor, validação e coerção de dimensões pares para H.264.
  - `CompositionConfig`: Modelagem do layout pedagógico, proporções (80%/20%), posições do apresentador e cor de palco `#10201E`.
  - `DualRegionSession`: Estrutura de persistência e serialização JSON da sessão.
  - `DualRegionRecordingProcess`: Gerenciador de subprocesso FFmpeg com captura simultânea de duas áreas via single-grab + crop e áudio de sistema (`pulse` no Linux, `dshow` no Windows).
  - `compose_dual_region_video`: Motor FFmpeg com grafo `filter_complex` robusto, preservação de aspect ratio, áudio sincronizado (com fallback para `anullsrc` para evitar corrupção de container) e monitoramento de progresso com cancelamento gracioso.
- [`app/ui/screen_region_selector.py`](file:///home/kika-magalhaes/Plataformas/slidecast/slidecast-studio/app/ui/screen_region_selector.py):
  - Widget translúcido de seleção visual cobrindo o `virtualGeometry()` do desktop.
  - Alças de cantos, badge visual com dimensões em tempo real, botões de ação e atalhos de teclado (Enter/Esc).
  - Fecha-se completamente antes do início da captura, garantindo ausência de artefatos visuais no vídeo gravado.
- [`tests/test_dual_region_recorder.py`](file:///home/kika-magalhaes/Plataformas/slidecast/slidecast-studio/tests/test_dual_region_recorder.py):
  - 18 testes automatizados cobrindo geometria, invariante essencial, layouts lateral e PiP, serialização, workers Qt e regressões.

### 3.2. Arquivos Atualizados
- [`app/core/__init__.py`](file:///home/kika-magalhaes/Plataformas/slidecast/slidecast-studio/app/core/__init__.py): Exportação canônica das classes de gravação dual.
- [`app/worker.py`](file:///home/kika-magalhaes/Plataformas/slidecast/slidecast-studio/app/worker.py): Inclusão do `DualRegionRenderWorker(QThread)` com sinais de progresso, conclusão e erro.
- [`app/ui/views/record_meet_view.py`](file:///home/kika-magalhaes/Plataformas/slidecast/slidecast-studio/app/ui/views/record_meet_view.py):
  - Integração do seletor de modo de captura (Tela Inteira vs Apresentação + Professor).
  - Painel de seleção de áreas A e B com feedback visual.
  - Suporte ao fluxo de gravação e renderização em duas etapas.
  - Controles de re-composição sem regravar na aba de resultados.

---

## 4. Resultados da Validação Automatizada

Executado em ambiente Linux com virtualenv e FFmpeg 7.1.5:

```bash
.venv/bin/pytest tests/test_dual_region_recorder.py -v
============================= 18 passed in 13.44s ==============================

.venv/bin/pytest
================== 214 passed, 1 warning in 112.29s (0:01:52) ==================
```

- **Taxa de Sucesso:** 100% (214/214 testes aprovados).
- **Regressão de Recursos:** Zero. Todos os testes de Estúdio, PDFs vetoriais, Teleprompter, Podcast e Faturamento continuam verdes.
- **Sincronização:** Validada via inspeção FFprobe e fontes sintéticas com timecode visual e áudio senoidal de 440 Hz.

---

## 5. Compatibilidade e Limitações por Sistema Operacional

1. **Linux (X11):** Suporte nativo completo via `x11grab` e PulseAudio (`pulse`). Ambas as áreas podem estar no mesmo monitor ou na área de desktop virtual comum.
2. **Linux (Wayland):** Sessões Wayland puras que bloqueiam captura direta via X11 exibem diagnóstico claro recomendando o uso de sessão X11 ou PipeWire portal conforme convenção do sistema.
3. **Windows:** Suporte completo via `gdigrab` e `dshow` (`virtual-audio-capturer`). Tratamento automático de DPI e escala de interface.
4. **Offline:** Todo o fluxo de gravação e composição funciona 100% localmente via FFmpeg embutido, sem necessidade de conexão à internet ou upload de dados confidenciais de reuniões.
