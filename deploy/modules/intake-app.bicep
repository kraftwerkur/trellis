// Intake — standalone content sourcer, feeds Trellis
param location string
param prefix string
param tags object
param environmentId string
param registryLoginServer string
param registryName string
param trellisUrl string

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: registryName
}

resource app 'Microsoft.App/containerApps@2023-11-02-preview' = {
  name: '${prefix}-intake'
  location: location
  tags: tags
  properties: {
    managedEnvironmentId: environmentId
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: null // no inbound traffic — Intake only pushes outbound
      secrets: [
        { name: 'registry-password', value: acr.listCredentials().passwords[0].value }
      ]
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
          name: 'intake'
          image: '${registryLoginServer}/intake:latest'
          resources: {
            cpu: json('0.25')
            memory: '0.5Gi'
          }
          env: [
            { name: 'TRELLIS_URL', value: 'https://${trellisUrl}' }
          ]
        }
      ]
      scale: {
        minReplicas: 1  // always running — it's a polling loop
        maxReplicas: 1
      }
    }
  }
}

output name string = app.name
