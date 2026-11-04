# Key management

Every secret Agnostic stores is sealed with envelope encryption: it gets its own random AES-256-GCM data key, and
the data key is wrapped by the **master key**. That covers instance JWT signing keys and security keys, client
certificate keys, IdP client secrets, TOTP secrets, git credentials, webhook secrets, SIEM and notification channel
credentials, the audit archive secret and the assistant's model key.

Each sealed value records the id of the master key that sealed it. The API and worker hold a **key ring**: they seal
with the current master key and open values sealed with any configured key, so a master key can be replaced without
downtime.

**Back up the master key.** It is not in the database. Without it every stored secret is lost: you would have to
reconnect instances, re-enter IdP secrets and recreate service-account tokens.

## Providers

`AGNOSTIC_SECRETS__PROVIDER` says where the master key comes from:

| Provider | `AGNOSTIC_SECRETS__MASTER_KEY` holds | The key is protected by |
|---|---|---|
| `local` (default) | the key itself, 32 bytes base64 | your secret store (Kubernetes Secret, Vault agent file, …) |
| `vault` | the key wrapped by a HashiCorp Vault or OpenBao Transit key (`vault:v1:…`) | Vault |
| `aws-kms` | the key wrapped by an AWS KMS key | AWS KMS |
| `azure-key-vault` | the key wrapped by an Azure Key Vault or Managed HSM RSA key (`<key version>:<value>`) | Azure Key Vault |
| `gcp-kms` | the key wrapped by a Cloud KMS key | Google Cloud KMS |

With a KMS provider, every API and worker process unwraps the master key once when it starts; sealing and opening
then happen in the process. A KMS outage stops processes from starting, never requests in flight. Every wrap is bound
to the context `agnostic/master-key/v1` (AWS encryption context `purpose`, GCP additional authenticated data), which a
key policy can require. All providers call the service's REST API; no vendor SDK is involved.

The key can also come from a file: `AGNOSTIC_SECRETS__MASTER_KEY_FILE`. Outside production, with no key set, a fixed
development key is used with a warning; production refuses to start.

### Settings

| Setting | Default | Notes |
|---|---|---|
| `AGNOSTIC_SECRETS__PROVIDER` | `local` | `local`, `vault`, `aws-kms`, `azure-key-vault`, `gcp-kms` |
| `AGNOSTIC_SECRETS__MASTER_KEY` / `__MASTER_KEY_FILE` | — | the current key (wrapped for a KMS provider) |
| `AGNOSTIC_SECRETS__PREVIOUS_KEYS` / `__PREVIOUS_KEYS_FILE` | — | retired keys, comma-separated or one per line (`#` comments allowed in the file) |

**Vault / OpenBao Transit**

| Setting | Default | Notes |
|---|---|---|
| `AGNOSTIC_SECRETS__VAULT__ADDRESS` | `VAULT_ADDR` | `https://vault.example.com:8200` |
| `AGNOSTIC_SECRETS__VAULT__NAMESPACE` | `VAULT_NAMESPACE` | Vault Enterprise namespace |
| `AGNOSTIC_SECRETS__VAULT__MOUNT` | `transit` | |
| `AGNOSTIC_SECRETS__VAULT__KEY_NAME` | `agnostic` | |
| `AGNOSTIC_SECRETS__VAULT__AUTH` | `token` | `token`, `kubernetes` or `approle` |
| `AGNOSTIC_SECRETS__VAULT__AUTH_MOUNT` | the method name | |
| `AGNOSTIC_SECRETS__VAULT__TOKEN` / `__TOKEN_FILE` | `VAULT_TOKEN` | token auth |
| `AGNOSTIC_SECRETS__VAULT__ROLE` | — | Kubernetes auth role |
| `AGNOSTIC_SECRETS__VAULT__KUBERNETES_TOKEN_FILE` | the pod's service-account token | |
| `AGNOSTIC_SECRETS__VAULT__ROLE_ID`, `__SECRET_ID` / `__SECRET_ID_FILE` | — | AppRole |
| `AGNOSTIC_SECRETS__VAULT__TLS__CA_FILE`, `__CERT_FILE`, `__KEY_FILE` | — | TLS to Vault |

**AWS KMS**

| Setting | Default | Notes |
|---|---|---|
| `AGNOSTIC_SECRETS__AWS__KEY_ID` | — | key id, key ARN or alias ARN |
| `AGNOSTIC_SECRETS__AWS__REGION` | `AWS_REGION`, `AWS_DEFAULT_REGION`, or the key ARN's region | |
| `AGNOSTIC_SECRETS__AWS__ENDPOINT` | `https://kms.<region>.amazonaws.com` | VPC or FIPS endpoints |
| `AGNOSTIC_SECRETS__AWS__ACCESS_KEY_ID`, `__SECRET_ACCESS_KEY`, `__SESSION_TOKEN` | the `AWS_*` variables | static credentials |
| `AGNOSTIC_SECRETS__AWS__ROLE_ARN`, `__WEB_IDENTITY_TOKEN_FILE` | `AWS_ROLE_ARN`, `AWS_WEB_IDENTITY_TOKEN_FILE` | web identity (IRSA on EKS) through STS |
| `AGNOSTIC_SECRETS__AWS__STS_ENDPOINT` | `https://sts.<region>.amazonaws.com` | |
| `AGNOSTIC_SECRETS__AWS__TLS__*` | — | |

