#!/usr/bin/env bash
# =============================================================================
#  deploy_aws.sh  --  MultiOmics-Reactome v3.0 AWS Deployment
#  Interactive, idempotent deployment of the full cloud stack.
#  Platforms: Linux, macOS, WSL2, Git Bash (Windows)
#
#  Usage:
#    ./scripts/deploy_aws.sh                    # interactive
#    ./scripts/deploy_aws.sh --config my.env    # reuse saved answers
#    ./scripts/deploy_aws.sh --dry-run          # show plan, change nothing
#    ./scripts/deploy_aws.sh --destroy          # tear down
#
#  Prerequisites: aws-cli v2, docker, node 20+, (jq optional)
# =============================================================================
set -euo pipefail
IFS=$'\n\t'

if [ -t 1 ]; then
  R='\033[0;31m'; G='\033[0;32m'; Y='\033[1;33m'
  B='\033[0;34m'; C='\033[0;36m'; W='\033[1;37m'; N='\033[0m'
else
  R=''; G=''; Y=''; B=''; C=''; W=''; N=''
fi
info() { printf "${G}[INFO]${N}  %s\n" "$*"; }
warn() { printf "${Y}[WARN]${N}  %s\n" "$*"; }
err()  { printf "${R}[ERROR]${N} %s\n" "$*" >&2; }
die()  { err "$*"; exit 1; }
step() { printf "\n${C}== %s ==${N}\n" "$*"; }
ask()  { printf "${W}%s${N}" "$*"; }

DRY_RUN=0; DESTROY=0; CONFIG_FILE=""; NON_INTERACTIVE=0

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --destroy) DESTROY=1; shift ;;
    --config)  CONFIG_FILE="${2:-}"; NON_INTERACTIVE=1; shift 2 ;;
    --yes|-y)  NON_INTERACTIVE=1; shift ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) die "Unknown option: $1 (try --help)" ;;
  esac
done

run() {
  if [ "$DRY_RUN" -eq 1 ]; then
    printf "${B}[DRY-RUN]${N} %s\n" "$*"
  else
    "$@"
  fi
}

# =============================================================================
step "Checking prerequisites"

need() {
  if command -v "$1" >/dev/null 2>&1; then
    info "$1 found"
  else
    die "$1 not found. Install: $2"
  fi
}
need aws    "https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html"
need docker "https://docs.docker.com/get-docker"
need node   "https://nodejs.org"
command -v jq >/dev/null 2>&1 || warn "jq not found (optional)"

CALLER=$(aws sts get-caller-identity --output text --query 'Account,Arn' 2>/dev/null) \
  || die "AWS credentials not configured. Run: aws configure"
DETECTED_ACCOUNT=$(printf '%s' "$CALLER" | awk '{print $1}')
DETECTED_ARN=$(printf '%s' "$CALLER" | awk '{print $2}')
info "AWS identity: $DETECTED_ARN"
info "AWS account : $DETECTED_ACCOUNT"

# =============================================================================
step "Deployment configuration"

DEFAULT_REGION="$(aws configure get region 2>/dev/null || echo eu-west-2)"

if [ -n "$CONFIG_FILE" ]; then
  [ -f "$CONFIG_FILE" ] || die "Config file not found: $CONFIG_FILE"
  info "Loading config from $CONFIG_FILE"
  . "$CONFIG_FILE"
fi

prompt() {
  local var="$1" question="$2" default="${3:-}" current reply
  current="$(eval "printf '%s' \"\${$var:-}\"")"
  if [ -n "$current" ]; then
    info "$question -> $current (from config)"; return
  fi
  if [ "$NON_INTERACTIVE" -eq 1 ]; then
    eval "$var=\"\$default\""
    info "$question -> $default (default)"; return
  fi
  if [ -n "$default" ]; then ask "  $question [$default]: "
  else ask "  $question: "; fi
  read -r reply
  eval "$var=\"\${reply:-\$default}\""
}

