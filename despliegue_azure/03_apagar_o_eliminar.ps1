<#
=============================================================================
QUINOR - Paso 3: controla el gasto del cluster AKS
=============================================================================
  estado    Muestra si el cluster esta encendido y con cuantos nodos
  detener   Apaga los nodos (el control plane Free no cobra). Conserva todo
  iniciar   Vuelve a encender un cluster detenido
  eliminar  Borra el cluster y el registro ACR. NO borra el grupo de recursos,
            porque ahi vive tambien la VM quinor-vm

Uso:
  .\03_apagar_o_eliminar.ps1 estado
  .\03_apagar_o_eliminar.ps1 detener
  .\03_apagar_o_eliminar.ps1 iniciar
  .\03_apagar_o_eliminar.ps1 eliminar -Acr quinoracr2026

Un cluster detenido deja de cobrar la VM de los nodos, pero los discos y la IP
publica siguen cobrando. Con credito limitado (Azure for Students vence el
01/12/2026), detenerlo al terminar cada sesion es lo mas barato.
=============================================================================
#>
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("estado", "detener", "iniciar", "eliminar")]
    [string]$Accion,
    [string]$GrupoRecursos = "quinor-rg",
    [string]$Cluster = "quinor-aks",
    [string]$Acr = ""
)

$ErrorActionPreference = "Continue"

function Verificar($texto) {
    if ($LASTEXITCODE -ne 0) { throw "Fallo: $texto" }
}

switch ($Accion) {
    "estado" {
        az aks show --resource-group $GrupoRecursos --name $Cluster `
            --query "{estado:powerState.code, version:kubernetesVersion, nodos:agentPoolProfiles[0].count, tamano:agentPoolProfiles[0].vmSize}" `
            -o table
        Verificar "consultar el estado"
    }
    "detener" {
        Write-Host "Deteniendo $Cluster (tarda un par de minutos)..."
        az aks stop --resource-group $GrupoRecursos --name $Cluster
        Verificar "detener el cluster"
        Write-Host "Cluster detenido." -ForegroundColor Green
    }
    "iniciar" {
        Write-Host "Iniciando $Cluster (tarda unos minutos)..."
        az aks start --resource-group $GrupoRecursos --name $Cluster
        Verificar "iniciar el cluster"
        az aks get-credentials --resource-group $GrupoRecursos --name $Cluster --overwrite-existing
        kubectl get nodes
    }
    "eliminar" {
        Write-Host "Se borrara el cluster '$Cluster' y, si se indico, el registro '$Acr'." -ForegroundColor Yellow
        Write-Host "El grupo de recursos '$GrupoRecursos' NO se toca."
        $respuesta = Read-Host "Escribe el nombre del cluster para confirmar"
        if ($respuesta -ne $Cluster) {
            Write-Host "No coincide. No se borro nada."
            return
        }
        az aks delete --resource-group $GrupoRecursos --name $Cluster --yes
        Verificar "eliminar el cluster"
        if ($Acr -ne "") {
            az acr delete --resource-group $GrupoRecursos --name $Acr --yes
            Verificar "eliminar el ACR"
        }
        Write-Host "Eliminado." -ForegroundColor Green
    }
}
