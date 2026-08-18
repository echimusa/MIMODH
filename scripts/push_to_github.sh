#!/usr/bin/env bash
# =============================================================================
#  push_to_github.sh  --  Push MultiOmics-Reactome to GitHub
#  Platforms: Linux, macOS, WSL2, Git Bash (Windows)
#
#  Usage:
#    ./scripts/push_to_github.sh                       # interactive
#    ./scripts/push_to_github.sh -u USER -r REPO       # named repo
#    ./scripts/push_to_github.sh --private             # create private repo
#    ./scripts/push_to_github.sh --secrets             # also upload CI secrets
#    ./scripts/push_to_github.sh --dry-run             # show plan only
#
#  Auth (first match wins):
#    1. $GITHUB_TOKEN environment variable
#    2. gh CLI  (gh auth token)
#    3. interactive prompt (hidden input)
#
#  Token scopes needed: repo, workflow, admin:repo_hook
#  Create one at: https://github.com/settings/tokens/new
# =============================================================================
set -euo pipefail
IFS=$'\n\t'

if [ -t 1 ]; then
  R='\033[0;31m'; G='\033[0;32m'; Y='\033[1;33m'
  C='\033[0;36m'; W='\033[1;37m'; N='\033[0m'
else
  R=''; G=''; Y=''; C=''; W=''; N=''
fi
info() { printf "${G}[INFO]${N}  %s\n" "$*"; }
warn() { printf "${Y}[WARN]${N}  %s\n" "$*"; }
die()  { printf "${R}[ERROR]${N} %s\n" "$*" >&2; exit 1; }
step() { printf "\n${C}== %s ==${N}\n" "$*"; }
ask()  { printf "${W}%s${N}" "$*"; }

GH_USER=""; GH_REPO=""; VISIBILITY="public"
DRY_RUN=0; DO_SECRETS=0; BRANCH="main"; FORCE=0

while [ $# -gt 0 ]; do
  case "$1" in
    -u|--user)    GH_USER="${2:-}"; shift 2 ;;
    -r|--repo)    GH_REPO="${2:-}"; shift 2 ;;
    -b|--branch)  BRANCH="${2:-main}"; shift 2 ;;
    --private)    VISIBILITY="private"; shift ;;
    --public)     VISIBILITY="public"; shift ;;
    --secrets)    DO_SECRETS=1; shift ;;
    --force)      FORCE=1; shift ;;
    --dry-run)    DRY_RUN=1; shift ;;
    -h|--help)    sed -n '2,22p' "$0"; exit 0 ;;
    *)            die "Unknown option: $1 (try --help)" ;;
  esac
done

run() {
  if [ "$DRY_RUN" -eq 1 ]; then printf "  [DRY-RUN] %s\n" "$*"; else "$@"; fi
}

# =============================================================================
step "Prerequisites"

command -v git >/dev/null 2>&1 || die "git not found. Install: https://git-scm.com"
info "git $(git --version | awk '{print $3}')"
command -v curl >/dev/null 2>&1 || die "curl not found"

# ── Resolve token ─────────────────────────────────────────────────────────────
TOKEN="${GITHUB_TOKEN:-}"
if [ -z "$TOKEN" ] && command -v gh >/dev/null 2>&1; then
  TOKEN="$(gh auth token 2>/dev/null || echo '')"
  [ -n "$TOKEN" ] && info "Token obtained from gh CLI"
fi
if [ -z "$TOKEN" ]; then
  warn "No GITHUB_TOKEN found."
  echo "  Create one at: https://github.com/settings/tokens/new"
  echo "  Scopes: repo, workflow, admin:repo_hook"
  ask "  Paste your token (input hidden): "
  stty -echo 2>/dev/null || true
  read -r TOKEN
  stty echo 2>/dev/null || true
  echo ""
fi
[ -n "$TOKEN" ] || die "No token provided."

API="https://api.github.com"
auth_curl() {
  curl -sS -H "Authorization: token ${TOKEN}" \
       -H "Accept: application/vnd.github+json" \
       -H "X-GitHub-Api-Version: 2022-11-28" "$@"
}

