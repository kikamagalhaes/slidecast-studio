# Plano de Transição Web — Presença Comercial e Isolamento do Estúdio Web

**Data:** 18 de Novembro de 2026  
**Responsável:** Muse / Agi (Engenharia de Mídia, Backend e Infraestrutura)  
**Destinatários:** Kika Magalhães / Codex (Design, UX/UI, Landing Page)  
**Objetivo:** Transformar a presença web do SlideCast em uma **landing page comercial** para venda e download do **SlideCast Studio Desktop**, sem descartar infraestrutura, dados de clientes ou cobrança, e com reversibilidade auditável.

---

## 1. Princípios da Transição Comercial

1. **O Produto é o Desktop:** O SlideCast Desktop para Windows e Linux é o estúdio completo local. Não será mantido um estúdio web concorrente na nuvem.
2. **Preservação Absoluta dos Ativos:** Nenhuma tabela de banco de dados (`storage/slidecast.db`), histórico de renderizações, arquivos de clientes, contas de usuários ou integração com o Stripe (`stripe_billing.py`) será deletada.
3. **Desativação Reversível e por Configuração:** O acesso ao antigo estúdio web no navegador é controlado por variável de ambiente / flag de roteamento (`ENABLE_WEB_STUDIO=false`), permitindo reativá-lo para auditoria ou suporte a qualquer momento.
4. **Assunção da Rota Raiz (`/`):** A landing page comercial pública assume a rota `/` da web. Nenhum painel privado ou editor em nuvem fica exposto publicamente sem autenticação.
5. **Sem Decisões Comerciais Fictícias:** Não inventar modelos de licenciamento, chaves seriais, assinaturas ou preços que não tenham sido definidos comercialmente pela proprietária do produto.

---

## 2. Inventário de Recursos Web e Estratégia de Isolamento

### 2.1 Mapeamento das Rotas Atuais (`app/web/server.py`)

| Rota / Prefixo | Função Atual | Destino na Transição Comercial |
|---|---|---|
| `GET /` | Servia o estúdio web React (`static/studio/index.html`) ou Jinja legado | **Assume a Landing Page Comercial** construída pelo Codex. |
| `GET /studio` / `GET /studio/*` | Estúdio web no navegador | **Isolado sob flag** `ENABLE_WEB_STUDIO`. Se desativado, redireciona para `/` ou retorna 404 seguro. |
| `GET /api/health` | Healthcheck (ffmpeg, disco, jobs) | **Mantido** para monitoramento da VPS e Traefik. |
| `POST /api/auth/*` | Registro, login, logout, me | **Preservado**; tabelas de usuários e sessões mantidas intactas no SQLite. |
| `POST /api/billing/*` | Checkout, portal, webhooks Stripe | **Preservado**; contratos mantidos para futuras vendas/licenciamento desktop. |
| `POST /api/upload` `POST /api/projects/*` | Upload e renderização de PDF no servidor | **Desativado no tráfego público** (mantido internamente caso `ENABLE_WEB_STUDIO=true`). |
| `GET /api/jobs/*` | Status e download de vídeos web | **Preservado** em modo leitura para histórico de clientes existentes. |
| `GET /downloads/*` | **Nova rota comercial:** Download dos instaladores desktop (Windows/Linux) com checksum | **Novo contrato comercial** para distribuição dos instaladores. |

### 2.2 Flag de Ativação do Estúdio Web (`ENABLE_WEB_STUDIO`)

Para garantir segurança operacional e auditoria, implementa-se no servidor FastAPI:

```python
ENABLE_WEB_STUDIO = os.getenv("ENABLE_WEB_STUDIO", "false").lower() in ("true", "1", "yes")
```

- Quando `ENABLE_WEB_STUDIO=false` (padrão comercial):
  - A rota `/` serve os assets estáticos da landing page comercial (`app/web/static/landing/index.html`).
  - Rotas de edição no navegador retornam redirecionamento ou página informativa indicando que a experiência de produção é feita através do SlideCast Desktop.
  - A infraestrutura de worker e Redis não precisa receber novos jobs pesados de renderização em nuvem.
- Quando `ENABLE_WEB_STUDIO=true` (modo de homologação/auditoria interna):
  - O estúdio web histórico volta a responder em `/studio` para conferência técnica de projetos legados.

---

## 3. Infraestrutura, Portas e Simplificação do Deploy

### 3.1 Portas e Serviços Existentes

Conforme registrado nos documentos operacionais (`deploy-local-e-vps.md`):
- **Porta 8000:** FastAPI interno (Docker expose 8000).
- **Porta 5173:** Vite dev server local (`strictPort`, proxy `/api` -> `8000`).
- **Porta 6379:** Redis interno (sem porta pública no host).
- **Portas 80 / 443:** Traefik existente na VPS com certificado Let's Encrypt (`websecure`).

### 3.2 Simplificação Gradual da Infraestrutura

Na fase atual de transição:
1. **Não alterar nem desligar imediatamente containers em VPS:** O arquivo `compose.production.yml` existente permanece íntegro com os volumes `storage-data` e `redis-data`.
2. **Landing Page Estática / Híbrida:** A landing page construída pelo Codex pode ser servida diretamente pelo FastAPI na porta 8000 ou como build estático no Traefik.
3. **Economia de Recursos na VPS:** Como as renderizações multimídia pesadas passam a acontecer nas máquinas dos usuários (SlideCast Studio Desktop), a VPS deixa de sofrer com consumo extremo de CPU por FFmpeg, permitindo reduzir instâncias de workers RQ no futuro sem qualquer interrupção de serviço.

---

## 4. Distribuição de Instaladores Desktop (Downloads & Versões)

### 4.1 Estrutura de Artefatos de Download

A landing page comercial precisa oferecer links diretos e confiáveis para instalação. A estrutura padronizada de releases e metadados é:

```json
{
  "app_name": "SlideCast Studio Desktop",
  "latest_version": "1.2.0",
  "release_date": "2026-11-18",
  "platforms": {
    "linux": {
      "filename": "SlideCastStudio-Linux-x86_64.tar.gz",
      "url": "/downloads/SlideCastStudio-Linux-x86_64.tar.gz",
      "size_mb": 385,
      "sha256": "PENDENTE_BUILD_RELEASE",
      "os_requirements": "Ubuntu 22.04+, Debian 12+, Fedora 38+ (64-bit)"
    },
    "windows": {
      "filename": "SlideCastStudio-Windows-x64.zip",
      "url": "/downloads/SlideCastStudio-Windows-x64.zip",
      "size_mb": 410,
      "sha256": "PENDENTE_BUILD_RELEASE",
      "os_requirements": "Windows 10 / 11 (64-bit)"
    }
  }
}
```

### 4.2 Endpoint Público de Metadados: `GET /api/releases/latest`

Um endpoint JSON simples e determinístico informando as versões disponíveis e hashes dos pacotes para a landing page exibir os botões de download dinamicamente.

---

## 5. Licenciamento e Vendas: Fronteira Técnica

> [!IMPORTANT]
> **Não inventar cobrança nem planos fictícios.**

- O Stripe atual possui planos legados de minutos de renderização web (`PLAN_MONTHLY_RENDERS=30`) e trial de 14 dias em nuvem.
- **Isso não é uma licença desktop.**
- **Diretriz de engenharia:** Manter `stripe_billing.py` preservado. Quando a proprietária definir o modelo comercial desktop (compra avulsa vitalícia, licença anual, ativação por serial ou conta de usuário), a camada de validação será conectada ao endpoint `/api/billing/license` sem misturar cotas de computação em nuvem com o software desktop local.
