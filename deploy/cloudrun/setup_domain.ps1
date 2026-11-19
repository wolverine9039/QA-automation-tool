# Put the Cloud Run service behind a static IP and a custom domain proxied by Cloudflare. Safe to re-run.
#   powershell -ExecutionPolicy Bypass -File deploy\cloudrun\setup_domain.ps1 -Project <project-id>
# Builds: reserved global IP -> HTTPS load balancer (Google-managed cert via DNS authorization, which works while
# Cloudflare proxies the name) -> Cloud Armor (only Cloudflare IPs) -> serverless NEG -> Cloud Run (LB-only ingress).
# Run deploy.ps1 first. Prints the two DNS records to add in Cloudflare.
param(
    [Parameter(Mandatory = $true)][string]$Project,
    [string]$Domain = "qa-tool.buildwithmayank.tech",
    [string]$Region = "us-central1",
    [string]$Service = "qa-tool"
)
$ErrorActionPreference = "Continue"   # gcloud writes progress to stderr; check $LASTEXITCODE instead
$gcloud = (Get-Command gcloud -ErrorAction SilentlyContinue).Source
if (-not $gcloud) { $gcloud = "C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd" }
if (-not (Test-Path $gcloud)) { Write-Error "gcloud not found - install the Google Cloud SDK"; exit 1 }

function Step($msg) { Write-Host "`n== $msg" -ForegroundColor Cyan }
function Check($what) { if ($LASTEXITCODE -ne 0) { Write-Error "$what failed (exit $LASTEXITCODE)"; exit 1 } }
# Create a resource only if `describe` can't find it (re-runs skip what already exists).
function Ensure([string]$what, [string[]]$describe, [string[]]$create) {
    & $gcloud @describe --project $Project *> $null
    if ($LASTEXITCODE -eq 0) { Write-Host "  $what exists"; return }
    & $gcloud @create --project $Project --quiet
    Check "Creating $what"
}

$ip = "$Service-ip"; $neg = "$Service-neg"; $backend = "$Service-backend"; $armor = "$Service-cloudflare-only"
$urlmap = "$Service-urlmap"; $dnsauth = "$Service-dnsauth"; $cert = "$Service-cert"; $certmap = "$Service-certmap"
$proxy = "$Service-https-proxy"; $rule = "$Service-https"

Step "Enabling APIs (Compute Engine, Certificate Manager)"
& $gcloud services enable compute.googleapis.com certificatemanager.googleapis.com --project $Project
Check "Enabling APIs"

Step "Static IP, serverless NEG and backend"
Ensure "static IP $ip" @("compute", "addresses", "describe", $ip, "--global") `
    @("compute", "addresses", "create", $ip, "--global", "--ip-version", "IPV4")
Ensure "NEG $neg" @("compute", "network-endpoint-groups", "describe", $neg, "--region", $Region) `
    @("compute", "network-endpoint-groups", "create", $neg, "--region", $Region,
      "--network-endpoint-type", "serverless", "--cloud-run-service", $Service)
Ensure "backend $backend" @("compute", "backend-services", "describe", $backend, "--global") `
    @("compute", "backend-services", "create", $backend, "--global", "--load-balancing-scheme", "EXTERNAL_MANAGED")
$hasNeg = & $gcloud compute backend-services describe $backend --global --project $Project --format "value(backends[].group)"
if ($hasNeg -notmatch $neg) {
    & $gcloud compute backend-services add-backend $backend --global --project $Project `
        --network-endpoint-group $neg --network-endpoint-group-region $Region
    Check "Attaching NEG"
}