**Azure Key Vault**

| Setting | Default | Notes |
|---|---|---|
| `AGNOSTIC_SECRETS__AZURE__VAULT_URL` | — | `https://<vault>.vault.azure.net` or a Managed HSM URL |
| `AGNOSTIC_SECRETS__AZURE__KEY_NAME`, `__KEY_VERSION` | — | the version pins wrapping; unwrapping uses the version stored with the wrap |
| `AGNOSTIC_SECRETS__AZURE__ALGORITHM` | `RSA-OAEP-256` | or `RSA-OAEP` |
| `AGNOSTIC_SECRETS__AZURE__TENANT_ID`, `__CLIENT_ID` | `AZURE_TENANT_ID`, `AZURE_CLIENT_ID` | |
| `AGNOSTIC_SECRETS__AZURE__CLIENT_SECRET` | `AZURE_CLIENT_SECRET` | client-secret credentials |
| `AGNOSTIC_SECRETS__AZURE__FEDERATED_TOKEN_FILE` | `AZURE_FEDERATED_TOKEN_FILE` | workload identity (AKS) |
| `AGNOSTIC_SECRETS__AZURE__MANAGED_IDENTITY` | `false` | the VM's or pod's managed identity |
| `AGNOSTIC_SECRETS__AZURE__AUTHORITY_HOST` | `https://login.microsoftonline.com` | sovereign clouds |
| `AGNOSTIC_SECRETS__AZURE__TLS__*` | — | |

**Google Cloud KMS**

| Setting | Default | Notes |
|---|---|---|
| `AGNOSTIC_SECRETS__GCP__KEY_NAME` | — | `projects/<p>/locations/<l>/keyRings/<r>/cryptoKeys/<k>` |
| `AGNOSTIC_SECRETS__GCP__CREDENTIALS_FILE` | `GOOGLE_APPLICATION_CREDENTIALS` | a service-account key; without one, the metadata server (GKE workload identity) |
| `AGNOSTIC_SECRETS__GCP__ENDPOINT` | `https://cloudkms.googleapis.com` | |
| `AGNOSTIC_SECRETS__GCP__TLS__*` | — | |

`AGNOSTIC_TLS__CA_FILE` is trusted for KMS calls too.

## Commands

| Command | Does |
|---|---|
| `agnostic secrets generate-key [--provider P]` | prints a new random master key, wrapped by the configured (or named) provider |
| `agnostic secrets wrap-key --to P` | unwraps the configured current and previous keys and prints them wrapped for provider `P` (or a newer KMS key version); the keys themselves don't change |
| `agnostic secrets status` | lists every sealed column with the number of values per master-key id; exits 1 when a value needs a key that isn't configured |
| `agnostic secrets rotate` | re-seals every stored value with the current key, in batches; safe to stop and run again |

`agnostic config check --connect` reports the provider, the current key id and the previous ones.

## Move to a KMS (same key)

1. Create the KMS key and give the API's and worker's identity encrypt and decrypt on it.
2. `agnostic secrets wrap-key --to vault` (with the new provider's settings in the environment) prints the wrapped
   current key and the wrapped previous keys.
3. Set `AGNOSTIC_SECRETS__PROVIDER`, the provider's settings, and replace `AGNOSTIC_SECRETS__MASTER_KEY` (and
   `__PREVIOUS_KEYS`) with the wrapped values. Roll out. Nothing needs re-sealing.

The same command re-wraps with a newer KMS key version after you rotate the KMS key.

## Rotate the master key

1. `agnostic secrets generate-key` and store the new value with your backups.
2. Configure it as `AGNOSTIC_SECRETS__MASTER_KEY` and move the old one to `AGNOSTIC_SECRETS__PREVIOUS_KEYS`.
3. Roll out the API and workers. New values are sealed with the new key; old ones still open.
4. `agnostic secrets rotate`, then `agnostic secrets status` until it says *every value uses the current key*.
5. Wait until service-account gateway tokens have been used once (see below), then remove the previous key and roll
   out again.

Values in the cache (pending MFA enrolments, cached git tokens) expire on their own within a day; keep the previous
key at least that long.

### Service-account tokens

Gateway tokens of service accounts are stored as hashes peppered with a value derived from the master key. After a
rotation, a token is looked up with the current pepper, then with the previous keys' peppers, and re-hashed with the
current one on its first use. Tokens not used before the previous key is removed stop working. To make them
independent of the master key, set `AGNOSTIC_SERVICE_ACCOUNTS__TOKEN_PEPPER` (any long random string) before
creating tokens.

## Try it locally

`just vault-up` starts an OpenBao server (the Vault Transit API) in the dev stack with a key named `agnostic`:

```bash
just vault-up
export AGNOSTIC_SECRETS__PROVIDER=vault AGNOSTIC_SECRETS__VAULT__ADDRESS=http://127.0.0.1:8200 \
       AGNOSTIC_SECRETS__VAULT__TOKEN=dev-root-token
cd backend && uv run agnostic secrets generate-key
```
