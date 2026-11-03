# 00 — Inventário-base do SlideCast Studio (antes da migração sem IA)

> Documento de partida exigido pela seção 8 do prompt
> `Prompt_Muse_SlideCast_Web_Sem_IA.md` (232 linhas, lido integralmente).
> Registra **o que existe, o que reutilizar, o que substituir, as dependências
> de IA encontradas e as decisões** — sem inventar contratos internos.
> Nenhum código foi alterado nesta etapa; o prompt original não foi tocado.

## 0. Proveniência e método

| Item | Valor verificado |
| --- | --- |
| Workspace | `/home/kika-magalhaes/Plataformas/slidecast` (só tinha o prompt) |
| Repositório | `https://github.com/kikamagalhaes/slidecast-studio` |
| Destino do clone | `/home/kika-magalhaes/Plataformas/slidecast/slidecast-studio` |
| Commit obtido | `01eda8e708332c84849d637b61c9af5c46b4c2da` — **idêntico** ao commit citado na seção 1 do prompt (`git ls-remote HEAD` + `git log --oneline -5`: `01eda8e CI: pin ubuntu-24.04 + pulseaudio libs for bundle smoke`) |
| Estado inicial | `git status --short --branch` → `## main...origin/main`, árvore limpa; nenhuma alteração local a preservar |
| Acesso | Clone HTTPS anônimo funcionou (repositório público). `gh auth status` falha (`token ... is invalid` em `~/.config/gh/hosts.yml`, conta `kikamagalhaes`) — irrelevante para o clone, mas a registrar se pushes via `gh` forem necessários |
| Método | Leitura integral dos corpos principais citados na seção 1 do prompt: `app/core/*`, `app/web/*`, `app/worker.py`, `main.py`, `Dockerfile`, `compose.production.yml`, `entrypoint.sh`, `run_web.sh`/`run_worker.sh`/`run.sh`, `requirements*.txt`, `pyproject.toml`, `.env.example`, `DEPLOY.md`, `README.md`, `.github/workflows/ci.yml`, frontend (`templates/index.html`, `static/app.js`) e listagem de `tests/` |
| Limite | Análise **estática**: nada foi executado nem certificado (mesma ressalva do prompt). Testes não foram rodados nesta etapa |

Comandos executados (evidência):

```bash
ls -la /home/kika-magalhaes/Plataformas/slidecast/
gh auth status                                   # token inválido (ver acima)
git ls-remote https://github.com/kikamagalhaes/slidecast-studio HEAD
# -> 01eda8e708332c84849d637b61c9af5c46b4c2da  HEAD
git clone https://github.com/kikamagalhaes/slidecast-studio \
  /home/kika-magalhaes/Plataformas/slidecast/slidecast-studio
git -C slidecast-studio log --oneline -5
git -C slidecast-studio status --short --branch
find . -type f -not -path './.git/*' | sort      # 100 arquivos
wc -l app/core/*.py app/web/*.py app/worker.py main.py
grep -rn "gemini|openai|elevenlabs|replicate|pollinations|edge_tts|google.genai" ...
```

## 1. O que existe (estado real em `01eda8e`)

### 1.1 Visão geral

- **100 arquivos** versionados (fora `.git/`), Python 3.12, duas frentes:
  desktop PySide6 (`main.py` + `app/ui/`) e web FastAPI (`app/web/`).
- Núcleo compartilhado em `app/core/` (18 módulos, ~3.900 linhas), web em
  `app/web/` (10 módulos + `static/` + `templates/`, ~2.350 linhas),
  desktop em `app/ui/` (~4.500 linhas), `tests/` com 19 arquivos.
- **Não existe** frontend React/TypeScript/Vite, pasta `docs/`, migrações
  versionadas de banco, nem rotas de projetos/gravações/legendas/modelos
  além do fluxo PDF+áudio (ver §5). A web atual confirma a descrição do
  prompt: concentra-se em PDF + áudio.

### 1.2 `app/core/` — módulo a módulo

