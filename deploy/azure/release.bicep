// App-only deployment: foundation, permissions and spend funding belong to the operator.
// Deploy incrementally. This template never creates the existing sponsored-allowance ledger.
targetScope = 'resourceGroup'

@minLength(3)
@maxLength(10)
param projectPrefix string = 'piiguard'
@allowed(['prod', 'dev'])
param environmentName string = 'prod'
param location string = resourceGroup().location
@description('Production public ingress remains an explicit release gate.')
param publicEnabled bool = false
@description('Prod stage only: the driver read the live app as already external (LAB-1541). Keeps, never opens, public ingress.')
param preserveExternalIngress bool = false
@description('Dev only: driver has verified the actual internal environment, disabled public network access, and reviewed proxy/TLS/ACL evidence. This flag is not evidence itself.')
param privateDevReviewed bool = false
@description('Reviewed immutable hosted image reference, shared by dev and prod.')
@minLength(1)
param image string
@description('Canonical HTTPS origin without a trailing slash; dev TLS terminates at its dedicated private proxy.')
@minLength(1)
param publicOrigin string
@description('Preserve the existing app ingress customDomains metadata exactly; pass [] only for an unbound app. Certificates and bindings are provisioned separately by an operator.')
param customDomains array
@minLength(1)
param googleClientId string
@description('Existing monitored action groups. A release must preserve them rather than clear alert recipients.')
@minLength(1)
param alertActionGroupIds array
@description('Existing dedicated HTTPS Blob account endpoint, with no query, SAS or account credentials. The operator precreates sponsored-allowance/<environment>.json and grants the app identity access.')
@minLength(1)
param ledgerAccountUrl string
@description('Existing identity-only Blob account for encrypted project configuration. The operator creates project-configuration/<environment>.projects.v1.enc explicitly; app releases never initialize it.')
@minLength(1)
param projectAccountUrl string
@description('Approved cumulative USD microdollar ceiling, reused with the same ID/expiry. Zero disables sponsorship. Releases never issue or replenish credit. Per-environment cap: prod USD 50, dev USD 10.')
@minValue(0)
@maxValue(50000000)
param sponsoredMicrodollars int = 0
param allocationId string = ''
@minValue(0)
param allocationExpiresAt int = 0
@description('Versioned Key Vault secret URIs only; secret values never enter ARM.')
@minLength(1)
param metaKeySecretUri string
@minLength(1)
param tenantKeySecretUri string
@minLength(1)
param googleSecretUri string
@description('Keep off until the actual production edge client-IP boundary has been verified. Dev always forces off.')
@allowed(['off', 'aca_xff_rightmost'])
param clientIpSource string = 'off'

