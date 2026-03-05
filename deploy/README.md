# Trellis — Azure Deploy

Deploys Trellis + Intake to Azure Container Apps. Estimated cost: **~$5-10/mo** at demo scale.

## What Gets Created

| Resource | SKU | Purpose | Cost |
|----------|-----|---------|------|
| Container Registry | Basic | Store Docker images | ~$5/mo |
| Container Apps Env | Consumption | Shared runtime | Free tier |
| Trellis (container) | 0.5 vCPU / 1GB | API + gateway + dashboard | Pay-per-use |
| Intake (container) | 0.25 vCPU / 0.5GB | Feed sourcer | Pay-per-use |
| Log Analytics | Free tier | Logs (<5GB/mo) | Free |

Trellis scales to zero when idle. Intake runs 1 replica (it's a polling loop).

## Prerequisites

- Azure CLI (`az`) authenticated
- VS Enterprise subscription with permissions to create resources
- API keys for at least one LLM provider (NVIDIA NIM recommended)

## Deploy (Azure Cloud Shell)

```bash
# Upload or clone the repos
git clone <trellis-repo>
git clone <intake-repo>

# Run setup
cd trellis/deploy
./deploy.sh setup
```

The script will:
1. Prompt for API keys
2. Create the resource group and infrastructure
3. Build Docker images via ACR (no local Docker needed!)
4. Deploy both container apps
5. Print the live URL

## Commands

```bash
./deploy.sh setup    # First-time: infra + images + deploy
./deploy.sh update   # Rebuild and push images after code changes
./deploy.sh status   # Check what's running
./deploy.sh destroy  # Tear it all down
```

## After Deploy

```bash
# Health check
curl https://<trellis-url>/health

# Dashboard
open https://<trellis-url>/dashboard

# Intake logs (verify feeds are flowing)
az containerapp logs show -n trellis-intake -g rg-trellis --follow
```

## Clean Up Agent-HR Resources

If you had the old Agent-HR deployment:
```bash
az group delete -n rg-agent-hr-dev --yes --no-wait
```