echo ""
echo "  Answer the prompts. Press ENTER to accept the [default]."
echo ""
prompt AWS_REGION        "AWS region"                                  "$DEFAULT_REGION"
prompt APP_NAME          "Application name (used in resource names)"   "multiomics"
prompt STAGE             "Stage (prod / staging / dev)"                "prod"
prompt DOMAIN            "Your domain (blank = CloudFront URL only)"   ""
prompt EC2_INSTANCE_TYPE "EC2 instance type"                           "t3.large"
prompt ADMIN_EMAIL       "Admin email (Cognito first user, optional)"  ""

AWS_ACCOUNT_ID="$DETECTED_ACCOUNT"
RESOURCE_PREFIX="${APP_NAME}-${STAGE}"
S3_DATA_BUCKET="${RESOURCE_PREFIX}-data-${AWS_ACCOUNT_ID}"
S3_WEB_BUCKET="${RESOURCE_PREFIX}-web-${AWS_ACCOUNT_ID}"
DYNAMO_TABLE="${RESOURCE_PREFIX}-jobs"
SQS_QUEUE="${RESOURCE_PREFIX}-jobs.fifo"
ECR_REPO="${RESOURCE_PREFIX}-pipeline"
ECR_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO}"
COGNITO_POOL_NAME="${RESOURCE_PREFIX}-users"

if [ -n "$DOMAIN" ]; then
  API_SUBDOMAIN="api.${DOMAIN}"
  WEB_URL="https://${DOMAIN}"
  API_URL="https://${API_SUBDOMAIN}"
else
  API_SUBDOMAIN=""
  WEB_URL="(CloudFront URL, assigned after deploy)"
  API_URL="(EC2 public DNS, assigned after deploy)"
fi

cat <<PLAN

  +----------------------------------------------------------------+
  |  DEPLOYMENT PLAN                                               |
  +----------------------------------------------------------------+

    AWS account      : ${AWS_ACCOUNT_ID}
    Region           : ${AWS_REGION}
    Stage            : ${STAGE}

    S3 data bucket   : ${S3_DATA_BUCKET}
    S3 web bucket    : ${S3_WEB_BUCKET}
    DynamoDB table   : ${DYNAMO_TABLE}
    SQS queue        : ${SQS_QUEUE}
    ECR repository   : ${ECR_REPO}
    Cognito pool     : ${COGNITO_POOL_NAME}
    EC2 instance     : ${EC2_INSTANCE_TYPE}

    Web URL          : ${WEB_URL}
    API URL          : ${API_URL}
PLAN

if [ -n "$DOMAIN" ]; then
  echo "    DNS to create    : ${DOMAIN} CNAME -> CloudFront"
  echo "                       ${API_SUBDOMAIN} CNAME -> EC2/ALB"
fi
echo ""
[ "$DRY_RUN" -eq 1 ] && warn "DRY-RUN mode: nothing will be created"

if [ "$NON_INTERACTIVE" -eq 0 ] && [ "$DRY_RUN" -eq 0 ]; then
  ask "  Proceed with deployment? (yes/no): "
  read -r confirm
  case "$confirm" in
    yes|y|Y|YES) ;;
    *) info "Aborted by user."; exit 0 ;;
  esac
fi

CONFIG_OUT="deploy_${STAGE}.env"
if [ "$DRY_RUN" -eq 0 ]; then
  cat > "$CONFIG_OUT" <<CFG
# MultiOmics-Reactome deployment config, generated $(date -u +%Y-%m-%dT%H:%M:%SZ)
# Re-run: ./scripts/deploy_aws.sh --config ${CONFIG_OUT}
AWS_REGION="${AWS_REGION}"
APP_NAME="${APP_NAME}"
STAGE="${STAGE}"
DOMAIN="${DOMAIN}"
EC2_INSTANCE_TYPE="${EC2_INSTANCE_TYPE}"
ADMIN_EMAIL="${ADMIN_EMAIL}"
CFG
  info "Config saved to ${CONFIG_OUT}"
fi

