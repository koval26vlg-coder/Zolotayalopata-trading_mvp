param(
    [Parameter(Mandatory = $true)]
    [string]$PlanPath,
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-fA-F]{64}$")]
    [string]$ExpectedPlanHash,
    [Parameter(Mandatory = $true)]
    [string]$ManifestPath,
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-fA-F]{64}$")]
    [string]$ExpectedManifestSha256,
    [switch]$Json
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

function Get-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Get-NormalizedPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    return [System.IO.Path]::GetFullPath($Path)
}

function Test-ExactPath {
    param($Actual, $Expected)
    if ([string]::IsNullOrWhiteSpace([string]$Actual)) { return $false }
    if ([string]::IsNullOrWhiteSpace([string]$Expected)) { return $false }
    return [System.StringComparer]::OrdinalIgnoreCase.Equals(
        (Get-NormalizedPath -Path ([string]$Actual)),
        (Get-NormalizedPath -Path ([string]$Expected))
    )
}

function Test-ExactHash {
    param($Actual, $Expected)
    return (
        [string]$Actual -match "^[0-9a-fA-F]{64}$" -and
        [string]$Expected -match "^[0-9a-fA-F]{64}$" -and
        ([string]$Actual).ToLowerInvariant() -eq
            ([string]$Expected).ToLowerInvariant()
    )
}

$PlanPath = Get-NormalizedPath -Path $PlanPath
$ExpectedPlanHash = $ExpectedPlanHash.ToLowerInvariant()
$ManifestPath = Get-NormalizedPath -Path $ManifestPath
$ExpectedManifestSha256 = $ExpectedManifestSha256.ToLowerInvariant()
if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) {
    throw "Runtime dependency manifest is missing: $ManifestPath"
}
if ((Get-Sha256 -Path $ManifestPath) -ne $ExpectedManifestSha256) {
    throw "Runtime dependency manifest hash mismatch."
}
$manifest = Get-Content -Raw -LiteralPath $ManifestPath |
    ConvertFrom-Json -Depth 100 -DateKind String
if (
    [string]$manifest.schema -ne
        "trading_mvp_dense_ws_runtime_dependency_manifest_v1"
) {
    throw "Runtime dependency manifest schema mismatch."
}
if (-not (Test-ExactHash $manifest.plan.plan_hash $ExpectedPlanHash)) {
    throw "ExpectedPlanHash does not match the frozen dependency manifest."
}
if (-not (Test-ExactPath $PlanPath $manifest.plan.path)) {
    throw "PlanPath does not match the frozen dependency manifest."
}
if (-not (Test-Path -LiteralPath $PlanPath -PathType Leaf)) {
    throw "PlanOnly file is missing: $PlanPath"
}

$blockers = [System.Collections.Generic.List[string]]::new()
$warnings = [System.Collections.Generic.List[string]]::new()
$checks = [System.Collections.Generic.List[object]]::new()

function Add-Check {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][bool]$Passed,
        [string]$Blocker = ""
    )
    $script:checks.Add([ordered]@{ name = $Name; passed = $Passed })
    if (-not $Passed -and -not [string]::IsNullOrWhiteSpace($Blocker)) {
        $script:blockers.Add($Blocker)
    }
}

$planFileSha256 = Get-Sha256 -Path $PlanPath
Add-Check "plan_file_sha256" `
    (Test-ExactHash $planFileSha256 $manifest.plan.file_sha256) `
    "plan_file_sha256_mismatch"
$plan = Get-Content -Raw -LiteralPath $PlanPath |
    ConvertFrom-Json -Depth 100 -DateKind String
Add-Check "plan_internal_hash" `
    (Test-ExactHash $plan.plan_hash $ExpectedPlanHash) `
    "plan_internal_hash_mismatch"
Add-Check "campaign_id" `
    ([string]$plan.campaign_id -ceq [string]$manifest.campaign_id) `
    "campaign_id_mismatch"

$contractPath = Get-NormalizedPath -Path ([string]$manifest.contract.path)
Add-Check "plan_contract_path" `
    (Test-ExactPath $plan.contract.path $contractPath) `
    "plan_contract_path_mismatch"
if (-not (Test-Path -LiteralPath $contractPath -PathType Leaf)) {
    Add-Check "contract_exists" $false "contract_missing"
    $contract = $null
} else {
    Add-Check "contract_exists" $true
    $contractFileSha256 = Get-Sha256 -Path $contractPath
    Add-Check "contract_file_sha256" `
        (Test-ExactHash $contractFileSha256 $manifest.contract.file_sha256) `
        "contract_file_sha256_mismatch"
    Add-Check "plan_contract_file_sha256" `
        (Test-ExactHash $plan.contract.file_sha256 $contractFileSha256) `
        "plan_contract_binding_mismatch"
    $contract = Get-Content -Raw -LiteralPath $contractPath |
        ConvertFrom-Json -Depth 100 -DateKind String
    Add-Check "contract_internal_hash" `
        (Test-ExactHash $contract.contract_hash $manifest.contract.contract_hash) `
        "contract_internal_hash_mismatch"
    Add-Check "plan_contract_hash" `
        (Test-ExactHash $plan.contract.contract_hash $manifest.contract.contract_hash) `
        "plan_contract_hash_mismatch"
}

