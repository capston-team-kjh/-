Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptRoot "..")
Set-Location $RepoRoot

$script:FailCount = 0
$script:SkipCount = 0
$script:PassCount = 0

function Write-Check {
    param(
        [Parameter(Mandatory=$true)][ValidateSet("PASS","FAIL","SKIP")] [string] $Status,
        [Parameter(Mandatory=$true)] [string] $Name,
        [string] $Message = ""
    )

    if ($Status -eq "PASS") { $script:PassCount += 1 }
    elseif ($Status -eq "FAIL") { $script:FailCount += 1 }
    else { $script:SkipCount += 1 }

    if ($Message) {
        Write-Host ("[{0}] {1} - {2}" -f $Status, $Name, $Message)
    } else {
        Write-Host ("[{0}] {1}" -f $Status, $Name)
    }
}

function Test-CommandExists {
    param([Parameter(Mandatory=$true)][string] $Name)
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Invoke-Logged {
    param(
        [Parameter(Mandatory=$true)][string] $Name,
        [Parameter(Mandatory=$true)][scriptblock] $Command
    )

    try {
        $global:LASTEXITCODE = 0
        & $Command
        if ($LASTEXITCODE -ne $null -and $LASTEXITCODE -ne 0) {
            Write-Check "FAIL" $Name "exit code $LASTEXITCODE"
            return $false
        }
        Write-Check "PASS" $Name
        return $true
    } catch {
        Write-Check "FAIL" $Name $_.Exception.Message
        return $false
    }
}

function Get-PythonRunner {
    $venvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython) {
        return @{ Command = $venvPython; Args = @(); Source = ".venv" }
    }

    if (Test-CommandExists "py") {
        return @{ Command = "py"; Args = @("-3.12"); Source = "py -3.12" }
    }

    if (Test-CommandExists "python") {
        return @{ Command = "python"; Args = @(); Source = "python" }
    }

    return $null
}

function Invoke-Python {
    param(
        [Parameter(Mandatory=$true)] $Runner,
        [Parameter(Mandatory=$true)] [string[]] $Args
    )
    & $Runner.Command @($Runner.Args + $Args)
}

function Get-PythonFiles {
    if (Test-CommandExists "rg") {
        $files = rg --files -g "*.py" -g "!**/.venv/**" -g "!**/venv/**" -g "!**/__pycache__/**" -g "!**/node_modules/**" -g "!ai/state_classifier_training/**"
        return @($files)
    }

    return @(Get-ChildItem -LiteralPath $RepoRoot -Recurse -Filter "*.py" |
        Where-Object {
            $_.FullName -notmatch "\\.venv\\" -and
            $_.FullName -notmatch "\\venv\\" -and
            $_.FullName -notmatch "\\__pycache__\\" -and
            $_.FullName -notmatch "\\node_modules\\" -and
            $_.FullName -notmatch "\\ai\\state_classifier_training\\"
        } |
        ForEach-Object { Resolve-Path -Relative $_.FullName })
}

Write-Host "FocusAI harness verification"
Write-Host ("Repo: {0}" -f $RepoRoot)

