# Publicação — 18/11/2026 (America/Sao_Paulo)

## Publicado

Landing: https://kikamagalhaes.com.br/slidecast/

Servidor existente `srv1934414`, aplicação `/opt/slidecast`, projeto Compose `slidecast`. A publicação foi autorizada expressamente pela solicitante. O conector Hostinger não concluiu a consulta; foi usado o acesso SSH existente, após conferir host, serviços, rotas, armazenamento e fila. Não foram alterados DNS, certificado, Traefik, portas públicas ou outros projetos.

O build Docker gera a landing com base `/slidecast/static/landing/`. A raiz serve o site comercial; `/studio` fica desativado por padrão, via `ENABLE_WEB_STUDIO=false`. `PUBLIC_SITE_URL` define canonical e redireciona a raiz do domínio legado para o domínio principal. Autenticação, APIs, SQLite, Redis e armazenamento foram preservados.

## Backup e ativação

Backup privado no servidor: `/opt/slidecast/backups/ux-20261119T020221Z` (UTC, ainda 18/11 em São Paulo). Contém fonte anterior, configuração, cópia dos arquivos, backup consistente de SQLite e IDs das imagens/containers. Permissões restritas ao root. Não copiar `.env` para repositório ou relatórios.

Imagens anteriores preservadas: `slidecast-web:rollback-20261119T020221Z` e `slidecast-worker:rollback-20261119T020221Z`.

A fonte foi sincronizada sem `--delete`, excluindo `.env`, storage, backups, dependências locais e evidências. Comandos de ativação:

```bash
cd /opt/slidecast
docker compose --env-file .env -p slidecast -f compose.production.yml config --quiet
docker compose --env-file .env -p slidecast -f compose.production.yml build web
docker compose --env-file .env -p slidecast -f compose.production.yml up -d --no-deps web
```

Apenas o container web foi recriado (`1193c5eb8d3a`). Worker (`79e4180dbadd`), Redis (`8cc0fa31c79e`) e todos os demais containers mantiveram seus IDs. A mudança é de UI e roteamento web; o worker já executava o motor existente. Fila e registro de jobs ativos estavam vazios antes da operação; fila continuou vazia após.

Imagem web gerada: `sha256:6f1d360206e6fa4620549b96508aaadfd0f99e6212cb11487c2a460aeb8d098d` (manifest list). SHA256 de `app/web/server.py`, idêntico local/container: `31052a4602ef657ae862aaaffc3136fc237a857b74aeb71a2e187e14120673ec`.

## Verificação pública

Chromium/Playwright em sessão isolada, com HTTPS validado, larguras 1440, 768 e 390 px:

- HTTP 200, título correto e canonical para o endereço principal.
- Imagens reais, JS e CSS carregados; nenhum recurso HTTP com erro ou exceção JavaScript.
- Sem overflow horizontal; FAQ abre e CTA aponta para `#disponibilidade`.
- `/slidecast/api/health`: HTTP 200, `healthy`, FFmpeg disponível, zero jobs pendentes.
- `/slidecast/studio`: HTTP 404 conforme flag.
- `/slidecast/api/auth/me`: HTTP 401 sem sessão, como esperado.
- Raiz do host legado: HTTP 307 para o endereço principal.
- Web, worker e Redis saudáveis após a atualização.

Resultados estruturados: [producao-checks.json](evidencias/producao-checks.json). Capturas: [desktop](evidencias/producao-1440.png), [tablet](evidencias/producao-768.png), [celular](evidencias/producao-390.png).

## Reversão se necessária

Não executada: a verificação passou. Para restaurar a imagem anterior sem reconstruir nem mexer nos dados:

```bash
cd /opt/slidecast
docker image tag slidecast-web:rollback-20261119T020221Z slidecast-web:latest
# Restaurar compose.production.yml do source.tar.gz do backup, se também for preciso reverter as variáveis/rotas da aplicação.
docker compose --env-file .env -p slidecast -f compose.production.yml up -d --no-deps --no-build --force-recreate web
```

O source.tar.gz permite recuperar os arquivos anteriores. Uma eventual restauração de banco/arquivos exige avaliar as gravações posteriores ao backup; não substituir dados automaticamente. Não há migração destrutiva nesta entrega.

## Desktop e comercial

O redesign desktop e a documentação são entregues no código-fonte. Não foi criado um instalador novo nem uma licença comercial. A landing informa isso expressamente. A validação Windows/hardware e o empacotamento de ffprobe permanecem como requisitos para a próxima distribuição; ver [validação](slidecast-ux-validacao.md).

O ajuste posterior de CI fixa Ubuntu 24.04, mantendo o ambiente de teste alinhado ao build desktop. Ele não altera a imagem publicada. A falha observada no runner Ubuntu 26.04/FFmpeg 8 está registrada na validação; não houve alteração do renderizador legado.
