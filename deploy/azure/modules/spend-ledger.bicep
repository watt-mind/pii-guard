// Operator-only foundation. App releases neither deploy this module nor fund its ledger.
targetScope = 'resourceGroup'

@minLength(3)
@maxLength(10)
param projectPrefix string = 'piiguard'
@allowed(['prod', 'dev'])
param envName string = 'prod'
param location string = resourceGroup().location
@description('Principal object ID of this environment\'s runtime user-assigned identity.')
@minLength(1)
param runtimeIdentityPrincipalId string
@description('Required for dev: existing dedicated VNet resource ID for the private Blob DNS link.')
param devVnetId string = ''
@description('Required for dev: existing dedicated private-endpoint subnet resource ID. No public fallback is allowed.')
param devPrivateEndpointSubnetId string = ''

var namePrefix = '${projectPrefix}-${envName}'
var suffix = uniqueString(resourceGroup().id)
var ledgerContainer = 'sponsored-allowance'
var tags = { project: 'pii-guard', environment: envName, purpose: 'sponsored-spend-ledger' }

// A distinct account from the legacy SMB marker share, with no shared-key authorization.
resource account 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: '${take(replace(projectPrefix, '-', ''), 4)}${envName}sp${suffix}'
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: {
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    defaultToOAuthAuthentication: true
    isHnsEnabled: false
    // Production has no VNet: its public endpoint still requires identity authorization.
    publicNetworkAccess: envName == 'dev' ? 'Disabled' : 'Enabled'
    networkAcls: {
      bypass: 'None'
      defaultAction: envName == 'dev' ? 'Deny' : 'Allow'
      ipRules: []
      virtualNetworkRules: []
    }
  }
}
resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: account
  name: 'default'
}
resource allowance 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: ledgerContainer
  properties: { publicAccess: 'None' }
}

// ABAC supports the Blob path resource attribute for read and write. Blob.List shares
// the read DataAction, so reject that suboperation explicitly; it has no Blob path.
// https://learn.microsoft.com/en-us/azure/storage/blobs/storage-auth-abac-attributes
// The exact path contains no container name or leading slash, as required by Azure.
var pathCondition = replace('''
(
  !(ActionMatches{'Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read'} AND SubOperationMatches{'Blob.List'})
)
AND
(
  (
    !(ActionMatches{'Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read'})
    AND
    !(ActionMatches{'Microsoft.Storage/storageAccounts/blobServices/containers/blobs/write'})
  )
  OR
  (
    @Resource[Microsoft.Storage/storageAccounts/blobServices/containers/blobs:path] StringEquals '__LEDGER_PATH__'
  )
)
''', '__LEDGER_PATH__', '${envName}.json')

resource ledgerRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' = {
  name: guid(resourceGroup().id, namePrefix, 'spend-ledger-writer-v1')
  properties: {
    roleName: '${namePrefix}-spend-ledger-writer'
    description: 'Read and write the condition-scoped sponsored ledger; no control-plane or delete permissions.'
    type: 'CustomRole'
    assignableScopes: [resourceGroup().id]
    permissions: [{
      actions: []
      notActions: []
      dataActions: [
        'Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read'
        'Microsoft.Storage/storageAccounts/blobServices/containers/blobs/write'
      ]
      notDataActions: []
    }]
  }
}
resource writer 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(allowance.id, runtimeIdentityPrincipalId, ledgerRole.id)
  scope: allowance
  properties: {
    principalId: runtimeIdentityPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: ledgerRole.id
    conditionVersion: '2.0'
    condition: pathCondition
  }
}
// This role is deliberately not tamper-proof: Blob write permits same-path creation
// and authority changes. The runtime identity/code remain trusted. LAB-1398's SDK
// must never create, reset or fund a ledger. Operators precreate/fund <env>.json.
// Broader inherited grants can bypass this assignment's condition; review them too.

resource privateDns 'Microsoft.Network/privateDnsZones@2020-06-01' = if (envName == 'dev') {
  name: 'privatelink.blob.${environment().suffixes.storage}'
  location: 'global'
  tags: tags
}
resource dnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = if (envName == 'dev') {
  parent: privateDns
  name: '${namePrefix}-spend-link'
  location: 'global'
  tags: tags
  properties: {
    registrationEnabled: false
    virtualNetwork: { id: devVnetId }
  }
}
resource privateEndpoint 'Microsoft.Network/privateEndpoints@2023-11-01' = if (envName == 'dev') {
  name: '${namePrefix}-spend-pe'
  location: location
  tags: tags
  properties: {
    subnet: { id: devPrivateEndpointSubnetId }
    privateLinkServiceConnections: [{
      name: '${namePrefix}-spend-blob'
      properties: {
        privateLinkServiceId: account.id
        groupIds: ['blob']
      }
    }]
  }
}
resource dnsGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2023-11-01' = if (envName == 'dev') {
  parent: privateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [{ name: 'blob', properties: { privateDnsZoneId: privateDns!.id } }]
  }
}

output accountUrl string = 'https://${account.name}.blob.${environment().suffixes.storage}'
output accountName string = account.name
output container string = allowance.name
