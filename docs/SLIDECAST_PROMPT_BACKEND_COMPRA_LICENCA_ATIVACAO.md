# Prompt para a IA responsável pelo backend — SlideCast Desktop

Você é responsável por concluir **compra, licenciamento e ativação do SlideCast Studio Desktop**, integrando a infraestrutura Python/FastAPI/Stripe existente ao aplicativo PySide6. Execute a implementação, os testes e o preparo da publicação; não entregue apenas uma proposta. Não refaça o editor, a landing ou o motor de mídia para implementar a licença. Preserve também a captura de duas áreas e a direção de aula pela linha do tempo integradas ao main em 19/11/2026.

## 1. Contexto confirmado e fronteira de trabalho

O produto principal é o desktop para Windows e Linux. A web é apresentação comercial e distribuição. Codex implementou os temas, editor PDF/MP4 com quatro faixas, landing e empacotamento. O refinamento mais recente remove bordas herdadas dos painéis e aumenta botões e áreas de clique. Preserve esse acabamento.

- Repositório: `https://github.com/kikamagalhaes/slidecast-studio`.
- Checkout canônico local: `/home/kika-magalhaes/Plataformas/slidecast/slidecast-studio`.
- Site público: `https://kikamagalhaes.com.br/slidecast/`.
- Desktop: `main.py`, `app/ui/`, `app/core/`.
- Landing: `frontend/src/landing.tsx`, `frontend/src/landing.css`.
- Distribuição: `.github/workflows/release.yml`, `slidecast.spec`, `scripts/fetch_ffmpeg.py`, `scripts/verify_bundle.py`.
- A release 1.2.0 introduz o novo desktop e FFmpeg/ffprobe empacotados. Confirme a release e seus artefatos no GitHub e em `docs/slidecast-distribuicao-validacao.md`; não reutilize links históricos como se fossem a versão nova.
- Os downloads são pacotes portáteis/aplicativo empacotado; não anuncie MSI, DEB ou RPM inexistentes.

A cobrança atual **não é uma licença desktop**. Ela controla uma assinatura do estúdio web, com trial/cotas de renderização. Não trate a cota mensal ou o trial histórico como uma decisão comercial sobre o aplicativo local.

A documentação `slidecast-web-transicao-comercial.md` contém planos e exemplos, inclusive `/api/billing/license`, `/downloads/*` e metadados ilustrativos. Esses trechos não provam que uma rota esteja implementada. A distribuição atual usa `/api/releases/latest` e `frontend/landing/public/releases.json`, com downloads reais hospedados nas Releases do GitHub. Leia o código atual e consulte as rotas reais antes de reutilizá-los.

## 2. Leia antes de editar

1. `docs/slidecast-editor-contract.md`.
2. `docs/slidecast-web-transicao-comercial.md`.
3. `docs/slidecast-ux-validacao.md` e `docs/slidecast-design-system.md`.
4. `docs/slidecast-deploy-2026-11-18.md` e `docs/slidecast-distribuicao-validacao.md`.
5. `app/web/server.py`, `app/web/auth.py`, `app/web/db.py`, `app/web/billing.py`, `app/web/stripe_billing.py` e testes correspondentes.
6. `compose.production.yml`, `Dockerfile`, pipeline CI/release e os arquivos atuais da landing.

Use branch/worktree própria a partir do `main` atual. Verifique mudanças concorrentes antes de editar arquivos compartilhados ou publicar; não sobrescreva o trabalho de interface/distribuição do Codex.

## 3. Decisões comerciais que ainda precisam ser fornecidas

No momento deste handoff, não foi informado um preço nem um modelo de licença desktop. **Não invente valores ou condições comerciais.** Verifique se a proprietária forneceu definições mais recentes; caso contrário, peça as decisões indispensáveis em uma pergunta curta e agrupada:

