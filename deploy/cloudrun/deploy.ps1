# Deploy the QA tool dashboard to Google Cloud Run as a public service. Safe to re-run (also used for updates).
# Run from anywhere:  powershell -ExecutionPolicy Bypass -File deploy\cloudrun\deploy.ps1 -Project <project-id>
# Requires: Google Cloud SDK logged in (gcloud auth login) and billing linked to the project.
param(
    [Parameter(Mandatory = $true)][string]$Project,
    [string]$Region = "us-central1",
    [string]$Service = "qa-tool",
    [switch]$SkipIamGrants   # skip the role grants (already done, or done by a project owner)
)
$ErrorActionPreference = "Continue"   # gcloud writes progress to stderr; check $LASTEXITCODE instead
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $root

$gcloud = (Get-Command gcloud -ErrorAction SilentlyContinue).Source
if (-not $gcloud) { $gcloud = "C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd" }
if (-not (Test-Path $gcloud)) { Write-Error "gcloud not found - install the Google Cloud SDK"; exit 1 }
$sa = "$Service@$Project.iam.gserviceaccount.com"

function Step($msg) { Write-Host "`n== $msg" -ForegroundColor Cyan }
function Check($what) { if ($LASTEXITCODE -ne 0) { Write-Error "$what failed (exit $LASTEXITCODE)"; exit 1 } }

Step "Enabling APIs (Cloud Run, Cloud Build, Artifact Registry)"
& $gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com --project $Project
Check "Enabling APIs"

# The tool calls no Google APIs, so its identity gets no roles: a compromised container holds no cloud access
# (the default compute service account would have Editor on the project).
Step "Service account $sa (no roles)"
& $gcloud iam service-accounts describe $sa --project $Project *> $null
if ($LASTEXITCODE -ne 0) {
    & $gcloud iam service-accounts create $Service --project $Project --display-name "QA tool dashboard (Cloud Run)"
    Check "Creating service account"
}

if (-not $SkipIamGrants) {
    Step "Build permissions for source deploys (default compute service account)"
    $projectNumber = (& $gcloud projects describe $Project --format "value(projectNumber)").Trim()
    $computeSa = "$projectNumber-compute@developer.gserviceaccount.com"
    foreach ($role in @("roles/run.builder", "roles/cloudbuild.builds.builder")) {
        & $gcloud projects add-iam-policy-binding $Project --member "serviceAccount:$computeSa" --role $role --condition=None --quiet *> $null
        Check "Granting $role"
    }
    # IAM changes can take a minute or two to apply; the first build right after granting may fail and just needs a re-run.
} else {
    Write-Host "Skipping IAM role grants (-SkipIamGrants)"
}

# max-instances 1: runs and the daily-run counter live in memory, so every request must reach the same instance.
# QA_TOOL_PUBLIC=1 blocks internal addresses (cloud metadata) and caps runs per day; see app/main.py.
Step "Building and deploying $Service to $Region (takes several minutes: Chromium is installed in the image)"
& $gcloud run deploy $Service `
    --source . `
    --project $Project `
    --region $Region `
    --service-account $sa `
    --set-env-vars QA_TOOL_PUBLIC=1 `
    --allow-unauthenticated `
    --min-instances 0 `
    --max-instances 1 `
    --memory 2Gi `
    --cpu 2 `
    --concurrency 10 `
    --timeout 900 `
    --cpu-boost `
    --quiet
Check "gcloud run deploy"

$url = (& $gcloud run services describe $Service --project $Project --region $Region --format "value(status.url)").Trim()
Write-Host "`nDeployed: $url" -ForegroundColor Green
Write-Host "  Logs   : gcloud run services logs read $Service --region $Region --project $Project"
