#!/usr/bin/env bash
# Deploy Mini Charlotte AI to Azure App Service (Linux, Python).
# Cloud-only mode: Ollama isn't reachable from App Service, so the
# "Private — Ollama" dropdown options will just fall back to the offline
# template automatically. Use Anthropic / OpenAI / Kimi (key pasted in the
# browser) for real explanations once deployed.
set -euo pipefail

RESOURCE_GROUP="${RESOURCE_GROUP:-rg-charlotte-ai}"
LOCATION="${LOCATION:-canadacentral}"  # this subscription is policy-restricted to: germanywestcentral, francecentral, denmarkeast, canadacentral, swedencentral
PLAN_NAME="${PLAN_NAME:-charlotte-plan}"
SKU="${SKU:-B1}"                       # B1 ~$13/mo, no daily CPU cap. F1 is free but capped at 60 CPU-min/day.
APP_NAME="${APP_NAME:?set APP_NAME to a globally-unique name, e.g. mini-charlotte-ai-yourname}"

echo "== whoami / subscription =="
az account show --output table

echo "== 1. resource group =="
az group create --name "$RESOURCE_GROUP" --location "$LOCATION" --output table

echo "== 2. Linux App Service plan ($SKU) =="
az appservice plan create \
  --name "$PLAN_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --location "$LOCATION" \
  --is-linux \
  --sku "$SKU" \
  --output table

echo "== 3. web app (Python 3.11) =="
az webapp create \
  --name "$APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --plan "$PLAN_NAME" \
  --runtime "PYTHON:3.11" \
  --output table

echo "== 4. startup command (gunicorn against wsgi.py) =="
az webapp config set \
  --name "$APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --startup-file "gunicorn --bind=0.0.0.0 --timeout 600 wsgi:app" \
  --output table

echo "== 5. package only git-tracked files (skips datapack_extracted/, runtime/, .git) =="
REPO_ROOT="$(git rev-parse --show-toplevel)"
ZIP_PATH="/tmp/mini-charlotte-deploy.zip"
git -C "$REPO_ROOT" archive --format=zip -o "$ZIP_PATH" HEAD
echo "zip: $ZIP_PATH ($(du -h "$ZIP_PATH" | cut -f1))"

echo "== 6. zip deploy =="
az webapp deploy \
  --name "$APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --src-path "$ZIP_PATH" \
  --type zip \
  --output table

URL="https://${APP_NAME}.azurewebsites.net"
echo
echo "Deployed. First load can take 1-2 min while Oryx builds the venv."
echo "$URL"
