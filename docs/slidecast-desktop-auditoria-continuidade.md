# Auditoria de Continuidade — SlideCast Studio Desktop

**Data:** 18 de Novembro de 2026  
**Responsável:** Muse / Agi (Engenharia de Mídia, Backend, Arquitetura e Empacotamento)  
**Destinatários:** Kika Magalhães / Codex (Design, UX/UI, Temas e Landing Page)  
**Repositório Alvo:** `slidecast/slidecast-studio`  
**Branch de Trabalho:** `feat/multitrack-multimedia-desktop` (baseada em `main` commit `7f02cfb`)  

---

## 1. Contexto e Decisão Estratégica

O SlideCast passou historicamente por duas frentes de desenvolvimento: uma versão **web** (FastAPI + React/TypeScript/Vite) e uma versão **desktop** (Python/PySide6 + FFmpeg). A estratégia atual define:

1. **SlideCast Studio Desktop é o produto principal**, instalável e executável localmente em Linux e Windows, oferecendo estúdio completo de gravação de aulas, apresentações, podcast, materiais didáticos e o novo **Criador de Vídeos Multimídia**.
2. **A presença web será uma landing page comercial** voltada a apresentar o produto, vender e disponibilizar os downloads dos instaladores para Windows e Linux (design e frontend a cargo do Codex).
3. **Não haverá estúdio web como produto concorrente**. Porém, nenhuma infraestrutura legada, banco de dados, usuários, histórico ou faturamento (Stripe) será apagado; a desativação do editor no navegador é planejada de forma reversível e protegida por rotas/flags.
4. **Nenhuma dependência de rede ou IA é obrigatória** para o Criador de Vídeos Multimídia nem para a landing page. O funcionamento principal de criação, mixagem e renderização é 100% local via FFmpeg e Python. Recursos opcionais legados de IA no desktop são preservados para quem possuir chaves de API, sem bloquear quem não as tiver.

---

## 2. Inspeção Real dos Repositórios e Árvores de Trabalho

### 2.1 Identificação dos Diretórios e Commits

Durante a fase zero de auditoria, foram examinados:
- **Repositório Canônico:** `/home/kika-magalhaes/Plataformas/slidecast/slidecast-studio`
  - Git Remote: `origin -> https://github.com/kikamagalhaes/slidecast-studio`
  - Branch ativa: `main` (rastreada a `origin/main`), sem alterações não commitadas pendentes (exceto `storage/`).
  - HEAD no momento da auditoria: `7f02cfb` (*"Web: optional dark theme with saved preference"*).
  - Tags relevantes: `v1.0.0` (`01eda8e`), `v1.1.0` (`e36cef8`), `v1.1.1` (`8be87b2`).
- **Diretório Histórico Identificado:** `/home/kika-magalhaes/.local/share/Trash/files/VideosCreate`
  - Movido para a lixeira em `2026-11-13T15:08:56` a partir de `Plataformas/StudioKika/VideosCreate`.
  - Branch anterior: `feat/studio-gravacao-web-desktop` no commit `2288c01` (*"Fix camera aspect (cover/contain), paginate long bible passages, move teleprompter above Program"*).
  - Continha alterações não commitadas de testes de gravação ao vivo, visualização de estúdio e arquivos de podcast/capas.

### 2.2 Comparação entre Forks e Histórico de Convergência

Ao comparar os dois diretórios, constatou-se que em **13 de Novembro de 2026**:
1. O repositório `slidecast-studio` já havia incorporado e mesclado a branch de paridade de estúdio (`7883dc1` e `e36cef8`).
2. Os avanços de podcast (capas com título/autor, geração de ondas, formatos quadrado/widescreen, áudio pré-gravado) desenvolvidos no fork `VideosCreate` foram commitados no repositório `slidecast-studio` nos commits `4e00e01`, `04df53a`, `a395391` e `7f02cfb`.
3. O tema claro padrão KikaMeet foi restabelecido como padrão no desktop (`04df53a`), alinhando a identidade visual entre as plataformas.
4. O diretório `VideosCreate` foi consequentemente descartado para a lixeira pela usuária em 13/11/2026 às 15:08, pois seu trabalho havia sido devidamente consolidado no `slidecast-studio`.

### 2.3 Declaração da Fonte da Verdade

> **A árvore de código em `/home/kika-magalhaes/Plataformas/slidecast/slidecast-studio` é declarada a FONTE ÚNICA DA VERDADE para o SlideCast Studio Desktop e para a transição web.**

