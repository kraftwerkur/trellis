// Trellis + Intake — Azure Container Apps Deploy
// Single file. Run from Azure Cloud Shell:
//   az deployment sub create --location eastus2 --template-file main.bicep --parameters nvidiaApiKey=<key>
//
// Total cost estimate: ~$5-10/mo (ACR Basic + Container Apps consumption)

targetScope = 'subscription'

@description('Azure region')
param location string = 'eastus2'

@description('NVIDIA NIM API key for LLM gateway')
@secure()
param nvidiaApiKey string = ''

@description('Anthropic API key (optional)')
@secure()
param anthropicApiKey string = ''

@description('OpenAI API key (optional)')
@secure()
param openaiApiKey string = ''

@description('Google API key (optional)')
@secure()
param googleApiKey string = ''

@description('Groq API key (optional)')
@secure()
param groqApiKey string = ''

@description('SQL Admin Password')
@secure()
param sqlAdminPassword string = ''

// --- Variables ---
var prefix = 'trellis'
var rgName = 'rg-${prefix}'
var tags = {
  project: 'trellis'
  managedBy: 'bicep'
}

// --- Resource Group ---
resource rg 'Microsoft.Resources/resourceGroups@2023-07-01' = {
  name: rgName
  location: location
  tags: tags
}

// --- Container Registry (Basic SKU ~$5/mo) ---
module acr 'modules/acr.bicep' = {
  scope: rg
  name: 'acr'
  params: {
    location: location
    prefix: prefix
    tags: tags
  }
}

// --- Log Analytics (free tier for <5GB/mo) ---
module logs 'modules/logs.bicep' = {
  scope: rg
  name: 'logs'
  params: {
    location: location
    prefix: prefix
    tags: tags
  }
}

// --- Container Apps Environment ---
module env 'modules/environment.bicep' = {
  scope: rg
  name: 'environment'
  params: {
    location: location
    prefix: prefix
    tags: tags
    logAnalyticsCustomerId: logs.outputs.customerId
    logAnalyticsSharedKey: logs.outputs.sharedKey
  }
}

// --- Storage (Persistent volumes/files) ---
module storage 'modules/storage.bicep' = {
  scope: rg
  name: 'storage'
  params: {
    location: location
    prefix: prefix
    tags: tags
  }
}

// --- SQL (Database) ---
module sql 'modules/sql.bicep' = {
  scope: rg
  name: 'sql'
  params: {
    location: location
    prefix: prefix
    tags: tags
    sqlAdminPassword: sqlAdminPassword
  }
}

// --- Key Vault (Secrets) ---
module kv 'modules/keyvault.bicep' = {
  scope: rg
  name: 'keyvault'
  params: {
    location: location
    prefix: prefix
    tags: tags
  }
}

// --- Trellis Container App ---
module trellis 'modules/trellis-app.bicep' = {
  scope: rg
  name: 'trellis-app'
  params: {
    location: location
    prefix: prefix
    tags: tags
    environmentId: env.outputs.environmentId
    registryLoginServer: acr.outputs.loginServer
    registryName: acr.outputs.registryName
    nvidiaApiKey: nvidiaApiKey
    anthropicApiKey: anthropicApiKey
    openaiApiKey: openaiApiKey
    googleApiKey: googleApiKey
    groqApiKey: groqApiKey
    databaseConnectionString: sql.outputs.connectionString
    keyVaultUri: kv.outputs.keyVaultUri
  }
}

// --- Intake Container App ---
module intake 'modules/intake-app.bicep' = {
  scope: rg
  name: 'intake-app'
  params: {
    location: location
    prefix: prefix
    tags: tags
    environmentId: env.outputs.environmentId
    registryLoginServer: acr.outputs.loginServer
    registryName: acr.outputs.registryName
    trellisUrl: trellis.outputs.fqdn
  }
}

// --- Outputs ---
output resourceGroup string = rg.name
output registryLoginServer string = acr.outputs.loginServer
output trellisUrl string = trellis.outputs.url
output trellisInternalUrl string = trellis.outputs.fqdn
