[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet("focused", "full", "static")]
    [string]$Scope = "full",

    [Parameter(Position = 1, ValueFromRemainingArguments = $true)]
    [string[]]$Arguments
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw "Project interpreter not found: $pythonPath"
}

$pythonPath = (Resolve-Path -LiteralPath $pythonPath).Path
Write-Host "[verify] interpreter=$pythonPath"
Write-Host "[verify] scope=$Scope"

Push-Location -LiteralPath $projectRoot
try {
    switch ($Scope) {
        "focused" {
            if (-not $Arguments -or $Arguments.Count -eq 0) {
                throw "focused scope requires at least one pytest path or argument"
            }
            & $pythonPath -B -m pytest @Arguments
        }
        "full" {
            & $pythonPath -B -m pytest @Arguments -q
        }
        "static" {
            $ruffTargets = @(
                "app",
                "tests/evaluation",
                "audit_golden_dataset.py",
                "run_answer_eval.py",
                "run_eval_suite.py",
                "run_gold_adjudication.py",
                "run_retrieval_comparison.py",
                "run_retrieval_eval.py",
                "run_structural_index_pilot.py",
                "run_structural_retrieval_eval.py"
            )
            & $pythonPath -m ruff check @ruffTargets --select E4,E7,E9,F
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
            & $pythonPath -m compileall -q app @($ruffTargets | Where-Object { $_ -like "*.py" })
        }
    }

    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}
finally {
    Pop-Location
}
