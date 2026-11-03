# 02 — Entrega: SlideCast Studio (Web + Desktop VideoCreate)

Branch (ambos): `feat/studio-gravacao-web-desktop`. Sem deploy em produção.

## O que foi implementado
- Núcleo compartilhado `app/core/studio.py` (idêntico nos dois repos): esquema
  v1 de projeto, 3 slots de PDF com página independente, cenas, PiP, caneta
  permanente/temporária (TTL 3/5/8s), marca-texto, Bíblia/quadro/brainstorm/
  quiz, teleprompter por marcadores, timeline de cenas, export/import de
  projeto e cartões PNG (PyMuPDF) para cenas didáticas.
- Web (`frontend/src/Studio.tsx`): palco canvas 16:9 WYSIWYG (1920×1080 ou
  1280×720), câmera PiP configurável, upload/troca instantânea de até 3 PDFs
  (página renderizada no servidor em alta), teleprompter em painel DOM fora
  do canvas (não vaza na gravação), nível de microfone, gravar/pausar/retomar/
  encerrar via `canvas.captureStream` + microfone, trechos em IndexedDB,
  prévia, download WebM e conversão para MP4 H.264+AAC no servidor
  (`POST /studio/recording`). Atalhos 1–8 e setas (fora de campos).
- Desktop (`VideosCreate`): slots PDF 1–3 na configuração e no estúdio ao
  vivo, botões de cena (Slides/Bíblia/Quadro/Brainstorm/Quiz/Abertura),
  `StudioPenOverlay` (temporária expira sozinha; PDF original intacto),
  segmentos gravados por cena e `StudioRenderWorker` (slides + cartões +
  tinta → MP4 via `generate_video`). Fluxo legado sem cenas continua igual.
- Correção: `QInputDialog` não importado em `RecordClassView` (NameError ao
  projetar quiz) — corrigido com teste de regressão offscreen.

## Evidências (nesta máquina)
- Web: `pytest` 136+ aprovados (1 skip Qt no venv web; `test_avatar_tts`
  excluído por falta pré-existente de `edge_tts` no venv web).
- Desktop: `pytest tests/test_studio_core.py tests/test_studio_desktop.py
  tests/test_podcast_recording.py tests/test_desktop_smoke.py` → 17 aprovados.
- Amostras reais em `storage/evidencias/`: `amostra-desktop-segmentos.mp4`
  (H.264 1280×720 + AAC, 8s, slides+quiz+Bíblia) e
  `amostra-web-estudio-convertida.mp4` (H.264+AAC, 3s, convertido via API).
- API exercitada com curl: registro, projeto, upload de PDF, página PNG e
  conversão/download de gravação (todos 200).

## Limites honestos (não homologados)
- Gravação contínua de 60 min não executada em nenhuma plataforma.
- Câmera/microfone reais e leitura humana das amostras não validados em
  ambiente headless; validar com a professora antes de uso em produção.
- Bíblia usa texto fornecido/licenciado pela usuária (sem scraping).
- Build instalável desktop (PyInstaller) não refeito nesta sessão.

## Como rodar
- Web: `./run_web.sh` (ou uvicorn `app.web.server:app`) → rota `/`, "Gravar aula".
- Desktop: `python3 main.py` em `VideosCreate/` → "Gravar Aula".
- Rollback: voltar à branch `main` (nenhuma migração destrutiva foi feita).

## Adendo 2026-11-02 — verificação em navegador real (headless)
- Playwright/Chromium pela UI real, 28/28 PASS: login, 3 PDFs com páginas
  independentes/preservadas, PiP, canetas permanente/temporária 3/5/8s,
  marca-texto, Bíblia, quadro, brainstorm, quiz com revelar, teleprompter
  rolando (scrollTop>0, fora do canvas), gravar/pausar/retomar/encerrar,
  prévia, download WebM (187.552 B) e MP4 convertido (741.648 B, H.264
  1920×1080 + AAC, 5,2s). Palco a 60,3 fps (rAF). Screenshots em
  `/tmp/studio-evidence/01..13*.png`, lidas de volta nesta sessão.
- Defeitos encontrados pela prova e corrigidos: autosave 409 (retry com
  revisão fresca) e ausência de aviso durante a conversão MP4; tema claro
  aplicado conforme a seção 2 do prompt (commit `55fe49a`).
- Gravação longa web: 10 min contínuos com troca de cena a cada minuto —
  WebM 1080p de 602,8s / 13,4MB íntegro e remuxável. Os 60 min do prompt
  seguem NÃO executados; câmera/microfone reais (hardware) não validados
  em ambiente headless (usado dispositivo simulado do Chromium).
- Desktop: bundle PyInstaller `dist/SlideCastStudio` (383MB) construído em
  `VideosCreate` e `--self-test` com saída `SELF-TEST OK` (exit 0).

## Adendo final — gravação contínua de 60 minutos (2026-11-02)
- Web: 60 min contínuos pela UI real (headless, troca de cena a cada
  minuto): `gravacao-longa-60min.webm` — 3.626,7s, VP9 1920×1080 + Opus,
  71MB, remux p/ MP4 íntegro e decodificação completa sem erros
  (log `long_rec60.log`: `LONG60 RECORDING DONE total=3640s`).
- Desktop: renderização de 60 min pelo pipeline real (`generate_video`,
  slides + cartão de Bíblia + narração): `desktop-longa-60min.mp4` —
  H.264 + AAC, 3.600s, concluída em 1.650s de render.
- Restante (único): câmera/microfone de hardware real — exige a
  professora com dispositivo físico; ambiente headless usou o
  dispositivo simulado do Chromium. Roteiro: abrir o estúdio, gravar
  2 min falando, conferir nível de microfone, prévia e MP4.
