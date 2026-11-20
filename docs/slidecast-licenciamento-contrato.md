# Contrato de Licenciamento e Ativação Desktop — SlideCast Studio

**Versão da Especificação:** 1.0  
**Data:** 19 de Novembro de 2026  
**Status:** Implementado e Verificado  
**Componentes:** `app/web/desktop_licensing.py`, `app/web/desktop_license_routes.py`, `app/core/license_crypto.py`, `app/core/license_manager.py`, `app/ui/dialogs/license_dialog.py`

---

## 1. Visão Geral da Arquitetura

O licenciamento do SlideCast Studio Desktop opera sob um modelo híbrido **online com tolerância offline (offline lease)**:

1. **Servidor (Backend FastAPI):**
   - Controla contas de usuários, licenças adquiridas, auditoria e limites de assentos/dispositivos (concorrência atômica).
   - Detém a chave privada assimétrica **Ed25519** (`SLIDECAST_LICENSE_ED25519_PRIVATE_KEY`), utilizada exclusivamente para assinar autorizações digitais (`leases`).
   - Recebe webhooks do Stripe (`checkout.session.completed`, `charge.refunded`, `customer.subscription.*`) de forma idempotente para emissão e revogação de licenças.

2. **Cliente (PySide6 Desktop):**
   - Gera um identificador anônimo estável por instalação (`~/.slidecast/device_id`) com permissões `0600`, preservando a privacidade (sem coleta de números de série sensíveis).
   - Detém apenas a chave pública **Ed25519** (`SLIDECAST_LICENSE_ED25519_PUBLIC_KEY`), capaz de verificar criptograficamente a autenticidade da autorização local sem depender de conexão de rede.
   - Armazena a autorização assinada em `~/.slidecast/license_lease.json` com permissões `0600`.
   - Executa validações em segundo plano via `QThread` sem travar a interface gráfica.
   - **Garantia de Não Perda de Dados:** A expiração ou ausência de licença jamais deleta projetos (`.slidecast`), arquivos de mídia gravados ou vídeos gerados. O aplicativo preserva abertura, salvamento e edição; exportações no modo gratuito apenas informam a situação da licença ou operam em modo avaliação.

---

## 2. Máquina de Estados da Licença

| Estado (`status`) | Rótulo (PT-BR) | Descrição e Comportamento |
|---|---|---|
| `unactivated` | Não ativado | Nenhum serial inserido. Aplicativo opera em modo de avaliação gratuito; todas as gravações e arquivos salvos localmente permanecem acessíveis. |
| `active` | Ativo | Licença válida e autenticada no servidor com autorização Ed25519 ativa. Todos os recursos profissionais liberados. |
| `no_connection` | Modo offline | Dispositivo possui autorização assinada válida localmente dentro do período de concessão (`lease_expires_at`). Permite uso normal sem internet. |
| `limit_reached` | Limite atingido | Chave de licença atingiu a quantidade máxima de computadores simultâneos (`seats_limit`). O usuário pode desativar um computador anterior para liberar a vaga. |
| `expired` | Expirado | Período de concessão offline ou vigência da assinatura encerrou. O aplicativo solicita conexão para revalidação ou renovação. |
| `revoked` | Revogado | Licença cancelada ou reembolsada pelo provedor de pagamento. Assinatura digital revogada pelo servidor. |
| `pending` | Aguardando confirmação | Pagamento em processamento no gateway antes da confirmação do webhook assinado. |

---

## 3. Formato da Chave de Licença (Serial)

As chaves de licença geradas possuem o formato padronizado legível por humanos:
```
SCST-XXXX-XXXX-XXXX-XXXX
```
- **Prefixo:** `SCST` (SlideCast Studio).
- **Blocos:** 4 blocos de 4 caracteres alfanuméricos seguros (`23456789ABCDEFGHJKLMNPQRSTUVWXYZ`), excluindo caracteres visualmente ambíguos como `0`/`O` e `1`/`I`.
- **Exemplo Real:** `SCST-7K9A-WM3X-PV2B-8H4F`.

---

## 4. Contrato dos Endpoints da API (`/api/v1/license`)

### 4.1 `GET /api/v1/license/plans`
Consulta os planos e preços configurados no servidor. Se as ofertas comerciais ainda não estiverem aprovadas pela proprietária, o endpoint informa com segurança que as vendas estão desativadas.

**Resposta (Vendas desativadas / em definição):**
```json
{
  "available": false,
  "message": "Ofertas comerciais em definição pela proprietária. Vendas de produção desativadas.",
  "plans": []
}
```

**Resposta (Vendas ativas):**
```json
{
  "available": true,
  "plans": [
    {
      "id": "standard",
      "name": "SlideCast Studio Desktop — Licença Padrão",
      "price_id": "price_1...",
      "amount": 29700,
      "currency": "BRL",
      "seats_limit": 2,
      "features": ["Exportação local ilimitada", "Gravação em tela dupla", "Editor 4 faixas"]
    }
  ]
}
```