| Arquivo | Linhas | O que faz (verificado no corpo) | IA? |
| --- | --- | --- | --- |
| `pdf_processor.py` | 118 | `inspect_pdf`, `render_thumbnail`, `render_all_slides_to_dir` via PyMuPDF; dataclasses `SlideInfo`/`PresentationInfo`; suporta `progress_callback`/`cancel_check` | Não |
| `audio_processor.py` | 92 | `get_audio_info`: mutagen primeiro, fallback ffprobe; `AudioInfo` com duração/sample-rate/canais | Não |
| `ffmpeg_utils.py` | 133 | `get_ffmpeg_paths` (PATH, `FFMPEG_PATH`/`FFPROBE_PATH`, dirs do app), `run_process_cancellable`, `format_duration`, `get_video_duration` | Não |
| `video_generator.py` | 168 | `generate_video`: concat demuxer + `scale/pad/format=yuv420p`, libx264/AAC, `-progress pipe:1`, cancelamento por terminate/kill, stderr em temp file | Não |
| `slide_timing.py` | 77 | Puro, sem Qt: `calculate_slide_durations_from_script` — marcadores `[Slide N]` ponderados por palavras → parágrafos 1:1 → uniforme; `MIN_SLIDE_SECONDS=1.5`, `ABSOLUTE_MIN_SECONDS=0.5`, `_normalize` força soma = total | Não |
| `class_video_builder.py` | 770 | `build_class_video` + cards de abertura/encerramento (PyMuPDF), `normalize_video_clip`, PIP de apresentador, BGM, SRT queimado, formatos 16:9/9:16. **Sem import de IA** | Não |
| `podcast_video_builder.py` | 147 | `build_podcast_video`: capa + `showwaves`, mix com BGM; **importa `generate_subtitles_with_gemini`** para legendas opcionais | **Sim (acoplado)** |
| `image_generator.py` | 315 | `generate_slide_image`: DALL·E 3 (se chave) → **Pollinations/Flux remoto mesmo sem chave** → card local PyMuPDF → fallback Qt (`QImage`). `enhance_*_prompt_with_gemini`, `create_pdf_from_images` | **Sim** |
| `ebook_generator.py` | 358 | `generate_class_ebook`: diagramação A4 PyMuPDF **após** `_generate_ebook_content_with_gemini`; sem chave cai em `default_data` genérico (ver §4.3); texto em caixa fixa de 240pt (risco de overflow citado no prompt) | **Sim** |
| `meeting_recorder.py` | 425 | Captura desktop FFmpeg (`x11grab`/`gdigrab`+pulse/dshow, PIP de câmera), parsers `pactl`/`dshow` puros e testáveis; `generate_meeting_notes` via Gemini com fallback genérico; `extract_audio_from_video` | **Sim (notas)** |
| `avatar_video_generator.py` | 475 | `generate_avatar_speech` (ElevenLabs IVC → Edge-TTS), `generate_replicate_lipsync` (Lipsync-2/Wav2Lip), `render_local_cadence_avatar` (silencedetect + overlay por pausas), `composite_avatar_with_slide` | **Sim** |
| `ai_synchronizer.py` | 151 | `synchronize_slides_with_gemini`: sobe áudio ao Gemini Files API, pede JSON de durações, normaliza p/ total | **Sim (puro IA)** |
| `subtitles_generator.py` | 114 | `generate_subtitles_with_gemini`: transcrição/tradução SRT via Gemini (9 idiomas) | **Sim (puro IA)** |
| `voice_dictation.py` | 38 | `transcribe_voice_prompt` via Gemini | **Sim (puro IA)** |
| `gemini_client.py` | 86 | `generate_with_fallback` + `get_client` (`google.genai`); lista `DEFAULT_GEMINI_MODELS`, override `GEMINI_MODELS` | **Sim (infra IA)** |
| `config_manager.py` | 138 | `~/.config/slidecast/config.json` (ou `%APPDATA%`); getters/setters de chaves Gemini/OpenAI/ElevenLabs/Replicate, `image_provider`, `avatar_engine`, clone ativo; env tem precedência | **Sim (chaves)** |
| `clone_manager.py` | 198 | CRUD de clones em disco (FFmpeg extrai voz 16kHz + frame de rosto); sem chamada remota na criação | Não (mas alimenta avatar IA) |
| `logging_config.py` | 44 | `setup_logging` via `LOG_LEVEL` | Não |

