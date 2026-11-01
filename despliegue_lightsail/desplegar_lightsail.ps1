# =============================================================================
# QUINOR S.A.C. - Despliegue de la base en AWS Lightsail (MySQL 8)
#
# Corre los scripts en orden contra la base de Lightsail, desde tu PC.
#
# Uso, desde PowerShell en esta carpeta:
#   .\desplegar_lightsail.ps1 -Servidor ls-xxxx.yyyy.us-east-1.rds.amazonaws.com -Base quinor -SoloDiagnostico
#   .\desplegar_lightsail.ps1 -Servidor ls-xxxx.yyyy.us-east-1.rds.amazonaws.com -Base quinor -ConDemo
#   .\desplegar_lightsail.ps1 -Servidor ... -Base quinor -CrearUsuarioApp
#
# Si Windows bloquea el script:
#   powershell -ExecutionPolicy Bypass -File .\desplegar_lightsail.ps1 -Servidor ... -Base quinor
#
# Que hace distinto del despliegue de MariaDB:
#   - Se conecta con SSL verificando el certificado de AWS (global-bundle.pem).
#     Si el archivo no esta en esta carpeta, lo descarga de AWS.
#   - Fija la sesion en -05:00 (Lima). Lightsail trabaja en UTC, y sin esto las
#     fechas que pone el script (tolerancias, datos de demo) quedarian 5 h
#     adelantadas respecto de las que escribe la aplicacion.
#   - Antes de tocar nada, comprueba que el parametro de los triggers este
#     activo. Sin el, el paso 02 fallaria con ERROR 1419 a mitad de camino.
#
# Las contrasenas no se escriben aqui ni quedan en el historial: se piden.
# =============================================================================

param(
    [Parameter(Mandatory = $true)][string]$Servidor,
    [Parameter(Mandatory = $true)][string]$Base,
    [int]$Puerto = 3306,
    [string]$Usuario = "dbmasteruser",
    [string]$Certificado = "",
    [switch]$ConDemo,
    [switch]$SoloDiagnostico,
    [switch]$CrearUsuarioApp,
    [string]$UsuarioApp = "quinor_app",
    [switch]$SinSSL
)

$ErrorActionPreference = "Stop"
$carpeta = Split-Path -Parent $MyInvocation.MyCommand.Path
$salida = Join-Path $carpeta "salida_despliegue.txt"
$URL_CERTIFICADO = "https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem"

# ------------------------------------------------------------ cliente mysql
function Buscar-Mysql {
    $enPath = Get-Command mysql -ErrorAction SilentlyContinue
    if ($enPath) { return $enPath.Source }
    # Rutas habituales en Windows: MySQL Server, el cliente suelto y Workbench,
    # que tambien trae mysql.exe.
    $candidatos = @(
        "C:\Program Files\MySQL\MySQL Server *\bin\mysql.exe",
        "C:\Program Files\MySQL\MySQL Workbench *\mysql.exe",
        "C:\Program Files (x86)\MySQL\MySQL Server *\bin\mysql.exe"
    )
    foreach ($patron in $candidatos) {
        $hallado = Get-ChildItem -Path $patron -ErrorAction SilentlyContinue |
            Sort-Object FullName -Descending | Select-Object -First 1
        if ($hallado) { return $hallado.FullName }
    }
    return $null
}

$mysql = Buscar-Mysql
if (-not $mysql) {
    Write-Host "No encuentro mysql.exe." -ForegroundColor Yellow
    Write-Host "Instala MySQL Workbench o el cliente de MySQL 8 y vuelve a correr el script."
    Write-Host "Tambien puedes cargar los .sql desde Workbench en el orden de LEEME_LIGHTSAIL.md."
    exit 1
}
Write-Host "Cliente mysql: $mysql"

# ------------------------------------------------------------ certificado SSL
$argsSsl = @()
if (-not $SinSSL) {
    if (-not $Certificado) { $Certificado = Join-Path $carpeta "global-bundle.pem" }
    if (-not (Test-Path $Certificado)) {
        Write-Host "Descargando el certificado de AWS en $Certificado"
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $URL_CERTIFICADO -OutFile $Certificado -UseBasicParsing
    }
    # VERIFY_IDENTITY: cifra y ademas comprueba que el servidor es el de AWS
    # con ese nombre. Es lo que recomienda la guia de Lightsail.
    $argsSsl = @("--ssl-mode=VERIFY_IDENTITY", "--ssl-ca=$Certificado")
}

# ------------------------------------------------------------ contrasena
$clave = Read-Host "Contrasena de $Usuario" -AsSecureString
# NetworkCredential recupera el texto igual en Windows PowerShell 5.1 y en
# PowerShell 7 (PtrToStringAuto solo funciona bien en Windows).
$claveTexto = (New-Object System.Net.NetworkCredential('', $clave)).Password
# MYSQL_PWD evita que la clave aparezca en la linea de comandos y en el
# historial de PowerShell.
$env:MYSQL_PWD = $claveTexto

