targetScope = 'resourceGroup'

@description('Dedicated pii-guard hosted resources only. Never target an existing shared production group.')
@minLength(3)
@maxLength(10)
param projectPrefix string = 'piiguard'
@allowed(['prod', 'dev'])
param environmentName string = 'prod'
param location string = resourceGroup().location
param deployApp bool = false
@description('External ingress is opt-in and must be enabled only after release gates; staging uses internal ingress.')
param publicEnabled bool = false
@description('Immutable image reference: registry.azurecr.io/pii-guard@sha256:...')
param image string = ''
@description('Canonical HTTPS origin, without trailing slash. Use the generated ACA host or a bound custom domain.')
param publicOrigin string = 'https://guard.watt-mind.com'
param googleClientId string = ''
@description('Existing Azure Monitor action groups reused by budget and app alerts; no recipient addresses in source.')
@minLength(1)
param alertActionGroupIds array
@description('Monthly cost budget in subscription billing currency. Alerts are not a spending cap.')
@minValue(1)
param monthlyBudgetAmount int
param budgetStartDate string = utcNow('yyyy-MM-01T00:00:00Z')
@description('Optional current operator object ID; grants Secrets Officer at this vault only for secret migration.')
param provisioningPrincipalObjectId string = ''
@minValue(0)
@maxValue(10000000)
@description('Explicit one-time sponsored allocation, USD microdollars. Default zero. Maximum $10 per allocation.')
param sponsoredMicrodollars int = 0
param allocationId string = ''
@description('Unix UTC expiry, required with a positive allocation. Reusing an allocation ID after restart refuses sponsored calls.')
param allocationExpiresAt int = 0
@description('Versioned Key Vault URI for the sponsored Meta key. Secret values never enter ARM.')
param metaKeySecretUri string = ''
param tenantKeySecretUri string = ''
param googleSecretUri string = ''

