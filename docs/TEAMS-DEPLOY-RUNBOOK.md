# Teams Deployment Runbook

**Last updated:** 2026-03-10
**Author:** Reef (for Eric)

---

## Findings Summary

### Code Review Results

The Teams integration is **solid and demo-ready** with the fixes applied below. Architecture is clean: no Bot Framework SDK dependency, just HTTP + JWT + httpx.

**Gaps Found & Fixed:**

| # | Gap | Severity | Status |
|---|-----|----------|--------|
| 1 | **SSRF via crafted serviceUrl** — No validation on `serviceUrl` from activities. An attacker with a valid JWT (or dev mode) could make Trellis send HTTP requests to arbitrary internal URLs. | 🔴 High | ✅ Fixed — added `_validate_service_url()` with allowlist of known Bot Framework domains. Applied to both `TeamsClient._send_activity()` and conversation ref storage. |
| 2 | **No auth on `/api/proactive`** — Anyone who can reach the endpoint can send messages to stored conversations. | 🟡 Medium | ✅ Fixed — Added bot credentials check. For production, should be behind internal network or API key middleware. |
| 3 | **No retry on transient failures** — `TeamsClient._send_activity` had no retry for 401 (expired token) or 429 (rate limit). | 🟡 Medium | ✅ Fixed — Added single retry with token refresh on 401, backoff on 429. |
| 4 | **In-memory conversation refs** — Lost on restart. | 🟡 Medium | ⚠️ Known limitation, documented. For demo this is fine. Production: persist to DB. |
| 5 | **No typing indicator** — No "bot is typing" shown while processing. | 🟢 Low | 📝 Noted — Nice UX improvement for later. |
| 6 | **Token auth errors in TeamsClient._get_token** — Raw httpx exceptions bubble up. | 🟢 Low | 📝 Noted — Caught by the outer try/except in bot_service. Acceptable for now. |

**Test Results:** 59/59 passing (including 9 new tests for the fixes above).

---

## Prerequisites

