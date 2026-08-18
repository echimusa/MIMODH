# =============================================================================
#  push_to_github.ps1  --  Push MultiOmics-Reactome to GitHub (Windows)
#  Functionally identical to scripts/push_to_github.sh
#
#  Usage:
#    .\scripts\push_to_github.ps1
#    .\scripts\push_to_github.ps1 -User USER -Repo REPO
#    .\scripts\push_to_github.ps1 -Private
#    .\scripts\push_to_github.ps1 -Secrets
#    .\scripts\push_to_github.ps1 -DryRun
#
#  Auth (first match wins):
#    1. $env:GITHUB_TOKEN
#    2. gh CLI (gh auth token)
#    3. interactive prompt (hidden)
#
#  Token scopes: repo, workflow, admin:repo_hook
#  Create at: https://github.com/settings/tokens/new
# =============================================================================
[CmdletBinding()]
param(
    [string]$User    = "",
    [string]$Repo    = "",
    [string]$Branch  = "main",
    [switch]$Private,
    [switch]$Secrets,
    [switch]$Force,
    [switch]$DryRun
)

#Requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"

try { Unblock-File -LiteralPath $MyInvocation.MyCommand.Path -ErrorAction SilentlyContinue } catch {}

function Write-Info { param($m) Write-Host "[INFO]  $m" -ForegroundColor Green }
function Write-Warn { param($m) Write-Host "[WARN]  $m" -ForegroundColor Yellow }
function Write-Bad  { param($m) Write-Host "[ERROR] $m" -ForegroundColor Red }
function Write-Step { param($m) Write-Host "`n== $m ==" -ForegroundColor Cyan }
function Die        { param($m) Write-Bad $m; exit 1 }
function Show-Run   { param($m) if ($DryRun) { Write-Host "  [DRY-RUN] $m" -ForegroundColor Blue } }

$repoRoot = if ($MyInvocation.MyCommand.Path) {
    Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
} else { (Get-Location).Path }
Set-Location $repoRoot

# =============================================================================
Write-Step "Prerequisites"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Die "git not found. Install: https://git-scm.com/download/win"
}
Write-Info "git $((git --version) -replace 'git version ','')"