`app/core/__init__.py` exporta apenas o núcleo sem IA
(`ffmpeg_utils`, `pdf_processor`, `audio_processor`, `video_generator`) —
bom sinal de separação já existente.

### 1.3 `app/web/` — API atual (contratos reais, `server.py`, 608 linhas)

Aplicação FastAPI única (`app.web.server:app`), templates Jinja2 +
`static/app.js` (465 linhas) + `style.css`. Rotas existentes:

| Rota | Auth | Observação |
| --- | --- | --- |
| `GET /` | — | `index.html` com `has_api_key` |
| `GET /api/health` | — | ffmpeg + disco livre (`HEALTH_MIN_DISK_MB`) + `pending_jobs` |
| `GET /api/config/key` | — | status mascarado da chave Gemini |
| `POST /api/config/key` | `X-Admin-Token` se `ADMIN_TOKEN` definido | grava chave Gemini via `set_gemini_api_key` |
| `POST /api/auth/register` `POST /api/auth/login` `POST /api/auth/logout` `GET /api/auth/me` | sessão | cookie HttpOnly `samesite=lax`, `secure` por env |
| `POST /api/billing/checkout` `POST /api/billing/portal` `POST /api/billing/webhook` | sessão/webhook | Stripe (`stripe_billing.py`) |
| `POST /api/upload` | sessão + plano | PDF+áudio juntos; nomes fixos em disco (`slides.pdf`, `audio<ext>`); valida assinatura `%PDF-`, inspeção e metadados; já devolve durações uniformes padrão |
| `GET /api/projects/{id}/thumbnail/{i}` | dono | PNG com cache em `thumbs/` |
| `POST /api/projects/{id}/ai-sync` | sessão + plano | **rota de IA**: `synchronize_slides_with_gemini` |
| `POST /api/projects/{id}/render` | sessão + render guard | valida durações/resolução/fps, enfileira |
| `GET /api/jobs/{id}` `DELETE /api/jobs/{id}` | dono | status/progresso real; cancelamento |
| `GET /api/jobs/{id}/video` `GET /api/jobs/{id}/download` | dono | `FileResponse` MP4 |

Sustentação verificada:

- `app/web/db.py` (94): SQLite em `storage/slidecast.db`, WAL, tabelas
  `users`, `sessions`, `subscriptions`, `ownership`, `usage`,
  `webhook_events`. **Sem migrações versionadas** (`CREATE TABLE IF NOT EXISTS`).
- `app/web/auth.py` (220): hash de senha, sessões por token hasheado,
  `current_user`, `cookie_secure()`, `SESSION_DAYS`/`TRIAL_DAYS`.
- `app/web/billing.py` (269) + `stripe_billing.py` (237): trial 14 dias,
  `PLAN_MONTHLY_RENDERS=30`, guards de plano/render, `owns()` por
  `(kind, object_id)`, idempotência de webhook. Cobrança **existe e está
  ligada** às rotas — o prompt manda preservar sem ampliar.
- `app/web/validation.py` (151): puro/testável — UUID4 de projeto,
  contenção de path, extensões de áudio (`.mp3 .wav .m4a .aac .ogg .flac
  .wma` — **sem `.webm`**), durações 0.1–7200s, resolução par ≤3840, fps 1–60.
- `app/web/queue_manager.py` (245): fila em memória, 1 render por vez,
  estados `queued/rendering/completed/failed/cancelled`, retenção
  `JOB_RETENTION_HOURS`, teto `MAX_JOBS=200`.
- `app/web/redis_queue.py` (269): backend Redis/RQ com a **mesma interface**,
  `result_ttl`/`failure_ttl` de `JOB_RESULT_TTL_HOURS`, timeout
  `RQ_JOB_TIMEOUT`, cancelamento via `meta[cancel_requested]`.