var suffix = uniqueString(resourceGroup().id)
var namePrefix = '${projectPrefix}-${environmentName}'
var appName = '${namePrefix}-app'
// Dev apps stay disabled until the dedicated tailnet-only network is implemented/reviewed.
var appDeploymentEnabled = deployApp && environmentName == 'prod'
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
resource vaultReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
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
resource environment 'Microsoft.App/managedEnvironments@2025-01-01' = {
  name: '${namePrefix}-env'
  location: location
  tags: tags
  properties: {
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
resource app 'Microsoft.App/containerApps@2025-01-01' = if (appDeploymentEnabled) {
  name: appName
  location: location
  tags: tags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identity.id}': {} } }
  properties: {
    managedEnvironmentId: environment.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      maxInactiveRevisions: 2
      ingress: {
        external: publicEnabled
        targetPort: 8787
        transport: 'http'
        allowInsecure: false
      }
      registries: [{ server: registry.properties.loginServer, identity: identity.id }]
      secrets: [
        { name: 'meta-key', keyVaultUrl: metaKeySecretUri, identity: identity.id }
        { name: 'tenant-key', keyVaultUrl: tenantKeySecretUri, identity: identity.id }
        { name: 'google-client-secret', keyVaultUrl: googleSecretUri, identity: identity.id }
      ]
    }
    template: {
      containers: [{
        name: 'pii-guard'
        image: image
        resources: { cpu: 2, memory: '4Gi' }
        volumeMounts: [{ volumeName: 'allocation-claims', mountPath: '/app/allocation-ledger' }]
        env: [
          { name: 'PII_GUARD_HOSTED', value: 'true' }
          { name: 'PII_GUARD_HOSTED_SINGLE_PROCESS', value: 'true' }
          { name: 'PII_GUARD_HOSTED_TRUST_EASY_AUTH', value: 'true' }
          { name: 'PII_GUARD_HOSTED_PUBLIC_ORIGIN', value: publicOrigin }
          { name: 'PII_GUARD_ALLOWED_HOSTS', value: '${split(replace(publicOrigin, 'https://', ''), '/')[0]},${appName}.${environment.properties.defaultDomain}' }
          { name: 'PII_GUARD_HOSTED_MODELS', value: 'muse-spark-1.3' }
          // Marker-only volume forfeits an allocation after restart; an operator must reconcile.
          { name: 'PII_GUARD_HOSTED_SPONSORED_MICRODOLLARS', value: string(sponsoredMicrodollars) }
          { name: 'PII_GUARD_HOSTED_SPONSORED_ALLOCATION_ID', value: allocationId }
          { name: 'PII_GUARD_HOSTED_ALLOCATION_DIRECTORY', value: '/app/allocation-ledger' }
          { name: 'PII_GUARD_HOSTED_ALLOCATION_EXPIRES_AT', value: string(allocationExpiresAt) }
          { name: 'PII_GUARD_UPSTREAM_BASE_URL', value: 'https://api.meta.ai/v1' }
          { name: 'PII_GUARD_UPSTREAM_API_KEY', secretRef: 'meta-key' }
          { name: 'PII_GUARD_TENANT_KEY', secretRef: 'tenant-key' }
          { name: 'PII_GUARD_TRAFFIC_LOG', value: 'off' }
          { name: 'PII_GUARD_METRICS', value: 'false' }
        ]
        probes: [
          { type: 'Startup', httpGet: { path: '/healthz', port: 8787, httpHeaders: [{ name: 'Host', value: 'localhost' }] }, periodSeconds: 10, failureThreshold: 60, timeoutSeconds: 5 }
          { type: 'Readiness', httpGet: { path: '/readyz', port: 8787, httpHeaders: [{ name: 'Host', value: 'localhost' }] }, periodSeconds: 10, failureThreshold: 3, timeoutSeconds: 5 }
          { type: 'Liveness', httpGet: { path: '/healthz', port: 8787, httpHeaders: [{ name: 'Host', value: 'localhost' }] }, periodSeconds: 30, failureThreshold: 3, timeoutSeconds: 5 }
        ]
      }]
      // Mandatory until LAB-1376. Revision changes still invalidate all in-memory state.
      scale: { minReplicas: 0, maxReplicas: 1 }
      volumes: [{ name: 'allocation-claims', storageType: 'AzureFile', storageName: allocationMount.name }]
    }
  }
  dependsOn: [vaultReader, pull]
}
resource auth 'Microsoft.App/containerApps/authConfigs@2025-01-01' = if (appDeploymentEnabled) {
  parent: app
  name: 'current'
  properties: {
    platform: { enabled: true }
    globalValidation: { unauthenticatedClientAction: 'AllowAnonymous' }
    httpSettings: { requireHttps: true }
    identityProviders: {
      google: {
        enabled: true
        registration: { clientId: googleClientId, clientSecretSettingName: 'google-client-secret' }
        login: { scopes: ['openid', 'profile', 'email'] }
        validation: { allowedAudiences: [googleClientId] }
      }
    }
    login: {
      cookieExpiration: { convention: 'FixedTime', timeToExpiration: '01:00:00' }
      nonce: { validateNonce: true, nonceExpirationInterval: '00:05:00' }
      // No provider access/refresh tokens stored by the app.
      tokenStore: { enabled: false }
      allowedExternalRedirectUrls: []
    }
  }
}
output registryServer string = registry.properties.loginServer
output vaultUri string = vault.properties.vaultUri
output environmentDomain string = environment.properties.defaultDomain
output appName string = appName
output appFqdn string = appDeploymentEnabled ? app!.properties.configuration.ingress.fqdn : ''

// Platform metrics contain counts/resource usage, never request bodies or credentials.
var alerts = [
  { name: 'restarts', metric: 'RestartCount', aggregation: 'Maximum', operator: 'GreaterThan', threshold: 0 }
  { name: 'cpu', metric: 'UsageNanoCores', aggregation: 'Average', operator: 'GreaterThan', threshold: 1800000000 }
  { name: 'memory', metric: 'WorkingSetBytes', aggregation: 'Average', operator: 'GreaterThan', threshold: 3600000000 }
]
resource metricAlerts 'Microsoft.Insights/metricAlerts@2018-03-01' = [for item in alerts: if (appDeploymentEnabled) {
  name: '${namePrefix}-${item.name}'
  location: 'global'
  tags: tags
  properties: {
    enabled: true
    severity: 2
    evaluationFrequency: 'PT1M'
    windowSize: 'PT5M'
    scopes: [app!.id]
    targetResourceType: 'Microsoft.App/containerApps'
    targetResourceRegion: location
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [{
        name: item.name
        criterionType: 'StaticThresholdCriterion'
        metricNamespace: 'Microsoft.App/containerapps'
        metricName: item.metric
        timeAggregation: item.aggregation
        operator: item.operator
        threshold: item.threshold
      }]
    }
    actions: [for actionGroupId in alertActionGroupIds: { actionGroupId: actionGroupId }]
  }
}]

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
output registryName string = registry.name
output vaultName string = vault.name
output runtimeIdentityName string = identity.name
output managedEnvironmentName string = environment.name
output allocationStorageName string = allocationStorage.name
output budgetName string = budget.name
