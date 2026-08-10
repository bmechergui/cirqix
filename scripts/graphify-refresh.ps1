[CmdletBinding()]
param(
    [ValidateSet("Ensure", "Root", "KicadTools", "CircuitSynth", "All", "Watcher")]
    [string]$Mode = "Ensure",
    [switch]$CheckOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$outputRoot = Join-Path $repoRoot "graphify-out"
$scopeRoot = Join-Path $outputRoot "scopes"
$rootGraph = Join-Path $outputRoot "graph.json"
$kicadRepo = Join-Path $repoRoot "services\kicad\kicad-tools"
$kicadOut = Join-Path $scopeRoot "kicad-tools"
$kicadGraph = Join-Path $kicadOut "graphify-out\graph.json"
$circuitRepo = Join-Path $repoRoot "services\kicad\circuit_synth"
$circuitOut = Join-Path $scopeRoot "circuit-synth"
$circuitGraph = Join-Path $circuitOut "graphify-out\graph.json"
$fullGraph = Join-Path $outputRoot "full-graph.json"
$statePath = Join-Path $scopeRoot "refresh-state.json"
$lockPath = Join-Path $outputRoot ".multi-graph-refresh.lock"
$watcherStatePath = Join-Path $outputRoot ".watcher-state.json"
$codePattern = '\.(c|cc|cpp|cs|go|h|hpp|java|js|jsx|json|kt|kts|mjs|cjs|php|ps1|py|rb|rs|scala|sh|sql|swift|toml|ts|tsx|yaml|yml)$'
$scriptSchemaVersion = 3

$graphifyCommand = Get-Command graphify -ErrorAction Stop
$graphify = $graphifyCommand.Source
$graphifyVersion = (& $graphify --version).Trim()

function Invoke-Checked {
    param(
        [string[]]$Arguments,
        [string]$GraphifyOutOverride
    )

    Push-Location $repoRoot
    $previousGraphifyOut = $env:GRAPHIFY_OUT
    try {
        if ($GraphifyOutOverride) {
            $env:GRAPHIFY_OUT = $GraphifyOutOverride
        }
        & $graphify @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "graphify $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
        }
    }
    finally {
        $env:GRAPHIFY_OUT = $previousGraphifyOut
        Pop-Location
    }
}

function Invoke-RootFullRebuild {
    $stagingRoot = Join-Path $outputRoot ".root-rebuild"
    $stagingGraphifyOut = Join-Path $stagingRoot "graphify-out"
    if (Test-Path -LiteralPath $stagingRoot) {
        Remove-Item -LiteralPath $stagingRoot -Recurse -Force
    }
    New-Item -ItemType Directory -Path $stagingRoot -Force | Out-Null

    try {
        Invoke-Checked -Arguments @("extract", $repoRoot, "--code-only", "--force", "--out", $stagingRoot) -GraphifyOutOverride "graphify-out"
        if (-not (Test-Path -LiteralPath (Join-Path $stagingGraphifyOut "graph.json"))) {
            throw "Staged root Graphify extraction did not produce graph.json"
        }
        foreach ($item in Get-ChildItem -LiteralPath $stagingGraphifyOut -Force) {
            Copy-Item -LiteralPath $item.FullName -Destination $outputRoot -Recurse -Force
        }
    }
    finally {
        if (Test-Path -LiteralPath $stagingRoot) {
            Remove-Item -LiteralPath $stagingRoot -Recurse -Force
        }
    }
}

