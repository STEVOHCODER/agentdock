# Oracle Cloud deployment

The OCI CLI is installed on this machine (`C:\oci-cli\Scripts\oci.exe`, version 3.96.3) and a `DEFAULT` profile exists in `~/.oci/config`. Preflight validated authentication by reading the object-storage namespace. No deployment has been launched.

## Verified locally

Environment discovered on this machine: region `eu-amsterdam-1`, availability domain `loen:eu-amsterdam-1-AD-1`, a public subnet `10.0.0.0/24`, and Canonical Ubuntu 24.04 images. `VM.Standard.E4.Flex` returned **Out of host capacity**; `VM.Standard.E5.Flex` launched successfully. The helper defaults to E5 Flex now.

```powershell
.\deploy\oracle\preflight.ps1 -Profile DEFAULT
```

This reports the CLI version, namespace and available compartments. Set `OCI_COMPARTMENT_ID` to also list compute shapes in that compartment.

## Deployed status

| Item | Value |
|---|---|
| Public URL | https://agentdock.link |
| Region | eu-amsterdam-1 |
| Availability domain | loen:eu-amsterdam-1-AD-1 |
| Shape | VM.Standard.E5.Flex (2 OCPU, 8 GB) |
| Image | Canonical Ubuntu 24.04, OCID `ocid1.image.oc1.eu-amsterdam-1.aaaaaaaautl7jrev66a22aft7qj7dutjcy7ojv5usu2vtrlse7hvq2shu3ra` |
| Repo | https://github.com/STEVOHCODER/agentdock |
| Health | `GET https://agentdock.link/api/health` returns 200 |
| Skills | 43 approved; imported set includes the 26 `igura-marketplace/.agents/skills/*` skills and the root `master-ui-engine/SKILL.md` |
| Payments | Manual invoice is the active provider; Paddle/Flutterwave/UrubutoPay are visible but awaiting credentials |

The deployed administrator email is `admin@agentdock.ai`. The password is stored in `.env.production` on this machine; it was generated with `python tmp_secrets2.py` output and is also the startup bootstrap password. If you need a fresh one, run that script again and update the admin user's email/password in Oracle SQL.

## Inputs you still need

The deployment helper requires these values. They are not stored in the repository:

| Input | Where to get it |
|---|---|
| `CompartmentId` | OCI console → Identity → Compartments, or `oci iam compartment list` |
| `SubnetId` | A public or private subnet with outbound internet access |
| `ImageId` | Canonical Ubuntu 22.04/24.04 image OCID for your region |
| `RepositoryUrl` | A Git URL the instance can clone |
| `SshAuthorizedKeysFile` | Public key file for `opc` SSH access |
| `AssignPublicIp` | Use it for a public instance; otherwise place the instance behind a load balancer/bastion |

Set these environment variables before launching (the script refuses to start without them):

`AGENTDOCK_SECRET_KEY`, `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `AGENTDOCK_ADMIN_EMAIL`, `AGENTDOCK_ADMIN_PASSWORD`, `AGENTDOCK_FRONTEND_ORIGINS`, `AGENTDOCK_PUBLIC_URL`.

Optional: `AGENTDOCK_GITHUB_TOKEN`, `AGENTDOCK_GITHUB_WEBHOOK_SECRET`, `AGENTDOCK_FIRST_PARTY_OWNERS`, SMTP settings, and payment provider credentials.

## Launch

```powershell
$env:AGENTDOCK_SECRET_KEY = '<32+ random characters>'
$env:POSTGRES_PASSWORD = '<random>'
$env:REDIS_PASSWORD = '<random>'
$env:AGENTDOCK_ADMIN_EMAIL = 'admin@example.com'
$env:AGENTDOCK_ADMIN_PASSWORD = '<12+ characters>'
$env:AGENTDOCK_FRONTEND_ORIGINS = 'https://agentdock.example.com'
$env:AGENTDOCK_PUBLIC_URL = 'https://agentdock.example.com'

.\deploy\oracle\deploy.ps1 `
  -CompartmentId '<compartment-ocid>' `
  -SubnetId '<subnet-ocid>' `
  -ImageId '<ubuntu-image-ocid>' `
  -RepositoryUrl '<git-url>' `
  -SshAuthorizedKeysFile 'C:\path\id_rsa.pub' `
  -AssignPublicIp

# Add -Apply only after reviewing the printed command.
```

The helper generates cloud-init that installs Docker, clones the repository, writes a `0600` `.env`, and runs `docker compose up -d --build`. `/api/health` is the readiness signal. The generated cloud-init file lives in `%TEMP%` and contains secrets; delete it after launch.

For production, replace inline secrets with OCI Vault secrets retrieved by an instance principal. The current helper is a convenient bootstrap path, not a secret-management system.

## After launch

1. Point DNS at the instance or load balancer and terminate TLS there.
2. Keep the web port private; the Compose file already binds `127.0.0.1:8000`.
3. Configure the GitHub push webhook and payment-provider webhooks with the exact HTTPS origin.
4. Verify `/api/health`, sign in as the bootstrap administrator, and check Administration → Control center → Settings for capability status.
5. Back up PostgreSQL and the SkillVault volume on the same schedule.

## Cost and access note

Launching a compute instance, public IP and block volumes incurs OCI charges. Confirm the compartment, shape and budget before using `-Apply`.
