<#
.SYNOPSIS
    Task runner for Windows - the PowerShell equivalent of the Makefile.

.EXAMPLE
    .\tasks.ps1 help
    .\tasks.ps1 setup
    .\tasks.ps1 check
    .\tasks.ps1 up

.NOTES
    Keep this file pure ASCII. Windows PowerShell 5.1 reads .ps1 files as ANSI
    unless they carry a UTF-8 BOM, so a stray em-dash or smart quote becomes
    mojibake and the script fails to parse with a misleading error pointing at
    an unrelated line.
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Task = "help",

    [Parameter(Position = 1, ValueFromRemainingArguments = $true)]
    [string[]]$Rest
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$ComposeFile = Join-Path $Root "infra/docker-compose.yml"

# Executables inside the backend virtual environment.
$VenvScripts = Join-Path $Backend ".venv/Scripts"
$Py = Join-Path $VenvScripts "python.exe"
$Ruff = Join-Path $VenvScripts "ruff.exe"
$Mypy = Join-Path $VenvScripts "mypy.exe"
$Pytest = Join-Path $VenvScripts "pytest.exe"

function Invoke-Step {
    param([string]$Name, [scriptblock]$Body)
    Write-Host ""
    Write-Host "==> $Name" -ForegroundColor Cyan
    & $Body
    if ($LASTEXITCODE -ne 0) { throw "$Name failed with exit code $LASTEXITCODE" }
}

function Assert-Venv {
    if (-not (Test-Path $Py)) {
        throw "backend/.venv not found. Run: .\tasks.ps1 setup"
    }
}

function Compose {
    param([string[]]$ComposeArgs)
    $envFile = Join-Path $Root ".env"
    if (-not (Test-Path $envFile)) { $envFile = Join-Path $Root ".env.example" }
    & docker compose --env-file $envFile -f $ComposeFile @ComposeArgs
}

switch ($Task.ToLower()) {

    "help" {
        Write-Host ""
        Write-Host "Tasks:" -ForegroundColor Cyan
        @(
            @("setup", "Create .env, backend venv, and install all dependencies"),
            @("env", "Create .env from .env.example if absent"),
            @("format", "Format backend code (ruff format)"),
            @("lint", "Lint backend code (ruff check)"),
            @("typecheck", "Type-check backend code (mypy)"),
            @("test", "Run backend tests (pytest)"),
            @("frontend-lint", "Lint frontend code (eslint)"),
            @("frontend-typecheck", "Type-check frontend code (tsc --noEmit)"),
            @("frontend-build", "Production build of the frontend"),
            @("compose-config", "Validate the Compose file"),
            @("check", "Run every quality gate"),
            @("up", "Build and start the Docker stack"),
            @("down", "Stop the stack (keeps the database volume)"),
            @("logs", "Follow logs from all services"),
            @("ps", "Show service status"),
            @("migrate", "Apply Alembic migrations in the api container"),
            @("revision", "Autogenerate a migration: .\tasks.ps1 revision ""message"""),
            @("shell-db", "Open psql against the running database"),
            @("clean", "Remove caches and build output")
        ) | ForEach-Object { "  {0,-20} {1}" -f $_[0], $_[1] }
        Write-Host ""
    }

    "env" {
        $envFile = Join-Path $Root ".env"
        if (Test-Path $envFile) {
            Write-Host ".env already exists - left untouched."
        }
        else {
            Copy-Item (Join-Path $Root ".env.example") $envFile
            Write-Host "Created .env from .env.example" -ForegroundColor Green
        }
    }

    "setup" {
        & $PSCommandPath env
        Invoke-Step "Create backend virtual environment" {
            if (-not (Test-Path $Py)) { py -3.12 -m venv (Join-Path $Backend ".venv") }
        }
        Invoke-Step "Install backend dependencies" {
            & $Py -m pip install --upgrade pip --quiet
            & $Py -m pip install -e "$Backend[dev]"
        }
        Invoke-Step "Install frontend dependencies" {
            Push-Location $Frontend; try { npm install } finally { Pop-Location }
        }
        Write-Host ""
        Write-Host "Setup complete." -ForegroundColor Green
    }

    "format" { Assert-Venv; Invoke-Step "ruff format" { & $Ruff format $Backend } }
    "lint" { Assert-Venv; Invoke-Step "ruff check" { & $Ruff check $Backend } }

    "typecheck" {
        Assert-Venv
        Invoke-Step "mypy" { Push-Location $Backend; try { & $Mypy } finally { Pop-Location } }
    }

    "test" {
        Assert-Venv
        Invoke-Step "pytest" { Push-Location $Backend; try { & $Pytest @Rest } finally { Pop-Location } }
    }

    "frontend-lint" {
        Invoke-Step "eslint" { Push-Location $Frontend; try { npm run lint } finally { Pop-Location } }
    }

    "frontend-typecheck" {
        Invoke-Step "tsc --noEmit" { Push-Location $Frontend; try { npm run typecheck } finally { Pop-Location } }
    }

    "frontend-build" {
        Invoke-Step "next build" { Push-Location $Frontend; try { npm run build } finally { Pop-Location } }
    }

    "compose-config" {
        Invoke-Step "docker compose config" { Compose @("config", "--quiet") }
    }

    "check" {
        & $PSCommandPath format
        & $PSCommandPath lint
        & $PSCommandPath typecheck
        & $PSCommandPath test
        & $PSCommandPath frontend-lint
        & $PSCommandPath frontend-typecheck
        & $PSCommandPath frontend-build
        & $PSCommandPath compose-config
        Write-Host ""
        Write-Host "All checks passed." -ForegroundColor Green
    }

    "up" { & $PSCommandPath env; Invoke-Step "docker compose up" { Compose @("up", "--build", "-d") } }
    "down" { Invoke-Step "docker compose down" { Compose @("down") } }
    "logs" { Compose @("logs", "-f") }
    "ps" { Compose @("ps") }
    "restart" { & $PSCommandPath down; & $PSCommandPath up }

    "migrate" { Invoke-Step "alembic upgrade head" { Compose @("exec", "api", "alembic", "upgrade", "head") } }

    "revision" {
        if (-not $Rest -or -not $Rest[0]) { throw 'Usage: .\tasks.ps1 revision "message"' }
        Invoke-Step "alembic revision" {
            Compose @("exec", "api", "alembic", "revision", "--autogenerate", "-m", $Rest[0])
        }
    }

    "shell-db" {
        $user = if ($env:POSTGRES_USER) { $env:POSTGRES_USER } else { "prms" }
        $db = if ($env:POSTGRES_DB) { $env:POSTGRES_DB } else { "prms" }
        Compose @("exec", "postgres", "psql", "-U", $user, "-d", $db)
    }

    "clean" {
        @(".pytest_cache", ".mypy_cache", ".ruff_cache", "htmlcov", ".coverage") | ForEach-Object {
            $p = Join-Path $Backend $_
            if (Test-Path $p) { Remove-Item $p -Recurse -Force }
        }
        $next = Join-Path $Frontend ".next"
        if (Test-Path $next) { Remove-Item $next -Recurse -Force }
        Get-ChildItem $Backend -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
        ForEach-Object { Remove-Item $_.FullName -Recurse -Force }
        Write-Host "Cleaned." -ForegroundColor Green
    }

    default {
        Write-Host "Unknown task: $Task" -ForegroundColor Red
        & $PSCommandPath help
        exit 1
    }
}