var suffix = uniqueString(resourceGroup().id)
var namePrefix = '${projectPrefix}-${environmentName}'
var appName = '${namePrefix}-app'
// The driver must establish actual network/privacy properties before approving dev.
// ARM resource conditions cannot inspect runtime properties of an existing environment.
var appDeploymentEnabled = environmentName == 'prod' || privateDevReviewed
var tags = { project: 'pii-guard', environment: environmentName, state: 'ephemeral-single-process' }
// Per-environment sponsored ceiling (LAB-1508): prod USD 50 (owner, 2026-10-29), dev USD 10.
// @maxValue holds only the larger prod cap; ARM has no throw, so int() of a non-numeric string
// fails template evaluation and refuses an over-cap dev release before anything is written.
var sponsoredCeilingMicrodollars = environmentName == 'prod' ? 50000000 : 10000000
var admittedSponsoredMicrodollars = sponsoredMicrodollars <= sponsoredCeilingMicrodollars ? sponsoredMicrodollars : int('sponsoredMicrodollars-exceeds-environment-ceiling')

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: '${replace(projectPrefix, '-', '')}${environmentName}${suffix}'
}
resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = {
  name: '${namePrefix}-runtime'
}
resource environment 'Microsoft.App/managedEnvironments@2025-01-01' existing = {
  name: '${namePrefix}-env'
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
        // An internal environment needs app-external ingress for its VNet proxy to wake it.
        // A prod stage keeps the live app's flag instead of rewriting it internal (LAB-1541).
        external: environmentName == 'dev' ? true : (publicEnabled || preserveExternalIngress)
        targetPort: 8787
        transport: 'http'
        allowInsecure: false
        customDomains: customDomains
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
        env: [
          { name: 'PII_GUARD_HOSTED', value: 'true' }
          { name: 'PII_GUARD_HOSTED_SINGLE_PROCESS', value: 'true' }
          { name: 'PII_GUARD_HOSTED_TRUST_EASY_AUTH', value: 'true' }
          { name: 'PII_GUARD_HOSTED_PUBLIC_ORIGIN', value: publicOrigin }
          { name: 'PII_GUARD_HOSTED_CLIENT_IP_SOURCE', value: environmentName == 'dev' ? 'off' : clientIpSource }
          { name: 'PII_GUARD_ALLOWED_HOSTS', value: '${split(replace(publicOrigin, 'https://', ''), '/')[0]},${appName}.${environment.properties.defaultDomain}' }
          { name: 'PII_GUARD_NER_MODEL', value: '/app/models/ner' }
          { name: 'PII_GUARD_DETECTORS', value: 'rules,ner' }
          // Hosted images (ADR 0014): local OCR + on-device faces and signatures only. The
          // owner's project policy decides visual actions; no server override (LAB-1444).
          { name: 'PII_GUARD_HOSTED_IMAGES', value: 'true' }
          { name: 'PII_GUARD_SEGMENTER', value: 'local' }
          { name: 'PII_GUARD_HOSTED_MODELS', value: 'muse-spark-1.3' }
          { name: 'PII_GUARD_HOSTED_SPONSORED_MICRODOLLARS', value: string(admittedSponsoredMicrodollars) }
          { name: 'PII_GUARD_HOSTED_SPONSORED_ALLOCATION_ID', value: allocationId }
          { name: 'PII_GUARD_HOSTED_ALLOCATION_EXPIRES_AT', value: string(allocationExpiresAt) }
          // The LAB-1398 ledger is fixed to <environment>.json; only an operator funds it.
          { name: 'PII_GUARD_HOSTED_SPEND_STORE', value: 'azure_blob' }
          { name: 'PII_GUARD_HOSTED_SPEND_ACCOUNT_URL', value: ledgerAccountUrl }
          { name: 'PII_GUARD_HOSTED_SPEND_CONTAINER', value: 'sponsored-allowance' }
          { name: 'PII_GUARD_HOSTED_SPEND_ENVIRONMENT', value: environmentName }
          { name: 'PII_GUARD_HOSTED_SPEND_MANAGED_IDENTITY_CLIENT_ID', value: identity.properties.clientId }
          // Stable tenant-key encrypts both the project snapshot and its provider credentials.
          { name: 'PII_GUARD_HOSTED_PROJECT_STORE', value: 'azure_blob' }
          { name: 'PII_GUARD_HOSTED_PROJECT_ACCOUNT_URL', value: projectAccountUrl }
          { name: 'PII_GUARD_HOSTED_PROJECT_CONTAINER', value: 'project-configuration' }
          { name: 'PII_GUARD_HOSTED_PROJECT_ENVIRONMENT', value: environmentName }
          { name: 'PII_GUARD_HOSTED_PROJECT_MANAGED_IDENTITY_CLIENT_ID', value: identity.properties.clientId }
          { name: 'PII_GUARD_UPSTREAM_BASE_URL', value: 'https://api.meta.ai/v1' }
          { name: 'PII_GUARD_UPSTREAM_API_KEY', secretRef: 'meta-key' }
          { name: 'PII_GUARD_TENANT_KEY', secretRef: 'tenant-key' }
          { name: 'PII_GUARD_TRAFFIC_LOG', value: 'off' }
          { name: 'PII_GUARD_METRICS', value: 'false' }
        ]
        // Readiness admits the replica while the bundled NER model still loads (LAB-1548):
        // scale-to-zero cold starts serve the landing page at once, detecting requests wait or
        // get 503 detector_loading. Full /readyz (model loaded) stays the deploy smoke gate.
        // Startup and Readiness tick every 2 s (LAB-1594): 10 s ticks cost about 11 s of a 54 s
        // cold start. Startup keeps failureThreshold 60 (2 min for /healthz, up in about 1 s);
        // Readiness tolerates 20 s of failures so the CPU-bound NER load never drops the replica.
        probes: [
          { type: 'Startup', httpGet: { path: '/healthz', port: 8787, httpHeaders: [{ name: 'Host', value: 'localhost' }] }, periodSeconds: 2, failureThreshold: 60, timeoutSeconds: 5 }
          { type: 'Readiness', httpGet: { path: '/readyz/serving', port: 8787, httpHeaders: [{ name: 'Host', value: 'localhost' }] }, periodSeconds: 2, failureThreshold: 10, timeoutSeconds: 5 }
          { type: 'Liveness', httpGet: { path: '/healthz', port: 8787, httpHeaders: [{ name: 'Host', value: 'localhost' }] }, periodSeconds: 30, failureThreshold: 3, timeoutSeconds: 5 }
        ]
      }]
      scale: { minReplicas: 0, maxReplicas: 1 }
    }
  }
}

resource auth 'Microsoft.App/containerApps/authConfigs@2025-01-01' = if (appDeploymentEnabled) {
  parent: app
  name: 'current'
  properties: {
    platform: { enabled: true }
    globalValidation: { unauthenticatedClientAction: 'AllowAnonymous' }
    httpSettings: {
      requireHttps: true
      // The proxy overwrites both dedicated headers, preserving the private HTTPS origin.
      forwardProxy: environmentName == 'dev' ? {
        convention: 'Custom'
        customHostHeaderName: 'X-Pii-Guard-External-Host'
        customProtoHeaderName: 'X-Pii-Guard-External-Proto'
      } : { convention: 'NoProxy' }
    }
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
      tokenStore: { enabled: false }
      allowedExternalRedirectUrls: []
    }
  }
}

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

output appName string = appName
output appFqdn string = appDeploymentEnabled ? app!.properties.configuration.ingress.fqdn : ''
