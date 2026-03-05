#!/bin/bash
# Trellis + Intake — Azure Deploy Script
# Run from Azure Cloud Shell
#
# Usage:
#   ./deploy.sh setup       # First time — full deploy
#   ./deploy.sh update      # Rebuild images only
#   ./deploy.sh destroy     # Tear down everything
#   ./deploy.sh status      # Check running state

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RG="rg-trellis"
LOCATION="eastus2"
ACR_NAME="acrtrellisprod"
TRELLIS_DIR="${TRELLIS_DIR:-$SCRIPT_DIR/..}"
INTAKE_DIR="${INTAKE_DIR:-}"

case "${1:-help}" in

setup)
  echo "=== Step 1: Collect API keys ==="
  echo "Press Enter to skip any optional key."
  read -sp "NVIDIA NIM API key: " NVIDIA_KEY && echo
  read -sp "Anthropic API key (optional): " ANTHROPIC_KEY && echo
  read -sp "OpenAI API key (optional): " OPENAI_KEY && echo
  read -sp "Google API key (optional): " GOOGLE_KEY && echo
  read -sp "Groq API key (optional): " GROQ_KEY && echo

  echo ""
  echo "=== Step 2: Create resource group + ACR ==="
  az group create -n "$RG" -l "$LOCATION" --tags project=trellis -o none

  if ! az acr show -n "$ACR_NAME" -g "$RG" &>/dev/null; then
    echo "Creating container registry: $ACR_NAME"
    az acr create -n "$ACR_NAME" -g "$RG" --sku Basic --admin-enabled true -o none
  fi
  ACR_SERVER=$(az acr show -n "$ACR_NAME" -g "$RG" --query loginServer -o tsv)
  echo "Registry: $ACR_SERVER"

  echo ""
  echo "=== Step 3: Build and push images ==="
  az acr build -r "$ACR_NAME" -t trellis:latest "$TRELLIS_DIR" --no-logs
  echo "✓ Trellis image built"
  if [ -n "$INTAKE_DIR" ] && [ -d "$INTAKE_DIR" ]; then
    az acr build -r "$ACR_NAME" -t intake:latest "$INTAKE_DIR" --no-logs
    echo "✓ Intake image built"
  else
    echo "⏭ Intake skipped (set INTAKE_DIR= to include)"
  fi

  echo ""
  echo "=== Step 4: Create Log Analytics ==="
  LOG_NAME="log-trellis"
  if ! az monitor log-analytics workspace show -n "$LOG_NAME" -g "$RG" &>/dev/null; then
    az monitor log-analytics workspace create -n "$LOG_NAME" -g "$RG" -l "$LOCATION" --retention-time 30 -o none
  fi
  LOG_ID=$(az monitor log-analytics workspace show -n "$LOG_NAME" -g "$RG" --query customerId -o tsv)
  LOG_KEY=$(az monitor log-analytics workspace get-shared-keys -n "$LOG_NAME" -g "$RG" --query primarySharedKey -o tsv)

  echo ""
  echo "=== Step 5: Create Container Apps Environment ==="
  ENV_NAME="cae-trellis"
  if ! az containerapp env show -n "$ENV_NAME" -g "$RG" &>/dev/null; then
    az containerapp env create -n "$ENV_NAME" -g "$RG" -l "$LOCATION" \
      --logs-workspace-id "$LOG_ID" --logs-workspace-key "$LOG_KEY" -o none
  fi

  echo ""
  echo "=== Step 6: Deploy Trellis ==="
  ACR_USER=$(az acr credential show -n "$ACR_NAME" --query username -o tsv)
  ACR_PASS=$(az acr credential show -n "$ACR_NAME" --query "passwords[0].value" -o tsv)

  # Build secrets (API keys go in secrets, not plain env vars)
  SECRETS="placeholder=unused"
  [ -n "$NVIDIA_KEY" ] && SECRETS="$SECRETS nvidia-api-key=$NVIDIA_KEY"
  [ -n "$ANTHROPIC_KEY" ] && SECRETS="$SECRETS anthropic-api-key=$ANTHROPIC_KEY"
  [ -n "$OPENAI_KEY" ] && SECRETS="$SECRETS openai-api-key=$OPENAI_KEY"
  [ -n "$GOOGLE_KEY" ] && SECRETS="$SECRETS google-api-key=$GOOGLE_KEY"
  [ -n "$GROQ_KEY" ] && SECRETS="$SECRETS groq-api-key=$GROQ_KEY"

  # Build env vars — plain for non-sensitive, secretref: for keys
  ENV_VARS="TRELLIS_HOST=0.0.0.0 TRELLIS_PORT=8000"
  [ -n "$NVIDIA_KEY" ] && ENV_VARS="$ENV_VARS NVIDIA_API_KEY=secretref:nvidia-api-key"
  [ -n "$ANTHROPIC_KEY" ] && ENV_VARS="$ENV_VARS TRELLIS_ANTHROPIC_API_KEY=secretref:anthropic-api-key"
  [ -n "$OPENAI_KEY" ] && ENV_VARS="$ENV_VARS TRELLIS_OPENAI_API_KEY=secretref:openai-api-key"
  [ -n "$GOOGLE_KEY" ] && ENV_VARS="$ENV_VARS TRELLIS_GOOGLE_API_KEY=secretref:google-api-key"
  [ -n "$GROQ_KEY" ] && ENV_VARS="$ENV_VARS TRELLIS_GROQ_API_KEY=secretref:groq-api-key"

  az containerapp create -n trellis-api -g "$RG" \
    --environment "$ENV_NAME" \
    --image "$ACR_SERVER/trellis:latest" \
    --registry-server "$ACR_SERVER" --registry-username "$ACR_USER" --registry-password "$ACR_PASS" \
    --target-port 8000 --ingress external \
    --cpu 0.5 --memory 1Gi \
    --min-replicas 1 --max-replicas 1 \
    --secrets $SECRETS \
    --env-vars $ENV_VARS \
    -o none 2>/dev/null || \
  az containerapp update -n trellis-api -g "$RG" \
    --image "$ACR_SERVER/trellis:latest" \
    --secrets $SECRETS \
    --set-env-vars $ENV_VARS \
    -o none

  TRELLIS_FQDN=$(az containerapp show -n trellis-api -g "$RG" --query "properties.configuration.ingress.fqdn" -o tsv)

  if [ -n "$INTAKE_DIR" ] && [ -d "$INTAKE_DIR" ]; then
    echo ""
    echo "=== Step 7: Deploy Intake ==="
    az containerapp create -n trellis-intake -g "$RG" \
      --environment "$ENV_NAME" \
      --image "$ACR_SERVER/intake:latest" \
      --registry-server "$ACR_SERVER" --registry-username "$ACR_USER" --registry-password "$ACR_PASS" \
      --cpu 0.25 --memory 0.5Gi \
      --min-replicas 1 --max-replicas 1 \
      --env-vars "TRELLIS_URL=http://trellis-api" \
      --ingress disabled \
      -o none 2>/dev/null || \
    az containerapp update -n trellis-intake -g "$RG" \
      --image "$ACR_SERVER/intake:latest" \
      --set-env-vars "TRELLIS_URL=http://trellis-api" \
      -o none
  else
    echo ""
    echo "⏭ Intake deploy skipped"
  fi

  echo ""
  echo "=== Done! ==="
  echo "Trellis API: https://$TRELLIS_FQDN"
  echo ""
  echo "Test it:     curl https://$TRELLIS_FQDN/health"
  echo "Logs:        az containerapp logs show -n trellis-api -g $RG --follow"
  echo "Intake logs: az containerapp logs show -n trellis-intake -g $RG --follow"
  ;;