$universePath = Get-NormalizedPath -Path ([string]$manifest.universe.path)
if (-not (Test-Path -LiteralPath $universePath -PathType Leaf)) {
    Add-Check "universe_exists" $false "universe_missing"
} else {
    Add-Check "universe_exists" $true
    Add-Check "universe_sha256" `
        (Test-ExactHash (Get-Sha256 -Path $universePath) $manifest.universe.sha256) `
        "universe_sha256_mismatch"
}
if ($contract) {
    Add-Check "contract_universe_path" `
        (Test-ExactPath $contract.universe_contract.source.path $universePath) `
        "contract_universe_path_mismatch"
    Add-Check "contract_universe_sha256" `
        (Test-ExactHash $contract.universe_contract.source.sha256 $manifest.universe.sha256) `
        "contract_universe_sha256_mismatch"
    Add-Check "contract_universe_rows" `
        ([int]$contract.universe_contract.source.rows -eq [int]$manifest.universe.rows) `
        "contract_universe_rows_mismatch"
}

foreach ($entry in @($manifest.required_local_files)) {
    $path = Get-NormalizedPath -Path ([string]$entry.path)
    $role = [string]$entry.role
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        Add-Check "local_file_$role" $false "local_file_missing:$role"
        continue
    }
    Add-Check "local_file_$role" `
        (Test-ExactHash (Get-Sha256 -Path $path) $entry.sha256) `
        "local_file_hash_mismatch:$role"
}

if ($contract) {
    $rawWriter = @($manifest.required_local_files |
        Where-Object { $_.role -eq "raw_websocket_writer" })[0]
    $durableWriter = @($manifest.required_local_files |
        Where-Object { $_.role -eq "durable_segment_writer" })[0]
    Add-Check "contract_raw_writer_path" `
        (Test-ExactPath $contract.source_bindings.raw_writer.path $rawWriter.path) `
        "contract_raw_writer_path_mismatch"
    Add-Check "contract_raw_writer_sha256" `
        (Test-ExactHash $contract.source_bindings.raw_writer.sha256 $rawWriter.sha256) `
        "contract_raw_writer_sha256_mismatch"
    Add-Check "contract_durable_writer_path" `
        (Test-ExactPath $contract.source_bindings.durable_collector.path $durableWriter.path) `
        "contract_durable_writer_path_mismatch"
    Add-Check "contract_durable_writer_sha256" `
        (Test-ExactHash $contract.source_bindings.durable_collector.sha256 $durableWriter.sha256) `
        "contract_durable_writer_sha256_mismatch"
}

$runner = @($manifest.required_local_files |
    Where-Object { $_.role -eq "campaign_runner" })[0]
$claim = @($manifest.required_local_files |
    Where-Object { $_.role -eq "global_writer_claim" })[0]
$launcher = @($manifest.required_local_files |
    Where-Object { $_.role -eq "frozen_visible_launcher" })[0]
Add-Check "plan_runner_path" `
    (Test-ExactPath $plan.launch_controls.tools.runner.path $runner.path) `
    "plan_runner_path_mismatch"
Add-Check "plan_runner_sha256" `
    (Test-ExactHash $plan.launch_controls.tools.runner.sha256 $runner.sha256) `
    "plan_runner_sha256_mismatch"
Add-Check "plan_global_claim_path" `
    (Test-ExactPath $plan.launch_controls.tools.global_writer_claim.path $claim.path) `
    "plan_global_claim_path_mismatch"
Add-Check "plan_global_claim_sha256" `
    (Test-ExactHash $plan.launch_controls.tools.global_writer_claim.sha256 $claim.sha256) `
    "plan_global_claim_sha256_mismatch"
Add-Check "plan_launcher_path" `
    (Test-ExactPath $plan.launch_controls.tools.launcher.path $launcher.path) `
    "plan_launcher_path_mismatch"
Add-Check "plan_launcher_sha256" `
    (Test-ExactHash $plan.launch_controls.tools.launcher.sha256 $launcher.sha256) `
    "plan_launcher_sha256_mismatch"