# ── Validate token and detect user ────────────────────────────────────────────
USER_JSON="$(auth_curl "${API}/user" || true)"
LOGIN="$(printf '%s' "$USER_JSON" | grep -o '"login"[^,]*' | head -1 | cut -d'"' -f4)"
[ -n "$LOGIN" ] || die "Token validation failed. Check the token and its scopes."
info "Authenticated as: ${LOGIN}"

SCOPES="$(curl -sS -I -H "Authorization: token ${TOKEN}" "${API}/user" 2>/dev/null \
          | tr -d '\r' | grep -i '^x-oauth-scopes:' | cut -d' ' -f2- || echo '')"
if [ -n "$SCOPES" ]; then
  info "Token scopes: ${SCOPES}"
  case "$SCOPES" in
    *repo*) ;;
    *) warn "Token appears to lack the 'repo' scope; push will likely fail." ;;
  esac
fi

# ── Repo target ───────────────────────────────────────────────────────────────
[ -n "$GH_USER" ] || GH_USER="$LOGIN"
if [ -z "$GH_REPO" ]; then
  DEFAULT_REPO="$(basename "$(pwd)")"
  ask "  Repository name [${DEFAULT_REPO}]: "
  read -r reply
  GH_REPO="${reply:-$DEFAULT_REPO}"
fi
REPO_FULL="${GH_USER}/${GH_REPO}"
REMOTE_URL="https://github.com/${REPO_FULL}.git"

# =============================================================================
step "Pre-push checks"

[ -f requirements.txt ] || warn "requirements.txt not found; are you in the repo root?"

# Python syntax check on everything we are about to push
if command -v python3 >/dev/null 2>&1; then
  info "Checking Python syntax..."
  BAD=$(python3 - <<'PY'
import ast, sys
from pathlib import Path
bad = []
for f in sorted(Path('.').rglob('*.py')):
    s = str(f)
    if any(x in s for x in ('.venv', 'build/', 'dist/', '__pycache__', '.git/')):
        continue
    try:
        ast.parse(f.read_text(encoding='utf-8', errors='replace'))
    except SyntaxError as e:
        bad.append(f"{f}:{e.lineno}: {e.msg}")
print("\n".join(bad))
PY
)
  if [ -n "$BAD" ]; then
    printf "%s\n" "$BAD" | while IFS= read -r l; do printf "  ${R}FAIL${N} %s\n" "$l"; done
    [ "$FORCE" -eq 1 ] || die "Python syntax errors found. Fix them, or re-run with --force."
    warn "Continuing despite syntax errors (--force)."
  else
    info "All Python files parse cleanly"
  fi
fi