# Like uno's origin lockdown: only Cloudflare may reach the load balancer, so nobody can skip Cloudflare's WAF.
Step "Cloud Armor policy $armor (allow Cloudflare IPs only)"
& $gcloud compute security-policies describe $armor --project $Project *> $null
if ($LASTEXITCODE -ne 0) {
    & $gcloud compute security-policies create $armor --project $Project --description "Only Cloudflare edge IPs" --quiet
}
if ($LASTEXITCODE -ne 0) {
    # New projects often have a SECURITY_POLICIES quota of 0; request an increase and re-run this script.
    Write-Warning "Cloud Armor unavailable (quota?). Skipping the Cloudflare-only lockdown: the load balancer IP also answers directly."
} else {
$ranges = @((Invoke-RestMethod https://www.cloudflare.com/ips-v4) -split "\s+" | Where-Object { $_ }) +
          @((Invoke-RestMethod https://www.cloudflare.com/ips-v6) -split "\s+" | Where-Object { $_ })
if ($ranges.Count -lt 10) { Write-Error "Could not download Cloudflare IP ranges"; exit 1 }
$priority = 1000
for ($i = 0; $i -lt $ranges.Count; $i += 10) {   # Cloud Armor allows 10 ranges per rule
    $chunk = ($ranges[$i..([Math]::Min($i + 9, $ranges.Count - 1))]) -join ","
    & $gcloud compute security-policies rules describe $priority --security-policy $armor --project $Project *> $null
    $verb = if ($LASTEXITCODE -eq 0) { "update" } else { "create" }
    & $gcloud compute security-policies rules $verb $priority --security-policy $armor --project $Project `
        --src-ip-ranges $chunk --action allow --quiet
    Check "Cloud Armor rule $priority"
    $priority++
}
& $gcloud compute security-policies rules update 2147483647 --security-policy $armor --project $Project --action deny-403 --quiet
Check "Default deny rule"
& $gcloud compute backend-services update $backend --global --project $Project --security-policy $armor --quiet
Check "Attaching Cloud Armor"
}

Step "Certificate for $Domain (DNS authorization)"
Ensure "DNS authorization" @("certificate-manager", "dns-authorizations", "describe", $dnsauth) `
    @("certificate-manager", "dns-authorizations", "create", $dnsauth, "--domain", $Domain)
Ensure "certificate" @("certificate-manager", "certificates", "describe", $cert) `
    @("certificate-manager", "certificates", "create", $cert, "--domains", $Domain, "--dns-authorizations", $dnsauth)
Ensure "certificate map" @("certificate-manager", "maps", "describe", $certmap) `
    @("certificate-manager", "maps", "create", $certmap)
Ensure "certificate map entry" @("certificate-manager", "maps", "entries", "describe", "$Service-entry", "--map", $certmap) `
    @("certificate-manager", "maps", "entries", "create", "$Service-entry", "--map", $certmap,
      "--certificates", $cert, "--hostname", $Domain)

Step "URL map, HTTPS proxy and forwarding rule (443 only; Cloudflare redirects HTTP to HTTPS)"
Ensure "URL map" @("compute", "url-maps", "describe", $urlmap, "--global") `
    @("compute", "url-maps", "create", $urlmap, "--global", "--default-service", $backend)
Ensure "HTTPS proxy" @("compute", "target-https-proxies", "describe", $proxy, "--global") `
    @("compute", "target-https-proxies", "create", $proxy, "--global", "--url-map", $urlmap, "--certificate-map", $certmap)
Ensure "forwarding rule" @("compute", "forwarding-rules", "describe", $rule, "--global") `
    @("compute", "forwarding-rules", "create", $rule, "--global", "--load-balancing-scheme", "EXTERNAL_MANAGED",
      "--address", $ip, "--target-https-proxy", $proxy, "--ports", "443")

Step "Cloud Run accepts traffic only from the load balancer (the run.app URL stops answering)"
& $gcloud run services update $Service --region $Region --project $Project --ingress internal-and-cloud-load-balancing --quiet
Check "Setting ingress"

$addr = (& $gcloud compute addresses describe $ip --global --project $Project --format "value(address)").Trim()
$cname = & $gcloud certificate-manager dns-authorizations describe $dnsauth --project $Project --format "value(dnsResourceRecord.name,dnsResourceRecord.data)"
$parts = $cname -split "\s+"
Write-Host "`nStatic IP: $addr" -ForegroundColor Green
Write-Host "Add in Cloudflare DNS for buildwithmayank.tech:"
Write-Host "  A      $Domain  ->  $addr                (Proxied, orange cloud)"
Write-Host "  CNAME  $($parts[0].TrimEnd('.'))  ->  $($parts[1].TrimEnd('.'))  (DNS only, grey cloud)"
Write-Host "Cloudflare SSL/TLS mode: Full (strict). Certificate status (ACTIVE after the CNAME is seen, ~5-60 min):"
Write-Host "  gcloud certificate-manager certificates describe $cert --project $Project --format='value(managed.state)'"