**Justificativa com evidências reproduzíveis:**
1. Contém o histórico completo e linear do projeto até `7f02cfb`.
2. A suíte automatizada existente (169 testes unitários e de integração cobrindo core, web API, filas Redis, billing Stripe, estúdio, capas e gravação) passa integralmente com 100% de sucesso (`169 passed in 43.52s`).
3. O comando `--self-test` do desktop (`main.py`) executa com código de saída 0 (`SELF-TEST OK`) após a instalação das dependências declaradas.
4. O diretório alternativo `VideosCreate` está na lixeira do sistema operacional (`~/.local/share/Trash/files/VideosCreate`), com deleção registrada em 13/11/2026, confirmando seu papel de workspace descartado pós-consolidação.

---

## 3. Matriz de Componentes e Decisões

| Módulo / Funcionalidade | Estado Atual no Repositório | Ação Estratégica | Justificativa |
|---|---|---|---|
| **Núcleo FFmpeg (`ffmpeg_utils.py`)** | Detecta ffmpeg/ffprobe em PATH, app dir e env vars; execução cancelável | **Preservar e Ampliar** | Base estável e confiável para execução multiplataforma. Será estendido com probe de vídeo (`inspect_video`). |
| **Criador de Vídeo PDF (`video_generator.py`)** | Concat demuxer de imagens de slides + áudio único | **Preservar (Legado) e Expandir** | Manter compatibilidade com projetos legados de 1 áudio; introduzir novo builder multitrack sem quebrar o anterior. |
| **Criador de Vídeo Multimídia (`multitrack_video_builder.py`)** | Não existia | **Novo (P0)** | Aceita visual PDF ou MP4 + até 4 faixas de áudio independentes com volume, mute e offset, mixagem sem clipping (`amix` + `alimiter`). |
| **Modelo de Projeto Multimídia (`multitrack.py`)** | Não existia para multitrack (havia apenas schema v1 de gravação em `studio.py`) | **Novo (P0)** | Dataclasses `AudioTrack`, `VideoInfo`, `MultimediaProject` com persistência JSON, schema v2 e retrocompatibilidade com v1. |
| **Processador de Áudio (`audio_processor.py`)** | Mutagen + fallback ffprobe, retorna `AudioInfo` | **Preservar e Reutilizar** | Decodifica e probe com precisão; suporta MP3, WAV, M4A, AAC, OGG, FLAC. |
| **Sincronização de Slides (`slide_timing.py`)** | Cálculo proporcional, uniforme e por roteiro; sem IA | **Preservar e Reutilizar** | Respeita tempos manuais e travas do usuário sem distorção secreta. |
| **Estúdio de Gravação (`studio.py`, `record_class_view.py`)** | 3 slots de PDF, cenas (Slides, Bíblia, Quadro, Brainstorm, Quiz), PiP, caneta temporária/permanente | **Preservar Intacto** | Funcionalidade central de gravação já consolidada e testada; não regredir. |
| **Podcast Desktop (`record_podcast_view.py`, `podcast_cover.py`)** | Capas prontas, upload de arte, título/autor com Pillow, exportação com forma de onda | **Preservar Intacto** | Recurso maduro adicionado nas versões 1.1.0/1.1.1; mantém operação desktop. |
| **Gravação de Reuniões (`record_meet_view.py`, `meeting_recorder.py`)** | Captura de tela x11/dshow + áudio | **Preservar Intacto** | Recurso operacional no desktop; sem alterações. |
| **Materiais Didáticos (`generate_materials_view.py`, `ebook_generator.py`)** | Diagramação de cards e apostilas | **Preservar Intacto** | Funcionalidade opcional local; sem alterações de escopo. |
| **IA Opcional (`ai_synchronizer.py`, `gemini_client.py`)** | Gemini, ElevenLabs, Replicate | **Preservar Opcional** | Não é requerida para criar vídeos nem para a landing page. Usuários com chave continuam podendo usar; sem chave não bloqueia nada. |
| **Web API / Servidor (`app/web/server.py`, `db.py`, `auth.py`)** | FastAPI, SQLite WAL, Stripe billing, filas de render | **Isolar Reversivelmente** | Não apagar rotas nem banco; preparar para a landing page assumir `/` enquanto rotas do estúdio ficam isoladas por configuração. |
| **Frontend Web Legado (`app/web/templates/`, `static/`, `frontend/`)** | React/Vite Studio e templates antigos | **Preservar Arquivado** | Fica preservado no repositório; o Codex criará a landing page comercial. |
| **Empacotamento Desktop (`slidecast.spec`, `scripts/fetch_ffmpeg.py`)** | PyInstaller one-dir bundle, Linux/Windows | **Preservar e Revalidar** | Self-test aprovado; pronto para gerar bundles quando acionado. |

