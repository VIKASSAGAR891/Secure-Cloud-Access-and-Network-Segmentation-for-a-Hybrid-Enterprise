# --------------------------------------------------------------------
# Azure side of the "Cloud Zone" — mirrors the AWS structure so the
# two clouds can be compared/federated for the ZTNA + IAM design.
# --------------------------------------------------------------------

resource "azurerm_resource_group" "thinkix_rg" {
  name     = "thinkix-hybrid-rg"
  location = "australiaeast"
}

resource "azurerm_virtual_network" "thinkix_vnet" {
  name                = "thinkix-hybrid-vnet"
  address_space       = ["10.20.0.0/16"]
  location            = azurerm_resource_group.thinkix_rg.location
  resource_group_name = azurerm_resource_group.thinkix_rg.name
}

resource "azurerm_subnet" "app_subnet" {
  name                 = "thinkix-app-subnet"
  resource_group_name  = azurerm_resource_group.thinkix_rg.name
  virtual_network_name = azurerm_virtual_network.thinkix_vnet.name
  address_prefixes     = ["10.20.1.0/24"]
}

# Network Security Group - default-deny placeholder, same principle
# as the AWS security group; zone-specific rules can be added as needed.
resource "azurerm_network_security_group" "app_zone_nsg" {
  name                = "thinkix-app-zone-nsg"
  location            = azurerm_resource_group.thinkix_rg.location
  resource_group_name = azurerm_resource_group.thinkix_rg.name

  tags = {
    Project = "ThinkiX-ZeroTrust"
  }
}

resource "azurerm_subnet_network_security_group_association" "app_subnet_nsg" {
  subnet_id                 = azurerm_subnet.app_subnet.id
  network_security_group_id = azurerm_network_security_group.app_zone_nsg.id
}
# Application zone (AWS) -> Cloud zone (Azure), matching the matrix.
# Same cross-cloud limitation as above: enforceable in the rule
# definition, but not yet a connected path pending VPN/peering.
resource "azurerm_network_security_rule" "app_to_cloud" {
  name                        = "AllowAppZoneHTTPS"
  priority                    = 100
  direction                   = "Inbound"
  access                      = "Allow"
  protocol                    = "Tcp"
  source_port_range           = "*"
  destination_port_range      = "443"
  source_address_prefix       = "10.10.3.0/24"
  destination_address_prefix  = "*"
  resource_group_name         = azurerm_resource_group.thinkix_rg.name
  network_security_group_name = azurerm_network_security_group.app_zone_nsg.name
}