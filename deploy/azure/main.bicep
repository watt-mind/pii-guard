targetScope = 'resourceGroup'

@description('Dedicated pii-guard hosted resources only. Never target an existing shared production group.')
@minLength(3)
@maxLength(10)
param projectPrefix string = 'piiguard'
@allowed(['prod', 'dev'])
param environmentName string = 'prod'
param location string = resourceGroup().location
@description('Existing Azure Monitor action groups reused by budget and app alerts; no recipient addresses in source.')
@minLength(1)
param alertActionGroupIds array
@description('Monthly cost budget in subscription billing currency. Alerts are not a spending cap.')
@minValue(1)
param monthlyBudgetAmount int
param budgetStartDate string = utcNow('yyyy-MM-01T00:00:00Z')
@description('Optional current operator object ID; grants Secrets Officer at this vault only for secret migration.')
param provisioningPrincipalObjectId string = ''
@description('Operator-only step: create the dedicated dev router after credentials, DNS/ACL scope and code review are ready. No app is deployed here.')
param deployDevRouter bool = false
param routerEnrollmentSecretUri string = ''
param routerTlsSecretUri string = ''
param routerAdminSshPublicKey string = ''
param routerVmSize string = 'Standard_B1s'

var suffix = uniqueString(resourceGroup().id)
var namePrefix = '${projectPrefix}-${environmentName}'
var appName = '${namePrefix}-app'
var tags = { project: 'pii-guard', environment: environmentName, state: 'ephemeral-single-process' }

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: '${replace(projectPrefix, '-', '')}${environmentName}${suffix}'
  location: location
  tags: tags
  sku: { name: 'Basic' }
  properties: { adminUserEnabled: false }
}
resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${namePrefix}-runtime'
  location: location
  tags: tags
}
resource vault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: '${take(projectPrefix, 4)}-${environmentName}-${take(suffix, 11)}'
  location: location
  tags: tags
  properties: {
    tenantId: tenant().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enablePurgeProtection: true
    softDeleteRetentionInDays: 7
    publicNetworkAccess: 'Enabled'
    // Data-plane access requires RBAC; no app or operator access policy is granted here.
    networkAcls: { bypass: 'AzureServices', defaultAction: 'Allow' }
  }
}
// Preserve the existing prod role; dev app access is granted only to its three app secrets.
resource vaultReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (environmentName == 'prod') {
  name: guid(vault.id, identity.id, 'secrets-user')
  scope: vault
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6')
  }
}
resource pull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, identity.id, 'acr-pull')
  scope: registry
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')
  }
}
resource environment 'Microsoft.App/managedEnvironments@2025-07-01' = {
  name: '${namePrefix}-env'
  location: location
  tags: tags
  properties: {
    publicNetworkAccess: environmentName == 'dev' ? 'Disabled' : 'Enabled'
    vnetConfiguration: environmentName == 'dev' ? { internal: true, infrastructureSubnetId: devNetwork!.outputs.acaSubnetId } : null
    // CLI --logs-destination none maps to JSON null, not the literal string 'none'.
    // Explicit null also clears a previously configured destination on updates.
    appLogsConfiguration: { destination: null }
    workloadProfiles: [{ name: 'Consumption', workloadProfileType: 'Consumption' }]
  }
}
// Durable only for atomic spend allocation claims; never store mappings, profiles or prompts.
resource allocationStorage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: '${take(replace(projectPrefix, '-', ''), 4)}${environmentName}${suffix}'
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: {
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    allowBlobPublicAccess: false
    publicNetworkAccess: 'Enabled'
  }
}
resource fileService 'Microsoft.Storage/storageAccounts/fileServices@2023-05-01' = {
  parent: allocationStorage
  name: 'default'
}
resource allocationShare 'Microsoft.Storage/storageAccounts/fileServices/shares@2023-05-01' = {
  parent: fileService
  name: 'allocation-claims'
  properties: { shareQuota: 1, enabledProtocols: 'SMB' }
}
resource allocationMount 'Microsoft.App/managedEnvironments/storages@2025-01-01' = {
  parent: environment
  name: 'allocation-claims'
  properties: {
    azureFile: {
      accountName: allocationStorage.name
      accountKey: allocationStorage.listKeys().keys[0].value
      shareName: allocationShare.name
      accessMode: 'ReadWrite'
    }
  }
}
resource secretProvisioner 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(provisioningPrincipalObjectId)) {
  name: guid(vault.id, provisioningPrincipalObjectId, 'secret-provisioner')
  scope: vault
  properties: {
    principalId: provisioningPrincipalObjectId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7')
  }
}
resource budget 'Microsoft.Consumption/budgets@2023-11-01' = {
  name: '${namePrefix}-budget'
  properties: {
    amount: monthlyBudgetAmount
    category: 'Cost'
    timeGrain: 'Monthly'
    timePeriod: { startDate: budgetStartDate }
    notifications: {
      Actual50: { enabled: true, operator: 'GreaterThanOrEqualTo', threshold: 50, thresholdType: 'Actual', contactEmails: [], contactGroups: alertActionGroupIds }
      Actual80: { enabled: true, operator: 'GreaterThanOrEqualTo', threshold: 80, thresholdType: 'Actual', contactEmails: [], contactGroups: alertActionGroupIds }
      Actual100: { enabled: true, operator: 'GreaterThanOrEqualTo', threshold: 100, thresholdType: 'Actual', contactEmails: [], contactGroups: alertActionGroupIds }
    }
  }
}
var devAppSecretNames = ['meta-api-key', 'tenant-key', 'google-oauth-client-secret', 'metrics-token']
resource devAppSecrets 'Microsoft.KeyVault/vaults/secrets@2023-07-01' existing = [for secretName in devAppSecretNames: {
  parent: vault
  name: secretName
}]
resource devAppSecretReaders 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for (secretName, i) in devAppSecretNames: if (environmentName == 'dev' && deployDevRouter) {
  name: guid(devAppSecrets[i].id, identity.id, 'dev-app-secret-reader')
  scope: devAppSecrets[i]
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6')
  }
}]