# ---- Resolve token ----------------------------------------------------------
$token = $env:GITHUB_TOKEN
if (-not $token -and (Get-Command gh -ErrorAction SilentlyContinue)) {
    $token = (gh auth token 2>$null)
    if ($token) { Write-Info "Token obtained from gh CLI" }
}
if (-not $token) {
    Write-Warn "No GITHUB_TOKEN found."
    Write-Host "  Create one at: https://github.com/settings/tokens/new" -ForegroundColor Yellow
    Write-Host "  Scopes: repo, workflow, admin:repo_hook" -ForegroundColor Yellow
    $sec = Read-Host "  Paste your token" -AsSecureString
    $token = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
             [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
}
if (-not $token) { Die "No token provided." }

$api = "https://api.github.com"
$headers = @{
    "Authorization"        = "token $token"
    "Accept"               = "application/vnd.github+json"
    "X-GitHub-Api-Version" = "2022-11-28"
}

# ---- Validate token ---------------------------------------------------------
try {
    $me = Invoke-RestMethod -Uri "$api/user" -Headers $headers -Method Get
    Write-Info "Authenticated as: $($me.login)"
} catch {
    Die "Token validation failed: $_`nCheck the token at https://github.com/settings/tokens"
}

try {
    $resp = Invoke-WebRequest -Uri "$api/user" -Headers $headers -Method Get -UseBasicParsing
    $scopes = $resp.Headers["X-OAuth-Scopes"]
    if ($scopes) {
        Write-Info "Token scopes: $scopes"
        if ($scopes -notmatch "repo") {
            Write-Warn "Token appears to lack the 'repo' scope; push will likely fail."
        }
    }
} catch {}

# ---- Repo target ------------------------------------------------------------
if (-not $User) { $User = $me.login }
if (-not $Repo) {
    $default = Split-Path -Leaf $repoRoot
    $reply = Read-Host "  Repository name [$default]"
    $Repo = if ($reply) { $reply } else { $default }
}
$repoFull  = "$User/$Repo"
$remoteUrl = "https://github.com/$repoFull.git"
$visibility = if ($Private) { "private" } else { "public" }

# =============================================================================
Write-Step "Pre-push checks"

if (-not (Test-Path "requirements.txt")) {
    Write-Warn "requirements.txt not found; are you in the repo root? ($repoRoot)"
}

# ---- Python syntax check ----------------------------------------------------
$py = $null
foreach ($c in @("python", "python3", "py")) {
    if (Get-Command $c -ErrorAction SilentlyContinue) { $py = $c; break }
}
if ($py) {
    Write-Info "Checking Python syntax..."
    $checkScript = @'
import ast, sys
from pathlib import Path
bad = []
for f in sorted(Path(".").rglob("*.py")):
    s = str(f)
    if any(x in s for x in (".venv", "build", "dist", "__pycache__", ".git")):
        continue
    try:
        ast.parse(f.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError as e:
        bad.append(str(f) + ":" + str(e.lineno) + ": " + e.msg)
for b in bad:
    print(b)
sys.exit(1 if bad else 0)
'@
    $tmp = Join-Path $env:TEMP "mimodh_syntax_check.py"
    [System.IO.File]::WriteAllText($tmp, $checkScript,
        (New-Object System.Text.UTF8Encoding $false))
    $out = & $py $tmp 2>&1
    $syntaxOK = ($LASTEXITCODE -eq 0)
    Remove-Item $tmp -Force -ErrorAction SilentlyContinue
    if ($syntaxOK) {
        Write-Info "All Python files parse cleanly"
    } else {
        $out | ForEach-Object { Write-Host "  FAIL $_" -ForegroundColor Red }
        if (-not $Force) { Die "Python syntax errors found. Fix them, or use -Force." }
        Write-Warn "Continuing despite syntax errors (-Force)"
    }
} else {
    Write-Warn "Python not found; skipping syntax check"
}

# ---- Large-file check -------------------------------------------------------
# GitHub hard-rejects any single file over 100 MB. Build artifacts (the desktop
# .exe is ~280 MB) are the usual culprit and must never be committed.
Write-Info "Checking for files over GitHub's 100 MB limit..."
$ghLimit   = 100MB
$warnLimit = 50MB
$oversized = @()
$largeish  = @()

$tracked = git ls-files 2>$null
if (-not $tracked) {
    $tracked = Get-ChildItem -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -notmatch '\\\.git\\' } |
        ForEach-Object { $_.FullName.Replace("$repoRoot\", "") }
}
foreach ($rel in $tracked) {
    $full = Join-Path $repoRoot $rel
    if (-not (Test-Path -LiteralPath $full -PathType Leaf)) { continue }
    $len = (Get-Item -LiteralPath $full).Length
    $mb  = [math]::Round($len / 1MB, 0)
    if     ($len -gt $ghLimit)   { $oversized += "$rel  ($mb MB)" }
    elseif ($len -gt $warnLimit) { $largeish  += "$rel  ($mb MB)" }
}

if ($largeish.Count -gt 0) {
    Write-Warn "Files over 50 MB (allowed, but slow to clone):"
    $largeish | ForEach-Object { Write-Host "    $_" -ForegroundColor Yellow }
}

# Also scan COMMIT HISTORY -- a file removed from the index is still pushed
# if any historical commit contains it.
$histBig = @()
if (Test-Path ".git") {
    try {
        $objs  = git rev-list --objects --all 2>$null
        $check = $objs | ForEach-Object { ($_ -split ' ', 2)[0] } |
                 git cat-file --batch-check='%(objectname) %(objecttype) %(objectsize)' 2>$null
        $bigOids = @{}
        foreach ($line in $check) {
            $p3 = $line -split ' '
            if ($p3.Length -ge 3 -and $p3[1] -eq 'blob' -and [int64]$p3[2] -gt $ghLimit) {
                $bigOids[$p3[0]] = [int64]$p3[2]
            }
        }
        foreach ($o in $objs) {
            $pp = $o -split ' ', 2
            if ($pp.Length -eq 2 -and $bigOids.ContainsKey($pp[0])) {
                $mb2 = [math]::Round($bigOids[$pp[0]] / 1MB, 0)
                $histBig += "$($pp[1])  ($mb2 MB)"
            }
        }
        $histBig = $histBig | Select-Object -Unique
    } catch { }
}

if ($histBig.Count -gt 0) {
    Write-Host "  Oversized files present in COMMIT HISTORY:" -ForegroundColor Red
    $histBig | ForEach-Object { Write-Host "    $_" -ForegroundColor Red }
    Write-Host ""
    Write-Host "  These are pushed even after 'git rm --cached'." -ForegroundColor Yellow
    Write-Host "  History must be rewritten." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  EASIEST FIX: run REPAIR_GIT.bat and choose option 1 (fresh start)." -ForegroundColor Cyan
    Write-Host ""
    if (-not $Force) { Die "Refusing to push -- GitHub will reject this. Clean history first." }
    Write-Warn "Continuing despite oversized history (-Force). Expect rejection."
}

if ($oversized.Count -gt 0) {
    Write-Host "  Files exceeding GitHub's 100 MB limit:" -ForegroundColor Red
    $oversized | ForEach-Object { Write-Host "    $_" -ForegroundColor Red }
    Write-Host ""
    Write-Host "  GitHub will reject the push. Remove them from git tracking:" -ForegroundColor Yellow
    foreach ($o in $oversized) {
        $fp = ($o -split '\s\s')[0]
        Write-Host "     git rm --cached `"$fp`"" -ForegroundColor Cyan
    }
    Write-Host ""
    Write-Host "  Then amend the commit:" -ForegroundColor Yellow
    Write-Host "     git add .gitignore; git commit --amend --no-edit" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  If the file is in an OLDER commit, rewrite history:" -ForegroundColor Yellow
    Write-Host "     git filter-branch --force --index-filter ``" -ForegroundColor Cyan
    Write-Host "       `"git rm --cached --ignore-unmatch <path>`" ``" -ForegroundColor Cyan
    Write-Host "       --prune-empty --tag-name-filter cat -- --all" -ForegroundColor Cyan
    Write-Host ""
    if (-not $Force) { Die "Refusing to push. Remove the large files first, or use -Force." }
    Write-Warn "Continuing despite oversized files (-Force). GitHub will very likely reject this."
} else {
    Write-Info "No files exceed the 100 MB limit"
}

# ---- Secret scan ------------------------------------------------------------
Write-Info "Scanning for accidentally committed secrets..."
$patterns = @(
    'AKIA[0-9A-Z]{16}',
    'ghp_[A-Za-z0-9]{36}',
    'github_pat_[A-Za-z0-9_]{20,}',
    '-----BEGIN (RSA|OPENSSH|EC) PRIVATE KEY-----'
)
$leaks = @()
Get-ChildItem -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object {
        $_.FullName -notmatch '\\(\.git|node_modules|\.venv[^\\]*|dist|build|__pycache__)\\' -and
        $_.Length -lt 2MB
    } |
    ForEach-Object {
        $f = $_
        try { $txt = [System.IO.File]::ReadAllText($f.FullName) } catch { return }
        foreach ($p in $patterns) {
            if ($txt -match $p) {
                $leaks += "$($f.FullName.Replace($repoRoot,'.')) matches /$p/"
                break
            }
        }
    }
if ($leaks.Count -gt 0) {
    $leaks | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
    if (-not $Force) { Die "Refusing to push. Remove the secrets, or use -Force." }
    Write-Warn "Continuing despite detected secrets (-Force)"
} else {
    Write-Info "No secrets detected"
}

# =============================================================================
Write-Step "Git repository"

$prevPref = $ErrorActionPreference
$ErrorActionPreference = "Continue"

if (Test-Path ".git") {
    Write-Info "Existing git repository detected"
} else {
    Write-Info "Initialising new repository on branch '$Branch'"
    $null = git init -b $Branch 2>&1
    if ($LASTEXITCODE -ne 0) {
        $null = git init 2>&1
        $null = git checkout -b $Branch 2>&1
    }
}

$null = git config user.name  2>&1
if ($LASTEXITCODE -ne 0) { $null = git config user.name  $me.login 2>&1 }
$null = git config user.email 2>&1
if ($LASTEXITCODE -ne 0) { $null = git config user.email "$($me.login)@users.noreply.github.com" 2>&1 }
$null = git config credential.helper "" 2>&1
$null = git config core.autocrlf false 2>&1

if (-not (Test-Path ".gitignore")) {
    Write-Info "Creating .gitignore"
    $gi = @'
__pycache__/
*.py[cod]
.venv*/
*.egg-info/
dist/
build/
.pytest_cache/
.coverage
htmlcov/
*.log
logs/
node_modules/
frontend/dist/
.env
.env.*
!.env.example
*.pem
deploy_*.env
deployment_*.txt
crash_log.txt
*.broken
.DS_Store
Thumbs.db
.vscode/
.idea/
multiomics_reactome_output/
output/
*.h5ad
*.parquet
'@
    [System.IO.File]::WriteAllText((Join-Path $repoRoot ".gitignore"), $gi,
        (New-Object System.Text.UTF8Encoding $false))
}

if ($DryRun) {
    Show-Run "git add -A"
} else {
    $null = git add -A 2>&1
    $staged = (git diff --cached --name-only 2>&1 | Measure-Object -Line).Lines
    Write-Info "$staged files staged"
    if ($staged -eq 0) { Die "Nothing staged. Is this the right directory?" }

    $null = git rev-parse HEAD 2>&1
    $msg = if ($LASTEXITCODE -eq 0) {
        "chore: update MultiOmics-Reactome ($(Get-Date -Format 'yyyy-MM-dd'))"
    } else {
        "feat: MultiOmics-Reactome v3.0 (MIMODH-compliant multi-omics pipeline)"
    }
    git commit -m $msg
    if ($LASTEXITCODE -ne 0) { Write-Info "Nothing new to commit" }
}

# =============================================================================
Write-Step "GitHub repository $repoFull"

$exists = $false
try {
    $null = Invoke-RestMethod -Uri "$api/repos/$repoFull" -Headers $headers -Method Get
    $exists = $true
    Write-Info "Repository exists"
} catch { }

if (-not $exists) {
    Write-Info "Creating $visibility repository..."
    $body = @{
        name        = $Repo
        private     = [bool]$Private
        has_issues  = $true
        has_wiki    = $false
        auto_init   = $false
        description = "MultiOmics-Reactome v3.0 - MIMODH-compliant multi-omics harmonization pipeline"
    } | ConvertTo-Json
    if ($DryRun) {
        Show-Run "POST /user/repos  name=$Repo private=$([bool]$Private)"
    } else {
        try {
            $null = Invoke-RestMethod -Uri "$api/user/repos" -Headers $headers `
                        -Method Post -Body $body -ContentType "application/json"
            Write-Info "Created https://github.com/$repoFull"
        } catch { Die "Failed to create repository: $_" }
    }
}

if (-not $DryRun) {
    try {
        $null = Invoke-RestMethod -Uri "$api/repos/$repoFull/branches/$Branch/protection" `
                    -Headers $headers -Method Delete
        Write-Info "Existing branch protection removed (re-applied at the end)"
    } catch { }
}

# =============================================================================
Write-Step "Pushing to $remoteUrl"

$authRemote = "https://$token@github.com/$repoFull.git"
$null = git remote add origin $authRemote 2>&1
if ($LASTEXITCODE -ne 0) { $null = git remote set-url origin $authRemote 2>&1 }

$env:GIT_TERMINAL_PROMPT = "0"

if ($DryRun) {
    Show-Run "git push -u origin HEAD:refs/heads/$Branch"
} else {
    $null = git -c credential.helper= push -u origin "HEAD:refs/heads/$Branch" 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "Normal push rejected; retrying with --force"
        git -c credential.helper= push -u origin "HEAD:refs/heads/$Branch" --force
        if ($LASTEXITCODE -ne 0) {
            $null = git remote set-url origin $remoteUrl 2>&1
            Write-Host ""
            Write-Bad "Push rejected by GitHub. Read the 'remote:' lines above."
            Write-Host ""
            Write-Host "  Most common causes, in order:" -ForegroundColor Yellow
            Write-Host ""
            Write-Host "  1. FILE TOO LARGE (GH001) -- a file exceeds 100 MB." -ForegroundColor White
            Write-Host "     Look for 'exceeds GitHub's file size limit' above."
            Write-Host "     Fix:  git rm --cached <path>" -ForegroundColor Cyan
            Write-Host "           git commit --amend --no-edit" -ForegroundColor Cyan
            Write-Host "     Build artifacts (*.exe, dist\) must never be committed."
            Write-Host ""
            Write-Host "  2. PROTECTED BRANCH (GH006) -- force-push blocked." -ForegroundColor White
            Write-Host "     Fix: disable protection in Settings > Branches, then re-run."
            Write-Host ""
            Write-Host "  3. TOKEN SCOPE -- the token lacks 'repo'." -ForegroundColor White
            Write-Host "     Fix: new token at https://github.com/settings/tokens/new"
            Write-Host ""
            Write-Host "  4. SECRET SCANNING -- GitHub blocked a detected credential." -ForegroundColor White
            Write-Host "     Fix: remove the secret and rewrite history."
            Write-Host ""
            exit 1
        }
        Write-Info "Force-pushed $Branch"
    } else {
        Write-Info "Pushed $Branch"
    }

    foreach ($b in @("dev", "staging")) {
        $null = git branch -D $b 2>&1
        $null = git checkout -b $b 2>&1
        $null = git -c credential.helper= push -u origin "HEAD:refs/heads/$b" --force --quiet 2>&1
        if ($LASTEXITCODE -eq 0) { Write-Info "Pushed $b" } else { Write-Warn "Could not push $b" }
        $null = git checkout $Branch 2>&1
    }
}

$null = git remote set-url origin $remoteUrl 2>&1
$env:GIT_TERMINAL_PROMPT = $null
$ErrorActionPreference = $prevPref

# =============================================================================
Write-Step "Repository settings"

if (-not $DryRun) {
    $topics = @{ names = @("multi-omics","mimodh","reactome","bioinformatics","fastapi",
                           "pyqt6","desktop-app","aws","python","genomics",
                           "transcriptomics","proteomics") } | ConvertTo-Json
    try {
        $null = Invoke-RestMethod -Uri "$api/repos/$repoFull/topics" -Headers $headers `
                    -Method Put -Body $topics -ContentType "application/json"
        Write-Info "Topics set"
    } catch { Write-Warn "Could not set topics" }

    $protection = @{
        required_status_checks        = @{ strict = $true; contexts = @() }
        enforce_admins               = $false
        required_pull_request_reviews = @{ required_approving_review_count = 1 }
        restrictions                 = $null
    } | ConvertTo-Json -Depth 5
    try {
        $null = Invoke-RestMethod -Uri "$api/repos/$repoFull/branches/$Branch/protection" `
                    -Headers $headers -Method Put -Body $protection -ContentType "application/json"
        Write-Info "Branch protection applied to $Branch"
    } catch { Write-Warn "Branch protection skipped (needs admin rights)" }
}

# =============================================================================
if ($Secrets -and -not $DryRun) {
    Write-Step "GitHub Actions secrets"
    if (Get-Command gh -ErrorAction SilentlyContinue) {
        $env:GH_TOKEN = $token
        Write-Host "  Press ENTER to skip any secret." -ForegroundColor Gray
        foreach ($name in @("AWS_ACCESS_KEY_ID","AWS_SECRET_ACCESS_KEY","AWS_REGION",
                            "ECR_REPO","S3_DATA_BUCKET","S3_WEB_BUCKET",
                            "COGNITO_USER_POOL_ID","COGNITO_CLIENT_ID",
                            "VITE_API_URL","CODECOV_TOKEN")) {
            $sec = Read-Host "    $name" -AsSecureString
            $val = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
                   [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
            if ($val) {
                $val | gh secret set $name --repo $repoFull 2>$null
                if ($LASTEXITCODE -eq 0) { Write-Info "  set $name" }
                else { Write-Warn "  failed $name" }
            }
        }
    } else {
        Write-Warn "gh CLI not installed; set secrets manually:"
        Write-Host "  https://github.com/$repoFull/settings/secrets/actions" -ForegroundColor Cyan
    }
}

# =============================================================================
Write-Step "Done"
Write-Host ""
Write-Host "  Repository : https://github.com/$repoFull" -ForegroundColor Cyan
Write-Host "  Clone      : git clone $remoteUrl"          -ForegroundColor Cyan
Write-Host "  Actions    : https://github.com/$repoFull/actions" -ForegroundColor Cyan
Write-Host "  Secrets    : https://github.com/$repoFull/settings/secrets/actions" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Next steps:" -ForegroundColor White
Write-Host "    1. Add CI/CD secrets (re-run with -Secrets, or use the link above)"
Write-Host "    2. Deploy to AWS:  bash scripts/deploy_aws.sh   (WSL / Git Bash)"
Write-Host "    3. Build desktop:  .\BUILD_APP.bat"
Write-Host ""
if ($DryRun) { Write-Warn "DRY RUN: nothing was pushed." }
