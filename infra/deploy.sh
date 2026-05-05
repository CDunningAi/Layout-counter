#!/usr/bin/env bash
# ==============================================================================
# deploy.sh — Idempotent deployment script for Layout-Counter Azure Function
#
# Usage:
#   export AZURE_SUBSCRIPTION_ID=<your-subscription-id>
#   ./infra/deploy.sh
#
# All output (stdout + stderr) is tee'd to infra/logs/deploy-<timestamp>.log
# ==============================================================================
set -euo pipefail
set -x

# ------------------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REGION="eastus"
RESOURCE_GROUP="rg-layout-counter"
DEPLOYMENT_NAME="layout-counter-deploy"
FUNCTION_APP_NAME="func-layout-counter"
BICEP_FILE="${SCRIPT_DIR}/main.bicep"
PARAMS_FILE="${SCRIPT_DIR}/parameters.json"
LOG_DIR="${SCRIPT_DIR}/logs"
LOG_FILE="${LOG_DIR}/deploy-$(date -u +%Y%m%dT%H%M%SZ).log"

# ------------------------------------------------------------------------------
# Prerequisites check
# ------------------------------------------------------------------------------
if [[ -z "${AZURE_SUBSCRIPTION_ID:-}" ]]; then
  echo "ERROR: AZURE_SUBSCRIPTION_ID environment variable is not set."
  echo "       Please run: export AZURE_SUBSCRIPTION_ID=<your-subscription-id>"
  exit 1
fi

# Ensure log directory exists.
mkdir -p "${LOG_DIR}"

# Tee all output to log file.
exec > >(tee -a "${LOG_FILE}") 2>&1

echo "======================================================================"
echo " Layout-Counter Deployment"
echo " Log: ${LOG_FILE}"
echo " Subscription: ${AZURE_SUBSCRIPTION_ID}"
echo " Region: ${REGION}"
echo " Resource Group: ${RESOURCE_GROUP}"
echo "======================================================================"

# ------------------------------------------------------------------------------
# Error trap
# ------------------------------------------------------------------------------
trap 'echo ""; echo "DEPLOYMENT FAILED at line $LINENO"; echo "Review log: ${LOG_FILE}"; exit 1' ERR

# ------------------------------------------------------------------------------
# STEP 1: Set active subscription
# ------------------------------------------------------------------------------
echo "===== STEP 1: Set active subscription ====="
az account set --subscription "${AZURE_SUBSCRIPTION_ID}"
echo "Active subscription set to ${AZURE_SUBSCRIPTION_ID}"

# ------------------------------------------------------------------------------
# STEP 2: Create Resource Group (idempotent)
# ------------------------------------------------------------------------------
echo "===== STEP 2: Create Resource Group ====="
az group create \
  --name "${RESOURCE_GROUP}" \
  --location "${REGION}" \
  --output table
echo "Resource group '${RESOURCE_GROUP}' is ready."

# ------------------------------------------------------------------------------
# STEP 3: Deploy Bicep template
# ------------------------------------------------------------------------------
echo "===== STEP 3: Deploy Bicep template ====="
DEPLOY_OUTPUT=$(az deployment group create \
  --name "${DEPLOYMENT_NAME}" \
  --resource-group "${RESOURCE_GROUP}" \
  --template-file "${BICEP_FILE}" \
  --parameters "@${PARAMS_FILE}" \
  --output json)

echo "Bicep deployment completed."
echo "${DEPLOY_OUTPUT}" | python3 -m json.tool 2>/dev/null || echo "${DEPLOY_OUTPUT}"

# ------------------------------------------------------------------------------
# STEP 4: Capture Bicep outputs
# ------------------------------------------------------------------------------
echo "===== STEP 4: Capture Bicep outputs ====="
FUNC_HOSTNAME=$(echo "${DEPLOY_OUTPUT}" | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(d['properties']['outputs']['functionAppHostname']['value'])
")
KV_NAME=$(echo "${DEPLOY_OUTPUT}" | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(d['properties']['outputs']['keyVaultName']['value'])
")

echo "Function App Hostname : ${FUNC_HOSTNAME}"
echo "Key Vault Name        : ${KV_NAME}"

# ------------------------------------------------------------------------------
# STEP 5: Copy config directory into function_app for packaging
# ------------------------------------------------------------------------------
echo "===== STEP 5: Copy config into function_app for packaging ====="
CONFIG_SRC="${REPO_ROOT}/config"
CONFIG_DST="${REPO_ROOT}/function_app/config"
if [[ -d "${CONFIG_SRC}" ]]; then
  rm -rf "${CONFIG_DST}"
  cp -r "${CONFIG_SRC}" "${CONFIG_DST}"
  echo "Copied ${CONFIG_SRC} -> ${CONFIG_DST}"
fi

# ------------------------------------------------------------------------------
# STEP 6: Next steps banner
# ------------------------------------------------------------------------------
echo ""
echo "======================================================================"
echo " DEPLOYMENT COMPLETE"
echo "======================================================================"
echo ""
echo " Next steps:"
echo ""
echo "  1. Upload your Graph client secret to Key Vault:"
echo "       ./infra/set-keyvault-secret.sh"
echo ""
echo "  2. Publish the function code (config/ is already copied into function_app/):"
echo "       cd function_app"
echo "       func azure functionapp publish ${FUNCTION_APP_NAME} --python"
echo ""
echo "  3. Test the endpoint:"
echo "       curl -X POST https://${FUNC_HOSTNAME}/api/process-floorplan \\"
echo "            -H 'x-functions-key: <your-function-key>' \\"
echo "            -F 'pdf=@/path/to/floorplan.pdf'"
echo ""
echo "======================================================================"
