# Deploy e atualização — SlideCast Studio

Não há auto-update. Atualizar = `git pull` + rebuild (servidor) ou `git pull` (desktop).

## Produção (servidor web)

Pré-requisitos no servidor: Docker + Compose, clone do repo, arquivo `.env`
(ver `.env.example`; todas as variáveis novas têm default — um `.env` antigo
continua funcionando, mas defina `ADMIN_TOKEN`).

```bash
cd /caminho/do/slidecast-studio
git pull origin main
docker compose -f compose.production.yml up -d --build
sleep 20
curl -s https://SEU-DOMINIO/api/health
docker compose -f compose.production.yml logs --tail=30 web
```

Resposta saudável da versão nova inclui `ffmpeg` e `disk_free_mb`:

```json
{"status":"healthy","service":"slidecast-web","ffmpeg":"...","disk_free_mb":1234,...}
```

Recomendado na primeira atualização: `QUEUE_BACKEND=memory`, `UVICORN_WORKERS=1`.
Redis (`QUEUE_BACKEND=redis`) só depois de validar um render no compose.

Rollback (se algo quebrar):

```bash
git log --oneline -3
git checkout <commit-anterior> -- .
docker compose -f compose.production.yml up -d --build
```

## Desktop (Linux/Windows)

```bash
cd /caminho/do/slidecast-studio
git pull origin main
./run.sh            # Linux — cria .venv e instala o que faltar
run.bat             # Windows
```

## Notas

- Nunca commite `.env` real nem a pasta `storage/` (só `.env.example`).
- Logs do servidor: `docker compose -f compose.production.yml logs -f web worker`.
