<#
=============================================================================
QUINOR - Paso 1: crea en Azure los recursos para desplegar en Kubernetes (AKS)
=============================================================================
Crea, en este orden:
  1. Registro de los proveedores de recursos de la suscripcion
  2. Grupo de recursos            (si ya existe, lo reutiliza)
  3. Azure Container Registry     (guarda las 5 imagenes propias)
  4. Cluster AKS                  (nivel Free, un grupo de nodos "system")
  5. Credenciales de kubectl y el namespace "quinor"

No crea base de datos ni almacen de clips: siguen en AWS Lightsail y Amazon S3.

Uso (PowerShell, con Azure CLI instalada):
  .\01_crear_aks.ps1 -Acr quinoracr2026
  .\01_crear_aks.ps1 -Acr quinoracr2026 -TamanoNodo Standard_D4s_v5 -ConIngress

El nombre del ACR debe ser unico en todo Azure: solo letras y numeros, 5 a 50.
Es seguro volver a ejecutarlo: lo que ya existe se conserva.
=============================================================================
#>
param(
    [Parameter(Mandatory = $true)][string]$Acr,
    [string]$Suscripcion = "",
    [string]$GrupoRecursos = "quinor-rg",
    [string]$Ubicacion = "westus2",
    [string]$Cluster = "quinor-aks",
    [string]$TamanoNodo = "Standard_B2s_v2",
    [int]$Nodos = 1,
    [int]$DiscoNodoGB = 64,
    [string]$Namespace = "quinor",
    [switch]$ConIngress
)

# Con "Continue" los errores de az no cortan el script a medias en PowerShell 5.1;
# cada llamada se comprueba a mano con Verificar.
$ErrorActionPreference = "Continue"

function Paso($texto) { Write-Host "`n== $texto" -ForegroundColor Cyan }
function Verificar($texto) {
    if ($LASTEXITCODE -ne 0) { throw "Fallo el paso: $texto" }
}

if ($Acr -notmatch '^[a-zA-Z0-9]{5,50}$') {
    throw "El nombre del ACR debe tener solo letras y numeros, entre 5 y 50 caracteres."
}

# --- 0. Sesion y suscripcion --------------------------------------------------
Paso "Comprobando la sesion de Azure"
az account show -o none 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    az login -o none
    Verificar "az login"
}
if ($Suscripcion -ne "") {
    az account set --subscription $Suscripcion
    Verificar "seleccionar la suscripcion"
}
az account show --query "{suscripcion:name, id:id}" -o table

# --- 1. Proveedores de recursos -----------------------------------------------
# Una suscripcion nueva (Azure for Students) puede no tenerlos registrados y el
# primer "az aks create" falla con un error poco claro.
Paso "Registrando proveedores de recursos (puede tardar unos minutos)"
foreach ($p in @("Microsoft.ContainerService", "Microsoft.ContainerRegistry",
                 "Microsoft.Compute", "Microsoft.Network", "Microsoft.Storage")) {
    az provider register --namespace $p --wait -o none
    Verificar "registrar $p"
}

# --- 2. Grupo de recursos ------------------------------------------------------
Paso "Grupo de recursos: $GrupoRecursos ($Ubicacion)"
az group create --name $GrupoRecursos --location $Ubicacion -o none
Verificar "crear el grupo de recursos"

# --- 3. Azure Container Registry ----------------------------------------------
Paso "Registro de contenedores: $Acr (Basic)"
az acr create --resource-group $GrupoRecursos --name $Acr --location $Ubicacion --sku Basic -o none
Verificar "crear el ACR"

# --- 4. Cluster AKS ------------------------------------------------------------
# --tier free          control plane sin costo y sin SLA: suficiente para la demo
# --network-plugin     Azure CNI en modo overlay: no consume IPs de la red virtual
# --attach-acr         da al cluster permiso de lectura sobre el registro; exige
#                      ser Owner de la suscripcion. Si falla por permisos, crear el
#                      cluster sin esa opcion y ejecutar despues:
#                        az aks update -g <grupo> -n <cluster> --attach-acr <acr>
Paso "Cluster AKS: $Cluster ($Nodos x $TamanoNodo). Tarda entre 5 y 10 minutos"
$argumentos = @(
    "aks", "create",
    "--resource-group", $GrupoRecursos,
    "--name", $Cluster,
    "--location", $Ubicacion,
    "--tier", "free",
    "--nodepool-name", "system",
    "--node-count", $Nodos,
    "--node-vm-size", $TamanoNodo,
    "--node-osdisk-size", $DiscoNodoGB,
    "--network-plugin", "azure",
    "--network-plugin-mode", "overlay",
    "--enable-managed-identity",
    "--attach-acr", $Acr,
    "--generate-ssh-keys",
    "-o", "none"
)
if ($ConIngress) { $argumentos += "--enable-app-routing" }
az @argumentos
Verificar "crear el cluster AKS"

# --- 5. kubectl y namespace ----------------------------------------------------
Paso "Credenciales de kubectl"
if (-not (Get-Command kubectl -ErrorAction SilentlyContinue)) {
    Write-Host "kubectl no esta instalado: instalandolo con az aks install-cli"
    az aks install-cli
    Verificar "instalar kubectl"
}
az aks get-credentials --resource-group $GrupoRecursos --name $Cluster --overwrite-existing
Verificar "obtener credenciales"

Paso "Namespace: $Namespace"
kubectl create namespace $Namespace --dry-run=client -o yaml | kubectl apply -f -
Verificar "crear el namespace"

Paso "Nodos del cluster"
kubectl get nodes -o wide

Write-Host "`nListo. Siguiente paso: .\02_publicar_imagenes_y_secretos.ps1 -Acr $Acr" -ForegroundColor Green
