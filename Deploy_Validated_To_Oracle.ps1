param(
    [string]$OracleHost = '92.4.90.35',
    [string]$OracleUser = 'ubuntu',
    [string]$KeyPath = "$HOME\.ssh\ssh-key-2026-10-05.key",
    [string]$RemoteAppPath = '/home/ubuntu/ProductionReviewWebApp',
    [string]$HealthUrl = 'https://machineshop.duckdns.org/api/health',
    [switch]$DryRun
)
$ErrorActionPreference='Stop'

function Invoke-NativeChecked {
    param(
        [Parameter(Mandatory)] [string]$Program,
        [Parameter(Mandatory)] [string[]]$Arguments,
        [string]$InputText
    )
    $resolvedProgram = (Get-Command $Program -ErrorAction Stop).Source
    $savedPreference = $ErrorActionPreference
    $nativeExitCode = $null
    try {
        $ErrorActionPreference = 'Continue'
        $PSNativeCommandUseErrorActionPreference = $false
        $LASTEXITCODE = $null
        if ($PSBoundParameters.ContainsKey('InputText')) {
            $nativeOutput = @($InputText | & $resolvedProgram @Arguments 2>&1)
        } else {
            $nativeOutput = @(& $resolvedProgram @Arguments 2>&1)
        }
        $nativeExitCode = if ($null -eq $LASTEXITCODE) { 0 } else { [int]$LASTEXITCODE }
    } finally {
        $ErrorActionPreference = $savedPreference
    }
    $outputLines = @($nativeOutput | ForEach-Object { $_.ToString() })
    if ($nativeExitCode -ne 0) {
        $outputLines | ForEach-Object { Write-Host $_ }
        throw "$Program failed with exit code $nativeExitCode."
    }
    $outputLines
}
function Invoke-NativeStreamingChecked {
    param(
        [Parameter(Mandatory)] [string]$Program,
        [Parameter(Mandatory)] [string[]]$Arguments,
        [string]$InputText
    )
    $resolvedProgram = (Get-Command $Program -ErrorAction Stop).Source
    $savedPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $PSNativeCommandUseErrorActionPreference = $false
        $LASTEXITCODE = $null
        if ($PSBoundParameters.ContainsKey('InputText')) {
            $InputText | & $resolvedProgram @Arguments 2>&1 | ForEach-Object { Write-Host $_.ToString() }
        } else {
            & $resolvedProgram @Arguments 2>&1 | ForEach-Object { Write-Host $_.ToString() }
        }
        $nativeExitCode = if ($null -eq $LASTEXITCODE) { 0 } else { [int]$LASTEXITCODE }
    } finally {
        $ErrorActionPreference = $savedPreference
    }
    if ($nativeExitCode -ne 0) {
        throw "$Program failed with exit code $nativeExitCode."
    }
}

Set-Location -LiteralPath $PSScriptRoot
$logDir=Join-Path $PSScriptRoot 'deployment_logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log=Join-Path $logDir ('deploy_'+(Get-Date -Format 'yyyyMMdd_HHmmss')+'.log')
Start-Transcript -LiteralPath $log -Force | Out-Null
try {
    Write-Host '[1/9] Checking Windows repository and deployment prerequisites...' -ForegroundColor Cyan
    foreach($cmd in @('git.exe','ssh.exe')){if(-not(Get-Command $cmd -ErrorAction SilentlyContinue)){throw "$cmd is unavailable."}}
    if(-not(Test-Path -LiteralPath $KeyPath)){throw "SSH key not found: $KeyPath"}
    $status=(& git.exe status --porcelain)
    if($LASTEXITCODE -ne 0){throw 'Unable to inspect local Git repository.'}
    if($status){throw 'Windows repository has uncommitted changes. Commit or stash them before deployment.'}
    $branch=(& git.exe branch --show-current).Trim()
    if($branch -ne 'main'){throw "Deploy only from main. Current branch: $branch"}
    & git.exe fetch origin main
    if($LASTEXITCODE -ne 0){throw 'git fetch failed.'}
    $tested=(& git.exe rev-parse HEAD).Trim()
    $remoteMain=(& git.exe rev-parse origin/main).Trim()
    if($tested -ne $remoteMain){throw "Windows-tested HEAD $tested is not current origin/main $remoteMain. Update/test Windows first."}
    Write-Host "      Validated commit: $tested" -ForegroundColor Green
    Write-Host '[2/9] Windows validation complete.' -ForegroundColor Green
    if($DryRun){Write-Host 'DRY RUN passed. No Oracle changes made.' -ForegroundColor Green; return}

    Write-Host '[3/9] Creating verified Oracle database + attachments backup...' -ForegroundColor Cyan
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'Backup_Oracle_Review_To_Windows.ps1') -OracleHost $OracleHost -OracleUser $OracleUser -KeyPath $KeyPath -RemoteAppPath $RemoteAppPath
    if($LASTEXITCODE -ne 0){throw 'Oracle backup helper failed; deployment cancelled.'}

    $target="$OracleUser@$OracleHost"
    $remote=@'