- `app/web/render_task.py` (167): pipeline único `run_render_pipeline`
  (slides 0–25% → FFmpeg 25–100%) usado pelos dois backends;
  `render_job_task` é o entrypoint RQ.
- `app/web/rate_limit.py` (85): limite em processo por IP+endpoint.
- Frontend atual: 3 passos (upload → sincronização manual/IA → exportar
  1080p/720p/4K/quadrado), modal de chave Gemini, polling de job.
  **Sem** navegação lateral do estúdio, editor, gravação ou biblioteca.

### 1.4 Desktop (`app/ui/`, `main.py`, `app/worker.py`)

- `main.py`: `QApplication` + `--self-test` headless (importa
  `google.genai`, `edge_tts`, `replicate` como requisito do bundle).
- `app/ui/`: `main_window.py` (945), views de aula/reunião/podcast/materiais,
  `class_panels.py`, diálogos de avatar/capa/fundo, `teleprompter_widget.py`,
  `floating_camera_widget.py` (QtMultimedia), `voice_prompt_button.py`.
- `app/worker.py` (139): `QThread`s `VideoRenderWorker`/`AISyncWorker` —
  **duplica** o pipeline de `render_task.py` no desktop (Qt).

### 1.5 Docker, scripts e testes

- `Dockerfile`: `python:3.12-slim` + ffmpeg/libgl; instala
  `requirements-web.txt`; `EXPOSE 8000`; `CMD ./entrypoint.sh`.
- `entrypoint.sh`: uvicorn com `UVICORN_WORKERS`/`PORT`/
  `PROXY_HEADERS`/`FORWARDED_ALLOW_IPS` por env.
- `compose.production.yml`: serviços `web` (Traefik `websecure`+
  letsencrypt, `expose 8000`, volume `./storage`), `worker`
  (`rq worker ... slidecast`), `redis:7-alpine` (volume `redis-data`,
  **sem** `appendonly` explícito). Passa `GEMINI_API_KEY` p/ web e worker.
- `DEPLOY.md`: rsync p/ VPS `179.199.133.126`, domínio
  `slidecast-179-199-133-126.sslip.io` — IPs/domínio **não reutilizar
  automaticamente** (seção 5 do prompt).
- `.env.example`: 40+ variáveis (fila, rate limit, billing, Stripe,
  `GEMINI_API_KEY`, `GEMINI_MODELS`, `EDGE_TTS_TIMEOUT`, captura desktop).
- `run_web.sh` (uvicorn `--reload` :8000), `run_worker.sh` (RQ local),
  `run.sh`/`run.bat` (desktop).
- `.github/workflows/ci.yml`: job web (`requirements-web+dev`, ruff,
  `pytest -q`) + `desktop-smoke` (Qt offscreen); `release.yml` empacota
  desktop (win/mac/linux) com PyInstaller (`slidecast.spec`,
  `scripts/fetch_ffmpeg.py`).
- `tests/` (19 arquivos, ~2.240 linhas): `test_slide_timing`,
  `test_pdf_processor`, `test_audio_ffmpeg`, `test_web_api` (pipeline real
  com ffmpeg, sem chave Gemini), `test_auth`, `test_billing` (440),
  `test_redis_queue` (fakeredis), `test_queue_cancel`, `test_validation`,
  `test_rate_limit`, `test_capture_devices`, `test_meeting_notes`,
  `test_class_cards`, `test_clone_manager`, `test_config_manager`,
  `test_gemini_client`, `test_avatar_tts`, `test_desktop_smoke`.

### 1.6 Dependências (`requirements*.txt`, `pyproject.toml`)