- [ ] Azure subscription with permissions to create resources (Contributor+ on a resource group)
- [ ] Azure CLI installed (`az --version` ≥ 2.50)
- [ ] Trellis running (locally or deployed to Azure Container Apps)
- [ ] For local dev: [ngrok](https://ngrok.com/) or [devtunnels](https://aka.ms/devtunnels)
- [ ] For production: Azure Container Apps with a public FQDN + TLS

---

## Phase 1: Azure App Registration (Entra ID)

This creates the identity your bot uses to authenticate with Microsoft.

### Portal Method

1. Go to [Azure Portal → Entra ID → App registrations](https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade)
2. Click **+ New registration**
3. Fill in:
   - **Name:** `Trellis Bot`
   - **Supported account types:** "Accounts in any organizational directory (Multitenant)"
   - **Redirect URI:** Leave blank
4. Click **Register**
5. Copy the **Application (client) ID** — this is your `TEAMS_APP_ID`
6. Go to **Certificates & secrets** → **+ New client secret**
   - Description: `trellis-bot-secret`
   - Expiry: 24 months (set a calendar reminder to rotate!)
7. Copy the **Value** immediately — this is your `TEAMS_APP_PASSWORD`
   - ⚠️ You can only see this once. Store in a password manager or Key Vault.

### CLI Method

```bash
# Login
az login

# Create the app registration
az ad app create \
  --display-name "Trellis Bot" \
  --sign-in-audience AzureADMultipleOrgs \
  --query appId -o tsv
# → outputs your TEAMS_APP_ID

# Create a client secret (valid 2 years)
az ad app credential reset \
  --id <TEAMS_APP_ID> \
  --years 2 \
  --query password -o tsv
# → outputs your TEAMS_APP_PASSWORD
```

### Required API Permissions

For basic bot messaging, **no additional API permissions are needed**. The Bot Framework handles auth via its own token exchange.

If you later want to look up user profiles (department, manager) from Azure AD:

```bash
az ad app permission add \
  --id <TEAMS_APP_ID> \
  --api 00000003-0000-0000-c000-000000000000 \
  --api-permissions e1fe6dd8-ba31-4d61-89e7-88639da4683d=Scope  # User.Read

# Grant admin consent (requires Global Admin or Privileged Role Admin)
az ad app permission admin-consent --id <TEAMS_APP_ID>
```

---

## Phase 2: Azure Bot Service Registration

### Portal Method

1. Go to [Azure Portal → Create a resource](https://portal.azure.com/#create/hub) → search **"Azure Bot"**
2. Click **Create**
3. Fill in:
   - **Bot handle:** `trellis-bot` (globally unique)
   - **Subscription:** Your subscription
   - **Resource group:** `rg-trellis` (create new if needed)
   - **Data residency:** Global (or your preferred region)
   - **Pricing tier:** **F0** (free, 10K messages/month) for dev; **S1** for production
   - **Type of App:** Multi Tenant
   - **Creation type:** "Use existing app registration"
   - **App ID:** paste your `TEAMS_APP_ID` from Phase 1
4. Click **Review + Create** → **Create**
5. After deployment, go to the resource → **Configuration**
6. Set **Messaging endpoint:** `https://<your-trellis-url>/api/messages`
7. Click **Apply**

### CLI Method

```bash
# Create resource group (if needed)
az group create --name rg-trellis --location eastus

# Create the bot
az bot create \
  --resource-group rg-trellis \
  --name trellis-bot \
  --kind registration \
  --appid <TEAMS_APP_ID> \
  --password <TEAMS_APP_PASSWORD> \
  --endpoint "https://<your-trellis-url>/api/messages" \
  --sku F0
```

### Enable Teams Channel

```bash
az bot msteams create \
  --resource-group rg-trellis \
  --name trellis-bot
```

Or in Portal: Bot resource → **Channels** → click **Microsoft Teams** → **Apply** → Accept ToS.

---

## Phase 3: Environment Variables

Set these on your Trellis instance:

| Variable | Required | Description |
|----------|----------|-------------|
| `TEAMS_APP_ID` | ✅ | Microsoft App ID from Phase 1 |
| `TEAMS_APP_PASSWORD` | ✅ | Client secret from Phase 1 |
| `TRELLIS_BOT_DEV_MODE` | ❌ | Set to `"true"` for local dev only (skips JWT validation when no auth header present). **Never enable in production.** |

### For local dev

```bash
export TEAMS_APP_ID="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
export TEAMS_APP_PASSWORD="your-secret-value"
export TRELLIS_BOT_DEV_MODE="true"
```

### For Azure Container Apps

```bash
az containerapp update \
  --name trellis \
  --resource-group rg-trellis \
  --set-env-vars \
    TEAMS_APP_ID=<app-id> \
    TEAMS_APP_PASSWORD=secretref:teams-app-password

# If using Key Vault (recommended for production):
az containerapp update \
  --name trellis \
  --resource-group rg-trellis \
  --set-env-vars \
    TEAMS_APP_ID=<app-id> \
    TEAMS_APP_PASSWORD=keyvaultref:<vault-uri>/secrets/teams-app-password,identityref:<managed-identity-id>
```

---

## Phase 4: Container Apps Configuration

If deploying Trellis to Azure Container Apps:

### Ingress Requirements

- **External ingress** must be enabled (Bot Framework needs to reach `/api/messages`)
- **Target port:** 8100 (or whatever port Trellis runs on)
- **Transport:** HTTP/1.1 (Bot Framework doesn't use HTTP/2 for webhooks)
- TLS is handled automatically by Container Apps

```bash
az containerapp ingress enable \
  --name trellis \
  --resource-group rg-trellis \
  --target-port 8100 \
  --type external \
  --transport http

# Get the FQDN
az containerapp show \
  --name trellis \
  --resource-group rg-trellis \
  --query properties.configuration.ingress.fqdn -o tsv
# → trellis.azurecontainerapps.io
```

Then update the Bot's messaging endpoint:
```bash
az bot update \
  --resource-group rg-trellis \
  --name trellis-bot \
  --endpoint "https://trellis.azurecontainerapps.io/api/messages"
```

### Health Check

Add a health probe so Container Apps knows Trellis is ready:

```bash
az containerapp update \
  --name trellis \
  --resource-group rg-trellis \
  --set-env-vars ... \
  # Trellis should have a /health endpoint — verify this exists
```

---

## Phase 5: Testing with Bot Framework Emulator

The [Bot Framework Emulator](https://github.com/microsoft/BotFramework-Emulator/releases) lets you test locally without deploying to Teams.

### Setup

1. Download and install the Emulator
2. Start Trellis locally:
   ```bash
   cd ~/projects/trellis
   TEAMS_APP_ID=<app-id> TEAMS_APP_PASSWORD=<password> TRELLIS_BOT_DEV_MODE=true \
     .venv/bin/python -m uvicorn trellis.main:app --port 8100
   ```
3. In Emulator: **File → Open Bot**
   - **Bot URL:** `http://localhost:8100/api/messages`
   - **Microsoft App ID:** Your `TEAMS_APP_ID`
   - **Microsoft App Password:** Your `TEAMS_APP_PASSWORD`
4. Send a test message

### What to Verify

- [ ] Bot responds with an Adaptive Card (not plain text)
- [ ] Card shows agent name, response text, and trace ID
- [ ] Non-message activities (conversationUpdate) return 200 with `{"status": "ok"}`
- [ ] Sending with no auth header returns 401 (when `TRELLIS_BOT_DEV_MODE` is not set)
- [ ] Check Trellis logs for the envelope routing

### Testing with ngrok (Teams integration)

```bash
# Terminal 1: Trellis
cd ~/projects/trellis
TEAMS_APP_ID=<app-id> TEAMS_APP_PASSWORD=<password> TRELLIS_BOT_DEV_MODE=true \
  .venv/bin/python -m uvicorn trellis.main:app --port 8100

# Terminal 2: ngrok tunnel
ngrok http 8100
# Copy the https URL (e.g., https://abc123.ngrok-free.app)
```

Update the Bot's messaging endpoint in Azure Portal to the ngrok URL + `/api/messages`, then open Teams and message the bot.

---

## Phase 6: Add Bot to Teams

### For Demo / Dev Testing

1. Azure Portal → Bot resource → **Channels** → **Microsoft Teams** → click **"Open in Teams"**
2. This opens a 1:1 chat with the bot in Teams
3. Send a message to test

### For Organization-Wide Deployment

1. Create a Teams App Package (ZIP containing `manifest.json` + 2 icon PNGs)
   - See `docs/TEAMS-SETUP.md` → Teams App Manifest section for the template
   - Replace `YOUR_APP_ID` with your `TEAMS_APP_ID`
   - Create `color.png` (192×192) and `outline.png` (32×32) icons
2. Go to [Teams Admin Center](https://admin.teams.microsoft.com/) → **Teams apps → Manage apps**
3. Click **+ Upload new app** → select the ZIP
4. Set the app policy to allow it for your target users
5. Users find "Trellis" in the Teams app store → **Add**

---

## Phase 7: Create Routing Rules

The bot needs at least one routing rule to match Teams messages to an agent:

```bash
# Route all Teams messages to a default agent
curl -X POST https://<trellis-url>/api/rules \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Teams default → SAM",
    "priority": 100,
    "conditions": {"source_type": "teams"},
    "actions": {"route_to": "sam-hr"},
    "active": true
  }'
```

Without this, the bot will respond with "I'm not sure how to help with that. No agent matched your request."

---

## End-to-End Verification Checklist

Run through this after everything is configured:

### Infrastructure
- [ ] Trellis is running and accessible at its public URL
- [ ] `curl https://<trellis-url>/api/messages` returns 405 (Method Not Allowed) — endpoint exists
- [ ] `TEAMS_APP_ID` and `TEAMS_APP_PASSWORD` are set
- [ ] `TRELLIS_BOT_DEV_MODE` is **NOT** set (or set to `"false"`) in production

### Azure Configuration
- [ ] Bot resource exists in Azure Portal
- [ ] Messaging endpoint matches your Trellis URL + `/api/messages`
- [ ] Teams channel is enabled (shows green checkmark)
- [ ] App registration has a valid (non-expired) client secret

### Teams Integration
- [ ] Can open bot in Teams (via "Open in Teams" from Azure Portal)
- [ ] Sending "Hello" returns an Adaptive Card response
- [ ] Card renders correctly (agent name, response text, trace ID visible)
- [ ] Sending a question that matches a routing rule gets routed to the correct agent
- [ ] Sending a question that matches NO rule returns the "no match" message

### Audit & Logging
- [ ] Trellis logs show the incoming envelope with `source_type=teams`
- [ ] Audit trail shows the routed envelope: `GET /api/audit?source_type=teams`
- [ ] Trace ID from the card matches the audit entry

### Security
- [ ] Sending a request without Authorization header returns 401 (production mode)
- [ ] Bot Framework tokens with wrong audience are rejected (401)
- [ ] `/api/proactive` returns 503 when bot is not configured
- [ ] Activities with untrusted serviceUrl do NOT store conversation references

### Proactive Messaging (Optional)
- [ ] After receiving a message, the conversation ref is stored
- [ ] `POST /api/proactive {"conversation_id": "<id>", "text": "Test"}` sends a message
- [ ] The proactive message appears in the Teams conversation

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| 503 on `/api/messages` | `TEAMS_APP_ID` or `TEAMS_APP_PASSWORD` not set | Set environment variables |
| 401 "Missing Authorization header" | No auth header + dev mode not enabled | Set `TRELLIS_BOT_DEV_MODE=true` for local dev, or ensure Bot Framework is sending tokens |
| 401 "Token audience mismatch" | `TEAMS_APP_ID` doesn't match the App ID in Azure Bot registration | Verify they're the same UUID |
| 401 "Untrusted token issuer" | Token from unexpected source | Check Bot Framework JWKS endpoint is reachable |
| Bot doesn't respond in Teams | No routing rule for `source_type=teams` | Create a routing rule (see Phase 7) |
| "No agent matched" response | Routing rule exists but conditions don't match | Check rule conditions vs. envelope fields |
| Card not rendering in Teams | Adaptive Card schema version > 1.5 | Trellis uses 1.5 (compatible). Check for custom card modifications. |
| Proactive message fails | Conversation ref not stored (bot hasn't received a message from that conversation yet) | Send a message to the bot first, then try proactive |
| ngrok tunnel not working | Free ngrok URLs change on restart | Update the messaging endpoint in Azure Portal each time |
| "Untrusted service URL" in logs | Activity has a serviceUrl not in the allowlist | If this is a legitimate Microsoft endpoint, add it to `ALLOWED_SERVICE_URL_PREFIXES` in `teams_adapter.py` |

---

## Production Hardening Checklist

Before going live beyond demo:

- [ ] Store `TEAMS_APP_PASSWORD` in Azure Key Vault (not plain env var)
- [ ] Persist conversation refs to database (currently in-memory, lost on restart)
- [ ] Put `/api/proactive` behind API key or internal-only network
- [ ] Set up monitoring/alerting on the `/api/messages` endpoint (latency, error rate)
- [ ] Add typing indicator while processing (send `typing` activity before routing)
- [ ] Set calendar reminder to rotate the client secret before expiry
- [ ] Create proper Teams app icons (color.png 192×192, outline.png 32×32)
- [ ] Review and customize the Teams App Manifest for Health First branding
- [ ] Test with Bot Framework Emulator's "Inspect" mode for detailed activity logging
- [ ] Load test with concurrent messages to verify async handling