# =============================================================================
if [ "$DESTROY" -eq 1 ]; then
  step "TEAR DOWN"
  ask "  Type '${STAGE}' to confirm deletion of all resources: "
  read -r conf
  [ "$conf" = "$STAGE" ] || die "Confirmation did not match. Nothing deleted."
  for b in "$S3_DATA_BUCKET" "$S3_WEB_BUCKET"; do
    info "Deleting bucket $b"
    run aws s3 rm "s3://${b}" --recursive --region "$AWS_REGION" 2>/dev/null || true
    run aws s3api delete-bucket --bucket "$b" --region "$AWS_REGION" 2>/dev/null || true
  done
  info "Deleting DynamoDB table"
  run aws dynamodb delete-table --table-name "$DYNAMO_TABLE" --region "$AWS_REGION" 2>/dev/null || true
  QURL=$(aws sqs get-queue-url --queue-name "$SQS_QUEUE" --region "$AWS_REGION" \
         --query QueueUrl --output text 2>/dev/null || echo "")
  if [ -n "$QURL" ]; then
    info "Deleting SQS queue"
    run aws sqs delete-queue --queue-url "$QURL" --region "$AWS_REGION" || true
  fi
  info "Deleting ECR repository"
  run aws ecr delete-repository --repository-name "$ECR_REPO" --force \
      --region "$AWS_REGION" 2>/dev/null || true
  info "Teardown complete. EC2 instances and Cognito pools must be removed manually."
  exit 0
fi

# =============================================================================
step "S3 buckets"

create_bucket() {
  local bucket="$1"
  if aws s3api head-bucket --bucket "$bucket" 2>/dev/null; then
    info "$bucket already exists"; return
  fi
  if [ "$AWS_REGION" = "us-east-1" ]; then
    run aws s3api create-bucket --bucket "$bucket" --region "$AWS_REGION"
  else
    run aws s3api create-bucket --bucket "$bucket" --region "$AWS_REGION" \
        --create-bucket-configuration "LocationConstraint=${AWS_REGION}"
  fi
  info "Created $bucket"
}
create_bucket "$S3_DATA_BUCKET"
create_bucket "$S3_WEB_BUCKET"

info "Enabling encryption and versioning on data bucket"
run aws s3api put-bucket-encryption --bucket "$S3_DATA_BUCKET" --region "$AWS_REGION" \
  --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
run aws s3api put-bucket-versioning --bucket "$S3_DATA_BUCKET" --region "$AWS_REGION" \
  --versioning-configuration Status=Enabled
run aws s3api put-public-access-block --bucket "$S3_DATA_BUCKET" --region "$AWS_REGION" \
  --public-access-block-configuration \
  "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"

CORS_ORIGIN="$WEB_URL"
[ -z "$DOMAIN" ] && CORS_ORIGIN="*"
info "Setting CORS (allowed origin: ${CORS_ORIGIN})"
run aws s3api put-bucket-cors --bucket "$S3_DATA_BUCKET" --region "$AWS_REGION" \
  --cors-configuration "{\"CORSRules\":[{\"AllowedHeaders\":[\"*\"],\"AllowedMethods\":[\"GET\",\"PUT\",\"POST\",\"HEAD\"],\"AllowedOrigins\":[\"${CORS_ORIGIN}\"],\"ExposeHeaders\":[\"ETag\"],\"MaxAgeSeconds\":3000}]}"

# =============================================================================
step "DynamoDB job-state table"

if aws dynamodb describe-table --table-name "$DYNAMO_TABLE" --region "$AWS_REGION" >/dev/null 2>&1; then
  info "$DYNAMO_TABLE already exists"
else
  run aws dynamodb create-table \
    --table-name "$DYNAMO_TABLE" \
    --attribute-definitions AttributeName=job_id,AttributeType=S \
    --key-schema AttributeName=job_id,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST --region "$AWS_REGION"
  if [ "$DRY_RUN" -eq 0 ]; then
    aws dynamodb wait table-exists --table-name "$DYNAMO_TABLE" --region "$AWS_REGION"
  fi
  info "Created $DYNAMO_TABLE"
fi

# =============================================================================
step "SQS FIFO job queue"

SQS_QUEUE_URL=$(aws sqs get-queue-url --queue-name "$SQS_QUEUE" --region "$AWS_REGION" \
                --query QueueUrl --output text 2>/dev/null || echo "")