| Arquivo | Conteúdo | Problema p/ web sem IA |
| --- | --- | --- |
| `requirements-base.txt` | `pymupdf`, `mutagen`, **`google-genai==2.25.0`** | SDK de IA **obrigatório** na base compartilhada — viola a seção 2.4 do prompt |
| `requirements-web.txt` | base + fastapi, uvicorn, python-multipart, jinja2, aiofiles, rq, redis, **stripe** | Herda `google-genai` via base |
| `requirements.txt` (desktop) | base + PySide6, requests, **edge-tts, replicate** | Correto ficar no desktop/legado, fora da web |
| `requirements-dev.txt` | pytest, ruff, httpx, fakeredis | OK |
| `requirements-packaging.txt` | pyinstaller, imageio-ffmpeg | OK (só empacotamento) |
| `pyproject.toml` | pytest `testpaths=tests`; ruff `E9,F`, line-length 100, py312 | OK |

## 2. O que reutilizar (manter/adaptar, sem IA)

Direção conforme a tabela da seção 1 do prompt, confirmada no código:

1. **Núcleo de mídia sem Qt/IA** — `pdf_processor.py`, `audio_processor.py`,
   `ffmpeg_utils.py`, `video_generator.py`: manter como estão na web;
   são independentes de interface e já têm progresso/cancelamento.
2. **`slide_timing.py`** — reutilizar como base das estimativas por roteiro.
   Revisar invariantes antes de expor: hoje `_proportional` impõe mínimo
   de 1.5s e `_normalize` **corrige o resíduo no último slide** e força a
   soma ao total — o prompt (seção 3.2) exige tratar duração insuficiente,
   travas e erro explícito em vez de corrigir silenciosamente. Faltam:
   pesos com trechos travados, distribuição uniforme como modo nomeado,
   importação/exportação de tabela de tempos.
3. **`class_video_builder.py`** — reutilizar composição (cards, PIP,
   trilhas, vinhetas, SRT). Já é 100% FFmpeg/PyMuPDF. Extrair do uso
   exclusivo desktop e ligar aos serviços web.
4. **`podcast_video_builder.py`** — reutilizar montagem/`showwaves`;
   **cortar** o import de `subtitles_generator` (legendas passam a ser
   fornecidas/editadas pelo usuário).
5. **Parte gráfica local de `image_generator.py`** — o card PyMuPDF
   (3º estágio de `generate_slide_image`) e `create_pdf_from_images`
   viram a implementação direta de capas/slides por modelo, sem rede.
6. **Diagramação de `ebook_generator.py`** — capa/capítulos/paginação
   PyMuPDF reutilizáveis após separar da geração textual; corrigir a
   caixa fixa (240pt) para paginação dinâmica (seção 3.5 do prompt).
7. **Parsers puros de `meeting_recorder.py`** (`parse_pactl_*`,
   `parse_dshow_devices`, `list_linux_cameras`) — úteis só no desktop;
   a captura em si migra para APIs do navegador (novo código web).
8. **Parte por cadência de `avatar_video_generator.py`** —
   `detect_audio_silences` (silencedetect) e
   `render_local_cadence_avatar`/`composite_avatar_with_slide` são
   composição convencional reutilizável, rotulada “Animação por ritmo”.
9. **Web existente** — `server.py` (upload/thumbnail/render/jobs com
   propriedade), `validation.py`, `db.py`/`auth.py`, filas
   (`queue_manager`/`redis_queue`/`render_task`), `rate_limit.py`:
   evoluir, preservando autenticação, dados e contratos necessários.
10. **Billing Stripe** — `billing.py`/`stripe_billing.py` e tabelas:
    preservar dados e regras; não ampliar nem testar cobrança real.
11. **Infra** — `Dockerfile`, `entrypoint.sh`, compose com Traefik,
    healthcheck ffmpeg/disco, CI (ruff+pytest) e a suíte de testes atual
    como rede de regressão (em especial `test_web_api`, `test_slide_timing`,
    `test_redis_queue`, `test_queue_cancel`, `test_billing`, `test_auth`).

## 3. O que substituir / remover do caminho web

