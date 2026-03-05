#!/bin/bash
# Trellis + Intake troubleshooting script
set -euo pipefail

RG="rg-trellis"
TRELLIS_APP="trellis-api"
INTAKE_APP="trellis-intake"

echo "=== 1. Trellis Health ==="
TRELLIS_FQDN=$(az containerapp show -n $TRELLIS_APP -g $RG --query "properties.configuration.ingress.fqdn" -o tsv 2>/dev/null)
echo "URL: https://$TRELLIS_FQDN"
curl -sf "https://$TRELLIS_FQDN/health" 2>/dev/null && echo "" || echo "FAILED — Trellis not responding"
echo ""

echo "=== 2. Trellis Env Vars ==="
az containerapp show -n $TRELLIS_APP -g $RG --query "properties.template.containers[0].env[].{name:name, value:value}" -o table 2>/dev/null
echo ""

echo "=== 3. Intake Env Vars ==="
az containerapp show -n $INTAKE_APP -g $RG --query "properties.template.containers[0].env[].{name:name, value:value}" -o table 2>/dev/null
echo ""

echo "=== 4. Intake Replicas ==="
az containerapp show -n $INTAKE_APP -g $RG --query "properties.template.scale" -o json 2>/dev/null
echo ""

echo "=== 5. Trellis API Test (agents) ==="
curl -sf "https://$TRELLIS_FQDN/api/agents" 2>/dev/null | python3 -m json.tool 2>/dev/null | head -20 || echo "FAILED"
echo ""

echo "=== 6. Trellis Adapter Endpoint Test (external) ==="
echo "Testing POST to /api/adapter/http..."
ADAPTER_RESP=$(curl -s -o /tmp/trellis_adapter_resp.txt -w "%{http_code}" -X POST "https://$TRELLIS_FQDN/api/adapter/http" \
  -H "Content-Type: application/json" \
  -d '{"text":"troubleshoot ping","sender_name":"troubleshoot"}' 2>/dev/null || echo "000")
echo "HTTP status: $ADAPTER_RESP"
cat /tmp/trellis_adapter_resp.txt 2>/dev/null && echo ""
if [ "$ADAPTER_RESP" = "200" ] || [ "$ADAPTER_RESP" = "201" ]; then
  echo "✓ Adapter endpoint works — envelope delivered!"
elif [ "$ADAPTER_RESP" = "422" ]; then
  echo "✓ Endpoint exists (422 = validation error)"
elif [ "$ADAPTER_RESP" = "405" ]; then
  echo "✗ 405 — wrong method or path"
else
  echo "? Response: $ADAPTER_RESP"
fi
echo ""

echo "=== 7. Internal DNS Test ==="
echo "Testing if Intake can reach Trellis internally..."
INTAKE_TRELLIS_URL=$(az containerapp show -n $INTAKE_APP -g $RG --query "properties.template.containers[0].env[?name=='TRELLIS_URL'].value" -o tsv 2>/dev/null)
echo "Intake TRELLIS_URL = $INTAKE_TRELLIS_URL"
echo "Expected for internal: http://trellis-api"
echo ""

echo "=== 8. Intake Recent Logs (last 15) ==="
az containerapp logs show -n $INTAKE_APP -g $RG --tail 15 2>/dev/null | grep -oP '"Log":"\K[^"]*' || echo "No logs available"
echo ""

echo "=== 9. Trellis Recent Logs (last 10) ==="
az containerapp logs show -n $TRELLIS_APP -g $RG --tail 10 2>/dev/null | grep -oP '"Log":"\K[^"]*' || echo "No logs available"
echo ""

echo "=== 10. Audit Events (last 5) ==="
curl -sf "https://$TRELLIS_FQDN/api/audit?limit=5" 2>/dev/null | python3 -m json.tool 2>/dev/null | head -30 || echo "No events"
echo ""

echo "=== Done ==="
