# =============================================================================
# QUINOR S.A.C. - Preparar la base de Lightsail para los triggers
#
# Por que hace falta: el esquema tiene 3 triggers (RN-06 y la auditoria
# inmutable de HU-16). En Lightsail el usuario maestro no tiene el privilegio
# SUPER y el binlog esta activo, asi que crear un trigger falla con:
#   ERROR 1419: You do not have the SUPER privilege and binary logging is enabled
# La salida que da AWS es poner log_bin_trust_function_creators = 1. Es un
# parametro dinamico: se aplica al momento, sin reiniciar la base.
#
# Requiere AWS CLI v2 configurado (aws configure) con un usuario que pueda
# administrar Lightsail.
#
# Uso:
#   .\configurar_lightsail.ps1 -NombreRecurso Database-1 -Region us-east-1
#   .\configurar_lightsail.ps1 -NombreRecurso Database-1 -Region us-east-1 -HacerPublica
#
# -NombreRecurso es el nombre que ves en la consola de Lightsail para la base
# (no el nombre de la base de datos interna).
# -HacerPublica activa el modo publico, necesario para conectarte desde tu PC.
# =============================================================================

param(
    [Parameter(Mandatory = $true)][string]$NombreRecurso,
    [Parameter(Mandatory = $true)][string]$Region,
    [switch]$HacerPublica
)

$ErrorActionPreference = "Stop"
$PARAMETRO = "log_bin_trust_function_creators"

if (-not (Get-Command aws -ErrorAction SilentlyContinue)) {
    Write-Host "No encuentro AWS CLI (aws.exe)." -ForegroundColor Yellow
    Write-Host "Instalalo desde https://aws.amazon.com/cli/ y corre 'aws configure'."
    Write-Host "Si no quieres instalarlo, mira la opcion manual en LEEME_LIGHTSAIL.md."
    exit 1
}

function Invocar-Aws([string[]]$argumentos) {
    $ErrorActionPreference = "Continue"
    $r = & aws @argumentos --region $Region --output json 2>&1
    $codigo = $LASTEXITCODE
    $ErrorActionPreference = "Stop"
    $texto = ($r | Out-String)
    if ($codigo -ne 0) { throw "aws $($argumentos[1]) fallo: $texto" }
    return $texto | ConvertFrom-Json
}

function Leer-Parametro {
    # Los parametros vienen por paginas; se recorren todas hasta encontrarlo.
    $token = $null
    do {
        $argumentos = @("lightsail", "get-relational-database-parameters",
                        "--relational-database-name", $NombreRecurso)
        if ($token) { $argumentos += @("--page-token", $token) }
        $pagina = Invocar-Aws $argumentos
        $hallado = $pagina.parameters | Where-Object { $_.parameterName -eq $PARAMETRO }
        if ($hallado) { return $hallado }
        $token = $pagina.nextPageToken
    } while ($token)
    return $null
}

# ------------------------------------------------------------ la base
Write-Host "== Base $NombreRecurso en $Region" -ForegroundColor Cyan
$base = (Invocar-Aws @("lightsail", "get-relational-database",
               "--relational-database-name", $NombreRecurso)).relationalDatabase
Write-Host ("Motor:     {0} {1}" -f $base.engine, $base.engineVersion)
Write-Host ("Estado:    {0}" -f $base.state)
Write-Host ("Endpoint:  {0}:{1}" -f $base.masterEndpoint.address, $base.masterEndpoint.port)
Write-Host ("Usuario:   {0}" -f $base.masterUsername)
Write-Host ("Base:      {0}" -f $base.masterDatabaseName)
Write-Host ("Publica:   {0}" -f $base.publiclyAccessible)

if ($base.engine -ne "mysql") {
    throw "La base es '$($base.engine)'. QUINOR necesita MySQL 8."
}

# ------------------------------------------------------------ modo publico
if (-not $base.publiclyAccessible) {
    if ($HacerPublica) {
        Write-Host ""
        Write-Host "== Activando el modo publico" -ForegroundColor Cyan
        Invocar-Aws @("lightsail", "update-relational-database",
              "--relational-database-name", $NombreRecurso,
              "--publicly-accessible") | Out-Null
        Write-Host "Pedido. Tarda unos minutos; el estado pasa por 'modifying'."
    } else {
        Write-Host ""
        Write-Host "La base NO es publica: desde tu PC no podras conectarte." -ForegroundColor Yellow
        Write-Host "Vuelve a correr con -HacerPublica, o activalo en la consola (pestana Redes)."
    }
}

# ------------------------------------------------------------ el parametro
Write-Host ""
Write-Host "== Parametro $PARAMETRO" -ForegroundColor Cyan
$actual = Leer-Parametro
if (-not $actual) { throw "La base no expone el parametro $PARAMETRO." }
Write-Host ("Valor actual: {0}  (modificable: {1}, tipo: {2})" -f `
    $actual.parameterValue, $actual.isModifiable, $actual.applyType)

if ($actual.parameterValue -eq "1") {
    Write-Host "Ya esta en 1. Los triggers se pueden crear." -ForegroundColor Green
    exit 0
}
if (-not $actual.isModifiable) {
    throw "AWS marca el parametro como no modificable en esta base."
}

# Se escribe el JSON a un archivo temporal: pasarlo en linea obliga a escapar
# comillas de forma distinta en PowerShell 5.1 y en 7.
$temporal = Join-Path ([IO.Path]::GetTempPath()) "quinor_parametros.json"
$cuerpo = @(@{ parameterName = $PARAMETRO; parameterValue = "1"; applyMethod = "immediate" })
ConvertTo-Json -InputObject $cuerpo -Depth 3 | Set-Content -Encoding ascii $temporal
try {
    $op = Invocar-Aws @("lightsail", "update-relational-database-parameters",
                "--relational-database-name", $NombreRecurso,
                "--parameters", "file://$temporal")
    Write-Host ("Operacion: {0}" -f $op.operations[0].status)
}
finally {
    Remove-Item $temporal -ErrorAction SilentlyContinue
}

# Confirmar que quedo aplicado. Suele tardar unos segundos.
for ($i = 1; $i -le 12; $i++) {
    Start-Sleep -Seconds 10
    $ahora = Leer-Parametro
    Write-Host ("  intento {0}: valor {1}" -f $i, $ahora.parameterValue)
    if ($ahora.parameterValue -eq "1") {
        Write-Host "Listo: $PARAMETRO = 1. Ya puedes correr desplegar_lightsail.ps1." -ForegroundColor Green
        exit 0
    }
}
Write-Host "AWS acepto el cambio pero aun no se refleja. Espera un par de minutos y" -ForegroundColor Yellow
Write-Host "vuelve a correr este script para confirmarlo."
exit 3
