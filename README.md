# SlideCast Studio 🎬📊

Estúdio de produção de vídeos: sincroniza apresentações de slides em **PDF** com **áudio/narração**, grava aulas, reuniões e podcasts, gera materiais didáticos (capas, fundos, apostilas/e-books) e avatares/clones digitais — com sincronização inteligente por IA (**Google Gemini**).

Duas frentes:

- **Desktop** (Linux/Windows): app PySide6 (Qt) completo.
- **Web** (FastAPI + Docker): API/serviço de upload → sincronização IA → renderização em fila.

---

## ✨ Funcionalidades

- **Criar Vídeo (PDF + áudio)**: durações por slide com auto-sincronização por IA, divisão uniforme ou ajuste manual; exportação MP4/H.264 em 720p, 1080p, 4K ou quadrado.
- **Gravar Aula**: estúdio com teleprompter, slides, câmera/PIP, vinhetas de abertura/encerramento, BGM com ducking e legendas queimadas (PT + traduções).
- **Clone Digital / Avatar**: calibração por vídeo curto, voz clonada (ElevenLabs) ou TTS neural (Edge), sincronia labial local ou em nuvem (Replicate).
- **Gravar Reunião**: captura de tela + câmera, transcrição, resumo executivo e e-book da aula.
- **Podcast**: capa + forma de onda animada sincronizada à voz, BGM e legendas.
- **Gerar Materiais**: capas, fundos e slides com IA, apostila/e-book em PDF intercalando slides e texto didático.
- **Web API**: os mesmos fluxos de PDF + áudio via navegador, com fila de renderização e acompanhamento de progresso.

---

## 🚀 Como executar (Desktop)

### Pré-requisitos

