# ==============================================================================
# deploy.ps1 — Idempotent deployment script for Layout-Counter Azure Function
#
# Usage:
#   $env:AZURE_SUBSCRIPTION_ID = "<your-subscription-id>"
#   .\infra\deploy.ps1
#
# All output is captured via Start-Transcript to infra\logs\deploy-<timestamp>.log
# ==============================================================================

#Requires -Version 7.0

$ErrorActionPreference = 'Stop'
Set-PSDebug -Trace 1

# ------------------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------------------
$ScriptDir       = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot        = Split-Path -Parent $ScriptDir
$Region          = 'eastus'
$ResourceGroup   = 'rg-layout-counter'
$DeploymentName  = 'layout-counter-deploy'
$FunctionAppName = 'func-layout-counter'
$BicepFile       = Join-Path $ScriptDir 'main.bicep'
$ParamsFile      = Join-Path $ScriptDir 'parameters.json'
$LogDir          = Join-Path $ScriptDir 'logs'
$Timestamp       = (Get-Date -Format 'yyyyMMddTHHmmssZ' -AsUTC)
$LogFile         = Join-Path $LogDir "deploy-$Timestamp.log"

# Ensure log directory exists.
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }

Start-Transcript -Path $LogFile -Append

try {
    # --------------------------------------------------------------------------
    # Prerequisites check
    # --------------------------------------------------------------------------
    if (-not $env:AZURE_SUBSCRIPTION_ID) {
        Write-Error 'ERROR: AZURE_SUBSCRIPTION_ID environment variable is not set.'
        Write-Host  '       Please run: $env:AZURE_SUBSCRIPTION_ID = "<your-subscription-id>"'
        exit 1
    }

    Write-Host '======================================================================'
    Write-Host ' Layout-Counter Deployment'
    Write-Host " Log: $LogFile"
    Write-Host " Subscription: $($env:AZURE_SUBSCRIPTION_ID)"
    Write-Host " Region: $Region"
    Write-Host " Resource Group: $ResourceGroup"
    Write-Host '======================================================================'

    # --------------------------------------------------------------------------
    # STEP 1: Set active subscription
    # --------------------------------------------------------------------------
    Write-Host '===== STEP 1: Set active subscription ====='
    az account set --subscription $env:AZURE_SUBSCRIPTION_ID
    if ($LASTEXITCODE -ne 0) { throw "az account set failed" }
    Write-Host "Active subscription set to $($env:AZURE_SUBSCRIPTION_ID)"

    # --------------------------------------------------------------------------
    # STEP 2: Create Resource Group (idempotent)
    # --------------------------------------------------------------------------
    Write-Host '===== STEP 2: Create Resource Group ====='
    az group create --name $ResourceGroup --location $Region --output table
    if ($LASTEXITCODE -ne 0) { throw "az group create failed" }
    Write-Host "Resource group '$ResourceGroup' is ready."

    # --------------------------------------------------------------------------
    # STEP 3: Deploy Bicep template
    # --------------------------------------------------------------------------
    Write-Host '===== STEP 3: Deploy Bicep template ====='
    $DeployOutputJson = az deployment group create `
        --name $DeploymentName `
        --resource-group $ResourceGroup `
        --template-file $BicepFile `
        --parameters "@$ParamsFile" `
        --output json
    if ($LASTEXITCODE -ne 0) { throw "az deployment group create failed" }
    Write-Host 'Bicep deployment completed.'

    # --------------------------------------------------------------------------
    # STEP 4: Capture Bicep outputs
    # --------------------------------------------------------------------------
    Write-Host '===== STEP 4: Capture Bicep outputs ====='
    $DeployOutput   = $DeployOutputJson | ConvertFrom-Json
    $FuncHostname   = $DeployOutput.properties.outputs.functionAppHostname.value
    $KvName         = $DeployOutput.properties.outputs.keyVaultName.value

    Write-Host "Function App Hostname : $FuncHostname"
    Write-Host "Key Vault Name        : $KvName"

    # --------------------------------------------------------------------------
    # STEP 5: Copy config directory into function_app for packaging
    # --------------------------------------------------------------------------
    Write-Host '===== STEP 5: Copy config into function_app for packaging ====='
    $ConfigSrc = Join-Path $RepoRoot 'config'
    $ConfigDst = Join-Path $RepoRoot 'function_app' 'config'
    if (Test-Path $ConfigSrc) {
        if (Test-Path $ConfigDst) { Remove-Item -Recurse -Force $ConfigDst }
        Copy-Item -Recurse $ConfigSrc $ConfigDst
        Write-Host "Copied $ConfigSrc -> $ConfigDst"
    }

    # --------------------------------------------------------------------------
    # STEP 6: Next steps banner
    # --------------------------------------------------------------------------
    Write-Host ''
    Write-Host '======================================================================'
    Write-Host ' DEPLOYMENT COMPLETE'
    Write-Host '======================================================================'
    Write-Host ''
    Write-Host ' Next steps:'
    Write-Host ''
    Write-Host '  1. Upload your Graph client secret to Key Vault:'
    Write-Host '       .\infra\set-keyvault-secret.sh   (or use Azure Portal / CLI)'
    Write-Host ''
    Write-Host '  2. Publish the function code (config/ already copied into function_app/):'
    Write-Host '       cd function_app'
    Write-Host "       func azure functionapp publish $FunctionAppName --python"
    Write-Host ''
    Write-Host '  3. Test the endpoint:'
    Write-Host "       curl -X POST https://$FuncHostname/api/process-floorplan ``"
    Write-Host "            -H 'x-functions-key: <your-function-key>' ``"
    Write-Host "            -F 'pdf=@/path/to/floorplan.pdf'"
    Write-Host ''
    Write-Host '======================================================================'
}
catch {
    Write-Error "DEPLOYMENT FAILED: $_"
    exit 1
}
finally {
    Stop-Transcript
}
