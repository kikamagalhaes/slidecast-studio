# Validação UX/UI — 18/11/2026

## Resultado e escopo

Redesign, temas, editor e landing **implementados**. PDF/MP4, quatro faixas, prévia e exportação **integrados ao motor real** (`MultimediaProject` / `MultimediaRenderWorker`). Nenhum renderizador paralelo foi criado. IA opcional mantém os serviços anteriores; não foi chamada durante a validação.

**196 testes passaram** na suíte completa em 116,47 s; após a correção pontual de duração, a suíte completa passou novamente (196 testes, 97,05 s). Depois dos ajustes finais de evidências, os 11 testes de UI e landing passaram novamente em 6,00 s. `ruff check app tests` passou após remover imports sem uso do teste multitrack anterior. Build TypeScript/Vite dos dois frontends passou. Há um aviso de depreciação do transporte httpx do TestClient, sem falha.

## Matriz de aceite

| ID | Cenário | Resultado e evidência |
|---|---|---|
| U01 | Home/navegação | Implementado; capturas home dos dois temas, tarefas e navegação persistente |
| U02 | Claro | Tokens e capturas das seis telas, etapas e modais; contraste automatizado |
| U03 | Escuro | Mesma matriz; teleprompter, campos e ações recoloridos sem inversão de texto |
| U04 | Projeto aberto e troca de tema | Teste preserva modelo completo, página selecionada e modal aberto |
| U05 | Persistência | QSettings gravado e nova instância do ThemeManager restaura a escolha |
| U06 | PDF | Importação real em thread; páginas, tempos, thumbnail e exportação real |
| U07 | MP4 | Inspeção real, frame via Qt, prévia renderizada e duração do motor |
| U08 | 1–4 faixas | Valores distintos, edição independente, remover/trocar e labels |
| U09 | Quinta faixa | Botão desabilitado e validação defensiva com mensagem; teste de limite |
| U10 | Volume/mute/início | Controles escrevem nos campos reais; suíte multitrack valida o áudio gerado |
| U11 | Duração | Escala proporcional e corte visível; faixa curta/longa diferenciada |
| U12 | Áudio original | Aviso na tela MP4 e exclusão no motor existente |
| U13 | Render/cancelar/erro | Exportação real, progresso do worker, prévia, cancelamento e arquivo inválido recuperável |
| U14 | Projeto antigo | v1 migrado, tempos mantidos; v2 reabre os valores exatos; mídias faltantes/versão desconhecida recusadas |
| U15 | Estúdio | Três PDFs, cenas, caneta e prompter preservados; não há TAKE desktop separado neste checkout |
| U16 | Escala/teclado | Capturas Linux 125%/150%, rolagem e controles Qt; atalhos de projeto. Leitor de tela e Windows pendentes |
| U17 | Landing | Build e navegador Chromium em desktop/móvel, âncoras/FAQ e ausência de overflow |
| U18 | Compra/download | Sem links falsos; licença e pacotes desta versão sinalizados em preparação |
| U19 | Regressões | Suíte de estúdio, podcast, engine e smoke desktop aprovada; etapas continuam acessíveis |
| U20 | Plataformas | Linux Qt offscreen verificado; Windows e câmera/microfone físicos não certificados nesta entrega |

## Matriz visual reproduzível

| Telas/estados | Claro e escuro | Evidência |
|---|---|---|
| Home/editor/aula/reunião/podcast/materiais | Ambos | `evidencias/depois-claro` e `depois-escuro` |
| Aula 5 etapas, reunião 2, podcast 3, materiais 3 | Ambos | Arquivos `*-etapa-N.png` nas duas pastas |
| Estúdio com três PDFs e prompter | Ambos | `estudio.png` |
| Modal aberto e troca imediata de tema | Ambos | `dialogo.png` e `dialogo-tema-alternado.png` |
| Menu, item desabilitado e seletor de arquivos Qt | Ambos | `menu.png` e `seletor-arquivos.png` |
| Escala 125% / 150%, janela lógica 1024×768 | Claro / escuro | `evidencias/linux-125` e `linux-150` |
| Sucesso de exportação PDF e prévia MP4 | Qt real | `evidencias/exportacao` |
| Landing | Desktop e móvel | `evidencias/landing-desktop.png` e `landing-mobile.png`; produção em `evidencias/producao-*` |

As imagens Qt 1440×1200 mostram dados demonstrativos importados. Em janelas menores a rolagem permite alcançar as faixas e ações. SVGs de controles são incluídos no empacotamento. As capturas não comprovam câmera, áudio de hardware, cor do monitor ou diálogos nativos do Windows.

## Comandos executados

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
.venv/bin/python -m ruff check app tests
npm run build --prefix frontend
QT_QPA_PLATFORM=offscreen SLIDECAST_EVIDENCE_DIR=docs/evidencias/exportacao \
  .venv/bin/python -m pytest -q tests/test_desktop_ux.py tests/test_landing.py
QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/capture_desktop_ux.py \
  --sample --matrix --theme light --height 1200 --output docs/evidencias/depois-claro
QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/capture_desktop_ux.py \
  --sample --matrix --theme dark --height 1200 --output docs/evidencias/depois-escuro
QT_QPA_PLATFORM=offscreen QT_SCALE_FACTOR=1.25 .venv/bin/python scripts/capture_desktop_ux.py \
  --sample --theme light --width 1024 --height 768 --output docs/evidencias/linux-125
QT_QPA_PLATFORM=offscreen QT_SCALE_FACTOR=1.5 .venv/bin/python scripts/capture_desktop_ux.py \
  --sample --theme dark --width 1024 --height 768 --output docs/evidencias/linux-150
```

Os vídeos de evidência são gerados por FFmpeg (PDF com quatro faixas e prévia de MP4), não simulados. WAVs/PDFs temporários e MP4s não são versionados. A revisão no navegador usa Chromium Playwright em sessão isolada.

## Limites e dependências

- **Validação humana/hardware:** captura de microfone, câmera e tela em ambiente gráfico real; sessão Windows; scaling/fontes específicos de cada sistema e tecnologias assistivas.
- **Distribuição:** releases históricas v1.0.0/v1.1.1 existem, mas não contêm este redesign. Não são anunciadas como a nova versão. A publicação de novos instaladores exige empacotar e verificar `ffprobe`: o script histórico de staging só copia FFmpeg e o novo motor de MP4 usa ffprobe. Não foi publicado um pacote incompleto.
- **Decisão comercial:** preço, licença desktop, ativação, suporte e política de atualização ainda não definidos. Stripe da web não foi convertido em licença desktop.
- **P2:** waveform detalhada, automação de volume e controles de fade. Não há waveform inventada nem botões que anunciem essas funções.
- **Motor legado:** a checagem pós-publicação encontrou um excesso de duração no renderizador PDF antigo: 60 s produziram 69,8 s no CI Ubuntu 26.04/FFmpeg 8.0.1 e 70 s em uma execução isolada no servidor com FFmpeg 7.1.5. A opção `-shortest` sozinha não limitava a saída à timeline. Foi aplicado o filtro `fps` para amostrar os frames esparsos do concat e acrescentado `-t` com a soma dos tempos já calculada pelo motor, mantendo API, schema, política de áudio e engine multitrack existentes. O teste de aceite foi endurecido para 59,8–60,2 s. A tentativa de fixar Ubuntu 24.04 foi descartada após a reprodução em produção; o CI continua no runner atual.

A publicação e a reversão estão registradas em [slidecast-deploy-2026-11-18.md](slidecast-deploy-2026-11-18.md).
