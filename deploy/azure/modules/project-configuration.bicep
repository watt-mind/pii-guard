// Operator-only private project configuration container; serving code never initializes it.
targetScope = 'resourceGroup'
@minLength(3)
@maxLength(10)
param projectPrefix string = 'piiguard'
@allowed(['prod', 'dev'])
param envName string = 'prod'
@minLength(3)
@maxLength(24)
param storageAccountName string
@minLength(1)
param runtimeIdentityPrincipalId string
var namePrefix = '${projectPrefix}-${envName}'
resource account 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}
resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' existing = {
  parent: account
  name: 'default'
}
resource configuration 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'project-configuration'
  properties: { publicAccess: 'None' }
}
// Same private endpoint/DNS and identity-only account as the separate spend container.
// Scope read/write to this environment's one encrypted snapshot and refuse Blob.List.
var projectPathCondition = replace('''
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
    @Resource[Microsoft.Storage/storageAccounts/blobServices/containers/blobs:path] StringEquals '__PROJECT_PATH__'
  )
)
''', '__PROJECT_PATH__', '${envName}.projects.v1.enc')

resource projectRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' = {
  name: guid(resourceGroup().id, namePrefix, 'project-configuration-writer-v1')
  properties: {
    roleName: '${namePrefix}-project-configuration-writer'
    description: 'Read and write the condition-scoped encrypted project configuration; no control-plane or delete permissions.'
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
resource projectWriter 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(configuration.id, runtimeIdentityPrincipalId, projectRole.id)
  scope: configuration
  properties: {
    principalId: runtimeIdentityPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: projectRole.id
    conditionVersion: '2.0'
    condition: projectPathCondition
  }
}

// Runtime writes remain trusted. Broader inherited grants bypass these conditions;
// review effective access. No delete, list, account keys, funding, or blob creation here.
// The explicit application initializer uses create-if-absent; serving code never calls it.
output accountUrl string = 'https://${account.name}.blob.${environment().suffixes.storage}'
output container string = configuration.name
output blobName string = '${envName}.projects.v1.enc'
