# Entrega — SlideCast Studio Web (sem IA)

Base: commit `01eda8e` + alterações não commitadas nesta árvore (ver `git status`).
Produto web atual: FastAPI + build React/TypeScript/Vite servido na mesma origem.
Sem Gemini/OpenAI/ElevenLabs/Replicate/PySide6/edge-tts no caminho web.

## Como rodar

| Modo | Comando exato | URL |
|---|---|---|
| Local (runner declarado) | `pip install -r requirements-web.txt` e `./run_web.sh` | http://localhost:8000 |
| Local (equivalente, sem reload) | `.venv/bin/python -m uvicorn app.web.server:app --host 127.0.0.1 --port 8000` | http://127.0.0.1:8000 |
| Frontend dev (opcional) | `cd frontend && npm run dev` | http://localhost:5173 (proxy `/api` → `:8000`, `strictPort`) |
| Compose dev | `docker compose up --build` | http://127.0.0.1:8000 (só loopback; Redis sem porta pública) |
| Compose produção | `APP_DOMAIN=<domínio> docker compose -f compose.production.yml up -d --build` | `https://<APP_DOMAIN>` via Traefik (443; web só `expose 8000`) |

Health: `GET /api/health`. Estúdio: `GET /` serve `app/web/static/studio/index.html` quando o build existe.

## Matriz mantido / adaptado / substituído por manual

| Área | Situação | Evidência |
|---|---|---|
| PDF+áudio → MP4, fila, billing, auth | Mantido | `app/web/server.py`, `queue_manager`, testes web verdes |
| Tempos por slide | Adaptado (sem IA) | `app/core/slide_timing.py`: uniforme/pesos/travas, erro explícito sem extensão silenciosa |
| Legendas | Adaptado (manual) | `app/core/subtitles.py`: importar/validar/editar/exportar SRT/VTT do usuário |
| Projetos/preferências/exports/jobs | Novo (persistente) | `app/services.py` + `app/web/db.py` (WAL, migrações, idempotência, isolamento por `user_id`) |
| Sincronização Gemini, `/ai-sync`, `/api/config/key` | Substituído por manual | Rotas removidas; durações por roteiro/travas/marcação ouvindo o áudio |
| Transcrição/resumo/e-book com IA | Substituído por manual | Materiais web usam só texto do usuário; sem fallback genérico |
| Avatar/clone/TTS IA | Fora da web (desktop legado) | SDKs em `requirements-desktop-ai.txt`, fora de `requirements-web.txt` |
| Podcast fade/normalização/ducking | Salvo, ainda não aplicado | Parâmetros persistidos no projeto; export de podcast ainda não os consome (declarado na UI) |
| Gravação navegador/tela | Manual, só no navegador | `getUserMedia`/`getDisplayMedia`/`MediaRecorder`; trechos na sessão + download `.webm`; sem upload incremental ao servidor |

## Testes (evidência herdada + esta etapa)

- Suíte web: 122 passed (prior 5; 124 com aceitação no prior 4), ignorando apenas testes desktop/IA por desenho.
- `npm run build` (tsc + vite): verde. `ruff` nos arquivos tocados: verde.
- Aceitação sem IA: tempos 20/20/20 e 10/20/30, render PDF+áudio→MP4, isolamento entre 2 usuários, idempotência sem job duplicado.
- Check HTTP desta entrega: registrado no fechamento (comando e URL acima).

## Limitações conhecidas

- `docker build` não executado nesta máquina (`permission denied` em `/var/run/docker.sock`); composes validados via `docker compose config`, stage frontend via `npm run build` equivalente.
- Sem reconciliação de jobs interrompidos no restart do worker RQ; sem medição real 4K/VPS (declarados não medidos).
- Sem upload incremental de gravações ao servidor; podcast sem export que aplique fade/normalização/ducking; apostila web sem PDF de backend.
- Legado acessível direto: `app/web/static/app.js` e `app/web/templates/index.html` (Gemini) continuam no repo, mas `GET /` não os expõe; remoção é decisão de corte pendente.
- Desktop legado não revalidado nesta entrega.

## Proposta futura — integração com a Lili (apenas documental, §7)

Sem implementar IA agora. Quando autorizada, a integração deve ser um adaptador isolado fora do caminho web atual: (1) contrato de entrada/saída versionado (projeto, roteiro e tempos entram; sugestões retornam como dados, nunca aplicadas sem revisão do usuário); (2) serviço separado com chave própria, atrás de flag, sem adicionar SDKs a `requirements-web.txt`; (3) toda saída da Lili rotulada como sugestão editável, preservando o modo manual como padrão e fallback; (4) testes de contrato com rede bloqueada para garantir que o estúdio continua funcional sem a Lili. Nenhum adaptador, tela ou dependência foi criado nesta entrega.
