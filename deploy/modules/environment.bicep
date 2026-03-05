// Container Apps Environment — shared runtime for Trellis + Intake
param location string
param prefix string
param tags object
param logAnalyticsCustomerId string
@secure()
param logAnalyticsSharedKey string

resource env 'Microsoft.App/managedEnvironments@2023-11-02-preview' = {
  name: 'cae-${prefix}'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalyticsCustomerId
        sharedKey: logAnalyticsSharedKey
      }
    }
    zoneRedundant: false
  }
}

output environmentId string = env.id
output environmentName string = env.name
