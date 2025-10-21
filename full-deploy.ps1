# Complete deployment script for KDD HR System
# This script creates all necessary Azure resources and deploys the application

param(
    [string]$ResourceGroup = "kdd-hr-complete-rg",
    [string]$Location = "East Asia",
    [string]$AcrName = "hrsysacr",
    [string]$AppServicePlan = "hrsys-plan",
    [string]$WebAppName = "hrsys",
    [string]$ImageName = "kdd-hr-system",
    [string]$CommitMessage = "Complete deployment"
)

Write-Host " KDD HR System - Complete Deployment" -ForegroundColor Cyan
Write-Host "========================================"
Write-Host ""

# Check if logged in to Azure
Write-Host " Checking Azure CLI login..." -ForegroundColor Yellow
try {
    $account = az account show --query name -o tsv
    Write-Host " Logged in as: $account" -ForegroundColor Green
} catch {
    Write-Host " Not logged into Azure. Please login first." -ForegroundColor Red
    az login
    if ($LASTEXITCODE -ne 0) {
        Write-Host " Failed to login to Azure" -ForegroundColor Red
        exit 1
    }
}

Write-Host ""
Write-Host "  Deployment Configuration:" -ForegroundColor Blue
Write-Host "  Resource Group: $ResourceGroup" -ForegroundColor White
Write-Host "  Location: $Location" -ForegroundColor White
Write-Host "  ACR Name: $AcrName" -ForegroundColor White
Write-Host "  App Service Plan: $AppServicePlan" -ForegroundColor White
Write-Host "  Web App: $WebAppName" -ForegroundColor White
Write-Host "  Image: $ImageName" -ForegroundColor White
Write-Host ""

