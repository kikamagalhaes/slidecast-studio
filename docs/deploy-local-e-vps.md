# Instalação — local e VPS (Hostinger) com Traefik/HTTPS

Produto **sem IA**: nenhuma chave de IA é pedida, lida ou enviada. O runtime
web não instala PySide6 nem SDKs de IA (`requirements-web.txt`).

## Limites explícitos (`.env`, ver `.env.example`)

| Variável | Default | Efeito |
|---|---|---|
| `MAX_CONCURRENT_RENDERS` | `1` | renders simultâneos (fila em memória) |
| `FFMPEG_THREADS` | `2` | `-threads` do FFmpeg |
| `MAX_UPLOAD_MB` | `200` | teto por arquivo (413 ao exceder) |
| `MAX_AUDIO_SECONDS` | `3600` | duração máxima do áudio (400 ao exceder) |
| `HEALTH_MIN_DISK_MB` | `500` | abaixo disso `/api/health` = `degraded` |

## Local (sem Docker)

```bash
cd slidecast-studio
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-web.txt -r requirements-dev.txt
uvicorn app.web.server:app --host 127.0.0.1 --port 8000
# frontend dev (opcional): cd frontend && npm ci && npm run dev  # :5173, proxy /api -> :8000
```

## Local (Docker)

```bash
cp .env.example .env
docker compose up --build        # API em http://127.0.0.1:8000 (só loopback)
docker compose ps                # web/worker/redis healthy; Redis sem porta pública
```

Volumes nomeados compartilhados web/worker: `storage-data` (`/app/storage`),
`redis-data` (Redis com `--appendonly yes`).

Healthchecks distintos: **web** = HTTP `GET /api/health`; **worker** = há ao
menos 1 worker RQ registrado no Redis; **redis** = `redis-cli ping`.

## VPS Hostinger com Traefik (443)

Pré-requisito: Traefik **já existente** na VPS (entrypoint `websecure`,
certresolver `letsencrypt`, provider Docker). Não suba um segundo Traefik.

```bash
# na VPS, diretório próprio do projeto (ex.: /opt/slidecast)
cp .env.example .env   # defina APP_DOMAIN e ADMIN_TOKEN
docker compose -p slidecast -f compose.production.yml config --quiet
docker compose -p slidecast -f compose.production.yml up -d --build
docker compose -p slidecast -f compose.production.yml ps
curl -s https://SEU-DOMINIO/api/health
```

Só o Traefik publica 443/80 no host; `web` apenas `expose 8000` na rede do
compose e o Redis não publica porta alguma.

## Backup / restauração

```bash
# backup (projetos, DB SQLite, vídeos e fila persistida)
docker run --rm -v slidecast_storage-data:/data -v "$PWD/backups:/b" alpine \
  tar czf /b/storage-$(date +%F).tgz -C /data .
docker run --rm -v slidecast_redis-data:/data -v "$PWD/backups:/b" alpine \
  tar czf /b/redis-$(date +%F).tgz -C /data .
# restauração (stack parada)
docker compose -p slidecast -f compose.production.yml down
docker run --rm -v slidecast_storage-data:/data -v "$PWD/backups:/b" alpine \
  sh -c "cd /data && tar xzf /b/storage-AAAA-MM-DD.tgz"
docker compose -p slidecast -f compose.production.yml up -d
```

## Atualização e rollback (sem tocar outros serviços)

Todos os comandos levam `-p slidecast` e `-f compose.production.yml`:
nenhum outro stack/container da VPS é parado, removido ou reconstruído.

```bash
git pull
docker compose -p slidecast -f compose.production.yml up -d --build
curl -s https://SEU-DOMINIO/api/health   # esperar status healthy/degraded coerente
# rollback: volte o código e reconstrua só este stack
git checkout <commit-anterior>
docker compose -p slidecast -f compose.production.yml up -d --build
```

## Medições desta entrega (2026-10-28, máquina de desenvolvimento)

- Suíte web: **124 passed** (`pytest tests/`, excluídos apenas testes
  desktop/IA legados que exigem `edge_tts`/PySide6 — fora do caminho web).
- Aceitação: PDF 3 slides + WAV 60s determinísticos -> MP4 320x180@5fps,
  duração ffprobe dentro de 55–65s; uniforme `20/20/20`; pesos `1:2:3` =
  `10/20/30`; trava preservada; isolamento entre 2 usuários (404 cruzado);
  cancelamento sem duplicar job; legendas com acentos (SRT->VTT);
  apostila longa (800 repetições) íntegra no projeto.
- Auditoria sem IA no caminho web: `grep` de SDKs/chaves/destinos de rede
  em `app/web/`, `app/services.py` e núcleos usados = **0 ocorrências**;
  backend importa e sobe sem `GEMINI_API_KEY` e sem PySide6.

## Limitações reais

- `docker build` não executado nesta máquina: sem permissão no socket
  Docker (`permission denied ... /var/run/docker.sock`). Os composes foram
  validados com `docker compose config`; o build do frontend foi validado
  via `npm run build` (mesma etapa do stage Node).
- Apostila web = texto do usuário salvo no projeto (sem PDF gerado no
  backend); o gerador de e-book com IA é legado desktop, fora do caminho web.
- Upload de trechos de gravação é só no navegador (sem endpoint incremental).