| Hoje | Substituição (prompt) |
| --- | --- |
| `POST /api/projects/{id}/ai-sync` + botão “Sincronizar com IA (Gemini)” | Modos determinísticos: gravar avançando slides, áudio por slide, “Ouvir e marcar trocas”, estimativa pelo roteiro, divisão uniforme (§3.1/3.2) |
| `GET/POST /api/config/key` + modal de chave no frontend | **Remover rota e UI**; sem configuração de chave de IA (§2.3) |
| Transcrição/tradução Gemini (`subtitles_generator`) | Importar/editar SRT/VTT fornecidos; rascunho estimado rotulado a partir do roteiro (§3.5) |
| `ai_synchronizer`, `voice_dictation` | Sem equivalente: funcionalidade sai do produto web |
| Geração remota de imagem (DALL·E/Pollinations) e “aprimorar prompt” | Editor por modelos com imagens enviadas e composição local (§3.5) |
| Conteúdo de apostila/ata gerado por Gemini | Textos/anotações cadastrados por slide; ata só com campos preenchidos (§3.3/3.5) |
| Captura desktop (`meeting_recorder.ScreenRecordingProcess`, QtMultimedia) | `getUserMedia`/`getDisplayMedia`/`MediaRecorder` no navegador + envio incremental (§3.3) |
| TTS/clone de voz e lipsync (`avatar_video_generator` partes IA, `clone_manager` como “clone”) | Narração gravada/importada; apresentador = vídeo gravado, imagem estática ou “Animação por ritmo” (§3.5) |
| Frontend Jinja/JS atual (3 passos PDF+áudio) | React + TypeScript + Vite servido na mesma origem, navegação lateral do estúdio (§3/4.1) — **ainda inexistente** |
| `app/worker.py` (QThread) no caminho web | Nada: web já usa `render_task.py`; manter Qt só no desktop |
| Fallbacks genéricos (ver §4.3) | Campo vazio ou modelo a preencher; nunca fato inventado (§1/2.5) |

Separação sem quebrar o desktop (§2.4): os módulos de IA continuam
existindo para o desktop legado, mas **saem das dependências e dos
imports do caminho web**. Nada de apenas esconder a interface.

## 4. Dependências de IA encontradas (auditoria)

### 4.1 Imports e chamadas (código)

| Origem | Destino de IA | Evidência |
| --- | --- | --- |
| `app/core/gemini_client.py` | Google Gemini (`google.genai`, import local em `get_client`) | `from google import genai`; modelos `gemini-3.8-flash`, `gemini-3-flash-preview`, `gemini-2.5-flash`, `gemini-flash-latest` |
| `app/core/ai_synchronizer.py` | Gemini (upload de áudio + `generate_content`) | importa `gemini_client`, `get_gemini_api_key`; `from google import genai` |
| `app/core/subtitles_generator.py` | Gemini (transcrição/tradução) | idem |
| `app/core/voice_dictation.py` | Gemini (transcrição de comando de voz) | idem |
| `app/core/ebook_generator.py` | Gemini (`_generate_ebook_content_with_gemini`) | idem; upload opcional do áudio da aula |
| `app/core/meeting_recorder.py` | Gemini (`generate_meeting_notes`) | idem |
| `app/core/image_generator.py` | Gemini (enhance de prompt) + **OpenAI DALL·E 3** (`api.openai.com/v1/images/generations`) + **Pollinations/Flux** (`image.pollinations.ai/prompt/...`, **sem chave**) | `urllib.request` direto; fallback local só depois da rede |
| `app/core/podcast_video_builder.py` | Gemini via `subtitles_generator` | `from app.core.subtitles_generator import generate_subtitles_with_gemini` |
| `app/core/avatar_video_generator.py` | **ElevenLabs** (`api.elevenlabs.io/v1/voices/add`, `/text-to-speech/{id}`, modelo `eleven_multilingual_v2`) + **Edge-TTS** (`edge_tts.Communicate`) + **Replicate** (`sync/lipsync-2`, `devxpy/cog-wav2lip`) | `import requests, edge_tts, replicate` |
| `app/core/config_manager.py` | Chaves das 4 plataformas | env/arquivo: `GEMINI_API_KEY`, `OPENAI_API_KEY`, `ELEVENLABS_API_KEY`, `REPLICATE_API_TOKEN`/`REPLICATE_API_KEY` |
| `app/web/server.py` | Gemini na web | `from app.core.ai_synchronizer import synchronize_slides_with_gemini`; `get/set_gemini_api_key` |
| `app/ui/*` (desktop) | Gemini/ElevenLabs/Replicate/Edge em views, diálogos e workers | dezenas de referências (`main_window`, `record_*_view`, `generate_materials_view`, `avatar_calibration_dialog`, `class_render_workers` etc.) — escopo desktop |

