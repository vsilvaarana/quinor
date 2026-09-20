# =============================================================================
# QUINOR S.A.C. - Despliegue de la base en vallesol.pe
#
# Ejecuta los scripts en orden contra el servidor, desde tu PC, que es donde si
# hay ruta hacia el 3306.
#
# Uso, desde PowerShell en la carpeta quinor\despliegue:
#     .\desplegar.ps1
#     .\desplegar.ps1 -ConDemo          # carga tambien los datos de ejemplo
#     .\desplegar.ps1 -SoloDiagnostico  # no toca nada, solo lee
#
# La contrasena no se escribe aqui ni queda en el historial: el script la pide.
# Es la misma regla del apartado 8 del documento funcional, que prohibe claves
# en archivos versionados.
#
# Requiere el cliente mysql.exe en el PATH. Si no lo tienes, el script te lo
# dice y puedes usar phpMyAdmin con estos mismos archivos (ver LEEME.md).
# =============================================================================

param(
    [string]$Servidor = "vallesol.pe",
    [int]$Puerto = 3306,
    [string]$Usuario = "vallesol_user_yolo",
    [string]$Base = "vallesol_yolo",
    [switch]$ConDemo,
    [switch]$SoloDiagnostico
)

$ErrorActionPreference = "Stop"
$carpeta = Split-Path -Parent $MyInvocation.MyCommand.Path
$salida = Join-Path $carpeta "salida_despliegue.txt"

$mysql = Get-Command mysql -ErrorAction SilentlyContinue
if (-not $mysql) {
    Write-Host "No encuentro mysql.exe en el PATH." -ForegroundColor Yellow
    Write-Host "Opciones: instalar MySQL Shell o el cliente de MySQL, o importar"
    Write-Host "los .sql por phpMyAdmin en el orden que dice LEEME.md."
    exit 1
}

$clave = Read-Host "Contrasena de $Usuario" -AsSecureString
$claveTexto = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($clave))
# MYSQL_PWD evita que la clave aparezca en la linea de comandos y en el
# historial de PowerShell.
$env:MYSQL_PWD = $claveTexto

function Ejecutar($archivo, $descripcion) {
    Write-Host ""
    Write-Host "== $descripcion" -ForegroundColor Cyan
    $ruta = Join-Path $carpeta $archivo
    if (-not (Test-Path $ruta)) { throw "Falta el archivo $archivo" }

    "===== $descripcion ($archivo) =====" | Out-File -Append -Encoding utf8 $salida
    & mysql --host=$Servidor --port=$Puerto --user=$Usuario `
            --default-character-set=utf8mb4 --table $Base -e "source $ruta" 2>&1 |
        Tee-Object -Variable resultado | Write-Host
    $resultado | Out-File -Append -Encoding utf8 $salida

    if ($LASTEXITCODE -ne 0) {
        throw "$archivo termino con error. Revisa la salida de arriba."
    }
}

"Despliegue QUINOR - $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" |
    Out-File -Encoding utf8 $salida

try {
    Ejecutar "00_diagnostico.sql" "Diagnostico: motor, privilegios y contenido actual"

    if (-not $SoloDiagnostico) {
        Ejecutar "01_esquema.sql"  "Esquema: tablas, vistas y tolerancias"
        Ejecutar "02_triggers.sql" "Triggers: RN-06 y auditoria inmutable"
        if ($ConDemo) {
            Ejecutar "03_datos_demo.sql" "Datos de demostracion"
        }
        Ejecutar "99_verificacion.sql" "Verificacion final"
    }

    Write-Host ""
    Write-Host "Listo. La salida completa quedo en:" -ForegroundColor Green
    Write-Host "  $salida"
    Write-Host "Pegamela para revisar que todo quedo como debe."
}
finally {
    Remove-Item Env:MYSQL_PWD -ErrorAction SilentlyContinue
    $claveTexto = $null
}
