param([string]$Profile = 'DEFAULT')

$ErrorActionPreference = 'Stop'
$cli = 'C:\oci-cli\Scripts\oci.exe'
if (-not (Test-Path $cli)) { $cli = (Get-Command oci -ErrorAction Stop).Source }

Write-Host 'OCI CLI version:'
& $cli --version

Write-Host 'Object storage namespace:'
& $cli --profile $Profile os ns get --query data --raw-output

Write-Host 'Available compartments:'
& $cli --profile $Profile iam compartment list --all `
  --query 'data[].{name:name,id:id}' --output table

if ($env:OCI_COMPARTMENT_ID) {
  Write-Host 'Available shapes (first 14 lines):'
  & $cli --profile $Profile compute shape list --compartment-id $env:OCI_COMPARTMENT_ID --all `
    --query 'data[].{shape:shape,ocpus:ocpus,memory:memory_in_gbs}' --output table | Select-Object -First 14
} else {
  Write-Host 'Set OCI_COMPARTMENT_ID to list available compute shapes.'
}
