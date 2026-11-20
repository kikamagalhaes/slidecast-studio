# Distribuição desktop e refinamento visual — 19/11/2026

## Escopo

Versão desktop 1.2.0: temas claro/escuro, editor PDF/MP4 com quatro faixas, gravação, captura em duas áreas e direção de aula por intervalos. O código de captura/direção integrado por outra frente foi preservado. O acabamento adicional corrige estilos de painéis herdados pelos filhos, reduz bordas decorativas a 1 px, amplia botões e organiza os campos da captura/direção em grades sem rolagem horizontal a 1280 px.

Fonte desktop preparada: `143cef1baacdd28a3021a091e95715feb72eba69`. A publicação é feita pelo workflow Desktop release, que só cria a release após os três sistemas passarem pelo teste do executável empacotado. Os dados finais dos arquivos constam em `evidencias/distribuicao/release-metadata.json`.

## Empacotamento e verificações

- FFmpeg completo e ffprobe são incluídos como binários PyInstaller, com dependências compartilhadas coletadas. O aplicativo congelado prioriza as ferramentas internas; execução pelo código-fonte mantém o comportamento de PATH.
- A versão compacta do FFmpeg do imageio foi substituída porque não oferecia PulseAudio. O teste agora exige `pulse`/`x11grab` no Linux, `dshow`/`gdigrab` no Windows e `avfoundation` no macOS.
- O Windows usa o arquivo oficial distribuído pela Gyan, com SHA256 fixado no workflow. Linux usa Ubuntu 24.04; macOS usa o runner 15 Apple Silicon. O runner macOS 14 foi substituído após sua retirada pelo GitHub.
- O teste executa o próprio bundle com PATH vazio no Linux/macOS e restrito ao System32 no Windows, sem overrides de FFmpeg/Python do desenvolvedor.
- São gerados MP4s reais a partir de PDF e MP4 com quatro faixas, validados por ffprobe; o projeto é salvo/reaberto e a janela Qt é desenhada em ambos os temas.
- A verificação local do bundle Linux passou com FFmpeg/ffprobe 6.1.1: PDF e MP4 de 2,0 s, 320×180, áudio presente e módulos de captura disponíveis.