# Shell script syntax check
for s in scripts/*.sh; do
  [ -f "$s" ] || continue
  if bash -n "$s" 2>/dev/null; then info "$s syntax OK"; else warn "$s has syntax errors"; fi
done

# ---- Large-file check -------------------------------------------------------
# GitHub hard-rejects any single file over 100 MB. Build artifacts (the desktop
# .exe is ~280 MB) are the usual culprit and must never be committed.
info "Checking for files over GitHub's 100 MB limit..."
GH_LIMIT=$((100 * 1024 * 1024))
WARN_LIMIT=$((50 * 1024 * 1024))
OVERSIZED=""
LARGEISH=""
while IFS= read -r f; do
  [ -f "$f" ] || continue
  # portable size lookup (GNU stat, then BSD stat, then wc)
  sz=$(stat -c%s "$f" 2>/dev/null || stat -f%z "$f" 2>/dev/null || wc -c <"$f")
  if [ "$sz" -gt "$GH_LIMIT" ]; then
    OVERSIZED="${OVERSIZED}  $f  ($((sz / 1024 / 1024)) MB)\n"
  elif [ "$sz" -gt "$WARN_LIMIT" ]; then
    LARGEISH="${LARGEISH}  $f  ($((sz / 1024 / 1024)) MB)\n"
  fi
done < <(git ls-files 2>/dev/null || find . -type f -not -path './.git/*')

if [ -n "$LARGEISH" ]; then
  warn "Files over 50 MB (allowed, but slow to clone):"
  printf "%b" "$LARGEISH"
fi

# Also scan COMMIT HISTORY -- a file removed from the index is still pushed
# if any historical commit contains it. This is the case that wastes a 280 MB
# upload only to be rejected by the server.
HIST_BIG=""
if [ -d .git ]; then
  HIST_BIG=$(git rev-list --objects --all 2>/dev/null \
    | git cat-file --batch-check='%(objectname) %(objecttype) %(objectsize) %(rest)' 2>/dev/null \
    | awk -v lim="$GH_LIMIT" '$2=="blob" && $3+0 > lim {printf "  %s  (%.0f MB)\n", $4, $3/1048576}' \
    | sort -u || true)
fi

if [ -n "$HIST_BIG" ]; then
  printf "${R}Oversized files present in COMMIT HISTORY:${N}\n"
  printf "%s\n" "$HIST_BIG"
  echo ""
  echo "  These are pushed even if you have removed them from the index."
  echo "  'git rm --cached' is NOT enough -- history must be rewritten."
  echo ""
  echo "  Simplest fix (start a clean single commit, keeps all your files):"
  echo "     git init -b main            # after moving .git aside"
  echo "  Windows users: run REPAIR_GIT.bat and choose option 1."
  echo ""
  echo "  To keep your commit history instead:"
  echo "     git filter-branch --force --index-filter \\"
  echo "       'git rm --cached --ignore-unmatch <path>' \\"
  echo "       --prune-empty --tag-name-filter cat -- --all"
  echo "     git reflog expire --expire=now --all && git gc --prune=now"
  echo ""
  [ "$FORCE" -eq 1 ] || die "Refusing to push -- GitHub will reject this. Clean history first."
  warn "Continuing despite oversized history (--force). Expect rejection."
fi

if [ -n "$OVERSIZED" ]; then
  printf "${R}Files exceeding GitHub's 100 MB limit:${N}\n"
  printf "%b" "$OVERSIZED"
  echo ""
  echo "  GitHub will reject the push. Remove them from git tracking:"
  printf "%b" "$OVERSIZED" | while IFS= read -r line; do
    fpath=$(printf '%s' "$line" | awk '{print $1}')
    [ -n "$fpath" ] && echo "     git rm --cached \"$fpath\""
  done
  echo ""
  echo "  Then make sure .gitignore covers them, and amend the commit:"
  echo "     git add .gitignore && git commit --amend --no-edit"
  echo ""
  echo "  If the file is in an OLDER commit, rewrite history:"
  echo "     git filter-branch --force --index-filter \\"
  echo "       'git rm --cached --ignore-unmatch <path>' \\"
  echo "       --prune-empty --tag-name-filter cat -- --all"
  echo ""
  [ "$FORCE" -eq 1 ] || die "Refusing to push. Remove the large files first, or use --force."
  warn "Continuing despite oversized files (--force). GitHub will very likely reject this."
else
  info "No files exceed the 100 MB limit"
fi

# Secret scan
info "Scanning for accidentally committed secrets..."
LEAKS=$(grep -rInE \
  '(AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{20,}|-----BEGIN (RSA|OPENSSH|EC) PRIVATE KEY-----)' \
  --exclude-dir=.git --exclude-dir=node_modules --exclude-dir=.venv* \
  --exclude-dir=dist --exclude-dir=build . 2>/dev/null || true)
if [ -n "$LEAKS" ]; then
  printf "${R}Potential secrets detected:${N}\n%s\n" "$LEAKS"
  [ "$FORCE" -eq 1 ] || die "Refusing to push. Remove the secrets, or re-run with --force."
  warn "Continuing despite detected secrets (--force)."
else
  info "No secrets detected"
fi

# =============================================================================
step "Git repository"

if [ -d .git ]; then
  info "Existing git repository detected"
  CURRENT=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
  [ -n "$CURRENT" ] && info "Current branch: ${CURRENT}"
else
  info "Initialising new repository on branch '${BRANCH}'"
  if git init -b "$BRANCH" >/dev/null 2>&1; then :; else
    git init >/dev/null
    git checkout -b "$BRANCH" >/dev/null 2>&1 || true
  fi
fi

git config user.name  >/dev/null 2>&1 || git config user.name  "$LOGIN"
git config user.email >/dev/null 2>&1 || git config user.email "${LOGIN}@users.noreply.github.com"
git config credential.helper "" 2>/dev/null || true
git config core.autocrlf false 2>/dev/null || true

# .gitignore safety net
if [ ! -f .gitignore ]; then
  info "Creating .gitignore"
  cat > .gitignore <<'GI'
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
GI
fi

run git add -A
STAGED=$(git diff --cached --name-only 2>/dev/null | wc -l | tr -d ' ')
info "${STAGED} files staged"
[ "$STAGED" -gt 0 ] || [ "$DRY_RUN" -eq 1 ] || die "Nothing staged. Is this the right directory?"

if git rev-parse HEAD >/dev/null 2>&1; then
  MSG="chore: update MultiOmics-Reactome ($(date -u +%Y-%m-%d))"
else
  MSG="feat: MultiOmics-Reactome v3.0 (MIMODH-compliant multi-omics pipeline)"
fi
if [ "$DRY_RUN" -eq 0 ]; then
  git commit -m "$MSG" || info "Nothing new to commit"
else
  printf "  [DRY-RUN] git commit -m \"%s\"\n" "$MSG"
fi

# =============================================================================
step "GitHub repository ${REPO_FULL}"

if auth_curl "${API}/repos/${REPO_FULL}" | grep -q '"full_name"'; then
  info "Repository exists"
else
  info "Creating ${VISIBILITY} repository..."
  PRIV=false; [ "$VISIBILITY" = "private" ] && PRIV=true
  BODY=$(printf '{"name":"%s","private":%s,"has_issues":true,"has_wiki":false,"auto_init":false,"description":"%s"}' \
    "$GH_REPO" "$PRIV" \
    "MultiOmics-Reactome v3.0 - MIMODH-compliant multi-omics harmonization pipeline")
  if [ "$DRY_RUN" -eq 0 ]; then
    RESP=$(auth_curl -X POST "${API}/user/repos" -d "$BODY")
    printf '%s' "$RESP" | grep -q '"full_name"' \
      || die "Failed to create repository: $(printf '%s' "$RESP" | head -c 300)"
    info "Created https://github.com/${REPO_FULL}"
  else
    printf "  [DRY-RUN] POST /user/repos  name=%s private=%s\n" "$GH_REPO" "$PRIV"
  fi
fi

# Remove branch protection so a force-push can succeed on re-runs
if [ "$DRY_RUN" -eq 0 ]; then
  auth_curl -X DELETE "${API}/repos/${REPO_FULL}/branches/${BRANCH}/protection" >/dev/null 2>&1 \
    && info "Existing branch protection removed (re-applied at the end)" \
    || true
fi

# =============================================================================
step "Pushing to ${REMOTE_URL}"

AUTH_REMOTE="https://${TOKEN}@github.com/${REPO_FULL}.git"
git remote add origin "$AUTH_REMOTE" 2>/dev/null || git remote set-url origin "$AUTH_REMOTE"

export GIT_TERMINAL_PROMPT=0
if [ "$DRY_RUN" -eq 0 ]; then
  if git -c credential.helper= push -u origin "HEAD:refs/heads/${BRANCH}" 2>&1; then
    info "Pushed ${BRANCH}"
  else
    warn "Normal push rejected; retrying with --force"
    if ! git -c credential.helper= push -u origin "HEAD:refs/heads/${BRANCH}" --force; then
      git remote set-url origin "$REMOTE_URL"
      echo ""
      err "Push rejected by GitHub. Read the 'remote:' lines above."
      echo ""
      echo "  Most common causes, in order:"
      echo ""
      echo "  1. FILE TOO LARGE (GH001) -- a file exceeds 100 MB."
      echo "     Look for 'exceeds GitHub's file size limit' above."
      echo "     Fix:  git rm --cached <path>"
      echo "           git commit --amend --no-edit"
      echo "     Build artifacts (*.exe, dist/) must never be committed."
      echo ""
      echo "  2. PROTECTED BRANCH (GH006) -- force-push blocked."
      echo "     Fix: disable protection in Settings > Branches, then re-run."
      echo ""
      echo "  3. TOKEN SCOPE -- the token lacks 'repo'."
      echo "     Fix: create a new token at https://github.com/settings/tokens/new"
      echo ""
      echo "  4. SECRET SCANNING -- GitHub blocked a detected credential."
      echo "     Fix: remove the secret and rewrite history."
      echo ""
      exit 1
    fi
    info "Force-pushed ${BRANCH}"
  fi

  # Optional dev / staging branches
  for b in dev staging; do
    git branch -D "$b" >/dev/null 2>&1 || true
    git checkout -b "$b" >/dev/null 2>&1
    git -c credential.helper= push -u origin "HEAD:refs/heads/${b}" --force --quiet 2>/dev/null \
      && info "Pushed ${b}" || warn "Could not push ${b}"
    git checkout "$BRANCH" >/dev/null 2>&1
  done
else
  printf "  [DRY-RUN] git push -u origin HEAD:refs/heads/%s\n" "$BRANCH"
fi

# Strip the token from the stored remote
git remote set-url origin "$REMOTE_URL"
unset GIT_TERMINAL_PROMPT

# =============================================================================
step "Repository settings"

if [ "$DRY_RUN" -eq 0 ]; then
  auth_curl -X PUT "${API}/repos/${REPO_FULL}/topics" \
    -d '{"names":["multi-omics","mimodh","reactome","bioinformatics","fastapi","pyqt6","desktop-app","aws","python","genomics","transcriptomics","proteomics"]}' \
    >/dev/null 2>&1 && info "Topics set" || warn "Could not set topics"

  auth_curl -X PUT "${API}/repos/${REPO_FULL}/branches/${BRANCH}/protection" -d '{
    "required_status_checks": {"strict": true, "contexts": []},
    "enforce_admins": false,
    "required_pull_request_reviews": {"required_approving_review_count": 1},
    "restrictions": null
  }' >/dev/null 2>&1 && info "Branch protection applied to ${BRANCH}" \
    || warn "Branch protection skipped (needs admin rights)"
fi

# =============================================================================
if [ "$DO_SECRETS" -eq 1 ] && [ "$DRY_RUN" -eq 0 ]; then
  step "GitHub Actions secrets"
  if command -v gh >/dev/null 2>&1; then
    export GH_TOKEN="$TOKEN"
    echo "  Press ENTER to skip any secret."
    for name in AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_REGION ECR_REPO \
                S3_DATA_BUCKET S3_WEB_BUCKET COGNITO_USER_POOL_ID \
                COGNITO_CLIENT_ID VITE_API_URL CODECOV_TOKEN; do
      ask "    ${name}: "
      stty -echo 2>/dev/null || true
      read -r val
      stty echo 2>/dev/null || true
      echo ""
      if [ -n "$val" ]; then
        printf '%s' "$val" | gh secret set "$name" --repo "$REPO_FULL" >/dev/null 2>&1 \
          && info "  set ${name}" || warn "  failed ${name}"
      fi
    done
  else
    warn "gh CLI not installed; secrets must be set manually."
    echo "  https://github.com/${REPO_FULL}/settings/secrets/actions"
  fi
fi

# =============================================================================
step "Done"
cat <<DONE

  Repository : https://github.com/${REPO_FULL}
  Clone      : git clone ${REMOTE_URL}
  Actions    : https://github.com/${REPO_FULL}/actions
  Secrets    : https://github.com/${REPO_FULL}/settings/secrets/actions

  Next steps:
    1. Add CI/CD secrets (re-run with --secrets, or use the link above)
    2. Deploy to AWS:  ./scripts/deploy_aws.sh
    3. Build desktop:  bash desktop/build_desktop.sh   (Linux/macOS)
                       .\\BUILD_APP.bat                 (Windows)
DONE
[ "$DRY_RUN" -eq 1 ] && warn "DRY RUN: nothing was pushed."
echo ""