- Tipo de venda: compra avulsa, licença por prazo ou assinatura; preço, moeda, periodicidade e produto/Price ID reais no Stripe.
- Regras da licença: quantidade de dispositivos, transferência/desativação, uso offline, eventual período de avaliação e funcionalidades autorizadas por estado.
- Tratamento de cancelamento, reembolso, inadimplência, atualização e suporte; não publique garantias ou prazos não aprovados.

Enquanto aguarda, implemente o que independe desses valores em modo de teste, com parâmetros explícitos e venda de produção desativada. Não transforme uma ausência de configuração em preço zero, gratuidade, acesso vitalício ou trial arbitrário.

## 4. Reaproveitamento do backend atual

Há autenticação por conta e sessão em `app/web/auth.py`; rotas de registro/login/logout/me em `server.py`; integração Stripe com checkout, portal e webhook assinado em `stripe_billing.py`.

O SQLite contém `users`, `sessions`, `subscriptions`, `ownership`, `usage`, `webhook_events`, `projects`, `assets`, `durable_jobs`, `exports`, `preferences`, `automations` e controle de migrações. Preserve registros, relações, histórico e dados de clientes.

Implemente direitos de uso desktop separados das cotas do serviço web. Proponha e documente migrações aditivas para pedidos/pagamentos, licenças, ativações/dispositivos e auditoria conforme necessário. A autorização de uma licença deve vir do servidor e de pagamento confirmado, não de um parâmetro de URL ou de um booleano enviado pelo aplicativo.

O site público está sob `/slidecast/`; o Traefik remove esse prefixo antes de encaminhar ao FastAPI. Respeite `PUBLIC_SITE_URL` e a base real ao criar URLs de checkout, retorno, portal, login e API. Não use cegamente `APP_DOMAIN` do host legado nem o header Host para construir redirecionamentos comerciais.

## 5. Fluxos a implementar de ponta a ponta

### Compra e pagamento

- Conta autenticada identifica o comprador e consulta as ofertas realmente configuradas no servidor.
- Checkout usa o produto/preço autorizado; cliente não escolhe preço, moeda, direitos ou estado de pagamento arbitrários.
- Confirmação vem de webhook Stripe com assinatura válida; retorno do navegador mostra “aguardando confirmação” quando ainda necessário.
- Webhooks idempotentes e eventos fora de ordem não devem duplicar pedido/licença, reativar indevidamente licença revogada nem apagar histórico.
- Cancelamento, falha, reembolso e renovação atualizam direitos conforme as regras aprovadas, preservando o histórico.
- Conta/portal permitem consultar situação e administrar a compra quando aplicável. Use o SDK Stripe e verifique o comportamento real da versão instalada.

### Licença e ativação desktop

- Defina o contrato versionado de consulta, ativação, validação/renovação, desativação e transferência, com exemplos reais de request/response e códigos de erro.
- Associe cada ativação ao usuário e à licença corretos; imponha limite de dispositivos atomicamente, inclusive sob requisições concorrentes.
- Use identificador de instalação estável com coleta mínima de dados. Não dependa de serial de hardware sensível sem necessidade.
- Nenhuma chave privada de assinatura, secret key Stripe ou credencial administrativa pode entrar no executável, no JSON público ou no frontend.
- Se houver uso offline, use credencial verificável assinada e política explícita de validade/renovação. A chave pública pode estar no aplicativo; a privada permanece no servidor. Não implemente criptografia própria ou promessa de DRM inviolável.
- Trate expiração, indisponibilidade do servidor, relógio alterado, dispositivo desativado e revogação de forma coerente com a política aprovada. Documente os limites de revogação durante períodos offline.
- Armazene credenciais pelo mecanismo adequado do sistema operacional. Não grave senha em projeto `.slidecast`, não registre tokens em logs e não envie mídias de aula para validar licença.
- A perda de licença não pode apagar mídias ou projetos. Defina claramente o que fica disponível em cada estado, preservando acesso aos arquivos e ao trabalho salvo.

### Integração com o aplicativo e com a landing