if [ -n "$SQS_QUEUE_URL" ]; then
  info "$SQS_QUEUE already exists"
else
  run aws sqs create-queue --queue-name "$SQS_QUEUE" --region "$AWS_REGION" \
    --attributes FifoQueue=true,ContentBasedDeduplication=true,VisibilityTimeout=3600
  SQS_QUEUE_URL=$(aws sqs get-queue-url --queue-name "$SQS_QUEUE" --region "$AWS_REGION" \
                  --query QueueUrl --output text 2>/dev/null || echo "pending")
  info "Created $SQS_QUEUE"
fi

# =============================================================================
step "Cognito user pool"

POOL_ID=$(aws cognito-idp list-user-pools --max-results 60 --region "$AWS_REGION" \
  --query "UserPools[?Name=='${COGNITO_POOL_NAME}'].Id | [0]" --output text 2>/dev/null || echo "None")

if [ "$POOL_ID" != "None" ] && [ -n "$POOL_ID" ]; then
  info "Pool exists: $POOL_ID"
elif [ "$DRY_RUN" -eq 0 ]; then
  POOL_ID=$(aws cognito-idp create-user-pool \
    --pool-name "$COGNITO_POOL_NAME" --region "$AWS_REGION" \
    --policies '{"PasswordPolicy":{"MinimumLength":12,"RequireUppercase":true,"RequireLowercase":true,"RequireNumbers":true,"RequireSymbols":true}}' \
    --auto-verified-attributes email --username-attributes email \
    --query 'UserPool.Id' --output text)
  info "Created pool: $POOL_ID"
else
  printf "${B}[DRY-RUN]${N} create Cognito pool %s\n" "$COGNITO_POOL_NAME"
  POOL_ID="dry-run-pool"
fi

CLIENT_ID=$(aws cognito-idp list-user-pool-clients --user-pool-id "$POOL_ID" \
  --region "$AWS_REGION" --query 'UserPoolClients[0].ClientId' --output text 2>/dev/null || echo "None")
if [ "$CLIENT_ID" = "None" ] || [ -z "$CLIENT_ID" ]; then
  if [ "$DRY_RUN" -eq 0 ]; then
    CLIENT_ID=$(aws cognito-idp create-user-pool-client \
      --user-pool-id "$POOL_ID" --client-name "${RESOURCE_PREFIX}-web" \
      --no-generate-secret \
      --explicit-auth-flows ALLOW_USER_SRP_AUTH ALLOW_REFRESH_TOKEN_AUTH \
      --region "$AWS_REGION" --query 'UserPoolClient.ClientId' --output text)
    info "Created app client: $CLIENT_ID"
  else
    CLIENT_ID="dry-run-client"
  fi
else
  info "App client exists: $CLIENT_ID"
fi

if [ -n "$ADMIN_EMAIL" ] && [ "$DRY_RUN" -eq 0 ]; then
  if aws cognito-idp admin-get-user --user-pool-id "$POOL_ID" \
       --username "$ADMIN_EMAIL" --region "$AWS_REGION" >/dev/null 2>&1; then
    info "Admin user $ADMIN_EMAIL already exists"
  else
    aws cognito-idp admin-create-user --user-pool-id "$POOL_ID" \
      --username "$ADMIN_EMAIL" \
      --user-attributes Name=email,Value="$ADMIN_EMAIL" Name=email_verified,Value=true \
      --desired-delivery-mediums EMAIL --region "$AWS_REGION" >/dev/null
    info "Admin user created; temporary password emailed to $ADMIN_EMAIL"
  fi
fi

# =============================================================================
step "ECR repository and container image"

if aws ecr describe-repositories --repository-names "$ECR_REPO" --region "$AWS_REGION" >/dev/null 2>&1; then
  info "$ECR_REPO already exists"
else
  run aws ecr create-repository --repository-name "$ECR_REPO" --region "$AWS_REGION" \
    --image-scanning-configuration scanOnPush=true
  info "Created $ECR_REPO"
fi

