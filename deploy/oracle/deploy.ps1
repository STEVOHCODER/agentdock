param(
  [string]$Profile = 'DEFAULT',
  [Parameter(Mandatory = $true)][string]$CompartmentId,
  [Parameter(Mandatory = $true)][string]$SubnetId,
  [Parameter(Mandatory = $true)][string]$ImageId,
  [Parameter(Mandatory = $true)][string]$RepositoryUrl,
  [Parameter(Mandatory = $true)][string]$SshAuthorizedKeysFile,
  [string]$AvailabilityDomain = 'loen:eu-amsterdam-1-AD-1',
  [string]$DisplayName = 'agentdock',
  [string]$Shape = 'VM.Standard.E5.Flex',
  [double]$Ocpus = 2,
  [double]$MemoryGb = 8,
  [bool]$SecureCookie = $false,
  [switch]$Apply,
  [switch]$AssignPublicIp
)

$ErrorActionPreference = 'Stop'
$cli = 'C:\oci-cli\Scripts\oci.exe'
if (-not (Test-Path $cli)) { $cli = (Get-Command oci -ErrorAction Stop).Source }
if (-not (Test-Path $SshAuthorizedKeysFile)) { throw "SSH key file not found: $SshAuthorizedKeysFile" }
foreach ($name in 'AGENTDOCK_SECRET_KEY','POSTGRES_PASSWORD','REDIS_PASSWORD','AGENTDOCK_ADMIN_EMAIL','AGENTDOCK_ADMIN_PASSWORD','AGENTDOCK_FRONTEND_ORIGINS','AGENTDOCK_PUBLIC_URL') {
  if (-not (Get-Item "Env:$name" -ErrorAction SilentlyContinue).Value) { throw "Set environment variable $name before launching" }
}

$cloudInit = @"
#cloud-config
ssh_authorized_keys:
  - $((Get-Content $SshAuthorizedKeysFile -Raw).Trim())
package_update: true
packages:
  - docker.io
  - git
  - curl
write_files:
  - path: /etc/agentdock.env
    permissions: '0600'
    content: |
      AGENTDOCK_ENV=production
      AGENTDOCK_SECRET_KEY=$env:AGENTDOCK_SECRET_KEY
      AGENTDOCK_ADMIN_EMAIL=$env:AGENTDOCK_ADMIN_EMAIL
      AGENTDOCK_ADMIN_PASSWORD=$env:AGENTDOCK_ADMIN_PASSWORD
      AGENTDOCK_DATABASE_URL=postgresql+psycopg://agentdock:$env:POSTGRES_PASSWORD@db:5432/agentdock
      AGENTDOCK_FRONTEND_ORIGINS=$env:AGENTDOCK_FRONTEND_ORIGINS
      AGENTDOCK_PUBLIC_URL=$env:AGENTDOCK_PUBLIC_URL
      AGENTDOCK_SESSION_SECURE_COOKIE=$SecureCookie
      AGENTDOCK_SEED_LIBRARY=true
      AGENTDOCK_GITHUB_TOKEN=$env:AGENTDOCK_GITHUB_TOKEN
      AGENTDOCK_GITHUB_WEBHOOK_SECRET=$env:AGENTDOCK_GITHUB_WEBHOOK_SECRET
      AGENTDOCK_FIRST_PARTY_OWNERS=$env:AGENTDOCK_FIRST_PARTY_OWNERS
      AGENTDOCK_SMTP_HOST=$env:AGENTDOCK_SMTP_HOST
      AGENTDOCK_SMTP_PORT=$env:AGENTDOCK_SMTP_PORT
      AGENTDOCK_SMTP_USER=$env:AGENTDOCK_SMTP_USER
      AGENTDOCK_SMTP_PASSWORD=$env:AGENTDOCK_SMTP_PASSWORD
      AGENTDOCK_SMTP_FROM=$env:AGENTDOCK_SMTP_FROM
      AGENTDOCK_PAYMENT_PROVIDER=$env:AGENTDOCK_PAYMENT_PROVIDER
      AGENTDOCK_PADDLE_API_KEY=$env:AGENTDOCK_PADDLE_API_KEY
      AGENTDOCK_PADDLE_WEBHOOK_SECRET=$env:AGENTDOCK_PADDLE_WEBHOOK_SECRET
      AGENTDOCK_FLUTTERWAVE_SECRET_KEY=$env:AGENTDOCK_FLUTTERWAVE_SECRET_KEY
      AGENTDOCK_FLUTTERWAVE_WEBHOOK_HASH=$env:AGENTDOCK_FLUTTERWAVE_WEBHOOK_HASH
      AGENTDOCK_URUBUTOPAY_API_KEY=$env:AGENTDOCK_URUBUTOPAY_API_KEY
      AGENTDOCK_URUBUTOPAY_WEBHOOK_SECRET=$env:AGENTDOCK_URUBUTOPAY_WEBHOOK_SECRET
      AGENTDOCK_URUBUTOPAY_CHECKOUT_URL=$env:AGENTDOCK_URUBUTOPAY_CHECKOUT_URL
      POSTGRES_PASSWORD=$env:POSTGRES_PASSWORD
      REDIS_PASSWORD=$env:REDIS_PASSWORD
runcmd:
  - systemctl enable --now docker
  - curl -fsSL https://github.com/docker/compose/releases/download/v2.29.7/docker-compose-linux-x86_64 -o /usr/local/bin/docker-compose
  - chmod +x /usr/local/bin/docker-compose
  - git clone $RepositoryUrl /opt/agentdock
  - cp /etc/agentdock.env /opt/agentdock/.env
  - chown root:root /opt/agentdock/.env && chmod 600 /opt/agentdock/.env
  - cd /opt/agentdock
  - sed -i 's/127.0.0.1:8000:8000/0.0.0.0:8000:8000/' docker-compose.yml
  - docker-compose up -d --build
"@

$cloudInitFile = Join-Path $env:TEMP 'agentdock-cloud-init.yaml'
[System.IO.File]::WriteAllText($cloudInitFile, $cloudInit, [System.Text.UTF8Encoding]::new($false))

$arguments = @(
  'compute', 'instance', 'launch',
  '--availability-domain', $AvailabilityDomain,
  '--compartment-id', $CompartmentId,
  '--subnet-id', $SubnetId,
  '--image-id', $ImageId,
  '--display-name', $DisplayName,
  '--shape', $Shape,
  '--ssh-authorized-keys-file', $SshAuthorizedKeysFile,
  '--user-data-file', $cloudInitFile,
  '--query', 'data.{id:id,display_name:display_name}',
  '--output', 'json'
)
if ($Shape -like '*.Flex') {
  $shapeFile = Join-Path $env:TEMP 'agentdock-shape.json'
  [System.IO.File]::WriteAllText($shapeFile, "{`"Ocpus`":$Ocpus,`"MemoryInGBs`":$MemoryGb}", [System.Text.UTF8Encoding]::new($false))
  $arguments += @('--shape-config', "file://$shapeFile")
}
if ($AssignPublicIp) { $arguments += @('--assign-public-ip', 'true') }

Write-Host "OCI command: $cli $($arguments -join ' ')"
if (-not $Apply) {
  Write-Host 'Dry run only. Re-run with -Apply to launch the instance.'
  Write-Host "Cloud-init written to $cloudInitFile (contains secrets; delete it after use)."
  exit 0
}

& $cli --profile $Profile @arguments
Write-Host "Instance launched. Delete $cloudInitFile now."