Referências primárias de distribuição: [FFmpeg](https://ffmpeg.org/download.html), [Gyan](https://www.gyan.dev/ffmpeg/builds/), [runners oficiais do GitHub](https://github.com/actions/runner-images).

## Interface e testes locais

A suíte final passou com **229 testes** em 146,73 s, após a integração dos recursos e dos ajustes. A validação direcionada anterior passou com 50 testes de desktop, gravação, direção e roteamento. Ruff e build TypeScript/Vite passaram. Há um aviso de depreciação do TestClient/httpx, sem falhas.

Capturas reais Qt: `evidencias/refino-claro/` e `evidencias/refino-escuro/`. Incluem painéis de aula, menu, editor, estúdio, captura em duas áreas e direção por linha do tempo. As amostras de mídia são sintéticas; não se trata de gravação de câmera/microfone físico. A interface também foi conferida a 1280×800 e escala 150% em cenários de estúdio.

## Site e disponibilidade

A landing usa `frontend/landing/public/releases.json`, copiado para o build e servido também por `GET /api/releases/latest`. O campo `status` controla a exposição dos downloads. Em preparação, não há botões que levem a arquivos ainda inexistentes. Na publicação, versão, data, tamanho e SHA256 devem vir dos assets reais da release, e cada relatório de self-test deve estar aprovado.

A landing não anuncia preço, gratuidade, trial ou licença comercial não definidos. Compra/ativação continuam como trabalho do backend, descrito no [prompt de implementação](SLIDECAST_PROMPT_BACKEND_COMPRA_LICENCA_ATIVACAO.md).

## Produção e reversão

Servidor existente, `/opt/slidecast`, Compose `slidecast`. Backup desta etapa: `/opt/slidecast/backups/distribution-20261119T201601Z`, restrito ao root, com landing anterior, fonte, cópia consistente do banco, imagens e IDs dos containers. Imagem web anterior preservada pela tag `slidecast-web:rollback-distribution-20261119T201601Z`.

Antes da distribuição, o site foi corrigido para mostrar o estado de preparação: Chromium a 390 px confirmou dois avisos de preparação, zero links para assets ainda não publicados e ausência de overflow horizontal. Essa correção estática emergencial foi incorporada à imagem final na ativação. Configuração, dados, Redis, worker e demais aplicações são preservados.

## Limites

Pacotes portáteis/aplicativo empacotado, sem assistente MSI/DEB/RPM nem assinatura comercial de código. Compatibilidade mínima anunciada: Windows 10/11 x64, Ubuntu 24.04 x64 (glibc 2.39), macOS 15 Apple Silicon. Os runners comprovam funcionamento automatizado; não substituem homologação com câmera, microfone, monitores, permissões e drivers físicos. No Linux, captura de tela usa X11; ambientes Wayland podem exigir sessão X11.

## Resultado final

A [release v1.2.0](https://github.com/kikamagalhaes/slidecast-studio/releases/tag/v1.2.0) foi publicada em 2026-11-19T20:34:19Z, com nove assets: três pacotes, três arquivos SHA256 e três relatórios. O [workflow de distribuição](https://github.com/kikamagalhaes/slidecast-studio/actions/runs/44607195571) terminou com sucesso nas três plataformas e na publicação. A etapa Linux foi retomada após lentidão no espelho de pacotes Ubuntu; os artefatos Windows/macOS aprovados foram preservados. O [CI da fonte desktop](https://github.com/kikamagalhaes/slidecast-studio/actions/runs/44607177905) também passou.

| Plataforma | Tamanho real (bytes) | SHA256 |
|---|---:|---|
| Windows 10/11 x64 | 182756566 | `1cee67ee08d5295f5b1eb5102e7da0a0623145fdce449e437b3df7f5ee3bb37a` |
| Ubuntu 24.04 x64 | 233132205 | `71dd69965a024bbe5bb8889fd5c04fd22502d88b9be49ac8bd45bf218fbe36de` |
| macOS 15 Apple Silicon | 118215924 | `782d6121acb93bb8fbefdab5f2bccc5048f55d2ed4f7500c896c7f0e6596d4f7` |

Os SHA256 publicados coincidem com os digests dos assets no GitHub. Os três downloads públicos responderam HTTP 200 com o tamanho esperado. O TAR.GZ Linux foi baixado integralmente do endereço público, conferido por SHA256, extraído e executado com o verificador de bundle: **aprovado**, com PDF/MP4 de 2,0 s, áudio, dois temas e módulos de captura. Evidência: `evidencias/distribuicao/linux-download-self-test.json`.

Ativação web concluída no commit `21e49fa`. Conferência pública em 2026-11-20T00:37:13.239Z:

- Chromium nas larguras 1440, 768 e 390 px: HTTP 200, canonical correto, imagens carregadas, FAQ funcional, dois downloads reais, botões com pelo menos 48 px de altura e nenhum overflow horizontal ou erro JavaScript/recurso.
- `/api/releases/latest` idêntico ao manifesto conferido. `/api/health`: healthy, zero jobs pendentes. `/studio`: 404; `/api/auth/me` sem sessão: 401.
- Somente o container web foi recriado; **23 containers** mantiveram seus IDs, incluindo worker e Redis. Os três serviços SlideCast estão saudáveis.
- Container web: `88d6958e169f9eb4b965c93fd8a59713e2c1a4e7e178071622f3dc24015c8a16`.
- Imagem web: `sha256:7012a3b0bfa6cd9e79161d8ab5d6edda1a75485321c93e2e6ace23e466fa8524`.
- Evidências: `evidencias/distribuicao/producao-checks.json`, screenshots por viewport e `downloads-publicados.png`.

Compra, licença e ativação desktop continuam pendentes da implementação descrita no prompt do backend. Nenhuma condição comercial foi inventada.