---

## 4. Mapeamento do Fluxo Atual de “Criar Vídeo” e Pontos de Faixa Única

### 4.1 Onde existia a premissa de áudio único
Na implementação anterior:
1. **Interface (`main_window.py`):**
   - Havia um único `DropAreaWidget` para áudio (`self.audio_drop`), guardando `self.audio_info: Optional[AudioInfo]`.
   - O balanceamento de tempo assumia `self.audio_info.duration`.
2. **Worker (`app/worker.py`):**
   - `VideoRenderWorker.__init__` recebia um único parâmetro `audio_path: str`.
3. **Gerador de Vídeo (`app/core/video_generator.py`):**
   - Assumia uma única entrada `-i audio_path`, combinando diretamente com o demuxer de imagens.
4. **Projeto / Persistência:**
   - Não havia arquivo de projeto para o criador de vídeo simples (apenas campos soltos na memória da janela); o projeto salvo em disco existia apenas para o módulo de estúdio (`studio.py`).

### 4.2 Arquitetura da Solução Multitrack e Multimídia
A nova arquitetura introduz:
- Suporte a duas modalidades de fonte visual: **PDF** (slides com tempos) ou **MP4** (vídeo mudo ou com áudio ignorado).
- Camada de áudio multitrack independente: até 4 faixas com metadata probada, ganho (`volume`), `mute` e `offset` temporal.
- Pipeline único de mixagem em FFmpeg:
  - Todas as faixas passam por normalização de taxa de amostragem (`44100Hz`, estéreo float).
  - Atraso de entrada configurado via `adelay=delays={ms}:all=1`.
  - Ganho ajustado via `volume={vol}` (volume 0.0 quando mutado).
  - Recorte exato no tempo final do vídeo via `atrim=0:{dur},apad=whole_dur={dur}`.
  - Mixagem via `amix=inputs={N}:duration=first:dropout_transition=0:normalize=0` e limitador de pico `alimiter=limit=0.99` para proteção contra distorção e clipping.
  - Caso todas as faixas estejam mutadas ou nenhuma faixa seja provida: sintetização determinística de faixa silenciosa (`anullsrc=channel_layout=stereo:sample_rate=44100`).
- Suporte a projeto recuperável (`.slidecast` em formato JSON) com schema versionado e retrocompatibilidade.
- `MultimediaRenderWorker` em `QThread` com cancelamento real e progresso sem travamento da interface.

---

## 5. Dependências, Portas e Contratos Técnicos

### 5.1 Dependências de Sistema e Pacotes
- **FFmpeg / FFprobe:** Versão 6.1.1 (ou superior), com suporte a decodificação de MP3, WAV, AAC, M4A, OGG, FLAC, WebM e codificação em `libx264` + `aac`.
- **Python:** 3.12+ com PySide6, PyMuPDF, mutagen, pillow.
- **Empacotamento:** PyInstaller 6.22.3 + `imageio-ffmpeg` para bundling de binários FFmpeg quando empacotado.

### 5.2 Portas e Infraestrutura
- Porta **8000**: API local FastAPI (ambiente de desenvolvimento/servidor).
- Porta **5173**: Vite dev server (`strictPort`, proxy `/api` -> `8000`).
- Porta **6379**: Redis interno para filas (sem exposição externa).
- Traefik em portas **80 / 443**: Mantido conforme convenção de produção em VPS, sem subida de proxies concorrentes.
- Nenhuma operação de rede externa é acionada na criação de vídeos local.

---

## 6. Critérios de Aceitação e Procedimento de Rollback

### 6.1 Critérios de Aceitação
1. **Regressão Zero:** Os 169 testes legados do repositório continuam passando integralmente.
2. **Cenários T01 a T18:** Testes reais executados com FFmpeg e PySide6 offscreen cobrindo todas as combinações de PDF/MP4 e 1 a 4 faixas.
3. **Contratos Documentados:** Contrato de dados e métodos em inglês disponibilizado para o Codex em `docs/slidecast-editor-contract.md`.
4. **Isolamento Web:** Plano de transição documentado em `docs/slidecast-web-transicao-comercial.md` sem perda de dados históricos.
5. **Auto-diagnóstico:** `python main.py --self-test` retornando código 0.

### 6.2 Procedimento de Rollback
Como todo o trabalho de implementação do criador multimídia é realizado na branch isolada `feat/multitrack-multimedia-desktop`:
- Para reverter qualquer alteração e retornar ao estado original anterior, basta executar:
  ```bash
  git checkout main
  ```
- Nenhuma modificação destrutiva em banco de dados, storage ou arquivos de produção foi realizada.
