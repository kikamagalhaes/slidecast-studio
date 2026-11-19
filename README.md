# SlideCast Studio 🎬📊

O produto principal é o **desktop PySide6**, com temas claro/escuro, editor PDF ou MP4 e até quatro faixas de áudio. O site apresenta o desktop; o estúdio web histórico permanece disponível apenas com `ENABLE_WEB_STUDIO=true`. Contas, APIs e dados existentes foram preservados.

- Site: https://kikamagalhaes.com.br/slidecast/
- [Auditoria e decisões de interface](docs/slidecast-ux-auditoria.md)
- [Sistema de design](docs/slidecast-design-system.md)
- [Testes, evidências e limites](docs/slidecast-ux-validacao.md)

A edição e a exportação locais não exigem IA. Recursos opcionais de IA dependem da configuração do serviço correspondente. A versão desktop 1.2.0 tem pacotes portáteis com FFmpeg e ffprobe incluídos. Compra, licença e ativação desktop ainda estão em preparação; veja o [handoff do backend](docs/SLIDECAST_PROMPT_BACKEND_COMPRA_LICENCA_ATIVACAO.md).

---

## ✨ Funcionalidades

- **Criar Vídeo (PDF/MP4 + até 4 áudios)**: durações por slide com auto-sincronização por IA, divisão uniforme ou ajuste manual; exportação MP4/H.264 em 720p, 1080p, 4K ou quadrado.
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
- **FFmpeg e ffprobe** no PATH (`sudo apt install ffmpeg` no Ubuntu/Debian; no Windows, baixe em [ffmpeg.org](https://ffmpeg.org/download.html) ou coloque `ffmpeg.exe` na pasta do projeto)
- Chave gratuita do **Google Gemini** ([AI Studio](https://aistudio.google.com/)) para os recursos de IA

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python3 main.py                    # ou ./run.sh (Linux) / run.bat (Windows)
```

Chaves de API podem ir em variáveis de ambiente (`GEMINI_API_KEY`, `OPENAI_API_KEY`, `ELEVENLABS_API_KEY`, `REPLICATE_API_TOKEN`) ou no botão 🔑 dentro do app (salvas em `~/.config/slidecast/config.json` no Linux / `%APPDATA%\slidecast` no Windows).

### Downloads — desktop 1.2.0

Baixe a [release 1.2.0](https://github.com/kikamagalhaes/slidecast-studio/releases/tag/v1.2.0) ou use a [página do SlideCast](https://kikamagalhaes.com.br/slidecast/#disponibilidade).

- **Windows 10/11 x64**: extraia todo o ZIP e abra `SlideCastStudio/SlideCastStudio.exe`.
- **Linux x64 / Ubuntu 24.04**: extraia o TAR.GZ e execute `./SlideCastStudio/SlideCastStudio`. O pacote usa glibc 2.39; em instalações mínimas podem faltar bibliotecas de sessão gráfica/áudio (`libgl1`, `libegl1`, `libxkbcommon0`, `libdbus-1-3`, `libpulse0`).
- **macOS 15 Apple Silicon**: abra o DMG e copie o aplicativo para Aplicativos.

São pacotes portáteis/aplicativo empacotado, sem assinatura comercial de código. Não há instaladores MSI/DEB/RPM. FFmpeg e ffprobe estão incluídos. Confira os arquivos SHA256 e os relatórios `*-self-test.json` na release. Câmera, microfone e captura da tela dependem dos dispositivos e permissões locais.

[Registro de distribuição e validação](docs/slidecast-distribuicao-validacao.md). O endpoint público `/api/releases/latest` entrega os mesmos metadados usados pela landing, provenientes de `frontend/landing/public/releases.json`.

Build local:

```bash
pip install -r requirements.txt -r requirements-desktop-ai.txt -r requirements-packaging.txt
# FFmpeg completo e ffprobe devem estar no PATH ou em FFMPEG_PATH/FFPROBE_PATH durante o build.
python scripts/fetch_ffmpeg.py
pyinstaller slidecast.spec --noconfirm --clean
python scripts/verify_bundle.py dist/SlideCastStudio/SlideCastStudio
```

O verificador executa o aplicativo empacotado com PATH restrito, abre os dois temas e gera MP4s reais a partir de PDF e MP4 com quatro faixas de áudio. No Windows, acrescente `.exe` ao caminho.

## 🌐 Como executar (Web)

```bash
pip install -r requirements-web.txt
./run_web.sh   # http://localhost:8000
```

Para desenvolver a landing: `npm ci --prefix frontend` e `npm run dev --prefix frontend` (porta 5173). O build `npm run build --prefix frontend` gera landing e estúdio legado em diretórios separados.

### Produção (Docker + Traefik)

```bash
cp .env.example .env   # configure domínio e variáveis conforme a documentação
docker compose --env-file .env -p slidecast -f compose.production.yml up -d --build
```

> A web não usa chaves de IA. Consulte [deploy-local-e-vps.md](docs/deploy-local-e-vps.md) e o [registro desta publicação](docs/slidecast-deploy-2026-11-18.md).

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