Nenhuma ocorrência de Whisper/Vosk/embeddings/OCR neural no repositório
(busca por `whisper` sem resultados) — nada a remover nesse eixo, e nada
a introduzir (§2.2).

### 4.2 Rotas, chaves e configuração expostas

- **Rotas web de IA**: `POST /api/projects/{id}/ai-sync`,
  `GET/POST /api/config/key` (§1.3). Nenhuma outra rota chama IA:
  upload/render/jobs já são determinísticos.
- **Variáveis de ambiente**: `GEMINI_API_KEY` (`.env.example`,
  `compose.production.yml` em web **e** worker, `README.md`),
  `GEMINI_MODELS`, `EDGE_TTS_TIMEOUT`; desktop: `OPENAI_API_KEY`,
  `ELEVENLABS_API_KEY`, `REPLICATE_API_TOKEN` (documentadas no README).
- **Pacotes**: `google-genai==2.25.0` em `requirements-base.txt`
  (arrasta para a web), `edge-tts`/`replicate`/`requests` em
  `requirements.txt` (desktop), `stripe` em `requirements-web.txt`
  (comercial, não é IA — preservar isolado).
- **Frontend**: modal “Chave de API do Google Gemini”, botão
  “✨ Sincronizar com IA (Gemini)”, textos “com IA” em `index.html`/`app.js`.
- **Rede de saída implícita**: mesmo sem chave alguma,
  `generate_slide_image` tenta Pollinations — ou seja, **o produto atual
  chama IA remota por padrão**; o critério de aceite §6.2 (rede bloqueada)
  falharia hoje também por esse caminho no desktop/materiais.

### 4.3 Fallbacks que inventam conteúdo (proibidos pelo prompt §1/§2.5)

| Local | Comportamento atual |
| --- | --- |
| `ebook_generator._generate_ebook_content_with_gemini` | Sem chave ou com erro do modelo, retorna `default_data`: “Explicação detalhada dos conceitos apresentados no slide N…”, resumo e exercícios genéricos apresentados como apostila da aula |
| `ebook_generator._render_ebook_slide_chapter` / `_render_ebook_summary_and_quiz` | Texto de enchimento quando `content`/`summary`/`exercises` estão vazios |
| `meeting_recorder.generate_meeting_notes` | Sem chave, devolve resumo executivo fabricado (“Os participantes alinharam as prioridades…”) e “Transcrição não processada” |
| `avatar_video_generator.generate_avatar_speech` | ElevenLabs/Egde-TTS são o próprio recurso (voz sintética/clonada), fora do escopo web novo |

## 5. Lacunas frente ao produto pedido (não presumir que existem)

Confirmado pela leitura — **ainda não há** no repositório:

- Frontend React+TypeScript+Vite, build estático na mesma origem, nem
  navegação lateral (Projetos, Criar vídeo, Gravar aula, Podcast, Gravar
  tela/reunião, Materiais, Biblioteca, Preferências).
- CRUD de projetos (criar/nomear/duplicar/reabrir/excluir), autosave com
  versionamento anti-sobrescrita, biblioteca de arquivos, histórico de
  exportações durável (hoje: projeto = pasta com `meta.json` mínimo +
  tabelas `ownership`/`usage`; job some com TTL do Redis/memória).
- Gravação no navegador (getUserMedia/getDisplayMedia/MediaRecorder),
  teleprompter web, envio incremental de trechos, ata editável.
- Podcast web, editor de legendas SRT/VTT, editor de capas/slides por
  modelos, apostila editável, apresentador web.
- Persistência de preferências/modelos/automações por usuário
  (`config_manager` atual é arquivo local do desktop, centrado em chaves).
