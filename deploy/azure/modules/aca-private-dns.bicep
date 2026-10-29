// An internal ACA environment's provider-assigned suffix is known only after creation.
param zoneName string
param staticIp string
param namePrefix string
param vnetId string
param tags object
resource zone 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: zoneName
  location: 'global'
  tags: tags
}
resource link 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  parent: zone
  name: '${namePrefix}-aca-dns'
  location: 'global'
  tags: tags
  properties: { registrationEnabled: false, virtualNetwork: { id: vnetId } }
}
resource wildcard 'Microsoft.Network/privateDnsZones/A@2020-06-01' = {
  parent: zone
  name: '*'
  properties: { ttl: 60, aRecords: [{ ipv4Address: staticIp }] }
}
resource root 'Microsoft.Network/privateDnsZones/A@2020-06-01' = {
  parent: zone
  name: '@'
  properties: { ttl: 60, aRecords: [{ ipv4Address: staticIp }] }
}
