#!/usr/bin/env bash
# ==============================================================================
# set-keyvault-secret.sh — Upload the Graph client secret to Key Vault
#
# Usage: ./infra/set-keyvault-secret.sh
#
# The script prompts for the secret value without echo (read -s), then stores
# it in Key Vault and restarts the Function App so the new value takes effect.
# ==============================================================================
set -euo pipefail

VAULT_NAME="kv-layout-counter"
SECRET_NAME="GraphClientSecret"
FUNCTION_APP_NAME="func-layout-counter"
RESOURCE_GROUP="rg-layout-counter"

echo ""
echo "===== Upload Graph Client Secret to Key Vault ====="
echo "Vault: ${VAULT_NAME}   Secret: ${SECRET_NAME}"
echo ""
echo -n "Paste the Graph client secret value (input is hidden): "
read -rs SECRET
echo ""

if [[ -z "${SECRET}" ]]; then
  echo "ERROR: Secret value cannot be empty."
  exit 1
fi

echo "Setting secret in Key Vault..."
az keyvault secret set \
  --vault-name "${VAULT_NAME}" \
  --name "${SECRET_NAME}" \
  --value "${SECRET}" \
  --output none

echo "Secret stored successfully."
echo ""
echo "Restarting Function App '${FUNCTION_APP_NAME}' so the new secret takes effect..."
az functionapp restart \
  --name "${FUNCTION_APP_NAME}" \
  --resource-group "${RESOURCE_GROUP}"

echo ""
echo "Done. The Function App has been restarted with the new secret."
