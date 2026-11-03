# 01 — Auditoria SlideCast Web + Desktop (VideoCreate) + referência KikaMeet

Data: 2026-11-02 (sessão Muse). Método: leitura de código, `git status/log`,
`diff -rq` entre os dois projetos. Nenhuma alteração no KikaMeet (só leitura).

## Caminhos reais confirmados
- Web + código compartilhado: `slidecast/slidecast-studio` (repo `slidecast-studio`, branch criada `feat/studio-gravacao-web-desktop`). FastAPI `app/web/server.py`, frontend React/Vite `frontend/`, build servido em `app/web/static/studio/`, desktop PySide6 no mesmo repo (`main.py`).
- Desktop de trabalho: `VideosCreate/` — fork do mesmo código (base `01eda8e` + commits próprios de podcast/sub-path), branch `feat/studio-gravacao-web-desktop`. Entry `main.py` → `app/ui/main_window.py`.
- Os dois divergiram: web tem `app/services.py`, `media_specs.py`, `subtitles.py` (sem IA); desktop tem `podcast_audio.py` e views de podcast mais novas. Núcleo `app/core/*` é a base comum a preservar.

## Matriz (Existe web / desktop / falta / reutilizável)
| Recurso | Web | Desktop | Ação |
|---|---|---|---|
| PDF+áudio → MP4 (FFmpeg, fila, progresso) | Sim | Sim | Preservar |
| Projetos persistidos c/ revisão/autosave | Sim (SQLite) | Parcial (arquivos) | Unificar esquema via `app/core/studio.py` |
| Gravar aula (câmera/mic, slides, teleprompter) | Básico (MediaRecorder s/ palco) | Sim (áudio+tempos→render) | Palco canvas web; cenas desktop |
| 3 PDFs c/ página independente | Não | Não (1 PDF) | Novo nas duas |
| Caneta temporária (TTL) / permanente | Não | Não | Novo nas duas |
| Bíblia projetável | Não | Não | Novo (texto da usuária/licenciado) |
| Quadro branco gravável | Não | Não | Novo nas duas |
| Brainstorm / Quiz c/ revelar | Não | Não | Novo nas duas (conceito KikaMeet Activities/Brainstorm) |
| Teleprompter fora da gravação | Parcial (textarea) | Sim (widget) | Web: painel DOM fora do canvas |
| Podcast (capa/onda/BGM) | Parcial (sem export) | Sim | Preservar desktop; web mantém |
| Timer visível opcional na gravação | Não | Parcial (cronômetro operador) | Novo nas duas |

## Referência KikaMeet (só UX/conceito, sem videoconferência)
`components/meet/Activities.tsx` (quiz criar/revelar/placar), `Brainstorm.tsx`,
`SharedBoard.tsx` (quadro), `BibleReader.tsx` (livro/capítulo/busca),
`lib/teleprompterParser.ts`. Nada de LiveKit/SFU/salas foi copiado.

## Regras
Sem IA obrigatória no fluxo principal; FFmpeg local; sem deploy em produção.