- Migrações versionadas do SQLite; reconciliação de jobs interrompidos;
  histórico além do TTL; portas: hoje só `8000` (web) — Vite `5173` e
  Redis interno `6379` serão novos no desenho (§5 do prompt).
- `.webm` não está em `AUDIO_EXTENSIONS` (prompt pede aceitar áudio WebM
  quando decodificável).

## 6. Decisões registradas (a partir do prompt, sem inventar contratos)

1. **Base**: trabalhar sobre este clone em `01eda8e`; preservar o desktop
   PySide6 e compartilhar só o núcleo sem Qt/IA. Nenhuma alteração local
   pré-existente foi encontrada (árvore limpa no clone).
2. **Sem IA em execução** (§2): remover do caminho web as rotas
   `/ai-sync` e `/config/key`, os imports de `ai_synchronizer`/
   `config_manager` de chaves em `server.py` e qualquer chamada remota
   (incl. Pollinations sem chave). Não substituir por IA local (§2.2).
3. **Dependências** (§2.4): `google-genai` sai de `requirements-base.txt`
   para um arquivo desktop/IA separado; a web deve subir sem SDKs de IA
   e sem PySide6 (critério §6.1). `edge-tts`/`replicate` idem.
4. **Sincronização** (§3.2): expor os cinco modos determinísticos;
   `slide_timing.py` é a base, mas seus mínimos/renormalização silenciosa
   serão revistos para erro explícito, com travas preservadas — os testes
   atuais de `test_slide_timing.py` serão atualizados se o comportamento
   mudar deliberadamente (§6.13).
5. **Fila/arquivos** (§4.2): manter Redis/RQ + worker separado e o
   pipeline único `render_task.py`; corrigir retenção/histórico além do
   TTL e reconciliação pós-restart antes de prometer durabilidade.
6. **Dados** (§4.1/4.3): manter SQLite+WAL no volume; acrescentar
   migrações versionadas e versionamento simples de projeto. Manter
   propriedade por usuário em toda rota nova (padrão `_owned_project`/
   `_owned_job` + `billing.owns`), cookies HttpOnly e validação atual.
7. **Cobrança** (§2.8): preservar `billing`/`stripe_billing` e dados;
   não ampliar, não ativar cobrança real em testes; isolar do teste de
   rede bloqueada (§6.2).
8. **Hospedagem** (§5): manter Docker Compose + Traefik existente;
   portas fixas API `8000` interna, Vite `5173` (`strictPort`), Redis
   `6379` interno, público só `443`. **Não** reutilizar IP/domínio de
   `DEPLOY.md`/compose sem autorização; nada de deploy em produção
   nesta etapa.
9. **Conteúdo ausente** (§1): vazio ou “modelo a preencher” — eliminar os
   fallbacks genéricos de §4.3 do caminho web.
10. **Lili** (§7): apenas proposta documental futura; nenhum adaptador,
    tela ou dependência agora.

## 7. Riscos e próximos passos

- **Risco 1 — acoplamento**: `podcast_video_builder` e `server.py`
  importam IA diretamente; a remoção exige religar legendas/modos de
  sincronização, não só deletar arquivos (desktop importa os mesmos
  módulos de `core`).
- **Risco 2 — `config_manager` compartilhado**: separar chaves de IA das
  preferências reutilizáveis sem quebrar o desktop.
- **Risco 3 — durabilidade de jobs**: hoje o histórico vive em
  memória/TTL do Redis (§4.2 do prompt exige persistência própria).
- **Próximo passo**: implementar na ordem da seção 8 do prompt —
  fundação sem IA (deps/rotas), serviços de aplicação e persistência,
  fluxos exportáveis (PDF+áudio primeiro), frontend do estúdio, pacote
  de implantação e validações da seção 6. Este inventário é a linha de
  base; cada entrega deve atualizar a matriz mantido/adaptado/substituído.

---

*Gerado em 28/10/2026 a partir do clone local em `01eda8e`. Arquivos-fonte
citados são relativos à raiz de `slidecast-studio/`.*