function Get-TextDigest {
    param([string]$Text)

    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($Text)
        return ([System.BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
    }
}

function Get-RepositorySignature {
    param(
        [string]$Repository,
        [string]$ExtractionKey,
        [string]$IgnorePath,
        [switch]$ExcludeVendored
    )

    $gitPrefix = @("-c", "safe.directory=$Repository", "-C", $Repository)
    $previousErrorAction = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $head = (& git @gitPrefix rev-parse HEAD 2>$null).Trim()
        $headExitCode = $LASTEXITCODE
        $trackedChanges = @(& git @gitPrefix diff HEAD --name-only 2>$null)
        $trackedExitCode = $LASTEXITCODE
        $untrackedChanges = @(& git @gitPrefix ls-files --others --exclude-standard 2>$null)
        $untrackedExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorAction
    }
    if ($headExitCode -ne 0 -or -not $head) {
        throw "Unable to read Git HEAD for $Repository"
    }
    if ($trackedExitCode -ne 0 -or $untrackedExitCode -ne 0) {
        throw "Unable to inspect changed files for $Repository"
    }

    $changed = @($trackedChanges) + @($untrackedChanges)
    $entries = foreach ($relativePath in ($changed | Sort-Object -Unique)) {
        $normalized = $relativePath.Replace("\", "/")
        if ($normalized -notmatch $codePattern) {
            continue
        }
        if ($normalized.StartsWith("graphify-out/")) {
            continue
        }
        if ($ExcludeVendored -and (
            $normalized.StartsWith("services/kicad/kicad-tools/") -or
            $normalized.StartsWith("services/kicad/circuit_synth/"))) {
            continue
        }

        $absolutePath = Join-Path $Repository $relativePath
        if (Test-Path -LiteralPath $absolutePath -PathType Leaf) {
            $item = Get-Item -LiteralPath $absolutePath
            "$normalized|$($item.Length)|$($item.LastWriteTimeUtc.Ticks)"
        }
        else {
            "$normalized|MISSING"
        }
    }

    $ignoreHash = if ($IgnorePath -and (Test-Path -LiteralPath $IgnorePath)) {
        (Get-FileHash -LiteralPath $IgnorePath -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    else {
        "MISSING"
    }
    $structurePayload = @(
        "schema=$scriptSchemaVersion"
        "graphify=$graphifyVersion"
        "extract=$ExtractionKey"
        "ignore=$ignoreHash"
    ) -join "`n"
    $contentPayload = @("head=$head", $entries) -join "`n"

    [pscustomobject]@{
        head = $head
        content_signature = Get-TextDigest $contentPayload
        structure_signature = Get-TextDigest $structurePayload
    }
}

function Get-SavedSignature {
    param(
        [object]$State,
        [string]$Name,
        [string]$Field
    )

    if ($null -eq $State) {
        return $null
    }
    $property = $State.PSObject.Properties[$Name]
    if ($null -eq $property -or $null -eq $property.Value) {
        return $null
    }
    $fieldProperty = $property.Value.PSObject.Properties[$Field]
    if ($null -eq $fieldProperty) {
        return $null
    }
    return $fieldProperty.Value
}

function Write-JsonAtomic {
    param(
        [object]$Value,
        [string]$Path,
        [int]$Depth = 6
    )

    $directory = Split-Path -Parent $Path
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
    $temporary = Join-Path $directory (".{0}.{1}.tmp" -f ([System.IO.Path]::GetFileName($Path)), ([Guid]::NewGuid().ToString("N")))
    $backup = Join-Path $directory (".{0}.{1}.bak" -f ([System.IO.Path]::GetFileName($Path)), ([Guid]::NewGuid().ToString("N")))
    try {
        $json = $Value | ConvertTo-Json -Depth $Depth
        [System.IO.File]::WriteAllText($temporary, $json, (New-Object System.Text.UTF8Encoding($false)))
        if (Test-Path -LiteralPath $Path) {
            [System.IO.File]::Replace($temporary, $Path, $backup)
        }
        else {
            [System.IO.File]::Move($temporary, $Path)
        }
    }
    finally {
        if (Test-Path -LiteralPath $temporary) {
            Remove-Item -LiteralPath $temporary -Force
        }
        if (Test-Path -LiteralPath $backup) {
            Remove-Item -LiteralPath $backup -Force
        }
    }
}

function Get-ArtifactStamp {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $null
    }
    $item = Get-Item -LiteralPath $Path
    [pscustomobject]@{
        length = $item.Length
        last_write_utc_ticks = $item.LastWriteTimeUtc.Ticks
    }
}

function Test-ArtifactFresh {
    param(
        [string]$Path,
        [object]$State,
        [string]$Name
    )

    $current = Get-ArtifactStamp $Path
    if ($null -eq $current -or $null -eq $State) {
        return $false
    }
    $graphsProperty = $State.PSObject.Properties["graphs"]
    if ($null -eq $graphsProperty) {
        return $false
    }
    $savedProperty = $graphsProperty.Value.PSObject.Properties[$Name]
    if ($null -eq $savedProperty -or $null -eq $savedProperty.Value) {
        return $false
    }
    return $current.length -eq $savedProperty.Value.length -and
        $current.last_write_utc_ticks -eq $savedProperty.Value.last_write_utc_ticks
}

function Enter-RefreshLock {
    param([switch]$NoWait)

    $deadline = [DateTime]::UtcNow.AddMinutes(45)
    do {
        try {
            return [System.IO.File]::Open(
                $lockPath,
                [System.IO.FileMode]::OpenOrCreate,
                [System.IO.FileAccess]::ReadWrite,
                [System.IO.FileShare]::None
            )
        }
        catch [System.IO.IOException] {
            if ($NoWait) {
                return $null
            }
            Write-Output "Graphify refresh already running; waiting for the lock."
            Start-Sleep -Seconds 2
        }
    } while ([DateTime]::UtcNow -lt $deadline)

    throw "Timed out waiting for the active Graphify refresh."
}

function Get-RepositoryWatcher {
    if (-not (Test-Path -LiteralPath $watcherStatePath)) {
        return $null
    }

    try {
        $watcherState = Get-Content -LiteralPath $watcherStatePath -Raw | ConvertFrom-Json
        $process = Get-Process -Id ([int]$watcherState.pid) -ErrorAction Stop
        $savedStart = [DateTime]::Parse($watcherState.started_at_utc).ToUniversalTime()
        $actualStart = $process.StartTime.ToUniversalTime()
        if ([Math]::Abs(($actualStart - $savedStart).TotalSeconds) -gt 2) {
            throw "PID was reused"
        }
        return $process
    }
    catch {
        Remove-Item -LiteralPath $watcherStatePath -Force -ErrorAction SilentlyContinue
        return $null
    }
}

function Stop-RepositoryWatcher {
    $watcher = Get-RepositoryWatcher
    if ($null -eq $watcher) {
        return
    }

    Stop-Process -Id $watcher.Id -ErrorAction Stop
    Wait-Process -Id $watcher.Id -Timeout 10 -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $watcherStatePath -Force -ErrorAction SilentlyContinue
    Write-Output "Stopped Cirqix Graphify watcher (PID $($watcher.Id))."
}

function Start-RepositoryWatcher {
    $watcher = Get-RepositoryWatcher
    if ($null -ne $watcher) {
        return
    }

    $pythonStatePath = Join-Path $outputRoot ".graphify_python"
    if (-not (Test-Path -LiteralPath $pythonStatePath)) {
        throw "Graphify interpreter state is missing: $pythonStatePath"
    }
    $watchPython = (Get-Content -LiteralPath $pythonStatePath -Raw).Trim()
    if (-not (Test-Path -LiteralPath $watchPython -PathType Leaf)) {
        throw "Graphify interpreter does not exist: $watchPython"
    }

    $process = Start-Process -WindowStyle Hidden -FilePath $watchPython -ArgumentList @("-m", "graphify.watch", $repoRoot, "--debounce", "3") -WorkingDirectory $repoRoot -PassThru
    $watcherState = [ordered]@{
        pid = $process.Id
        started_at_utc = $process.StartTime.ToUniversalTime().ToString("o")
        repository = $repoRoot
    }
    Write-JsonAtomic -Value $watcherState -Path $watcherStatePath
    Write-Output "Started Cirqix Graphify watcher (PID $($process.Id))."
}

New-Item -ItemType Directory -Path $scopeRoot -Force | Out-Null
$lockStream = Enter-RefreshLock -NoWait:($Mode -eq "Watcher")
if ($null -eq $lockStream) {
    Write-Output "Graphify refresh owns the watcher; no restart is needed."
    exit 0
}
try {
    if ($Mode -eq "Watcher") {
        if ($CheckOnly) {
            $watcher = Get-RepositoryWatcher
            Write-Output "Graphify watcher running=$($null -ne $watcher)"
        }
        else {
            Start-RepositoryWatcher
        }
        exit 0
    }

    $rootSignature = Get-RepositorySignature -Repository $repoRoot -ExtractionKey "update:root" -IgnorePath (Join-Path $repoRoot ".graphifyignore") -ExcludeVendored
    $kicadSignature = Get-RepositorySignature -Repository $kicadRepo -ExtractionKey "extract:code-only:kicad-tools" -IgnorePath (Join-Path $kicadRepo ".graphifyignore")
    $circuitSignature = Get-RepositorySignature -Repository $circuitRepo -ExtractionKey "extract:code-only:circuit-synth" -IgnorePath (Join-Path $circuitRepo ".graphifyignore")
    $state = $null
    if (Test-Path -LiteralPath $statePath) {
        try {
            $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
        }
        catch {
            Write-Warning "Graphify refresh state is invalid and will be rebuilt."
        }
    }

    $hasState = $null -ne $state -and $state.version -eq $scriptSchemaVersion
    $rootContentChanged = -not $hasState -or (Get-SavedSignature $state "root" "content_signature") -ne $rootSignature.content_signature
    $kicadContentChanged = -not $hasState -or (Get-SavedSignature $state "kicad_tools" "content_signature") -ne $kicadSignature.content_signature
    $circuitContentChanged = -not $hasState -or (Get-SavedSignature $state "circuit_synth" "content_signature") -ne $circuitSignature.content_signature
    $forceRoot = -not $hasState -or (Get-SavedSignature $state "root" "structure_signature") -ne $rootSignature.structure_signature
    $forceKicad = -not $hasState -or (Get-SavedSignature $state "kicad_tools" "structure_signature") -ne $kicadSignature.structure_signature
    $forceCircuit = -not $hasState -or (Get-SavedSignature $state "circuit_synth" "structure_signature") -ne $circuitSignature.structure_signature

    $rootArtifactFresh = Test-ArtifactFresh $rootGraph $state "root"
    $kicadArtifactFresh = Test-ArtifactFresh $kicadGraph $state "kicad_tools"
    $circuitArtifactFresh = Test-ArtifactFresh $circuitGraph $state "circuit_synth"
    $fullArtifactFresh = Test-ArtifactFresh $fullGraph $state "full"

    $refreshRoot = -not $rootArtifactFresh -or $rootContentChanged -or $forceRoot -or $Mode -in @("Root", "All")
    $refreshKicad = -not $kicadArtifactFresh -or $kicadContentChanged -or $forceKicad -or $Mode -in @("KicadTools", "All")
    $refreshCircuit = -not $circuitArtifactFresh -or $circuitContentChanged -or $forceCircuit -or $Mode -in @("CircuitSynth", "All")
    $refreshFull = -not $fullArtifactFresh -or $refreshRoot -or $refreshKicad -or $refreshCircuit

    Write-Output "Graphify freshness: root=$refreshRoot kicad-tools=$refreshKicad circuit_synth=$refreshCircuit merge=$refreshFull"
    if ($CheckOnly) {
        exit 0
    }

    if ($refreshFull) {
        Stop-RepositoryWatcher
    }
    if ($refreshRoot) {
        if ($forceRoot) {
            Invoke-RootFullRebuild
        }
        else {
            Invoke-Checked -Arguments @("update", $repoRoot) -GraphifyOutOverride $outputRoot
        }
    }
    if ($refreshKicad) {
        $kicadArguments = @("extract", $kicadRepo, "--code-only", "--out", $kicadOut)
        if ($forceKicad) { $kicadArguments += "--force" }
        Invoke-Checked -Arguments $kicadArguments -GraphifyOutOverride (Join-Path $kicadOut "graphify-out")
    }
    if ($refreshCircuit) {
        $circuitArguments = @("extract", $circuitRepo, "--code-only", "--out", $circuitOut)
        if ($forceCircuit) { $circuitArguments += "--force" }
        Invoke-Checked -Arguments $circuitArguments -GraphifyOutOverride (Join-Path $circuitOut "graphify-out")
    }
    if ($refreshFull) {
        Invoke-Checked -Arguments @(
            "merge-graphs",
            $rootGraph,
            $kicadGraph,
            $circuitGraph,
            "--out",
            $fullGraph
        )
    }

    $newState = [ordered]@{
        version = $scriptSchemaVersion
        updated_at_utc = [DateTime]::UtcNow.ToString("o")
        root = $rootSignature
        kicad_tools = $kicadSignature
        circuit_synth = $circuitSignature
        graphs = [ordered]@{
            root = Get-ArtifactStamp $rootGraph
            kicad_tools = Get-ArtifactStamp $kicadGraph
            circuit_synth = Get-ArtifactStamp $circuitGraph
            full = Get-ArtifactStamp $fullGraph
        }
    }
    Write-JsonAtomic -Value $newState -Path $statePath
}
finally {
    if (-not $CheckOnly) {
        Start-RepositoryWatcher
    }
    if ($null -ne $lockStream) {
        $lockStream.Dispose()
    }
}
