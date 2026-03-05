// Trellis — FastAPI agent orchestration platform
param location string
param prefix string
param tags object
param environmentId string
param registryLoginServer string
param registryName string

@secure()
param nvidiaApiKey string
@secure()
param anthropicApiKey string
@secure()
param openaiApiKey string
@secure()
param googleApiKey string
@secure()
param groqApiKey string

param databaseConnectionString string
param keyVaultUri string

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: registryName
}

resource app 'Microsoft.App/containerApps@2023-11-02-preview' = {
  name: '${prefix}-api'
  location: location
  tags: tags
  properties: {
    managedEnvironmentId: environmentId
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
        allowInsecure: false
      }
      secrets: concat(
        [
          { name: 'registry-password', value: acr.listCredentials().passwords[0].value }
          { name: 'db-connection-string', value: databaseConnectionString }
        ],
        !empty(nvidiaApiKey) ? [{ name: 'nvidia-api-key', value: nvidiaApiKey }] : [],
        !empty(anthropicApiKey) ? [{ name: 'anthropic-api-key', value: anthropicApiKey }] : [],
        !empty(openaiApiKey) ? [{ name: 'openai-api-key', value: openaiApiKey }] : [],
        !empty(googleApiKey) ? [{ name: 'google-api-key', value: googleApiKey }] : [],
        !empty(groqApiKey) ? [{ name: 'groq-api-key', value: groqApiKey }] : []
      )
      registries: [
        {
          server: registryLoginServer
          username: acr.listCredentials().username
          passwordSecretRef: 'registry-password'
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'trellis'
          image: '${registryLoginServer}/${prefix}:latest'
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: concat(
            [
              { name: 'TRELLIS_HOST', value: '0.0.0.0' }
              { name: 'TRELLIS_PORT', value: '8000' }
              { name: 'DATABASE_URL', secretRef: 'db-connection-string' }
              { name: 'KEYVAULT_URI', value: keyVaultUri }
            ],
            !empty(nvidiaApiKey) ? [{ name: 'NVIDIA_API_KEY', secretRef: 'nvidia-api-key' }] : [],
            !empty(anthropicApiKey) ? [{ name: 'TRELLIS_ANTHROPIC_API_KEY', secretRef: 'anthropic-api-key' }] : [],
            !empty(openaiApiKey) ? [{ name: 'TRELLIS_OPENAI_API_KEY', secretRef: 'openai-api-key' }] : [],
            !empty(googleApiKey) ? [{ name: 'TRELLIS_GOOGLE_API_KEY', secretRef: 'google-api-key' }] : [],
            !empty(groqApiKey) ? [{ name: 'TRELLIS_GROQ_API_KEY', secretRef: 'groq-api-key' }] : []
          )
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 2
      }
    }
  }
}

output fqdn string = app.properties.configuration.ingress.fqdn
output url string = 'https://${app.properties.configuration.ingress.fqdn}'
