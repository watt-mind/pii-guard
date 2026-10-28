// Operator-only VM bootstrap. Custom data contains SOURCE + secret references, never values.
param namePrefix string
param location string
param tags object
param subnetId string
param privateIp string
param acaFqdn string
param vaultName string
@description('Versioned enrollment-secret URI in this dev vault; never an auth key value.')
param enrollmentSecretUri string
@description('Versioned combined PEM certificate/key secret URI in this dev vault.')
param tlsSecretUri string
@description('Public SSH key required by Azure provisioning; SSH is disabled and no inbound NSG port is open.')
param adminSshPublicKey string
param vmSize string = 'Standard_B1s'
param adminUsername string = 'piiguardops'

resource routerIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${namePrefix}-router-identity'
  location: location
  tags: tags
}
resource vault 'Microsoft.KeyVault/vaults@2023-07-01' existing = { name: vaultName }
resource enrollmentSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' existing = {
  parent: vault
  name: split(enrollmentSecretUri, '/')[4]
}
resource tlsSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' existing = {
  parent: vault
  name: split(tlsSecretUri, '/')[4]
}
resource enrollmentReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(enrollmentSecret.id, routerIdentity.id, 'enrollment-reader')
  scope: enrollmentSecret
  properties: {
    principalId: routerIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6')
  }
}
resource tlsReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(tlsSecret.id, routerIdentity.id, 'tls-reader')
  scope: tlsSecret
  properties: {
    principalId: routerIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6')
  }
}
resource outboundIp 'Microsoft.Network/publicIPAddresses@2024-05-01' = {
  name: '${namePrefix}-router-outbound-ip'
  location: location
  tags: tags
  sku: { name: 'Standard' }
  properties: { publicIPAllocationMethod: 'Static', publicIPAddressVersion: 'IPv4' }
}
resource nic 'Microsoft.Network/networkInterfaces@2024-05-01' = {
  name: '${namePrefix}-router-nic'
  location: location
  tags: tags
  properties: {
    enableIPForwarding: false
    ipConfigurations: [{
      name: 'primary'
      properties: {
        privateIPAllocationMethod: 'Static'
        privateIPAddress: privateIp
        subnet: { id: subnetId }
        publicIPAddress: { id: outboundIp.id }
      }
    }]
  }
}
var config = string({
  hostname: 'piiguard-dev'
  aca_fqdn: acaFqdn
  secret_uri: enrollmentSecretUri
  tls_secret_uri: tlsSecretUri
  managed_identity_client_id: routerIdentity.properties.clientId
})
var cloudInitTemplate = '''
#cloud-config
write_files:
  - path: /opt/piiguard-dev-router/bootstrap.py
    permissions: '0700'
    encoding: b64
    content: __BOOTSTRAP__
  - path: /opt/piiguard-dev-router/install.sh
    permissions: '0700'
    encoding: b64
    content: __INSTALL__
  - path: /opt/piiguard-dev-router/piiguard-dev-router.service
    permissions: '0600'
    encoding: b64
    content: __SERVICE__
  - path: /etc/piiguard-dev-router/config.json
    permissions: '0600'
    encoding: b64
    content: __CONFIG__
runcmd:
  - [bash, /opt/piiguard-dev-router/install.sh]
'''
var cloudInit = replace(replace(replace(replace(cloudInitTemplate, '__BOOTSTRAP__', base64(loadTextContent('../dev_router/bootstrap.py'))), '__INSTALL__', base64(loadTextContent('../dev_router/install.sh'))), '__SERVICE__', base64(loadTextContent('../dev_router/piiguard-dev-router.service'))), '__CONFIG__', base64(config))
resource vm 'Microsoft.Compute/virtualMachines@2024-07-01' = {
  name: '${namePrefix}-router'
  location: location
  tags: tags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${routerIdentity.id}': {} } }
  properties: {
    hardwareProfile: { vmSize: vmSize }
    osProfile: {
      computerName: 'piiguard-dev'
      adminUsername: adminUsername
      customData: base64(cloudInit)
      linuxConfiguration: {
        disablePasswordAuthentication: true
        provisionVMAgent: true
        ssh: { publicKeys: [{ path: '/home/${adminUsername}/.ssh/authorized_keys', keyData: adminSshPublicKey }] }
      }
    }
    storageProfile: {
      imageReference: { publisher: 'Canonical', offer: 'ubuntu-24_04-lts', sku: 'server', version: 'latest' }
      osDisk: { createOption: 'FromImage', diskSizeGB: 32, managedDisk: { storageAccountType: 'Standard_LRS' } }
    }
    networkProfile: { networkInterfaces: [{ id: nic.id }] }
    diagnosticsProfile: { bootDiagnostics: { enabled: false } }
  }
  dependsOn: [enrollmentReader, tlsReader]
}
output vmName string = vm.name
output identityName string = routerIdentity.name