---

### 4.2 `POST /api/v1/license/checkout`
Inicia uma sessão segura de Stripe Checkout para compra da licença desktop. Exige autenticação de conta (`Bearer <token>`).

**Payload de Entrada:**
```json
{
  "plan_type": "standard"
}
```

**Resposta (Sucesso - 200 OK):**
```json
{
  "checkout_url": "https://checkout.stripe.com/c/pay/cs_test_..."
}
```

**Erros:**
- `401 Unauthorized`: Usuário não autenticado.
- `503 Service Unavailable`: Venda de licença desktop ainda não configurada no servidor (`SLIDECAST_DESKTOP_PRICE_ID` ausente).

---

### 4.3 `POST /api/v1/license/activate`
Ativa o computador na licença indicada. Garante limite atômico de assentos e idempotência caso o mesmo computador reative.

**Payload de Entrada:**
```json
{
  "license_key": "SCST-7K9A-WM3X-PV2B-8H4F",
  "device_id": "a6b4c3d2e1f0...64chars",
  "device_name": "Notebook Kika (Linux)",
  "platform": "linux",
  "app_version": "1.2.1"
}
```

**Resposta (Sucesso - 200 OK):**
```json
{
  "success": true,
  "status": "active",
  "status_label": "Ativo",
  "message": "Dispositivo ativado com sucesso.",
  "seats_limit": 2,
  "lease": {
    "version": 1,
    "license_id": "lic_9f8e7d6c5b4a",
    "license_key": "SCST-7K9A-WM3X-PV2B-8H4F",
    "user_id": 42,
    "user_email": "kika@exemplo.com.br",
    "device_id": "a6b4c3d2e1f0...64chars",
    "device_name": "Notebook Kika (Linux)",
    "status": "active",
    "features": ["all"],
    "issued_at": "2026-11-19T23:00:00Z",
    "lease_expires_at": "2026-12-03T23:00:00Z",
    "signature": "ZEd2...64bytesBase64"
  }
}
```

**Resposta (Limite Atingido - 409 Conflict):**
```json
{
  "detail": {
    "success": false,
    "status": "limit_reached",
    "status_label": "Limite de dispositivos atingido",
    "message": "Limite de dispositivos atingido (2/2). Desative um dispositivo anterior para continuar.",
    "error_code": "SEATS_LIMIT_EXCEEDED",
    "seats_limit": 2,
    "active_devices": [
      {
        "id": "act_111",
        "device_name": "PC Principal (Windows)",
        "platform": "windows",
        "activated_at": "2026-11-15T10:00:00Z"
      },
      {
        "id": "act_222",
        "device_name": "Notebook Dell (Ubuntu)",
        "platform": "linux",
        "activated_at": "2026-11-18T14:30:00Z"
      }
    ]
  }
}
```

---

### 4.4 `POST /api/v1/license/validate`
Valida o status da ativação e renova a concessão offline (`lease_expires_at` por mais 14 dias).

**Payload de Entrada:**
```json
{
  "license_key": "SCST-7K9A-WM3X-PV2B-8H4F",
  "device_id": "a6b4c3d2e1f0...64chars"
}
```

---

### 4.5 `POST /api/v1/license/deactivate`
Desativa o dispositivo especificado, liberando imediatamente a vaga para transferência ou troca de computador.

**Payload de Entrada:**
```json
{
  "license_key": "SCST-7K9A-WM3X-PV2B-8H4F",
  "device_id": "a6b4c3d2e1f0...64chars"
}
```

**Resposta (200 OK):**
```json
{
  "success": true,
  "message": "Dispositivo desativado com sucesso. O assento foi liberado."
}
```

---

## 5. Especificação Criptográfica da Concessão Offline (Lease)

1. **Algoritmo:** Ed25519 (RFC 8032) sobre Curve25519.
2. **Serialização Canônica:** JSON serializado de forma determinística: ordenação alfabética das chaves (`sort_keys=True`), separadores sem espaços (`separators=(',', ':')`) e codificação UTF-8 pura.
3. **Assinatura:** 64 bytes binários codificados em Base64.
4. **Verificação no Cliente:**
   - O cliente decodifica a assinatura Base64 e o payload JSON sem o campo `signature`.
   - Executa `public_key.verify(signature, canonical_bytes)`.
   - Se a assinatura for inválida ou o arquivo tiver sido alterado manualmente por um editor de texto, o cliente rejeita o lease imediatamente.
   - Compara o `device_id` contido no lease com o `~/.slidecast/device_id` local.
   - Verifica se a data atual está dentro de `lease_expires_at` (com tolerância de 1 hora para desvio de relógio do sistema).