- Acrescente uma área clara de conta/licença no PySide6 e estados humanos em português: ativar, ativo, pendente, expirado, limite atingido e sem conexão, conforme o contrato.
- Use `ThemeManager`, tokens e `apply_style`; preserve os temas, botões confortáveis e o isolamento de bordas dos painéis. Não recrie o editor e não introduza um frontend web dentro do desktop.
- A licença não pode bloquear a thread da interface; use o padrão de workers/sinais já existente. Evite interromper uma gravação ou destruir um render em andamento sem política e UX explícitas.
- Ligue CTAs comerciais da landing a telas/checkout reais somente após o fluxo estar implementado e configurado. Preserve screenshots e links de download publicados.
- As mídias continuam sendo processadas localmente. Não restaure o estúdio web como produto principal.

## 6. Segurança, testes e critérios de aceite

Inclua testes com dados sintéticos e Stripe em modo de teste, sem cobranças reais:

| Cenário | Resultado exigido |
|---|---|
| Compra confirmada | Uma licença vinculada ao comprador correto |
| Retorno de checkout sem webhook | Não concede licença indevidamente |
| Webhook inválido/repetido/fora de ordem | Rejeição ou processamento idempotente e coerente |
| Acesso a licença/dispositivo de outra conta | Negado, sem exposição de dados |
| Ativações simultâneas no limite | Limite respeitado atomicamente |
| Desativação e transferência | Estado persistente e direitos corretos |
| Expiração/renovação/cancelamento/reembolso | Regras aprovadas aplicadas e auditáveis |
| Offline, falha de rede e relógio | Estado previsível; nenhum projeto perdido |
| Token adulterado/replay/secret ausente | Não concede acesso por fallback inseguro |
| Migração em cópia do banco existente | Contas, projetos e histórico preservados |
| Qt claro/escuro e teclado | Novas telas legíveis, sem bordas herdadas ou controles espremidos |
| Pacotes Windows/Linux | Ativação e render funcionam com os binários distribuídos |

Execute a suíte existente, lint, build da landing e testes do pacote. Adicione apenas testes que comprovem comportamento e integração relevantes. Não afirme validar câmera/microfone físicos com testes offscreen. Não afirme venda de produção concluída usando somente mocks.

## 7. Produção e preservação

O servidor existente usa `/opt/slidecast`, Compose `-p slidecast -f compose.production.yml`, serviços `web`, `worker` e `redis`. A configuração e os dados existentes não devem ser sobrescritos por um `.env` local. Redis não tem porta pública. Outros projetos compartilham a VPS e o Traefik: não reinicie nem altere esses serviços.

Antes de migrar banco, faça backup consistente e teste a migração em uma cópia. Prepare reversão compatível com gravações posteriores ao backup; não restaure banco antigo automaticamente. Confira jobs ativos antes de atualizar o worker.

Publique somente código validado, com URLs/segredos reais configurados pelos canais autorizados. Se preço/modelo/credenciais comerciais ainda faltarem, mantenha a compra desativada e liste a informação exata que falta. Não invente um checkout funcional. Não envie mensagens a clientes nem realize cobranças para provar o fluxo sem instrução explícita.

## 8. Entrega obrigatória

1. Backend funcional de venda/licença e integração no desktop, conforme decisões aprovadas.
2. `docs/slidecast-licenciamento-contrato.md`: estados, endpoints, schema, regras de autorização e exemplos reais.
3. `docs/slidecast-licenciamento-operacao.md`: configuração por nomes de variáveis (sem valores secretos), migração, rotatividade de chaves, suporte, deploy e reversão.
4. Relatório de testes com resultados reais, limites e pendências discriminadas.
5. Resumo dos arquivos/commits, alterações comerciais na landing e nova versão dos pacotes se o desktop mudar.

Comece conferindo o estado atual do repositório e da distribuição, reutilize o que já existe e avance sem refazer a interface ou o motor de mídia.