# Step 1: Create Resource Group
Write-Host " Step 1: Creating Resource Group..." -ForegroundColor Yellow
$rgExists = az group exists --name $ResourceGroup
if ($rgExists -eq "false") {
    Write-Host "Creating resource group: $ResourceGroup" -ForegroundColor Gray
    az group create --name $ResourceGroup --location $Location
    if ($LASTEXITCODE -eq 0) {
        Write-Host " Resource group created successfully" -ForegroundColor Green
    } else {
        Write-Host " Failed to create resource group" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host " Resource group already exists" -ForegroundColor Green
}

# Step 2: Create Azure Container Registry
Write-Host ""
Write-Host " Step 2: Creating Azure Container Registry..." -ForegroundColor Yellow
$acrExists = az acr show --name $AcrName --resource-group $ResourceGroup --query "name" -o tsv 2>$null
if (-not $acrExists) {
    Write-Host "Creating ACR: $AcrName" -ForegroundColor Gray
    az acr create --resource-group $ResourceGroup --name $AcrName --sku Basic --admin-enabled true
    if ($LASTEXITCODE -eq 0) {
        Write-Host " ACR created successfully" -ForegroundColor Green
    } else {
        Write-Host " Failed to create ACR" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host " ACR already exists" -ForegroundColor Green
}

# Step 3: Get ACR credentials
Write-Host ""
Write-Host " Step 3: Getting ACR credentials..." -ForegroundColor Yellow
$acrServer = az acr show --name $AcrName --resource-group $ResourceGroup --query "loginServer" -o tsv
$acrUsername = az acr credential show --name $AcrName --resource-group $ResourceGroup --query "username" -o tsv
$acrPassword = az acr credential show --name $AcrName --resource-group $ResourceGroup --query "passwords[0].value" -o tsv

if ($acrServer -and $acrUsername -and $acrPassword) {
    Write-Host " ACR credentials retrieved successfully" -ForegroundColor Green
    Write-Host "  Server: $acrServer" -ForegroundColor Gray
} else {
    Write-Host " Failed to get ACR credentials" -ForegroundColor Red
    exit 1
}

# Step 4: Build image with timestamp
Write-Host ""
Write-Host " Step 4: Building Docker image inside ACR..." -ForegroundColor Yellow

# Generate version tag and full image name
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$versionTag = "deploy-$timestamp"
$fullImageName = "$acrServer/$ImageName"

Write-Host "Building image: $fullImageName`:$versionTag" -ForegroundColor Gray

az acr build `
    --registry $AcrName `
    --image "$($fullImageName):$versionTag" `
    --image "$($fullImageName):latest" `
    --platform linux/amd64 `
    --timeout 1800 `
    .

if ($LASTEXITCODE -ne 0) {
    Write-Host " ACR build failed" -ForegroundColor Red
    exit 1
}
Write-Host " ACR build completed successfully" -ForegroundColor Green

# Step 5: Create App Service Plan
Write-Host ""
Write-Host " Step 5: Creating App Service Plan..." -ForegroundColor Yellow
$planExists = az appservice plan show --name $AppServicePlan --resource-group $ResourceGroup --query "name" -o tsv 2>$null
if (-not $planExists) {
    Write-Host "Creating App Service Plan: $AppServicePlan" -ForegroundColor Gray
    az appservice plan create --name $AppServicePlan --resource-group $ResourceGroup --is-linux --sku B1
    if ($LASTEXITCODE -eq 0) {
        Write-Host " App Service Plan created successfully" -ForegroundColor Green
    } else {
        Write-Host " Failed to create App Service Plan" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host " App Service Plan already exists" -ForegroundColor Green
}

# Step 6: Create Web App
Write-Host ""
Write-Host " Step 6: Creating Web App..." -ForegroundColor Yellow
$webappExists = az webapp show --name $WebAppName --resource-group $ResourceGroup --query "name" -o tsv 2>$null
if (-not $webappExists) {
    Write-Host "Creating Web App: $WebAppName" -ForegroundColor Gray
    az webapp create --resource-group $ResourceGroup --plan $AppServicePlan --name $WebAppName --deployment-container-image-name "$fullImageName`:$versionTag"
    if ($LASTEXITCODE -eq 0) {
        Write-Host " Web App created successfully" -ForegroundColor Green
    } else {
        Write-Host " Failed to create Web App" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host " Web App already exists, updating container..." -ForegroundColor Green
    az webapp config container set --name $WebAppName --resource-group $ResourceGroup --docker-custom-image-name "$fullImageName`:$versionTag" --docker-registry-server-url "https://$acrServer"
}

# Step 7: Configure ACR authentication
Write-Host ""
Write-Host " Step 7: Configuring container registry authentication..." -ForegroundColor Yellow
az webapp config container set --name $WebAppName --resource-group $ResourceGroup --docker-registry-server-url "https://$acrServer" --docker-registry-server-user $acrUsername --docker-registry-server-password $acrPassword

if ($LASTEXITCODE -eq 0) {
    Write-Host " ACR authentication configured successfully" -ForegroundColor Green
} else {
    Write-Host " Failed to configure ACR authentication" -ForegroundColor Red
    exit 1
}

# Step 8: Configure application settings
Write-Host ""
Write-Host " Step 8: Configuring application settings..." -ForegroundColor Yellow

$appSettings = @(
    "WEBSITES_PORT=8501",
    "DOCKER_REGISTRY_SERVER_URL=https://$acrServer",
    "DOCKER_REGISTRY_SERVER_USERNAME=$acrUsername",
    "DOCKER_REGISTRY_SERVER_PASSWORD=$acrPassword",
    "SEARXNG_SETTINGS_PATH=/etc/searxng/settings.yml",
    "REDIS_URL=redis://localhost:6379",
    "SEARXNG_BASE_URL=http://localhost:8080",
    "WEBSITES_CONTAINER_START_TIME_LIMIT=300"
)

Write-Host "Setting application configuration..." -ForegroundColor Gray
foreach ($setting in $appSettings) {
    $parts = $setting -split "=", 2
    az webapp config appsettings set --resource-group $ResourceGroup --name $WebAppName --settings "$($parts[0])=$($parts[1])" | Out-Null
}

Write-Host " Application settings configured successfully" -ForegroundColor Green

# Step 9: Start the application
Write-Host ""
Write-Host " Step 9: Starting the application..." -ForegroundColor Yellow
az webapp start --resource-group $ResourceGroup --name $WebAppName
if ($LASTEXITCODE -eq 0) {
    Write-Host " Application started successfully" -ForegroundColor Green
} else {
    Write-Host " Failed to start application" -ForegroundColor Red
    exit 1
}

# Final summary
Write-Host ""
Write-Host " Deployment Completed Successfully!" -ForegroundColor Green
Write-Host "====================================="
Write-Host ""
Write-Host " Deployment Summary:" -ForegroundColor Blue
Write-Host "   Version: $versionTag" -ForegroundColor White
Write-Host "   Application URL: https://$WebAppName.azurewebsites.net" -ForegroundColor White
Write-Host "   Container Image: $fullImageName`:latest" -ForegroundColor White
Write-Host "   Resource Group: $ResourceGroup" -ForegroundColor White
Write-Host "   ACR: $acrServer" -ForegroundColor White
Write-Host ""
Write-Host " Next Steps:" -ForegroundColor Yellow
Write-Host "  1. Wait 2-3 minutes for all services to start" -ForegroundColor White
Write-Host "  2. Visit: https://$WebAppName.azurewebsites.net" -ForegroundColor White
Write-Host "  3. Monitor logs: az webapp log tail --resource-group $ResourceGroup --name $WebAppName" -ForegroundColor White
Write-Host "  4. Use .\monitor-app.ps1 for real-time monitoring" -ForegroundColor White
Write-Host ""
Write-Host " Showing initial startup logs:" -ForegroundColor Cyan
Start-Sleep -Seconds 15
az webapp log tail --resource-group $ResourceGroup --name $WebAppName --provider application --lines 30
