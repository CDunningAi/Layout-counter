// =============================================================================
// Layout-Counter — Azure Infrastructure (Bicep)
// =============================================================================
// All resources are idempotent. Re-running this template will update in place.
// No numeric suffixes are used on resource names.
//
// Deploy via:  infra/deploy.sh  (or deploy.ps1 on Windows)
// =============================================================================

targetScope = 'resourceGroup'

@description('Azure region for all resources.')
param location string = 'eastus'

@description('Log Analytics Workspace name.')
param logAnalyticsWorkspaceName string = 'log-layout-counter'

@description('Application Insights name.')
param appInsightsName string = 'appi-layout-counter'

@description('Storage Account name (must be globally unique, 3-24 lowercase alphanumeric).')
param storageAccountName string = 'stlayoutcounter'

@description('Key Vault name (must be globally unique, 3-24 alphanumeric/hyphens).')
param keyVaultName string = 'kv-layout-counter'

@description('Azure OpenAI resource name.')
param aoaiName string = 'aoai-layout-counter'

@description('GPT-4o model deployment name.')
param aoaiDeploymentName string = 'gpt-4o'

@description('Flex Consumption App Service Plan name.')
param appServicePlanName string = 'plan-layout-counter'

@description('Function App name (must be globally unique).')
param functionAppName string = 'func-layout-counter'

@description('SharePoint site hostname.')
param sharepointSiteHostname string = 'brigholme.sharepoint.com'

@description('SharePoint site path.')
param sharepointSitePath string = '/'

@description('SharePoint upload folder path.')
param sharepointFolderPath string = '/IT-PowerAppStorage/Layout-Counter'

@description('Graph API tenant ID.')
param graphTenantId string = 'ed98cf63-c631-48b8-9937-817ea8c6cf53'

@description('Graph API client ID.')
param graphClientId string = '569177ec-898b-46c7-8c37-70ce7fff62e6'

// =============================================================================
// Log Analytics Workspace
// =============================================================================
resource logAnalyticsWorkspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logAnalyticsWorkspaceName
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

// =============================================================================
// Application Insights (workspace-based)
// =============================================================================
resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalyticsWorkspace.id
    IngestionMode: 'LogAnalytics'
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
  }
}

// =============================================================================
// Storage Account
// =============================================================================
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: storageAccountName
  location: location
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    accessTier: 'Hot'
    allowBlobPublicAccess: false
  }
}

resource storageDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'diag-storage'
  scope: storageAccount
  properties: {
    workspaceId: logAnalyticsWorkspace.id
    metrics: [
      {
        category: 'Transaction'
        enabled: true
      }
    ]
  }
}

// =============================================================================
// Key Vault
// =============================================================================
resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  properties: {
    sku: {
      family: 'A'
      name: 'standard'
    }
    tenantId: subscription().tenantId
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 90
    enablePurgeProtection: true
  }
}

resource keyVaultDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'diag-keyvault'
  scope: keyVault
  properties: {
    workspaceId: logAnalyticsWorkspace.id
    logs: [
      {
        categoryGroup: 'allLogs'
        enabled: true
      }
    ]
    metrics: [
      {
        category: 'AllMetrics'
        enabled: true
      }
    ]
  }
}

// Placeholder secret — actual value set by set-keyvault-secret.sh.
resource graphClientSecretPlaceholder 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'GraphClientSecret'
  properties: {
    value: 'placeholder-replace-via-set-keyvault-secret-sh'
    attributes: {
      enabled: true
    }
  }
}

// =============================================================================
// Azure OpenAI
// =============================================================================
resource aoai 'Microsoft.CognitiveServices/accounts@2024-04-01-preview' = {
  name: aoaiName
  location: location
  kind: 'OpenAI'
  sku: {
    name: 'S0'
  }
  properties: {
    customSubDomainName: aoaiName
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      defaultAction: 'Allow'
    }
  }
}

resource aoaiDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'diag-aoai'
  scope: aoai
  properties: {
    workspaceId: logAnalyticsWorkspace.id
    logs: [
      {
        categoryGroup: 'allLogs'
        enabled: true
      }
    ]
    metrics: [
      {
        category: 'AllMetrics'
        enabled: true
      }
    ]
  }
}