$argsBase = @("--protocol=TCP", "--host=$Servidor", "--port=$Puerto", "--user=$Usuario",
              "--default-character-set=utf8mb4",
              "--init-command=SET time_zone='-05:00'") + $argsSsl

function Consultar($sql) {
    # Una consulta corta sin cabeceras, para las comprobaciones previas.
    # En Windows PowerShell 5.1, con "Stop", cualquier aviso que mysql.exe
    # escriba por stderr se convierte en error fatal. Se decide por el codigo
    # de salida, que es lo que de verdad dice si fallo.
    $ErrorActionPreference = "Continue"
    $r = & $mysql @argsBase "--batch" "--skip-column-names" $Base "-e" $sql 2>&1
    $ErrorActionPreference = "Stop"
    if ($LASTEXITCODE -ne 0) { throw "No se pudo consultar la base: $r" }
    return ($r | Out-String).Trim()
}

function Ejecutar($archivo, $descripcion) {
    Write-Host ""
    Write-Host "== $descripcion" -ForegroundColor Cyan
    $ruta = Join-Path $carpeta $archivo
    if (-not (Test-Path $ruta)) { throw "Falta el archivo $archivo" }

    "===== $descripcion ($archivo) =====" | Out-File -Append -Encoding utf8 $salida
    # El cliente mysql entiende "/" en Windows y asi no hay barras que escapar.
    $rutaMysql = $ruta -replace '\\', '/'
    $ErrorActionPreference = "Continue"
    $resultado = & $mysql @argsBase "--table" $Base "-e" "source $rutaMysql" 2>&1
    $codigo = $LASTEXITCODE
    $ErrorActionPreference = "Stop"
    $resultado | ForEach-Object { Write-Host $_ }
    $resultado | Out-File -Append -Encoding utf8 $salida

    if ($codigo -ne 0) {
        throw "$archivo termino con error. Revisa la salida de arriba."
    }
}

"Despliegue QUINOR en Lightsail - $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" |
    Out-File -Encoding utf8 $salida

try {
    Ejecutar "00_diagnostico.sql" "Diagnostico: motor, privilegios, SSL, zona horaria"

    if (-not $SoloDiagnostico) {
        # Se comprueba ANTES de crear tablas: si falta el parametro, es mejor
        # no empezar que dejar el esquema a medias.
        $estado = Consultar "SELECT CONCAT(@@log_bin, ',', @@log_bin_trust_function_creators)"
        if ($estado -eq "1,0") {
            Write-Host ""
            Write-Host "ALTO: log_bin_trust_function_creators esta en 0." -ForegroundColor Red
            Write-Host "Los triggers (RN-06 y auditoria) fallarian con ERROR 1419."
            Write-Host "Corre primero .\configurar_lightsail.ps1 y vuelve a intentarlo."
            exit 2
        }

        Ejecutar "01_esquema.sql"  "Esquema: tablas, vistas y tolerancias"
        Ejecutar "02_triggers.sql" "Triggers: RN-06 y auditoria inmutable"
        if ($ConDemo) {
            Ejecutar "03_datos_demo.sql" "Datos de demostracion"
        }
        Ejecutar "99_verificacion.sql" "Verificacion final"
    }

    if ($CrearUsuarioApp) {
        # La aplicacion no crea ni altera tablas: le basta leer y escribir
        # datos. Asi, si su clave se filtra, no se puede borrar el esquema.
        Write-Host ""
        Write-Host "== Usuario de la aplicacion: $UsuarioApp" -ForegroundColor Cyan
        $claveApp = Read-Host "Contrasena nueva para $UsuarioApp (min. 12 caracteres)" -AsSecureString
        $claveAppTexto = (New-Object System.Net.NetworkCredential('', $claveApp)).Password
        if ($claveAppTexto.Length -lt 12) { throw "La contrasena debe tener al menos 12 caracteres." }
        if ($claveAppTexto -match "['\\]") { throw "Usa una contrasena sin comillas simples ni barras invertidas." }
        $sqlUsuario = "CREATE USER IF NOT EXISTS '$UsuarioApp'@'%' IDENTIFIED BY '$claveAppTexto'; " +
                      "ALTER USER '$UsuarioApp'@'%' IDENTIFIED BY '$claveAppTexto'; " +
                      "GRANT SELECT, INSERT, UPDATE, DELETE ON ``$Base``.* TO '$UsuarioApp'@'%';"
        $ErrorActionPreference = "Continue"
        $r = & $mysql @argsBase $Base "-e" $sqlUsuario 2>&1
        $codigoUsuario = $LASTEXITCODE
        $ErrorActionPreference = "Stop"
        if ($codigoUsuario -ne 0) { throw "No se pudo crear el usuario: $r" }
        $claveAppTexto = $null
        Write-Host "Usuario $UsuarioApp listo, con permisos de lectura y escritura sobre $Base." -ForegroundColor Green
    }

    Write-Host ""
    Write-Host "Listo. La salida completa quedo en:" -ForegroundColor Green
    Write-Host "  $salida"
}
finally {
    Remove-Item Env:MYSQL_PWD -ErrorAction SilentlyContinue
    $claveTexto = $null
}