update)
  echo "=== Rebuilding and pushing images ==="
  az acr build -r "$ACR_NAME" -t trellis:latest "$TRELLIS_DIR" --no-logs --build-arg CACHEBUST="$(date +%s)"
  echo "✓ Trellis image built"

  ACR_SERVER=$(az acr show -n "$ACR_NAME" -g "$RG" --query loginServer -o tsv)
  az containerapp update -n trellis-api -g "$RG" --image "$ACR_SERVER/trellis:latest" -o none

  if [ -n "$INTAKE_DIR" ] && [ -d "$INTAKE_DIR" ]; then
    az acr build -r "$ACR_NAME" -t intake:latest "$INTAKE_DIR" --no-logs
    echo "✓ Intake image built"
    az containerapp update -n trellis-intake -g "$RG" --image "$ACR_SERVER/intake:latest" \
      --set-env-vars "TRELLIS_URL=http://trellis-api" -o none
  fi

  TRELLIS_FQDN=$(az containerapp show -n trellis-api -g "$RG" --query "properties.configuration.ingress.fqdn" -o tsv)
  echo "Updated! https://$TRELLIS_FQDN"
  ;;

rotate-secrets)
  echo "=== Rotate API key secrets ==="
  echo "Press Enter to skip (keeps existing secret)."
  read -sp "NVIDIA NIM API key: " NVIDIA_KEY && echo
  read -sp "Anthropic API key: " ANTHROPIC_KEY && echo
  read -sp "OpenAI API key: " OPENAI_KEY && echo
  read -sp "Google API key: " GOOGLE_KEY && echo
  read -sp "Groq API key: " GROQ_KEY && echo

  SECRETS=""
  [ -n "$NVIDIA_KEY" ] && SECRETS="$SECRETS nvidia-api-key=$NVIDIA_KEY"
  [ -n "$ANTHROPIC_KEY" ] && SECRETS="$SECRETS anthropic-api-key=$ANTHROPIC_KEY"
  [ -n "$OPENAI_KEY" ] && SECRETS="$SECRETS openai-api-key=$OPENAI_KEY"
  [ -n "$GOOGLE_KEY" ] && SECRETS="$SECRETS google-api-key=$GOOGLE_KEY"
  [ -n "$GROQ_KEY" ] && SECRETS="$SECRETS groq-api-key=$GROQ_KEY"

  if [ -z "$SECRETS" ]; then
    echo "No keys provided, nothing to rotate."
    exit 0
  fi

  az containerapp secret set -n trellis-api -g "$RG" --secrets $SECRETS -o none
  echo "✓ Secrets rotated. Container will pick up changes on next revision."
  ;;

destroy)
  echo "This will delete ALL Trellis resources in $RG"
  read -p "Are you sure? (yes/no): " CONFIRM
  if [ "$CONFIRM" = "yes" ]; then
    az group delete -n "$RG" --yes --no-wait
    echo "Deleting $RG... (runs in background)"
  else
    echo "Cancelled."
  fi
  ;;

status)
  echo "=== Trellis ==="
  FQDN=$(az containerapp show -n trellis-api -g "$RG" --query "properties.configuration.ingress.fqdn" -o tsv 2>/dev/null)
  if [ -n "$FQDN" ]; then
    echo "URL: https://$FQDN"
    curl -s "https://$FQDN/health" 2>/dev/null || echo "(not responding)"
  else
    echo "Not deployed"
  fi
  echo ""
  echo "=== Intake ==="
  az containerapp show -n trellis-intake -g "$RG" --query "properties.runningStatus" -o tsv 2>/dev/null || echo "Not deployed"
  ;;

*)
  echo "Usage: $0 {setup|update|rotate-secrets|destroy|status}"
  ;;

esac