$pythonRunner = Get-PythonRunner
if ($null -eq $pythonRunner) {
    Write-Check "FAIL" "Python executable" "Python 3.12 runner was not found"
} else {
    try {
        $version = Invoke-Python $pythonRunner @("-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')")
        if ($version -like "3.12.*") {
            Write-Check "PASS" "Python version" ("{0} via {1}" -f $version, $pythonRunner.Source)
        } else {
            Write-Check "FAIL" "Python version" ("expected 3.12.x, got {0} via {1}" -f $version, $pythonRunner.Source)
        }
    } catch {
        Write-Check "FAIL" "Python version" $_.Exception.Message
    }

    if ($pythonRunner.Source -eq ".venv") {
        Write-Check "PASS" "Python virtualenv" ".venv is present and selected"
    } elseif (Test-Path -LiteralPath (Join-Path $RepoRoot ".venv")) {
        Write-Check "FAIL" "Python virtualenv" ".venv exists but its python.exe was not selected"
    } else {
        Write-Check "SKIP" "Python virtualenv" ".venv directory is not present"
    }

    $pythonFiles = Get-PythonFiles
    if ($pythonFiles.Count -eq 0) {
        Write-Check "SKIP" "Python syntax" "no Python files found"
    } else {
        $null = Invoke-Logged "Python syntax" { Invoke-Python $pythonRunner (@("-m", "py_compile") + $pythonFiles) | Out-Host }
    }

    if (Test-Path -LiteralPath (Join-Path $RepoRoot "ai\tests")) {
        $null = Invoke-Logged "Python AI tests" { Invoke-Python $pythonRunner @("-m", "unittest", "discover", "-s", "ai\tests") | Out-Host }
    } else {
        Write-Check "SKIP" "Python AI tests" "ai\tests directory is missing"
    }

    $backendTestDirs = @(@("tests", "backend\tests") | Where-Object { Test-Path -LiteralPath (Join-Path $RepoRoot $_) })
    if ($backendTestDirs.Count -eq 0) {
        Write-Check "SKIP" "FastAPI backend tests" "no backend test suite exists"
    } else {
        foreach ($testDir in $backendTestDirs) {
            $null = Invoke-Logged "FastAPI backend tests ($testDir)" { Invoke-Python $pythonRunner @("-m", "unittest", "discover", "-s", $testDir) | Out-Host }
        }
    }
}

$frontendDir = Join-Path $RepoRoot "frontend"
$frontendPackage = Join-Path $frontendDir "package.json"
if (-not (Test-Path -LiteralPath $frontendPackage)) {
    Write-Check "SKIP" "React checks" "frontend\package.json is missing"
} elseif (-not (Test-CommandExists "npm")) {
    Write-Check "SKIP" "React checks" "npm is not available"
} else {
    $pkg = Get-Content -LiteralPath $frontendPackage -Raw | ConvertFrom-Json
    $scripts = $pkg.scripts
    if ($scripts -and ($scripts.PSObject.Properties.Name -contains "lint")) {
        $null = Invoke-Logged "React lint" { Push-Location $frontendDir; try { npm run lint | Out-Host } finally { Pop-Location } }
    } else {
        Write-Check "SKIP" "React lint" "frontend package has no lint script"
    }

    if ($scripts -and ($scripts.PSObject.Properties.Name -contains "build")) {
        $null = Invoke-Logged "React build" { Push-Location $frontendDir; try { npm run build | Out-Host } finally { Pop-Location } }
    } else {
        Write-Check "SKIP" "React build" "frontend package has no build script"
    }
}

$dockerfile = Join-Path $RepoRoot "Dockerfile"
if (Test-Path -LiteralPath $dockerfile) {
    $dockerText = Get-Content -LiteralPath $dockerfile -Raw
    if ($dockerText -match "FROM\s+python:3\.12") {
        Write-Check "PASS" "Dockerfile Python base" "python:3.12 base image is configured"
    } else {
        Write-Check "FAIL" "Dockerfile Python base" "expected python:3.12 base image"
    }
} else {
    Write-Check "SKIP" "Dockerfile Python base" "Dockerfile is missing"
}

$composeFiles = @(@("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml") |
    Where-Object { Test-Path -LiteralPath (Join-Path $RepoRoot $_) })
if ($composeFiles.Count -eq 0) {
    Write-Check "SKIP" "Docker Compose config" "no compose file exists"
} elseif (Test-CommandExists "docker") {
    $null = Invoke-Logged "Docker Compose config" { docker compose config | Out-Host }
} else {
    Write-Check "SKIP" "Docker Compose config" "docker CLI is not available"
}

