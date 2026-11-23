# Give the QA tool a neutral client-facing URL (https://<site>.web.app) via Firebase Hosting. Safe to re-run.
#   powershell -ExecutionPolicy Bypass -File deploy\firebase\setup_hosting.ps1 -Project <project-id>
# Hosting serves no files: every path is rewritten to the Cloud Run service. Uses the gcloud login (no Firebase CLI).
# Run deploy\cloudrun\deploy.ps1 first. Firebase stops waiting for Cloud Run after 60 seconds per request.
param(
    [Parameter(Mandatory = $true)][string]$Project,
    [string]$Site = $Project,
    [string]$Region = "us-central1",
    [string]$Service = "qa-tool"
)
$ErrorActionPreference = "Continue"   # gcloud writes progress to stderr; check $LASTEXITCODE instead
$gcloud = (Get-Command gcloud -ErrorAction SilentlyContinue).Source
if (-not $gcloud) { $gcloud = "C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd" }
if (-not (Test-Path $gcloud)) { Write-Error "gcloud not found - install the Google Cloud SDK"; exit 1 }

function Step($msg) { Write-Host "`n== $msg" -ForegroundColor Cyan }
function Check($what) { if ($LASTEXITCODE -ne 0) { Write-Error "$what failed (exit $LASTEXITCODE)"; exit 1 } }

Step "Enabling APIs (Firebase, Firebase Hosting)"
& $gcloud services enable firebase.googleapis.com firebasehosting.googleapis.com --project $Project
Check "Enabling APIs"

$token = (& $gcloud auth print-access-token).Trim()
$headers = @{ Authorization = "Bearer $token"; "x-goog-user-project" = $Project }
# Returns the parsed response, or $null on 404; any other error stops the script.
function Api([string]$method, [string]$url, $body = $null) {
    try {
        $json = if ($null -ne $body) { $body | ConvertTo-Json -Depth 10 -Compress } else { $null }
        return Invoke-RestMethod -Method $method -Uri $url -Headers $headers -ContentType "application/json" -Body $json
    } catch {
        if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 404) { return $null }
        Write-Error "$method $url failed: $($_.Exception.Message) $($_.ErrorDetails.Message)"; exit 1
    }
}
$fb = "https://firebase.googleapis.com/v1beta1"
$hosting = "https://firebasehosting.googleapis.com/v1beta1"

Step "Firebase on project $Project"
if (Api GET "$fb/projects/$Project") {
    Write-Host "  already enabled"
} else {
    # Fails if this Google account never accepted Firebase's terms: click "Add Firebase" once in the console, then re-run.
    $op = Api POST "$fb/projects/${Project}:addFirebase" @{}
    while (-not $op.done) { Start-Sleep -Seconds 5; $op = Api GET "$fb/$($op.name)" }
    if ($op.error) { Write-Error "addFirebase failed: $($op.error.message)"; exit 1 }
    Write-Host "  added"
}

Step "Hosting site $Site"
$sites = Api GET "$hosting/projects/$Project/sites"
if ($sites.sites.name -contains "projects/$Project/sites/$Site") {
    Write-Host "  exists"
} else {
    Api POST "$hosting/projects/$Project/sites?siteId=$Site" @{} | Out-Null
    Write-Host "  created"
}

Step "Releasing: all paths -> Cloud Run $Service ($Region)"
$version = Api POST "$hosting/sites/$Site/versions" @{
    config = @{ rewrites = @(@{ glob = "**"; run = @{ serviceId = $Service; region = $Region } }) }
}
Api PATCH "$hosting/$($version.name)?update_mask=status" @{ status = "FINALIZED" } | Out-Null
Api POST "$hosting/sites/$Site/releases?versionName=$($version.name)" | Out-Null

# Firebase Hosting reaches Cloud Run from outside Google's load balancers, so ingress must be "all".
Step "Cloud Run ingress: all"
& $gcloud run services update $Service --region $Region --project $Project --ingress all --quiet
Check "Setting ingress"

Write-Host "`nClient URL: https://$Site.web.app" -ForegroundColor Green