$campaignRoot = Get-NormalizedPath -Path ([string]$plan.outputs.campaign_root)
$campaignRootExistedBefore = Test-Path -LiteralPath $campaignRoot
$pythonPath = Get-NormalizedPath -Path ([string]$manifest.python_runtime.path)
if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    Add-Check "python_runtime_exists" $false "python_runtime_missing"
    $pythonProbe = [ordered]@{
        imports_ok = $false
        blockers = @("python_runtime_missing")
        outbound_network_events = @()
    }
} else {
    Add-Check "python_runtime_exists" $true
    $pythonProbeSource = @'
import hashlib
import importlib
import importlib.metadata as metadata
import json
import os
import site
import ssl
import sys
from pathlib import Path

manifest_path = Path(sys.argv[1])
project_root = Path(sys.argv[2])
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
expected_runtime = manifest["python_runtime"]
blockers = []
checks = []
outbound_events = []

def add(name, passed, blocker):
    checks.append({"name": name, "passed": bool(passed)})
    if not passed:
        blockers.append(blocker)

def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def normalized(path):
    return os.path.normcase(str(Path(path).resolve()))

def distribution_tree(name):
    dist = metadata.distribution(name)
    digest = hashlib.sha256()
    count = 0
    missing = []
    for relative in sorted(
        dist.files or [], key=lambda item: str(item).replace("\\", "/").lower()
    ):
        relative_text = str(relative).replace("\\", "/")
        if relative_text.endswith(".pyc") or "/__pycache__/" in relative_text:
            continue
        path = Path(dist.locate_file(relative))
        if not path.is_file():
            missing.append(relative_text)
            continue
        digest.update(relative_text.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
        count += 1
    return {
        "version": dist.version,
        "tree_sha256": digest.hexdigest(),
        "files_hashed": count,
        "missing_files": missing,
    }

add(
    "python_executable_path",
    normalized(sys.executable) == normalized(expected_runtime["path"]),
    "python_executable_path_mismatch",
)
add(
    "python_executable_sha256",
    sha256_file(sys.executable) == expected_runtime["executable_sha256"],
    "python_executable_sha256_mismatch",
)
add(
    "python_version",
    list(sys.version_info[:3]) == expected_runtime["version_info"],
    "python_version_mismatch",
)
add(
    "openssl_version",
    ssl.OPENSSL_VERSION == expected_runtime["openssl_version"],
    "openssl_version_mismatch",
)
add(
    "user_site_root",
    normalized(site.getusersitepackages()) == normalized(expected_runtime["user_site_root"]),
    "python_user_site_root_mismatch",
)

distribution_results = {}
for expected in manifest["required_python_distributions"]:
    name = expected["name"]
    try:
        actual = distribution_tree(name)
        distribution_results[name] = actual
        add(
            f"distribution_{name}",
            actual["version"] == expected["version"]
            and actual["tree_sha256"] == expected["tree_sha256"]
            and actual["files_hashed"] == expected["files_hashed"]
            and not actual["missing_files"],
            f"python_distribution_mismatch:{name}",
        )
    except Exception as exc:
        distribution_results[name] = {"error": str(exc)}
        add(f"distribution_{name}", False, f"python_distribution_missing:{name}")

certifi = importlib.import_module("certifi")
ca_path = Path(certifi.where())
add(
    "certifi_ca_path",
    normalized(ca_path) == normalized(manifest["tls"]["certifi_ca_path"]),
    "certifi_ca_path_mismatch",
)
add(
    "certifi_ca_sha256",
    ca_path.is_file() and sha256_file(ca_path) == manifest["tls"]["certifi_ca_sha256"],
    "certifi_ca_sha256_mismatch",
)

def audit(event, args):
    if event in {"socket.connect", "socket.getaddrinfo"}:
        outbound_events.append(event)
        raise RuntimeError(f"outbound network disabled during dependency probe: {event}")

sys.addaudithook(audit)
src_root = project_root / "trading_mvp" / "src"
sys.path.insert(0, str(src_root))
module_results = {}
for expected in manifest["required_local_files"]:
    module_name = expected.get("module")
    if not module_name:
        continue
    try:
        module = importlib.import_module(module_name)
        module_path = getattr(module, "__file__", None)
        module_results[module_name] = module_path
        add(
            f"module_{module_name}",
            module_path is not None and normalized(module_path) == normalized(expected["path"]),
            f"python_module_path_mismatch:{module_name}",
        )
    except Exception as exc:
        module_results[module_name] = {"error": str(exc)}
        add(f"module_{module_name}", False, f"python_module_import_failed:{module_name}")

try:
    websocket = importlib.import_module("websocket")
    module_results["websocket"] = websocket.__file__
    add("websocket_import", True, "websocket_import_failed")
except Exception as exc:
    module_results["websocket"] = {"error": str(exc)}
    add("websocket_import", False, "websocket_import_failed")

try:
    config = importlib.import_module("config")
    exchanges = importlib.import_module("exchanges")
    multi_bot = importlib.import_module("multi_bot")
    durable = importlib.import_module("ws_durable_collector")
    config_json = next(
        item["path"] for item in manifest["required_local_files"]
        if item["role"] == "config_json_used_for_public_discovery_timeout"
    )
    cfg = config.load_config(config_json)
    add(
        "config_timeout_sec",
        cfg.exchange.timeout_sec == manifest["semantic_probe"]["config_timeout_sec"],
        "config_timeout_sec_mismatch",
    )
    clients = exchanges.build_clients(
        manifest["semantic_probe"]["exchanges"],
        timeout_sec=cfg.exchange.timeout_sec,
    )
    add(
        "public_client_set",
        sorted(clients) == sorted(manifest["semantic_probe"]["exchanges"]),
        "public_client_set_mismatch",
    )
    add(
        "public_clients_ignore_environment_proxies",
        all(client.session.trust_env is False for client in clients.values()),
        "public_client_trust_env_mismatch",
    )
    add(
        "resolve_symbols_callable",
        callable(durable.resolve_symbols_for_universe),
        "resolve_symbols_not_callable",
    )
    add(
        "build_pairs_callable",
        callable(multi_bot.build_pairs_for_universe),
        "build_pairs_not_callable",
    )
except Exception as exc:
    add("semantic_probe", False, f"semantic_probe_failed:{type(exc).__name__}")

add(
    "outbound_network_events",
    not outbound_events,
    "outbound_network_event_during_dependency_probe",
)

print(json.dumps({
    "imports_ok": not blockers,
    "checks": checks,
    "blockers": blockers,
    "outbound_network_events": outbound_events,
    "distributions": distribution_results,
    "module_paths": module_results,
    "python_executable": sys.executable,
    "python_version": sys.version,
    "openssl_version": ssl.OPENSSL_VERSION,
    "certifi_ca_path": str(ca_path),
}, ensure_ascii=True))
'@
    $previousBytecodeSetting = $env:PYTHONDONTWRITEBYTECODE
    $env:PYTHONDONTWRITEBYTECODE = "1"
    try {
        $probeRaw = & $pythonPath -c $pythonProbeSource $ManifestPath $projectRoot 2>&1
        $probeExitCode = $LASTEXITCODE
    } finally {
        $env:PYTHONDONTWRITEBYTECODE = $previousBytecodeSetting
    }
    $probeText = $probeRaw | Out-String
    if ($probeExitCode -ne 0) {
        $blockers.Add("python_probe_failed")
        $pythonProbe = [ordered]@{
            imports_ok = $false
            blockers = @("python_probe_failed")
            outbound_network_events = @()
            error = $probeText.Trim()
        }
    } else {
        try {
            $pythonProbe = $probeText | ConvertFrom-Json -Depth 100 -DateKind String
            foreach ($blocker in @($pythonProbe.blockers)) {
                $blockers.Add([string]$blocker)
            }
        } catch {
            $blockers.Add("python_probe_invalid_json")
            $pythonProbe = [ordered]@{
                imports_ok = $false
                blockers = @("python_probe_invalid_json")
                outbound_network_events = @()
                error = $probeText.Trim()
            }
        }
    }
}

$campaignRootExistedAfter = Test-Path -LiteralPath $campaignRoot
$noRunOrOutputWrites = $campaignRootExistedBefore -eq $campaignRootExistedAfter
if (-not $noRunOrOutputWrites) {
    $blockers.Add("campaign_output_root_changed_during_dependency_check")
}

$result = [ordered]@{
    schema = "trading_mvp_dense_ws_runtime_dependency_readiness_v1"
    status = if ($blockers.Count -eq 0) { "READY" } else { "BLOCKED" }
    observed_at_local = [DateTimeOffset]::Now.ToString("o")
    campaign_id = [string]$manifest.campaign_id
    plan_path = $PlanPath
    plan_hash = $ExpectedPlanHash
    plan_file_sha256 = $planFileSha256
    manifest_path = $ManifestPath
    manifest_sha256 = $ExpectedManifestSha256
    campaign_root = $campaignRoot
    campaign_root_existed_before = $campaignRootExistedBefore
    campaign_root_existed_after = $campaignRootExistedAfter
    no_run_or_output_writes = $noRunOrOutputWrites
    checks = @($checks)
    python_probe = $pythonProbe
    blockers = @($blockers | Select-Object -Unique)
    warnings = @($warnings)
    network_request_performed = $false
    writer_started = $false
    market_rows_read = $false
    returns_read = $false
    pnl_read = $false
    oos_run = $false
    grid_or_retune = $false
    paper_or_live = $false
    private_api_keys = $false
    real_capital = $false
    leverage_or_margin = $false
}

if ($Json) {
    $result | ConvertTo-Json -Depth 100
} else {
    $result | Format-List
}