resource aoaiDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-04-01-preview' = {
  parent: aoai
  name: aoaiDeploymentName
  sku: {
    name: 'GlobalStandard'
    capacity: 10
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-4o'
      version: '2024-11-20'
    }
    versionUpgradeOption: 'OnceCurrentVersionExpired'
  }
}

// =============================================================================
// Flex Consumption Plan
// =============================================================================
resource appServicePlan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: appServicePlanName
  location: location
  sku: {
    name: 'FC1'
    tier: 'FlexConsumption'
  }
  kind: 'functionapp'
  properties: {
    reserved: true // Linux
  }
}

// =============================================================================
// Function App
// =============================================================================
resource functionApp 'Microsoft.Web/sites@2023-12-01' = {
  name: functionAppName
  location: location
  kind: 'functionapp,linux'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: appServicePlan.id
    reserved: true
    siteConfig: {
      linuxFxVersion: 'Python|3.11'
      appSettings: [
        {
          name: 'AzureWebJobsStorage__accountName'
          value: storageAccount.name
        }
        {
          name: 'FUNCTIONS_WORKER_RUNTIME'
          value: 'python'
        }
        {
          name: 'FUNCTIONS_EXTENSION_VERSION'
          value: '~4'
        }
        {
          name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
          value: appInsights.properties.ConnectionString
        }
        {
          name: 'AZURE_OPENAI_ENDPOINT'
          value: 'https://${aoai.properties.endpoint != null ? aoai.name : aoaiName}.openai.azure.com/'
        }
        {
          name: 'AZURE_OPENAI_DEPLOYMENT'
          value: aoaiDeploymentName
        }
        {
          name: 'AZURE_OPENAI_API_VERSION'
          value: '2024-08-01-preview'
        }
        {
          name: 'GRAPH_TENANT_ID'
          value: graphTenantId
        }
        {
          name: 'GRAPH_CLIENT_ID'
          value: graphClientId
        }
        {
          name: 'GRAPH_CLIENT_SECRET'
          value: '@Microsoft.KeyVault(SecretUri=https://${keyVaultName}.vault.azure.net/secrets/GraphClientSecret/)'
        }
        {
          name: 'SHAREPOINT_SITE_HOSTNAME'
          value: sharepointSiteHostname
        }
        {
          name: 'SHAREPOINT_SITE_PATH'
          value: sharepointSitePath
        }
        {
          name: 'SHAREPOINT_FOLDER_PATH'
          value: sharepointFolderPath
        }
        {
          name: 'LOG_LEVEL'
          value: 'INFO'
        }
        {
          name: 'PYTHON_ENABLE_WORKER_EXTENSIONS'
          value: '1'
        }
      ]
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
    }
    httpsOnly: true
  }
  dependsOn: [
    appServicePlan
    storageAccount
    appInsights
    aoai
    keyVault
  ]
}

resource functionAppDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'diag-functionapp'
  scope: functionApp
  properties: {
    workspaceId: logAnalyticsWorkspace.id
    logs: [
      {
        category: 'FunctionAppLogs'
        enabled: true
      }
    ]
    metrics: [
      {
        category: 'AllMetrics'
        enabled: true
      }
    ]
  }
}

// =============================================================================
// Role Assignments (Function App system MI)
// =============================================================================

// Storage Blob Data Owner — required for identity-based AzureWebJobsStorage.
resource storageBlobDataOwnerRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, functionApp.id, 'storageBlobDataOwner')
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      'b7e6dc6d-f1e8-4753-8033-0f276bb0955b' // Storage Blob Data Owner
    )
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// Cognitive Services OpenAI User — allows the function app MI to call AOAI.
resource aoaiOpenAIUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(aoai.id, functionApp.id, 'cognitiveServicesOpenAIUser')
  scope: aoai
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd' // Cognitive Services OpenAI User
    )
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// Key Vault Secrets User — allows the function app to read Key Vault secrets.
resource kvSecretsUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, functionApp.id, 'keyVaultSecretsUser')
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '4633458b-17de-408a-b874-0445c86b69e6' // Key Vault Secrets User
    )
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// =============================================================================
// Outputs
// =============================================================================
output functionAppHostname string = functionApp.properties.defaultHostName
output keyVaultName string = keyVault.name
output functionAppName string = functionApp.name
output aoaiEndpoint string = 'https://${aoaiName}.openai.azure.com/'
