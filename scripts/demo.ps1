<#
.SYNOPSIS
    Live demo: runs the whole SkyPoints pipeline step by step, from tests to Gold.

.EXAMPLE
    .\scripts\demo.ps1                     # pauses before each step so you can explain it
    .\scripts\demo.ps1 -Fresh              # drop and rebuild the demo database first
    .\scripts\demo.ps1 -NoPause -SkipIntegration

.NOTES
    Uses the database in -Database (default SKYPOINTS_DEMO), never the one in .env, so a demo
    can't touch your working data. -Fresh only drops databases whose name ends in _DEMO.
#>
param(
    [string]$Database = "SKYPOINTS_DEMO",
    [switch]$Fresh,
    [switch]$NoPause,
    [switch]$SkipIntegration
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "No .venv found. Run: py -3.12 -m venv .venv; .venv\Scripts\pip install -e "".[dev,snowflake]""" }
$env:SNOWFLAKE_DATABASE = $Database
$step = 0

function Step([string]$title, [string]$why) {
    $script:step++
    Write-Host ""
    Write-Host ("=" * 90) -ForegroundColor DarkGray
    Write-Host ("STEP {0}: {1}" -f $script:step, $title) -ForegroundColor Cyan
    Write-Host ("  Why: {0}" -f $why) -ForegroundColor DarkCyan
    Write-Host ("=" * 90) -ForegroundColor DarkGray
    if (-not $NoPause) { [void](Read-Host "Press Enter to run") }
}

function Run([string]$exe, [string[]]$arguments) {
    Write-Host ("> {0} {1}" -f (Split-Path -Leaf $exe), ($arguments -join " ")) -ForegroundColor Yellow
    & $exe @arguments
    if ($LASTEXITCODE -ne 0) { throw "failed (exit $LASTEXITCODE): $exe $arguments" }
}

Write-Host "SkyPoints loyalty pipeline - live demo (database $Database)" -ForegroundColor Green

Step "How it was built: test-first commits" `
     "Each Gold slice has a test(...) commit (red) before its feat(...) commit (green)."
Run "git" @("log", "--oneline", "-16")

Step "Lint and unit tests (no Snowflake needed)" `
     "Fast feedback first: generator, loader, config and SQL rendering are tested locally."
Run $python @("-m", "ruff", "check", ".")
Run $python @("-m", "pytest", "-q")

Step "Generate the source feeds (simulated source system)" `
     "Same seed, same files. ~5% injected defects; MANIFEST_*.json lists each one = answer key."
Run $python @("-m", "skypoints.datagen", "--out", "data/landing", "--days", "3", "--members", "1000", "--seed", "42")
Get-Content data\landing\MEMBER_PROFILE_20240115_06000000.txt -TotalCount 3
Get-Content data\landing\REDEMPTIONS_20240115.json -TotalCount 1

if ($Fresh) {
    if ($Database -notlike "*_DEMO") { throw "-Fresh only drops *_DEMO databases, not $Database" }
    Step "Drop $Database to start from zero" "Prove the whole pipeline builds from an empty account."
    Run $python @("-c", "from skypoints.config import SnowflakeSettings as S; from skypoints.snowflake_conn import connect; c = connect(S.from_env(), use_database=False); c.cursor().execute('DROP DATABASE IF EXISTS $Database'); c.close(); print('dropped $Database')")
}

Step "Create database objects (sql/ddl/V001..V008)" `
     "Versioned, idempotent DDL: re-running changes nothing. Same files build DEV or PROD."
Run $python @("-m", "skypoints.sql_runner")

Step "BRONZE: upload and COPY INTO the raw tables" `
     "Everything lands as text / VARIANT, so nothing is lost at load. Row counts reconcile per file."
Run $python @("-m", "skypoints.bronze", "--landing", "data/landing")

Step "BRONZE again: prove each file loads exactly once" `
     "META.FILE_LOAD_LOG (plus MD5) skips files already loaded; COPY load history is a second net."
Run $python @("-m", "skypoints.bronze", "--landing", "data/landing")

Step "SILVER: validate, latest record wins, country split, flatten redemptions" `
     "Rejects keep a reason code; fixable values are repaired and flagged. One transaction per batch."
Run $python @("-m", "skypoints.silver")

Step "GOLD: DIM_MEMBER (SCD Type 2) and MEMBER_360" `
     "History for point-in-time joins, and one business-facing row per member."
Run $python @("-m", "skypoints.gold")

if (-not $SkipIntegration) {
    Step "Integration tests in Snowflake (~2 minutes)" `
         "Real SQL over hand-made edge cases in throwaway schemas, plus checks against the manifest."
    Run $python @("-m", "pytest", "-q", "-m", "integration", "-p", "no:logging")
}

Step "Show the results (sql/demo/demo_queries.sql)" `
     "Rejects, repairs, country moves, orphans, SCD2 history and the point-in-time join."
Run $python @("-m", "skypoints.demo")

Write-Host ""
Write-Host "Demo complete." -ForegroundColor Green
