# Formulate — minimal Azure footprint: one Linux App Service, one OpenAI
# account with a chat deployment, one Key Vault holding the API key, one
# Log Analytics workspace for app logs.
#
#   terraform -chdir=infra init && terraform -chdir=infra apply

terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
  }
}

provider "azurerm" {
  features {}
}

variable "base_name" {
  type    = string
  default = "formulate"
}

variable "location" {
  type    = string
  default = "eastus2"
}

variable "model_name" {
  type    = string
  default = "gpt-4o"
}

variable "model_version" {
  type    = string
  default = "2024-08-06"
}

data "azurerm_client_config" "current" {}

resource "random_string" "suffix" {
  length  = 6
  special = false
  upper   = false
}

resource "azurerm_resource_group" "rg" {
  name     = "${var.base_name}-rg"
  location = var.location
}

resource "azurerm_log_analytics_workspace" "logs" {
  name                = "${var.base_name}-logs"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
}

resource "azurerm_cognitive_account" "openai" {
  name                  = "${var.base_name}-openai-${random_string.suffix.result}"
  location              = azurerm_resource_group.rg.location
  resource_group_name   = azurerm_resource_group.rg.name
  kind                  = "OpenAI"
  sku_name              = "S0"
  custom_subdomain_name = "${var.base_name}-openai-${random_string.suffix.result}"
}

resource "azurerm_cognitive_deployment" "chat" {
  name                 = var.model_name
  cognitive_account_id = azurerm_cognitive_account.openai.id

  model {
    format  = "OpenAI"
    name    = var.model_name
    version = var.model_version
  }

  sku {
    name     = "GlobalStandard"
    capacity = 10
  }
}

resource "azurerm_key_vault" "kv" {
  name                      = "${var.base_name}-kv-${random_string.suffix.result}"
  location                  = azurerm_resource_group.rg.location
  resource_group_name       = azurerm_resource_group.rg.name
  tenant_id                 = data.azurerm_client_config.current.tenant_id
  sku_name                  = "standard"
  enable_rbac_authorization = true
}

resource "azurerm_key_vault_secret" "openai_key" {
  name         = "azure-openai-api-key"
  value        = azurerm_cognitive_account.openai.primary_access_key
  key_vault_id = azurerm_key_vault.kv.id
}

resource "azurerm_service_plan" "plan" {
  name                = "${var.base_name}-plan"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  os_type             = "Linux"
  sku_name            = "B1"
}

resource "azurerm_linux_web_app" "app" {
  name                = "${var.base_name}-app-${random_string.suffix.result}"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  service_plan_id     = azurerm_service_plan.plan.id
  https_only          = true

  identity {
    type = "SystemAssigned"
  }

  site_config {
    app_command_line = "uvicorn api.main:app --host 0.0.0.0 --port 8000"
    application_stack {
      python_version = "3.12"
    }
  }

  app_settings = {
    AZURE_OPENAI_ENDPOINT   = azurerm_cognitive_account.openai.endpoint
    AZURE_OPENAI_DEPLOYMENT = var.model_name
    # AZURE_OPENAI_API_KEY is intentionally NOT set here. The key lives in
    # Key Vault (secret "azure-openai-api-key"); after deploy, point this
    # app setting at that secret with an App Service Key Vault reference so
    # the value never enters Terraform state or plaintext settings.
  }
}

# allow the app's managed identity to read the secret
resource "azurerm_role_assignment" "kv_reader" {
  scope                = azurerm_key_vault.kv.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_linux_web_app.app.identity[0].principal_id
}

output "app_url" {
  value = "https://${azurerm_linux_web_app.app.default_hostname}"
}

output "openai_endpoint" {
  value = azurerm_cognitive_account.openai.endpoint
}