module devNetwork 'modules/dev-network.bicep' = if (environmentName == 'dev') {
  name: '${namePrefix}-network'
  params: { namePrefix: namePrefix, location: location, tags: tags }
}
module devDns 'modules/aca-private-dns.bicep' = if (environmentName == 'dev') {
  name: '${namePrefix}-private-dns'
  params: {
    zoneName: environment.properties.defaultDomain
    staticIp: environment.properties.staticIp
    namePrefix: namePrefix
    vnetId: devNetwork!.outputs.virtualNetworkId
    tags: tags
  }
}
module spendLedger 'modules/spend-ledger.bicep' = {
  name: '${namePrefix}-spend-ledger'
  params: {
    projectPrefix: projectPrefix
    envName: environmentName
    location: location
    runtimeIdentityPrincipalId: identity.properties.principalId
    devVnetId: environmentName == 'dev' ? devNetwork!.outputs.virtualNetworkId : ''
    devPrivateEndpointSubnetId: environmentName == 'dev' ? devNetwork!.outputs.privateEndpointSubnetId : ''
  }
}
module projectConfiguration 'modules/project-configuration.bicep' = {
  name: '${namePrefix}-project-configuration'
  params: {
    projectPrefix: projectPrefix
    envName: environmentName
    storageAccountName: spendLedger.outputs.accountName
    runtimeIdentityPrincipalId: identity.properties.principalId
  }
}
module devRouter 'modules/dev-router.bicep' = if (environmentName == 'dev' && deployDevRouter) {
  name: '${namePrefix}-router-bootstrap'
  params: {
    namePrefix: namePrefix
    location: location
    tags: tags
    subnetId: devNetwork!.outputs.routerSubnetId
    privateIp: devNetwork!.outputs.routerPrivateIp
    acaFqdn: '${appName}.${environment.properties.defaultDomain}'
    vaultName: vault.name
    enrollmentSecretUri: routerEnrollmentSecretUri
    tlsSecretUri: routerTlsSecretUri
    adminSshPublicKey: routerAdminSshPublicKey
    vmSize: routerVmSize
  }
  dependsOn: [devDns]
}
output registryServer string = registry.properties.loginServer
output vaultUri string = vault.properties.vaultUri
output environmentDomain string = environment.properties.defaultDomain
output appName string = appName
output appFqdn string = ''
output registryName string = registry.name
output vaultName string = vault.name
output runtimeIdentityName string = identity.name
output runtimeIdentityClientId string = identity.properties.clientId
output managedEnvironmentName string = environment.name
output allocationStorageName string = allocationStorage.name
output budgetName string = budget.name
output ledgerAccountUrl string = spendLedger.outputs.accountUrl
output ledgerContainer string = spendLedger.outputs.container
output devPrivateNetwork bool = environmentName == 'dev'
output devRouterName string = environmentName == 'dev' && deployDevRouter ? devRouter!.outputs.vmName : ''
output projectAccountUrl string = projectConfiguration.outputs.accountUrl
output projectContainer string = projectConfiguration.outputs.container
output projectBlobName string = projectConfiguration.outputs.blobName