if [ "$DRY_RUN" -eq 0 ]; then
  info "Logging Docker in to ECR"
  aws ecr get-login-password --region "$AWS_REGION" \
    | docker login --username AWS --password-stdin \
      "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
  IMAGE_TAG="$(git rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M%S)"
  info "Building image ${ECR_REPO}:${IMAGE_TAG}"
  docker build -f docker/Dockerfile -t "${ECR_URI}:${IMAGE_TAG}" -t "${ECR_URI}:latest" .
  info "Pushing image"
  docker push "${ECR_URI}:${IMAGE_TAG}"
  docker push "${ECR_URI}:latest"
  info "Image pushed: ${ECR_URI}:${IMAGE_TAG}"
else
  printf "${B}[DRY-RUN]${N} docker build + push to %s\n" "$ECR_URI"
  IMAGE_TAG="dry-run"
fi

# =============================================================================
step "Frontend build and upload"

if [ -d frontend ]; then
  if [ "$DRY_RUN" -eq 0 ]; then
    (
      cd frontend
      if [ -f package-lock.json ]; then npm ci --silent; else npm install --silent; fi
      VITE_API_URL="${API_URL}" \
      VITE_COGNITO_POOL_ID="${POOL_ID}" \
      VITE_COGNITO_CLIENT_ID="${CLIENT_ID}" \
      VITE_AWS_REGION="${AWS_REGION}" \
      VITE_S3_DATA_BUCKET="${S3_DATA_BUCKET}" \
        npm run build
    )
    info "Frontend built"
    aws s3 sync frontend/dist/ "s3://${S3_WEB_BUCKET}/" --delete --region "$AWS_REGION" \
      --cache-control "public,max-age=31536000,immutable" --exclude "index.html"
    aws s3 cp frontend/dist/index.html "s3://${S3_WEB_BUCKET}/index.html" \
      --region "$AWS_REGION" --cache-control "no-cache,must-revalidate"
    info "Frontend uploaded to s3://${S3_WEB_BUCKET}/"
  else
    printf "${B}[DRY-RUN]${N} npm build + s3 sync to %s\n" "$S3_WEB_BUCKET"
  fi
else
  warn "frontend/ not found; skipping web build"
fi

# =============================================================================
step "CloudFront distribution"

CF_DOMAIN=""
if [ "$DRY_RUN" -eq 0 ]; then
  CF_ID=$(aws cloudfront list-distributions \
    --query "DistributionList.Items[?Comment=='${RESOURCE_PREFIX}'].Id | [0]" \
    --output text 2>/dev/null || echo "None")
  if [ "$CF_ID" != "None" ] && [ -n "$CF_ID" ]; then
    CF_DOMAIN=$(aws cloudfront get-distribution --id "$CF_ID" \
      --query 'Distribution.DomainName' --output text)
    info "CloudFront exists: $CF_ID ($CF_DOMAIN)"
    info "Invalidating cache"
    aws cloudfront create-invalidation --distribution-id "$CF_ID" --paths "/*" >/dev/null
  else
    warn "No CloudFront distribution with Comment='${RESOURCE_PREFIX}' found."
    warn "Create one with:"
    warn "  Origin  : ${S3_WEB_BUCKET}.s3.${AWS_REGION}.amazonaws.com"
    warn "  Comment : ${RESOURCE_PREFIX}   (so this script finds it next time)"
  fi
else
  printf "${B}[DRY-RUN]${N} create/refresh CloudFront distribution\n"
fi

