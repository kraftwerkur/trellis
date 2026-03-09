# Teams Bot Setup Guide

Step-by-step guide for connecting Trellis to Microsoft Teams via Azure Bot Service.

**Audience:** Hospital IT teams deploying Trellis at Health First.

---

## Prerequisites

- Azure subscription with admin access
- Trellis instance running (locally or on Azure Container Apps)
- A publicly accessible URL for your Trellis instance (or ngrok for dev)

---

## Step 1: Register the Bot in Azure

1. Go to [Azure Portal](https://portal.azure.com) → **Create a resource** → search **Azure Bot**
2. Click **Create**
3. Fill in:
   - **Bot handle:** `trellis-bot` (or `trellis-bot-dev` for dev)
   - **Subscription:** Your Azure subscription
   - **Resource group:** `rg-trellis` (create if needed)
   - **Pricing tier:** F0 (free) for dev, S1 for production
   - **Microsoft App ID:** Select **Create new Microsoft App ID**
4. Click **Review + Create** → **Create**

## Step 2: Get App ID and Password

1. After creation, go to the Bot resource → **Configuration**
2. Copy the **Microsoft App ID** — this is your `TEAMS_APP_ID`
3. Click **Manage Password** → **New client secret**
4. Copy the secret value immediately — this is your `TEAMS_APP_PASSWORD`
   - ⚠️ You can only see this once. Store it securely.
   - In production, put it in Azure Key Vault.

## Step 3: Configure the Messaging Endpoint

1. In the Bot resource → **Configuration**
2. Set **Messaging endpoint** to: `https://your-trellis-url/api/messages`
   - Local dev with ngrok: `https://abc123.ngrok.io/api/messages`
   - Azure Container Apps: `https://trellis.azurecontainerapps.io/api/messages`
3. Click **Apply**

## Step 4: Enable the Teams Channel

1. In the Bot resource → **Channels**
2. Click **Microsoft Teams** → **Apply**
3. Accept the Terms of Service
4. The Teams channel is now active

## Step 5: Configure Trellis

Set these environment variables on your Trellis instance:

```bash
# Required
export TEAMS_APP_ID="your-microsoft-app-id"
export TEAMS_APP_PASSWORD="your-client-secret"

# Optional (dev only — skips JWT validation)
# export TRELLIS_BOT_DEV_MODE="true"
```

For Azure Container Apps, set these in the container app's environment variables or reference Key Vault secrets.

## Step 6: Add the Bot to Teams

### For development/testing:
1. In the Bot resource → **Channels** → **Microsoft Teams** → **Open in Teams**
2. This opens Teams with the bot. Send a message to test.

### For organization-wide deployment:
1. Create a Teams App Package (see [Teams App Manifest](#teams-app-manifest) below)
2. Upload to your organization's Teams Admin Center
3. Users find the bot in the Teams app store

## Step 7: Verify End-to-End

1. Open Teams → find the bot (or the channel where it's added)
2. Send: `Hello`
3. You should get an Adaptive Card response from the matched Trellis agent
4. Check Trellis audit logs: `GET /api/audit?source_type=teams`

---

## Teams App Manifest

For org-wide deployment, create a `manifest.json`:

```json
{
  "$schema": "https://developer.microsoft.com/en-us/json-schemas/teams/v1.16/MicrosoftTeams.schema.json",
  "manifestVersion": "1.16",
  "version": "1.0.0",
  "id": "YOUR_APP_ID",
  "developer": {
    "name": "Health First IT",
    "websiteUrl": "https://hf.org",
    "privacyUrl": "https://hf.org/privacy",
    "termsOfUseUrl": "https://hf.org/terms"
  },
  "name": {
    "short": "Trellis",
    "full": "Trellis AI Agent Platform"
  },
  "description": {
    "short": "AI agent orchestration for Health First",
    "full": "Route requests to the right AI agent — HR, IT, Security, Revenue Cycle."
  },
  "icons": {
    "outline": "outline.png",
    "color": "color.png"
  },
  "bots": [
    {
      "botId": "YOUR_APP_ID",
      "scopes": ["personal", "team", "groupChat"],
      "commandLists": [
        {
          "scopes": ["personal"],
          "commands": [
            {"title": "help", "description": "What can Trellis do?"},
            {"title": "status", "description": "Check agent status"}
          ]
        }
      ]
    }
  ],
  "permissions": ["identity", "messageTeamMembers"],
  "validDomains": ["your-trellis-url.azurecontainerapps.io"]
}
```

Package as a ZIP with `manifest.json` + two icon PNGs (32x32 outline, 192x192 color).

---

## Local Development with ngrok

```bash
# Terminal 1: Run Trellis
cd ~/projects/trellis
TEAMS_APP_ID=your-id TEAMS_APP_PASSWORD=your-secret TRELLIS_BOT_DEV_MODE=true \
  python -m uvicorn trellis.main:app --port 8100

# Terminal 2: Expose via ngrok
ngrok http 8100

# Copy the ngrok URL → set as Messaging Endpoint in Azure Bot Configuration
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| 401 on `/api/messages` | Check `TEAMS_APP_ID` matches your Bot registration. Token audience must equal your App ID. |
| 503 on `/api/messages` | `TEAMS_APP_ID` or `TEAMS_APP_PASSWORD` not set. |
| Bot doesn't respond | Check Trellis logs. Likely no routing rule matches `source_type=teams`. Add one. |
| "No agent matched" | Create a routing rule: `{"source_type": "teams"} → route_to: your-agent-id` |
| Card not rendering | Ensure Adaptive Card schema version ≤1.5 (Teams doesn't support 1.6+). |

---

## Routing Rules for Teams

Create a rule to route Teams messages to an agent:

```bash
curl -X POST http://localhost:8100/api/rules \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Teams to SAM",
    "priority": 100,
    "conditions": {"source_type": "teams"},
    "actions": {"route_to": "sam-hr"},
    "active": true
  }'
```

For department-specific routing, combine with classification:

```json
{
  "name": "Teams HR questions to SAM",
  "conditions": {
    "source_type": "teams",
    "routing_hints.department": "HR"
  },
  "actions": {"route_to": "sam-hr"}
}
```
