// Azure Container Registry — Basic SKU (~$5/mo)
param location string
param prefix string
param tags object

// ACR names must be globally unique, alphanumeric only
var registryName = replace('acr${prefix}${uniqueString(resourceGroup().id)}', '-', '')

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: registryName
  location: location
  tags: tags
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: true // needed for Container Apps pull
  }
}

output registryName string = acr.name
output loginServer string = acr.properties.loginServer