- **Python 3.10+** (recomendado 3.12)
- **FFmpeg** no PATH (`sudo apt install ffmpeg` no Ubuntu/Debian; no Windows, baixe em [ffmpeg.org](https://ffmpeg.org/download.html) ou coloque `ffmpeg.exe` na pasta do projeto)
- Chave gratuita do **Google Gemini** ([AI Studio](https://aistudio.google.com/)) para os recursos de IA

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python3 main.py                    # ou ./run.sh (Linux) / run.bat (Windows)
```

Chaves de API podem ir em variáveis de ambiente (`GEMINI_API_KEY`, `OPENAI_API_KEY`, `ELEVENLABS_API_KEY`, `REPLICATE_API_TOKEN`) ou no botão 🔑 dentro do app (salvas em `~/.config/slidecast/config.json` no Linux / `%APPDATA%\slidecast` no Windows).

### Instaladores desktop (Releases)

Na página [Releases](https://github.com/kikamagalhaes/slidecast-studio/releases) há pacotes prontos, gerados automaticamente a cada tag `v*`:

- **Linux**: `SlideCastStudio-linux-x64.tar.gz` — extraia e rode `./SlideCastStudio/SlideCastStudio` (em sistemas mínimos pode faltar Qt/OpenGL/áudio: `sudo apt install libgl1 libegl1 libxkbcommon0 libdbus-1-3 libpulse0`).
- **Windows**: `SlideCastStudio-windows-x64.zip` — extraia e rode `SlideCastStudio.exe` (o SmartScreen pode avisar por ser app não assinado; clique em "Mais informações → Executar assim mesmo").
- **macOS (Apple Silicon)**: `SlideCastStudio-macos-arm64.dmg` — arraste para Aplicativos (não assinado: no primeiro uso, clique com botão direito → Abrir).

Os pacotes já incluem ffmpeg próprio — não precisa instalar nada. Para diagnosticar qualquer instalação: `./SlideCastStudio --self-test` (código de saída 0 = tudo certo).

> Build local: `pip install -r requirements.txt -r requirements-packaging.txt`, `python scripts/fetch_ffmpeg.py`, `pyinstaller slidecast.spec`.

## 🌐 Como executar (Web)

```bash
pip install -r requirements-web.txt
./run_web.sh   # http://localhost:8000
```

### Produção (Docker + Traefik)

```bash
cp .env.example .env   # preencha GEMINI_API_KEY e ADMIN_TOKEN!
docker compose -f compose.production.yml up -d --build
```

> ⚠️ **Segurança**: em produção, defina `ADMIN_TOKEN` — sem ele, o endpoint `POST /api/config/key` fica aberto.

### Fila de renderização: memória vs Redis

- **Desenvolvimento** (`QUEUE_BACKEND=memory`, padrão no código): fila em memória do processo, **1 worker** uvicorn, zero dependências extras.
- **Produção** (`QUEUE_BACKEND=redis`, padrão no compose): jobs duráveis no Redis, N workers uvicorn + processos `rq worker` separados (serviço `worker` no compose), sobrevivendo a restarts. Web e workers **devem compartilhar** o volume `./storage` (os payloads carregam caminhos).
- Desenvolvimento local com Redis: suba um servidor (`docker run -d -p 6379:6379 redis:7-alpine`), rode `./run_worker.sh` em um terminal e a web com `QUEUE_BACKEND=redis` em outro.

### Variáveis de ambiente

| Variável | Padrão | Efeito |
|---|---|---|
| `GEMINI_API_KEY` | — | Chave do Gemini (precede a salva no servidor) |
| `ADMIN_TOKEN` | — | Exige header `X-Admin-Token` em `POST /api/config/key` |
| `MAX_UPLOAD_MB` | `500` | Teto por arquivo enviado |
| `QUEUE_BACKEND` | `memory` | `memory` ou `redis` |
| `REDIS_URL` | `redis://localhost:6379/0` | Conexão Redis (backend `redis`) |
| `JOB_RETENTION_HOURS` | `24` | Evicção de jobs concluídos da memória (backend `memory`) |
| `JOB_RESULT_TTL_HOURS` | `24` | Expiração de jobs no Redis (backend `redis`) |
| `RQ_JOB_TIMEOUT` | `3600` | Timeout duro por render no worker RQ (s) |
| `UVICORN_WORKERS` | `1` | Workers HTTP (só >1 com backend `redis`) |
| `PROXY_HEADERS` | `0` | `1` atrás de Traefik/Nginx (IP real p/ rate limit) |
| `FORWARDED_ALLOW_IPS` | `*` | IPs confiáveis p/ `X-Forwarded-*` |
| `RATE_LIMIT_PER_MINUTE` | `120` | Teto por IP+endpoint (upload/IA/render) |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | Janela do rate limit |
| `HEALTH_MIN_DISK_MB` | `500` | Disco mínimo p/ `/api/health` saudável |
| `GEMINI_MODELS` | lista interna | Ordem de modelos, ex.: `gemini-2.5-flash,gemini-flash-latest` |
| `EDGE_TTS_TIMEOUT` | `180` | Teto da síntese de voz neural (s) |
| `SLIDECAST_PULSE_SOURCE` | auto | Fonte PulseAudio da gravação (Linux) |
| `SLIDECAST_DSHOW_AUDIO` | auto | Dispositivo de áudio dshow (Windows) |
| `LOG_LEVEL` | `INFO` | Verbosidade dos logs |

---

## 📦 Executável standalone

```bash
pip install pyinstaller
pyinstaller --noconsole --name "SlideCast" main.py
# saída em dist/SlideCast/
```

---

## 🧪 Desenvolvimento (testes e lint)

```bash
pip install -r requirements-dev.txt
pytest -q
ruff check app tests
```

- Convenção de progresso no `core`: callbacks recebem fração **0.0–1.0** (views Qt adaptam para 0–100 na borda).
- Logs via `logging` (`LOG_LEVEL`); `print` direto só em scripts efêmeros.
- Modelos Gemini centralizados em `app/core/gemini_client.py` (override por `GEMINI_MODELS`).
- Testes desktop usam Qt offscreen no mesmo `pytest` (pulados sem PySide6); o backend Redis é testado com fakeredis, sem servidor real.
- Operações longas aceitam `cancel_check` e a API expõe `DELETE /api/jobs/{id}`.

---

## 📂 Estrutura do código

```
VideosCreate/
├── app/
│   ├── core/                  # Regras de negócio (sem Qt/FastAPI)
│   │   ├── pdf_processor.py       # Inspeção de PDF e renderização de slides (PyMuPDF)
│   │   ├── audio_processor.py     # Duração/metadados de áudio (mutagen/ffprobe)
│   │   ├── ffmpeg_utils.py        # Descoberta de ffmpeg/ffprobe + durações
│   │   ├── video_generator.py     # Pipeline FFmpeg (concat) com progresso
│   │   ├── ai_synchronizer.py     # Durações por slide via Gemini
│   │   ├── subtitles_generator.py # Transcrição/tradução SRT via Gemini
│   │   ├── class_video_builder.py # Montagem da videoaula (vinhetas, PIP, BGM, SRT)
│   │   ├── podcast_video_builder.py
│   │   ├── avatar_video_generator.py # TTS clonado/neural + lipsync local/nuvem
│   │   ├── clone_manager.py       # Perfis de clones digitais
│   │   ├── meeting_recorder.py    # Gravação de tela + atas via Gemini
│   │   ├── ebook_generator.py     # Apostila/e-book em PDF
│   │   ├── image_generator.py     # Capas/slides (DALL-E, Pollinations, local)
│   │   ├── gemini_client.py       # Cliente Gemini com fallback de modelos
│   │   ├── slide_timing.py        # Roteiro → durações por slide (puro, testável)
│   │   ├── config_manager.py      # Chaves e preferências (env + arquivo)
│   │   └── logging_config.py      # Configuração central de logs
│   ├── ui/                    # Desktop PySide6
│   │   ├── main_window.py         # Janela principal e navegação
│   │   ├── home_cards.py          # Cards do menu inicial (dados + builders)
│   │   ├── views/                 # Telas: aula, reunião, podcast, materiais…
│   │   │   └── class_panels.py    # Painéis setup/studio/resultado da aula
│   │   ├── workers/               # Workers QThread extraídos das views
│   │   ├── dialogs/               # Calibração de avatar, capas, fundos, motores
│   │   ├── widgets.py, styles.py, teleprompter_widget.py, ...
│   │   └── floating_camera_widget.py
│   ├── web/                   # API FastAPI
│   │   ├── server.py              # Rotas (upload, IA, render, jobs, cancel)
│   │   ├── validation.py          # Validação de entrada (pura, testável)
│   │   ├── rate_limit.py          # Rate limit por IP+endpoint (429)
│   │   ├── render_task.py         # Pipeline de render + entrypoint RQ
│   │   ├── queue_manager.py       # Fila em memória + seleção de backend
│   │   ├── redis_queue.py         # Backend Redis/RQ (escala horizontal)
│   │   └── static/ templates/     # Cliente web
│   └── worker.py              # Workers QThread do fluxo PDF+áudio (desktop)
├── tests/                     # Testes (pytest): core, web, redis, desktop…
├── main.py                    # Entrada do desktop
├── requirements-base.txt      # Deps compartilhadas (pinadas)
├── requirements.txt           # Desktop = base + PySide6 + TTS/avatar
├── requirements-web.txt       # Web = base + FastAPI (usado no Docker)
├── requirements-dev.txt       # pytest + ruff + httpx
├── Dockerfile / compose.production.yml / .env.example
├── entrypoint.sh              # Workers uvicorn + proxy headers via env
└── run.sh / run.bat / run_web.sh / run_worker.sh
```