# =============================================================================
if [ -n "$DOMAIN" ]; then
  step "ACM certificate for ${DOMAIN}"
  CERT_ARN=$(aws acm list-certificates --region us-east-1 \
    --query "CertificateSummaryList[?DomainName=='${DOMAIN}'].CertificateArn | [0]" \
    --output text 2>/dev/null || echo "None")
  if [ "$CERT_ARN" != "None" ] && [ -n "$CERT_ARN" ]; then
    CERT_STATUS=$(aws acm describe-certificate --certificate-arn "$CERT_ARN" \
      --region us-east-1 --query 'Certificate.Status' --output text)
    info "Certificate exists: $CERT_ARN (status: $CERT_STATUS)"
    if [ "$CERT_STATUS" != "ISSUED" ]; then
      warn "Not yet ISSUED. Add these DNS validation records:"
      aws acm describe-certificate --certificate-arn "$CERT_ARN" --region us-east-1 \
        --query 'Certificate.DomainValidationOptions[].ResourceRecord' --output table || true
    fi
  elif [ "$DRY_RUN" -eq 0 ]; then
    CERT_ARN=$(aws acm request-certificate --region us-east-1 \
      --domain-name "$DOMAIN" --subject-alternative-names "*.${DOMAIN}" \
      --validation-method DNS --query CertificateArn --output text)
    info "Certificate requested: $CERT_ARN"
    sleep 5
    warn "Add these DNS validation records at your registrar:"
    aws acm describe-certificate --certificate-arn "$CERT_ARN" --region us-east-1 \
      --query 'Certificate.DomainValidationOptions[].ResourceRecord' --output table || true
  else
    printf "${B}[DRY-RUN]${N} request ACM certificate for %s\n" "$DOMAIN"
  fi
fi

# =============================================================================
step "Deployment summary"

SUMMARY_FILE="deployment_${STAGE}_$(date -u +%Y%m%d_%H%M%S).txt"
{
  echo "MultiOmics-Reactome v3.0 -- Deployment Summary"
  echo "Generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "==========================================================="
  echo ""
  echo "AWS account       : ${AWS_ACCOUNT_ID}"
  echo "Region            : ${AWS_REGION}"
  echo "Stage             : ${STAGE}"
  echo ""
  echo "S3 data bucket    : ${S3_DATA_BUCKET}"
  echo "S3 web bucket     : ${S3_WEB_BUCKET}"
  echo "DynamoDB table    : ${DYNAMO_TABLE}"
  echo "SQS queue URL     : ${SQS_QUEUE_URL}"
  echo "ECR image         : ${ECR_URI}:${IMAGE_TAG}"
  echo "Cognito pool ID   : ${POOL_ID}"
  echo "Cognito client ID : ${CLIENT_ID}"
  [ -n "$CF_DOMAIN" ] && echo "CloudFront domain : ${CF_DOMAIN}"
  echo ""
  if [ -n "$DOMAIN" ]; then
    echo "DNS RECORDS TO CREATE AT YOUR REGISTRAR"
    echo "---------------------------------------"
    if [ -n "$CF_DOMAIN" ]; then
      echo "  ${DOMAIN}         CNAME  ${CF_DOMAIN}"
    else
      echo "  ${DOMAIN}         CNAME  <CloudFront domain once created>"
    fi
    echo "  ${API_SUBDOMAIN}  CNAME  <EC2 public DNS or ALB DNS>"
    echo ""
    echo "Web app : ${WEB_URL}"
    echo "API     : ${API_URL}"
  elif [ -n "$CF_DOMAIN" ]; then
    echo "Web app : https://${CF_DOMAIN}"
  fi
  echo ""
  echo "GITHUB ACTIONS SECRETS"
  echo "----------------------"
  echo "  AWS_REGION           = ${AWS_REGION}"
  echo "  ECR_REPO             = ${ECR_REPO}"
  echo "  S3_DATA_BUCKET       = ${S3_DATA_BUCKET}"
  echo "  S3_WEB_BUCKET        = ${S3_WEB_BUCKET}"
  echo "  COGNITO_USER_POOL_ID = ${POOL_ID}"
  echo "  COGNITO_CLIENT_ID    = ${CLIENT_ID}"
  echo "  VITE_API_URL         = ${API_URL}"
  echo "  plus AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY"
  echo ""
  echo "Re-run  : ./scripts/deploy_aws.sh --config ${CONFIG_OUT}"
  echo "Destroy : ./scripts/deploy_aws.sh --config ${CONFIG_OUT} --destroy"
} | tee "$SUMMARY_FILE"

echo ""
info "Summary written to ${SUMMARY_FILE}"
[ "$DRY_RUN" -eq 1 ] && warn "DRY RUN: no resources were created."
echo ""