set -euo pipefail
APP="__APP__"
TARGET="__TARGET__"
cd "$APP"
test -d .git
PREVIOUS="$(git rev-parse HEAD)"
printf 'PREVIOUS_COMMIT=%s\n' "$PREVIOUS"
git fetch origin main
git cat-file -e "$TARGET^{commit}"
if ! git merge-base --is-ancestor "$TARGET" origin/main; then
  echo "Target commit is not on origin/main" >&2
  exit 20
fi
git status --porcelain
if [ -n "$(git status --porcelain)" ]; then
  echo "Oracle repository has local changes; refusing deployment." >&2
  exit 21
fi
rollback_code() {
  echo "[ROLLBACK] Deployment failed; rolling application code back to $PREVIOUS" >&2
  git checkout --detach "$PREVIOUS" || true
  docker compose build --no-cache backend frontend || true
  docker compose up -d --force-recreate backend frontend || true
}
trap rollback_code ERR
echo "[4/9] Checking out validated commit $TARGET"
git checkout --detach "$TARGET"
echo "[5/9] Building backend and frontend images (live Docker output follows)"
docker compose build --no-cache backend frontend
BACKEND_IMAGE="$(docker image inspect productionreviewwebapp-backend:latest --format '{{.Id}}')"
FRONTEND_IMAGE="$(docker image inspect productionreviewwebapp-frontend:latest --format '{{.Id}}')"
echo "      Backend image:  $BACKEND_IMAGE"
echo "      Frontend image: $FRONTEND_IMAGE"
echo "[6/9] Checking database readiness"
docker compose up -d db
for n in $(seq 1 30); do
  docker compose exec -T db pg_isready -U pms -d pms >/dev/null && break
  [ "$n" -eq 30 ] && exit 30
  sleep 2
done
echo "[7/9] Applying database migrations"
docker compose run --rm backend alembic upgrade head
echo "[8/9] Recreating backend and frontend with the newly built images"
docker compose up -d --force-recreate backend frontend
docker compose exec -T db pg_isready -U pms -d pms
RUNNING_BACKEND_IMAGE="$(docker inspect productionreviewwebapp-backend-1 --format '{{.Image}}')"
RUNNING_FRONTEND_IMAGE="$(docker inspect productionreviewwebapp-frontend-1 --format '{{.Image}}')"
echo "      Running backend image:  $RUNNING_BACKEND_IMAGE"
echo "      Running frontend image: $RUNNING_FRONTEND_IMAGE"
test "$RUNNING_BACKEND_IMAGE" = "$BACKEND_IMAGE"
test "$RUNNING_FRONTEND_IMAGE" = "$FRONTEND_IMAGE"
test "$(git rev-parse HEAD)" = "$TARGET"
echo "[9/9] Running final deployment verification"
trap - ERR
printf 'DEPLOYED_COMMIT=%s\n' "$TARGET"
'@
    $remote=$remote.Replace('__APP__',$RemoteAppPath).Replace('__TARGET__',$tested)
    try {
        Invoke-NativeStreamingChecked -Program 'ssh.exe' -Arguments @(
            '-T','-i',$KeyPath,$target,"tr -d '\r' | bash -s"
        ) -InputText $remote
    } catch {
        throw "Oracle deployment failed. Application-code rollback was attempted remotely. Database backup is preserved for guarded recovery. $($_.Exception.Message)"
    }

    Write-Host "      Checking public health endpoint: $HealthUrl" -ForegroundColor Cyan
    $health=Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 30
    if($health.StatusCode -ne 200){throw "Public health check returned HTTP $($health.StatusCode)."}
    Write-Host "DEPLOYMENT SUCCESSFUL - Oracle verified at commit $tested" -ForegroundColor Green
} finally {
    Stop-Transcript | Out-Null
    Write-Host "Deployment log: $log"
}
