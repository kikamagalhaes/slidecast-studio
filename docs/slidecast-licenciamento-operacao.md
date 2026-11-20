# Operação, Configuração e Suporte do Licenciamento — SlideCast Studio

**Data:** 19 de Novembro de 2026  
**Responsável Técnico:** Muse / Agi (Engenharia de Mídia e Backend)  
**Ambiente de Produção:** Hostinger VPS `179.199.133.126`, `/opt/slidecast`

---

## 1. Variáveis de Ambiente e Configuração

Todas as variáveis sensíveis são injetadas exclusivamente via `.env` do servidor de produção ou segredos de ambiente. Nenhuma chave secreta ou privada é compilada dentro do binário cliente.

| Variável | Obrigatória | Onde Atua | Descrição |
|---|:---:|---|---|
| `SLIDECAST_LICENSE_ED25519_PRIVATE_KEY` | Sim (Prod) | Servidor FastAPI | Chave privada Ed25519 em Base64 para assinatura de autorizações. |
| `SLIDECAST_LICENSE_ED25519_PUBLIC_KEY` | Opcional | Cliente e Servidor | Chave pública Ed25519 em Base64. Embutida com valor padrão seguro no aplicativo; permite rotação por override. |
| `SLIDECAST_DESKTOP_PRICE_ID` | Sim (Venda) | Servidor FastAPI | ID do produto/preço no Stripe (`price_...`) para venda da licença desktop. Quando ausente, a venda permanece desativada (503 seguro). |
| `SLIDECAST_DESKTOP_PRICE_AMOUNT` | Opcional | Servidor / Landing | Valor da licença em centavos (ex.: `29700` para R$ 297,00). |
| `SLIDECAST_DESKTOP_PRICE_CURRENCY` | Opcional | Servidor | Moeda da licença (`BRL`, `USD`). Padrão: `BRL`. |
| `SLIDECAST_DESKTOP_SEATS_LIMIT` | Opcional | Servidor | Quantidade padrão de computadores permitidos por licença. Padrão: `2`. |
| `SLIDECAST_DESKTOP_CHECKOUT_MODE` | Opcional | Servidor | Modo do Stripe Checkout: `payment` (compra avulsa/vitalícia) ou `subscription` (recorrente). Padrão: `payment`. |
| `STRIPE_SECRET_KEY` | Sim (Stripe) | Servidor FastAPI | Chave secreta da API do Stripe (`sk_live_...` ou `sk_test_...`). |
| `STRIPE_WEBHOOK_SECRET` | Sim (Stripe) | Servidor FastAPI | Segredo de assinatura de webhooks do Stripe (`whsec_...`). |
| `PUBLIC_SITE_URL` | Sim | Servidor / Cliente | URL base pública do serviço (`https://kikamagalhaes.com.br/slidecast/`). |

---

## 2. Geração e Rotação de Par de Chaves Ed25519

Para gerar um novo par de chaves assimétricas Ed25519 seguro para o servidor:

```bash
python3 -c "
from app.core import license_crypto
priv, pub = license_crypto.generate_keypair()
print('SLIDECAST_LICENSE_ED25519_PRIVATE_KEY=' + priv)
print('SLIDECAST_LICENSE_ED25519_PUBLIC_KEY=' + pub)
"
```

### Procedimento de Rotação sem Interrupção:
1. No release de atualização do aplicativo, adicione a nova chave pública mantendo a chave anterior como alternativa válida de verificação.
2. Atualize `SLIDECAST_LICENSE_ED25519_PRIVATE_KEY` no `.env` do servidor.
3. No próximo ciclo de revalidação online (`POST /api/v1/license/validate`), todos os clientes ativos receberão novos leases assinados com a nova chave privada.

---

## 3. Migração do Banco de Dados SQLite

A migração de esquema versão 2 adiciona de forma aditiva:
- Tabela `desktop_licenses` (chaves, status, assentos, expiração, metadados);
- Tabela `desktop_activations` (dispositivos, leases, datas de validação e desativação);
- Tabela `desktop_license_audit` (registro imutável de todas as ações de licença).

### Execução Segura em Produção:
```bash
# 1. Backup consistente com timestamp
sqlite3 /opt/slidecast/storage/slidecast.db ".backup '/opt/slidecast/backups/slidecast_pre_lic_$(date +%Y%m%d_%H%M%S).db'"

# 2. As migrações são aplicadas automaticamente na inicialização do serviço web via `apply_migrations(conn)`.
# Para conferir manualmente:
python3 -c "
from app.web import db
conn = db.connect('/opt/slidecast/storage/slidecast.db')
print([r[0] for r in conn.execute(\"SELECT version FROM schema_migrations\")])
"
```

---

## 4. Procedimentos de Suporte ao Cliente

### 4.1 Cliente Atingiu o Limite de Computadores (`SEATS_LIMIT_EXCEEDED`):
- **Causa:** O cliente instalou o SlideCast em mais computadores do que o contratado (padrão: 2).
- **Solução Autônoma pelo Cliente:** No computador que não será mais utilizado, o cliente abre a janela **Licença** e clica em **"Desativar este computador"**. A vaga é liberada instantaneamente.
- **Suporte Administrativo:** Caso o computador antigo tenha queimado ou sido formatado, o administrador pode liberar a vaga no banco:
  ```sql
  UPDATE desktop_activations
  SET status = 'deactivated', deactivated_at = datetime('now')
  WHERE license_id = 'lic_...' AND device_id = '...';
  ```

### 4.2 Emissão Manual de Chave de Cortesia / Teste / Imprensa:
```python
from app.web import desktop_licensing

# Cria uma licença com 2 assentos vinculada ao e-mail informado
lic = desktop_licensing.create_license(
    user_id=1,  # ID do usuário ou admin
    plan_type="parceria",
    seats_limit=2,
    metadata={"origem": "cortesia_lancamento"}
)
print("Chave gerada:", lic["license_key"])
```

---

## 5. Reversão e Contingência (Rollback)

- As tabelas de licença são **aditivas** e não alteram a estrutura de `users`, `sessions`, `projects` ou arquivos de mídia.
- Em caso de falha de rede ou indisponibilidade do backend de ativação, o aplicativo local entra automaticamente no estado `no_connection`, permitindo o uso normal com a autorização offline salva localmente até o encerramento do prazo de tolerância (14 dias).