if (Test-CommandExists "docker") {
    $null = Invoke-Logged "Docker CLI" { docker --version | Out-Host }
} else {
    Write-Check "SKIP" "Docker CLI" "docker CLI is not available"
}

$envExample = Join-Path $RepoRoot ".env.example"
if (Test-Path -LiteralPath $envExample) {
    $envNames = @{}
    foreach ($line in Get-Content -LiteralPath $envExample) {
        if ($line -match "^\s*([A-Za-z_][A-Za-z0-9_]*)=") {
            $envNames[$Matches[1]] = $true
        }
    }

    $requiredNames = @(
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_REGION",
        "SQS_QUEUE_URL",
        "S3_DOWNLOAD_DIR",
        "AI_CHUNK_RESULT_DIR",
        "SAMPLING_FPS",
        "RESULT_SINK",
        "RDS_HOST",
        "RDS_PORT",
        "RDS_USER",
        "RDS_PASSWORD",
        "RDS_DATABASE",
        "ANALYSIS_RESULT_TABLE",
        "ANALYSIS_FEEDBACK_TABLE",
        "OPENAI_VISION_ENABLED",
        "OPENAI_VISION_DRY_RUN",
        "OPENAI_API_KEY",
        "OPENAI_VISION_APPLY_CORRECTION",
        "BACKEND_RESULT_API_URL"
    )
    $missing = @($requiredNames | Where-Object { -not $envNames.ContainsKey($_) })
    if ($missing.Count -eq 0) {
        Write-Check "PASS" "Environment variable names" "required names are present in .env.example"
    } else {
        Write-Check "FAIL" "Environment variable names" ("missing: {0}" -f ($missing -join ", "))
    }

    $envMap = @{}
    foreach ($line in Get-Content -LiteralPath $envExample) {
        if ($line -match "^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$") {
            $envMap[$Matches[1]] = $Matches[2]
        }
    }
    $safeDefaultsOk = (
        $envMap["OPENAI_VISION_ENABLED"] -eq "false" -and
        $envMap["OPENAI_VISION_DRY_RUN"] -eq "true" -and
        $envMap["OPENAI_API_KEY"] -eq "" -and
        $envMap["OPENAI_VISION_APPLY_CORRECTION"] -eq "false"
    )
    if ($safeDefaultsOk) {
        Write-Check "PASS" "OpenAI Vision safe defaults"
    } else {
        Write-Check "FAIL" "OpenAI Vision safe defaults" "expected disabled, dry-run, empty API key, and correction disabled"
    }
} else {
    Write-Check "FAIL" "Environment variable names" ".env.example is missing"
}

$trackedEnv = @(git ls-files -- .env .env.local frontend/.env frontend/.env.local ai/.env ai/.env.local)
if ($LASTEXITCODE -ne 0) {
    Write-Check "FAIL" ".env git tracking" "git ls-files failed"
} elseif ($trackedEnv.Count -eq 0) {
    Write-Check "PASS" ".env git tracking" ".env and .env.local are not tracked"
} else {
    Write-Check "FAIL" ".env git tracking" "one or more env files are tracked"
}

$gitignore = Join-Path $RepoRoot ".gitignore"
if (Test-Path -LiteralPath $gitignore) {
    $gitignoreLines = @(Get-Content -LiteralPath $gitignore | ForEach-Object { $_.Trim() })
    if ($gitignoreLines -contains ".env" -and $gitignoreLines -contains ".env.local") {
        Write-Check "PASS" ".env gitignore" ".env and .env.local are ignored"
    } else {
        Write-Check "FAIL" ".env gitignore" ".env or .env.local is missing from .gitignore"
    }
} else {
    Write-Check "FAIL" ".env gitignore" ".gitignore is missing"
}

Write-Host ("Summary: PASS={0} FAIL={1} SKIP={2}" -f $script:PassCount, $script:FailCount, $script:SkipCount)
if ($script:FailCount -gt 0) {
    exit 1
}
exit 0
