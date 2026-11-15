<#
=============================================================================
QUINOR - Paso 2: sube las imagenes al ACR y carga la configuracion en AKS
=============================================================================
  1. Inicia sesion en el ACR
  2. Etiqueta y sube las 5 imagenes propias que construyo Docker Compose
  3. Crea en el cluster el Secret "quinor-env" a partir del .env
  4. Crea el ConfigMap "aws-certs" con el certificado de la base (global-bundle.pem)

Antes, construye las imagenes en local desde despacho\api:
  docker compose build

Uso:
  .\02_publicar_imagenes_y_secretos.ps1 -Acr quinoracr2026
  .\02_publicar_imagenes_y_secretos.ps1 -Acr quinoracr2026 -Etiqueta 1.1 -SoloImagenes

IMPORTANTE: el .env contiene claves (base, bucket S3, administrador). Este script
las manda al cluster como Secret y NO las imprime. El .env no se sube al ACR.
=============================================================================
#>
param(
    [Parameter(Mandatory = $true)][string]$Acr,
    [string]$Etiqueta = "1.0",
    # Prefijo con el que Compose nombra las imagenes locales: es el "name:" del
    # docker-compose.yml. Con "name: quinor" las imagenes son quinor-api, etc.
    [string]$PrefijoLocal = "quinor",
    [string]$Namespace = "quinor",
    [string]$RutaApi = "",
    [switch]$SoloImagenes,
    [switch]$SoloSecretos
)

$ErrorActionPreference = "Continue"

function Paso($texto) { Write-Host "`n== $texto" -ForegroundColor Cyan }
function Verificar($texto) {
    if ($LASTEXITCODE -ne 0) { throw "Fallo el paso: $texto" }
}

if ($RutaApi -eq "") {
    $RutaApi = Join-Path $PSScriptRoot "..\despacho\api"
}
$RutaApi = (Resolve-Path $RutaApi).Path

# Servicios con imagen propia (un Dockerfile cada uno).
$servicios = @("api", "grabador", "yolo", "vlm", "notificaciones")

# --- 1 y 2. Imagenes ----------------------------------------------------------
if (-not $SoloSecretos) {
    Paso "Iniciando sesion en el registro $Acr"
    az acr login --name $Acr
    Verificar "az acr login"
    $servidor = az acr show --name $Acr --query loginServer -o tsv
    Verificar "leer el servidor del ACR"

    foreach ($s in $servicios) {
        $local = "$PrefijoLocal-$s"
        $remota = "$servidor/quinor-${s}:$Etiqueta"

        docker image inspect $local 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "No existe la imagen local '$local'. Ejecuta 'docker compose build' en $RutaApi o revisa -PrefijoLocal."
        }

        Paso "Subiendo $local -> $remota"
        docker tag $local $remota
        Verificar "etiquetar $local"
        docker push $remota
        Verificar "subir $remota"
    }

    Paso "Contenido del registro"
    az acr repository list --name $Acr -o table
}

# --- 3 y 4. Secret y ConfigMap ------------------------------------------------
if (-not $SoloImagenes) {
    $rutaEnv = Join-Path $RutaApi ".env"
    $rutaCert = Join-Path $RutaApi "certs\global-bundle.pem"
    if (-not (Test-Path $rutaEnv)) { throw "No existe $rutaEnv" }
    if (-not (Test-Path $rutaCert)) { throw "No existe $rutaCert" }

    Paso "Secret quinor-env (desde el .env, sin mostrar su contenido)"
    # Un .env creado en Windows trae fines de linea CRLF; kubectl los dejaria
    # pegados al final de cada valor (por ejemplo en la clave de S3). Se limpian
    # en una copia temporal que se borra al terminar.
    $temporal = Join-Path $env:TEMP ("quinor-env-" + [guid]::NewGuid().ToString("N") + ".env")
    try {
        $texto = [IO.File]::ReadAllText($rutaEnv) -replace "`r", ""
        [IO.File]::WriteAllText($temporal, $texto, (New-Object Text.UTF8Encoding $false))
        kubectl create secret generic quinor-env `
            --from-env-file="$temporal" --namespace $Namespace `
            --dry-run=client -o yaml | kubectl apply -f -
        Verificar "crear el Secret quinor-env"
    }
    finally {
        if (Test-Path $temporal) { Remove-Item $temporal -Force }
    }

    Paso "ConfigMap aws-certs (certificado para el SSL de la base)"
    # En el pod debe montarse en /certs: DATABASE_URL usa ssl_ca=/certs/global-bundle.pem
    kubectl create configmap aws-certs `
        --from-file="global-bundle.pem=$rutaCert" --namespace $Namespace `
        --dry-run=client -o yaml | kubectl apply -f -
    Verificar "crear el ConfigMap aws-certs"

    Paso "Objetos creados en el namespace $Namespace"
    kubectl get secret,configmap --namespace $Namespace
}

Write-Host "`nListo. Las imagenes quedan en <servidor-acr>/quinor-<servicio>:$Etiqueta" -ForegroundColor Green
