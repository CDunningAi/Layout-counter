#!/usr/bin/env bash
# Helper script to deploy the function app with config directory copied
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONFIG_SRC="${REPO_ROOT}/config"
CONFIG_DST="${SCRIPT_DIR}/config"

echo "======================================================================"
echo " Layout-Counter Function App Deployment"
echo "======================================================================"

# Copy config directory into function_app for packaging
if [[ -d "${CONFIG_SRC}" ]]; then
  echo "Copying config directory..."
  rm -rf "${CONFIG_DST}"
  cp -r "${CONFIG_SRC}" "${CONFIG_DST}"
  echo "✓ Copied ${CONFIG_SRC} -> ${CONFIG_DST}"
else
  echo "ERROR: Config directory not found at ${CONFIG_SRC}"
  exit 1
fi

# Deploy to Azure
echo ""
echo "Publishing to Azure Function App..."
func azure functionapp publish func-layout-counter --python

echo ""
echo "======================================================================"
echo " Deployment Complete!"
echo "======================================================================"
