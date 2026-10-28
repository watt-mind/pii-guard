// Dedicated private dev network. No peering, subnet routes, public app or shared node reuse.
param namePrefix string
param location string
param tags object
var acaPrefix = '10.76.0.0/27'
var routerPrefix = '10.76.0.32/28'
var privateEndpointPrefix = '10.76.0.48/28'
var routerIp = '10.76.0.36'

resource routerNsg 'Microsoft.Network/networkSecurityGroups@2024-05-01' = {
  name: '${namePrefix}-router-nsg'
  location: location
  tags: tags
  properties: {
    securityRules: [
      { name: 'deny-unsolicited-inbound', properties: { priority: 100, direction: 'Inbound', access: 'Deny', protocol: '*', sourcePortRange: '*', destinationPortRange: '*', sourceAddressPrefix: '*', destinationAddressPrefix: '*' } }
      { name: 'private-aca-https', properties: { priority: 100, direction: 'Outbound', access: 'Allow', protocol: 'Tcp', sourcePortRange: '*', destinationPortRanges: ['443', '31443'], sourceAddressPrefix: '*', destinationAddressPrefix: acaPrefix } }
      { name: 'platform-dns', properties: { priority: 110, direction: 'Outbound', access: 'Allow', protocol: '*', sourcePortRange: '*', destinationPortRange: '53', sourceAddressPrefix: '*', destinationAddressPrefix: 'AzurePlatformDNS' } }
      { name: 'managed-identity', properties: { priority: 120, direction: 'Outbound', access: 'Allow', protocol: 'Tcp', sourcePortRange: '*', destinationPortRange: '80', sourceAddressPrefix: '*', destinationAddressPrefix: 'AzurePlatformIMDS' } }
      // Signed apt metadata/packages, Vault GET, and encrypted Tailscale control/DERP.
      { name: 'bootstrap-and-tailnet-https', properties: { priority: 130, direction: 'Outbound', access: 'Allow', protocol: 'Tcp', sourcePortRange: '*', destinationPortRanges: ['80', '443'], sourceAddressPrefix: '*', destinationAddressPrefix: 'Internet' } }
      { name: 'tailnet-stun', properties: { priority: 140, direction: 'Outbound', access: 'Allow', protocol: 'Udp', sourcePortRange: '*', destinationPortRanges: ['3478', '41641'], sourceAddressPrefix: '*', destinationAddressPrefix: 'Internet' } }
      { name: 'azure-vm-agent', properties: { priority: 150, direction: 'Outbound', access: 'Allow', protocol: 'Tcp', sourcePortRange: '*', destinationPortRanges: ['80', '32526'], sourceAddressPrefix: '*', destinationAddressPrefix: '168.63.129.16' } }
      { name: 'deny-other-outbound', properties: { priority: 4096, direction: 'Outbound', access: 'Deny', protocol: '*', sourcePortRange: '*', destinationPortRange: '*', sourceAddressPrefix: '*', destinationAddressPrefix: '*' } }
    ]
  }
}
resource acaNsg 'Microsoft.Network/networkSecurityGroups@2024-05-01' = {
  name: '${namePrefix}-aca-nsg'
  location: location
  tags: tags
  properties: {
    securityRules: [
      { name: 'router-https-only', properties: { priority: 100, direction: 'Inbound', access: 'Allow', protocol: 'Tcp', sourcePortRange: '*', destinationPortRanges: ['443', '31443'], sourceAddressPrefix: routerIp, destinationAddressPrefix: acaPrefix } }
      { name: 'aca-internal-services', properties: { priority: 110, direction: 'Inbound', access: 'Allow', protocol: '*', sourcePortRange: '*', destinationPortRange: '*', sourceAddressPrefix: acaPrefix, destinationAddressPrefix: acaPrefix } }
      { name: 'platform-health-probes', properties: { priority: 120, direction: 'Inbound', access: 'Allow', protocol: 'Tcp', sourcePortRange: '*', destinationPortRange: '30000-32767', sourceAddressPrefix: 'AzureLoadBalancer', destinationAddressPrefix: acaPrefix } }
      { name: 'deny-other-ingress', properties: { priority: 4096, direction: 'Inbound', access: 'Deny', protocol: '*', sourcePortRange: '*', destinationPortRange: '*', sourceAddressPrefix: '*', destinationAddressPrefix: '*' } }
    ]
  }
}
resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: '${namePrefix}-vnet'
  location: location
  tags: tags
  properties: {
    addressSpace: { addressPrefixes: ['10.76.0.0/24'] }
    subnets: [
      { name: 'aca', properties: { addressPrefix: acaPrefix, networkSecurityGroup: { id: acaNsg.id }, delegations: [{ name: 'container-apps', properties: { serviceName: 'Microsoft.App/environments' } }] } }
      { name: 'router', properties: { addressPrefix: routerPrefix, defaultOutboundAccess: false, networkSecurityGroup: { id: routerNsg.id } } }
      { name: 'private-endpoints', properties: { addressPrefix: privateEndpointPrefix, privateEndpointNetworkPolicies: 'Disabled' } }
    ]
  }
}
output virtualNetworkId string = vnet.id
output acaSubnetId string = '${vnet.id}/subnets/aca'
output routerSubnetId string = '${vnet.id}/subnets/router'
output privateEndpointSubnetId string = '${vnet.id}/subnets/private-endpoints'
output routerPrivateIp string = routerIp
