#!/usr/bin/env bash
# =============================================================================
#  deploy.sh  —  Multi-Omics Pipeline  Full Deployment
#  Provisions AWS backend + builds React frontend + deploys to cPanel domain
#
#  Prerequisites
#  -------------
#  - AWS CLI v2  configured (aws configure)
#  - Node.js >= 18  (frontend build)
#  - Python >= 3.11 (local tooling)
#  - Docker         (image build + ECR push)
#  - jq             (JSON parsing)
#  - curl + scp     (cPanel upload)
#  - sshpass        (non-interactive SSH — install: brew/apt install sshpass)
# =============================================================================
set -euo pipefail
IFS=$'\n\t'

# ── colour helpers ─────────────────────────────────────────────────────────────
G='\033[0;32m'; Y='\033[1;33m'; R='\033[0;31m'; C='\033[0;36m'; N='\033[0m'
info()  { echo -e "${G}[INFO]${N}  $*"; }
warn()  { echo -e "${Y}[WARN]${N}  $*"; }
error() { echo -e "${R}[ERROR]${N} $*" >&2; exit 1; }
step()  { echo -e "\n${C}══ $* ${N}"; }

# =============================================================================
# CONFIGURATION  —  edit these before running
# =============================================================================

## AWS
AWS_REGION="eu-west-2"
AWS_ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
APP_NAME="multiomics"
ENV="prod"

## S3
S3_DATA_BUCKET="${APP_NAME}-data-${AWS_ACCOUNT_ID}"
S3_WEB_BUCKET="${APP_NAME}-web-${AWS_ACCOUNT_ID}"

## ECR / Docker
ECR_REPO="${APP_NAME}-pipeline"
IMAGE_TAG="latest"
ECR_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO}"

## EC2
EC2_INSTANCE_TYPE="g4dn.xlarge"
EC2_AMI="ami-0eb260c4d5475b901"    # Deep Learning AMI Ubuntu 22.04 eu-west-2
EC2_KEY_PAIR="${APP_NAME}-key"
EC2_SG_NAME="${APP_NAME}-sg"

## DynamoDB
DYNAMO_TABLE="${APP_NAME}Jobs"

## SQS (FIFO queue)
SQS_QUEUE_NAME="${APP_NAME}-jobs.fifo"

## SageMaker
SM_ROLE_NAME="${APP_NAME}-sagemaker-role"

## Cognito
COGNITO_POOL_NAME="${APP_NAME}-users"

## API Gateway
APIGW_NAME="${APP_NAME}-api"

## Amplify / CloudFront
CF_COMMENT="${APP_NAME}-cdn"

## Lambda authorizer
LAMBDA_AUTHORIZER_NAME="${APP_NAME}-authorizer"
LAMBDA_ROLE_NAME="${APP_NAME}-lambda-role"

## cPanel / domain
CPANEL_HOST="yourdomain.com"         # ← change
CPANEL_USER="cpanelusername"         # ← change
CPANEL_PASS="cpanelpassword"         # ← change (or use SSH key)
CPANEL_SSH_PORT="22"
DOMAIN="yourdomain.com"              # ← change
API_SUBDOMAIN="api.${DOMAIN}"
REMOTE_PUBLIC_HTML="/home/${CPANEL_USER}/public_html"
REMOTE_API_DIR="/home/${CPANEL_USER}/multiomics-api"

# =============================================================================
# STEP 0 — Preflight checks
# =============================================================================
step "Preflight checks"
for cmd in aws docker node npm jq curl scp sshpass; do
  command -v "$cmd" &>/dev/null && info "✓ $cmd" || error "$cmd not found"
done
aws sts get-caller-identity &>/dev/null || error "AWS credentials not configured"
info "AWS account: ${AWS_ACCOUNT_ID}  region: ${AWS_REGION}"

# =============================================================================
# STEP 1 — S3 buckets
# =============================================================================
step "S3 buckets"

create_bucket() {
  local bucket=$1
  if aws s3api head-bucket --bucket "$bucket" 2>/dev/null; then
    warn "Bucket $bucket already exists — skipping"
  else
    if [ "$AWS_REGION" = "us-east-1" ]; then
      aws s3api create-bucket --bucket "$bucket" --region "$AWS_REGION"
    else
      aws s3api create-bucket --bucket "$bucket" --region "$AWS_REGION" \
        --create-bucket-configuration LocationConstraint="$AWS_REGION"
    fi
    info "Created: $bucket"
  fi
}

create_bucket "$S3_DATA_BUCKET"
create_bucket "$S3_WEB_BUCKET"

# Block public access on data bucket
aws s3api put-public-access-block \
  --bucket "$S3_DATA_BUCKET" \
  --public-access-block-configuration \
    "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"

# CORS on data bucket (presigned uploads from browser)
aws s3api put-bucket-cors --bucket "$S3_DATA_BUCKET" --cors-configuration '{
  "CORSRules": [{
    "AllowedHeaders": ["*"],
    "AllowedMethods": ["GET","PUT","POST","DELETE","HEAD"],
    "AllowedOrigins": ["*"],
    "ExposeHeaders":  ["ETag"],
    "MaxAgeSeconds":  3600
  }]
}'

# Versioning on data bucket
aws s3api put-bucket-versioning --bucket "$S3_DATA_BUCKET" \
  --versioning-configuration Status=Enabled

# TTL lifecycle (delete results after 30 days)
aws s3api put-bucket-lifecycle-configuration \
  --bucket "$S3_DATA_BUCKET" \
  --lifecycle-configuration '{
    "Rules": [{
      "ID": "expire-results",
      "Status": "Enabled",
      "Filter": {"Prefix": "results/"},
      "Expiration": {"Days": 30}
    }]
  }'

info "S3 configured."

# =============================================================================
# STEP 2 — DynamoDB
# =============================================================================
step "DynamoDB table"
if aws dynamodb describe-table --table-name "$DYNAMO_TABLE" \
    --region "$AWS_REGION" &>/dev/null; then
  warn "Table $DYNAMO_TABLE already exists"
else
  aws dynamodb create-table \
    --table-name "$DYNAMO_TABLE" \
    --attribute-definitions \
        AttributeName=job_id,AttributeType=S \
        AttributeName=user_id,AttributeType=S \
    --key-schema \
        AttributeName=job_id,KeyType=HASH \
    --global-secondary-indexes '[{
      "IndexName": "user_id-index",
      "KeySchema": [{"AttributeName":"user_id","KeyType":"HASH"}],
      "Projection": {"ProjectionType":"ALL"},
      "ProvisionedThroughput": {"ReadCapacityUnits":5,"WriteCapacityUnits":5}
    }]' \
    --provisioned-throughput ReadCapacityUnits=5,WriteCapacityUnits=5 \
    --region "$AWS_REGION"
  aws dynamodb wait table-exists --table-name "$DYNAMO_TABLE" --region "$AWS_REGION"
  info "DynamoDB table created: $DYNAMO_TABLE"
fi

# TTL on job records
aws dynamodb update-time-to-live \
  --table-name "$DYNAMO_TABLE" \
  --time-to-live-specification "Enabled=true, AttributeName=ttl" \
  --region "$AWS_REGION" 2>/dev/null || true

# =============================================================================
# STEP 3 — SQS FIFO queue
# =============================================================================
step "SQS FIFO queue"
SQS_QUEUE_URL=$(aws sqs get-queue-url \
  --queue-name "$SQS_QUEUE_NAME" \
  --region "$AWS_REGION" \
  --query QueueUrl --output text 2>/dev/null || true)

if [ -z "$SQS_QUEUE_URL" ]; then
  SQS_QUEUE_URL=$(aws sqs create-queue \
    --queue-name "$SQS_QUEUE_NAME" \
    --attributes '{
      "FifoQueue":"true",
      "ContentBasedDeduplication":"true",
      "VisibilityTimeout":"3600",
      "MessageRetentionPeriod":"86400"
    }' \
    --region "$AWS_REGION" \
    --query QueueUrl --output text)
  info "SQS queue created: $SQS_QUEUE_URL"
else
  warn "SQS queue already exists"
fi

# =============================================================================
# STEP 4 — IAM roles
# =============================================================================
step "IAM roles"

# ── EC2 instance role ─────────────────────────────────────────────────────────
EC2_ROLE_NAME="${APP_NAME}-ec2-role"
if ! aws iam get-role --role-name "$EC2_ROLE_NAME" &>/dev/null; then
  aws iam create-role \
    --role-name "$EC2_ROLE_NAME" \
    --assume-role-policy-document '{
      "Version":"2012-10-17",
      "Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},
                    "Action":"sts:AssumeRole"}]}'
  aws iam attach-role-policy --role-name "$EC2_ROLE_NAME" \
    --policy-arn arn:aws:iam::aws:policy/AmazonS3FullAccess
  aws iam attach-role-policy --role-name "$EC2_ROLE_NAME" \
    --policy-arn arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess
  aws iam attach-role-policy --role-name "$EC2_ROLE_NAME" \
    --policy-arn arn:aws:iam::aws:policy/AmazonSQSFullAccess
  aws iam attach-role-policy --role-name "$EC2_ROLE_NAME" \
    --policy-arn arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy
  aws iam create-instance-profile \
    --instance-profile-name "${EC2_ROLE_NAME}-profile" 2>/dev/null || true
  aws iam add-role-to-instance-profile \
    --instance-profile-name "${EC2_ROLE_NAME}-profile" \
    --role-name "$EC2_ROLE_NAME" 2>/dev/null || true
  info "EC2 IAM role created."
fi

# ── SageMaker execution role ──────────────────────────────────────────────────
if ! aws iam get-role --role-name "$SM_ROLE_NAME" &>/dev/null; then
  aws iam create-role \
    --role-name "$SM_ROLE_NAME" \
    --assume-role-policy-document '{
      "Version":"2012-10-17",
      "Statement":[{"Effect":"Allow","Principal":{"Service":"sagemaker.amazonaws.com"},
                    "Action":"sts:AssumeRole"}]}'
  aws iam attach-role-policy --role-name "$SM_ROLE_NAME" \
    --policy-arn arn:aws:iam::aws:policy/AmazonSageMakerFullAccess
  aws iam attach-role-policy --role-name "$SM_ROLE_NAME" \
    --policy-arn arn:aws:iam::aws:policy/AmazonS3FullAccess
  info "SageMaker IAM role created."
fi
SM_ROLE_ARN="arn:aws:iam::${AWS_ACCOUNT_ID}:role/${SM_ROLE_NAME}"

# ── Lambda execution role ─────────────────────────────────────────────────────
if ! aws iam get-role --role-name "$LAMBDA_ROLE_NAME" &>/dev/null; then
  aws iam create-role \
    --role-name "$LAMBDA_ROLE_NAME" \
    --assume-role-policy-document '{
      "Version":"2012-10-17",
      "Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},
                    "Action":"sts:AssumeRole"}]}'
  aws iam attach-role-policy --role-name "$LAMBDA_ROLE_NAME" \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
  info "Lambda IAM role created."
fi
LAMBDA_ROLE_ARN="arn:aws:iam::${AWS_ACCOUNT_ID}:role/${LAMBDA_ROLE_NAME}"

# =============================================================================
# STEP 5 — Cognito user pool
# =============================================================================
step "Cognito user pool"
POOL_ID=$(aws cognito-idp list-user-pools --max-results 20 --region "$AWS_REGION" \
  --query "UserPools[?Name=='${COGNITO_POOL_NAME}'].Id" --output text)

if [ -z "$POOL_ID" ]; then
  POOL_ID=$(aws cognito-idp create-user-pool \
    --pool-name "$COGNITO_POOL_NAME" \
    --policies '{
      "PasswordPolicy":{"MinimumLength":10,"RequireUppercase":true,
                        "RequireLowercase":true,"RequireNumbers":true}
    }' \
    --auto-verified-attributes email \
    --username-attributes email \
    --region "$AWS_REGION" \
    --query UserPool.Id --output text)
  info "User pool created: $POOL_ID"
fi

CLIENT_ID=$(aws cognito-idp list-user-pool-clients \
  --user-pool-id "$POOL_ID" --region "$AWS_REGION" \
  --query "UserPoolClients[?ClientName=='${APP_NAME}-app'].ClientId" --output text)

if [ -z "$CLIENT_ID" ]; then
  CLIENT_ID=$(aws cognito-idp create-user-pool-client \
    --user-pool-id "$POOL_ID" \
    --client-name "${APP_NAME}-app" \
    --explicit-auth-flows ALLOW_USER_PASSWORD_AUTH ALLOW_REFRESH_TOKEN_AUTH \
    --region "$AWS_REGION" \
    --query UserPoolClient.ClientId --output text)
  info "Cognito app client created: $CLIENT_ID"
fi

# =============================================================================
# STEP 6 — ECR + Docker build + push
# =============================================================================
step "ECR repository + Docker image"

aws ecr get-login-password --region "$AWS_REGION" | \
  docker login --username AWS --password-stdin \
  "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

if ! aws ecr describe-repositories --repository-names "$ECR_REPO" \
    --region "$AWS_REGION" &>/dev/null; then
  aws ecr create-repository --repository-name "$ECR_REPO" --region "$AWS_REGION"
  info "ECR repo created: $ECR_REPO"
fi

# Write Dockerfile
cat > Dockerfile <<'DOCKERFILE'
FROM python:3.11-slim

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl build-essential libhdf5-dev && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /opt/multiomics
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY multiomics_reactome.py backend/app.py infra/run_job.py ./
COPY backend/ ./backend/

ENV PYTHONUNBUFFERED=1 MODE=api
EXPOSE 8000

CMD ["python", "app.py"]
DOCKERFILE

# Write run_job.py (SageMaker entrypoint)
mkdir -p infra
cat > infra/run_job.py <<'RUNJOB'
"""SageMaker Processing Job entrypoint."""
import argparse, os, sys
sys.path.insert(0, "/opt/multiomics")

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--job-id");   p.add_argument("--mode", default="synthetic")
    p.add_argument("--n-samples", type=int, default=120)
    p.add_argument("--n-cells",   type=int, default=400)
    p.add_argument("--n-perm",    type=int, default=200)
    a = p.parse_args()
    from multiomics_reactome import run_pipeline, InputConfig
    from pathlib import Path
    import multiomics_reactome as mr
    mr.OUTPUT_DIR = Path("/opt/ml/output")
    mr.OUTPUT_DIR.mkdir(exist_ok=True)
    cfg = InputConfig(mode=a.mode, n_samples=a.n_samples,
                      n_cells=a.n_cells)
    run_pipeline(cfg, n_perm=a.n_perm)

if __name__ == "__main__":
    main()
RUNJOB

docker build -t "${ECR_REPO}:${IMAGE_TAG}" .
docker tag  "${ECR_REPO}:${IMAGE_TAG}" "${ECR_URI}:${IMAGE_TAG}"
docker push "${ECR_URI}:${IMAGE_TAG}"
info "Docker image pushed: ${ECR_URI}:${IMAGE_TAG}"

# =============================================================================
# STEP 7 — EC2 security group + launch
# =============================================================================
step "EC2 security group + instance"

VPC_ID=$(aws ec2 describe-vpcs \
  --filters Name=isDefault,Values=true \
  --query "Vpcs[0].VpcId" --output text --region "$AWS_REGION")

SG_ID=$(aws ec2 describe-security-groups \
  --filters Name=group-name,Values="$EC2_SG_NAME" \
  --query "SecurityGroups[0].GroupId" --output text \
  --region "$AWS_REGION" 2>/dev/null || echo "")

if [ -z "$SG_ID" ] || [ "$SG_ID" = "None" ]; then
  SG_ID=$(aws ec2 create-security-group \
    --group-name "$EC2_SG_NAME" \
    --description "MultiOmics API server" \
    --vpc-id "$VPC_ID" \
    --region "$AWS_REGION" \
    --query GroupId --output text)
  # Allow HTTP/HTTPS and API port from anywhere (restrict in prod)
  for port in 22 80 443 8000; do
    aws ec2 authorize-security-group-ingress \
      --group-id "$SG_ID" \
      --protocol tcp --port "$port" --cidr "0.0.0.0/0" \
      --region "$AWS_REGION" 2>/dev/null || true
  done
  info "Security group created: $SG_ID"
fi

# Key pair
if ! aws ec2 describe-key-pairs --key-names "$EC2_KEY_PAIR" \
    --region "$AWS_REGION" &>/dev/null; then
  aws ec2 create-key-pair \
    --key-name "$EC2_KEY_PAIR" \
    --query KeyMaterial --output text \
    --region "$AWS_REGION" > "${EC2_KEY_PAIR}.pem"
  chmod 400 "${EC2_KEY_PAIR}.pem"
  info "Key pair saved: ${EC2_KEY_PAIR}.pem"
fi

# User-data: pull image and start container
USER_DATA=$(base64 -w0 <<USERDATA
#!/bin/bash
set -e
aws ecr get-login-password --region ${AWS_REGION} | \
  docker login --username AWS --password-stdin \
  ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com
docker pull ${ECR_URI}:${IMAGE_TAG}
docker run -d --restart always \
  -p 8000:8000 \
  -e AWS_REGION=${AWS_REGION} \
  -e S3_DATA_BUCKET=${S3_DATA_BUCKET} \
  -e DYNAMO_TABLE=${DYNAMO_TABLE} \
  -e SQS_QUEUE_URL=${SQS_QUEUE_URL} \
  -e SM_ROLE_ARN=${SM_ROLE_ARN} \
  -e SM_IMAGE_URI=${ECR_URI}:${IMAGE_TAG} \
  -e MODE=api \
  ${ECR_URI}:${IMAGE_TAG}
USERDATA
)

INSTANCE_ID=$(aws ec2 run-instances \
  --image-id "$EC2_AMI" \
  --instance-type "$EC2_INSTANCE_TYPE" \
  --key-name "$EC2_KEY_PAIR" \
  --security-group-ids "$SG_ID" \
  --iam-instance-profile Name="${EC2_ROLE_NAME}-profile" \
  --user-data "$USER_DATA" \
  --count 1 \
  --region "$AWS_REGION" \
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=${APP_NAME}-api}]" \
  --query "Instances[0].InstanceId" --output text)

info "EC2 instance launched: $INSTANCE_ID"
aws ec2 wait instance-running --instance-ids "$INSTANCE_ID" --region "$AWS_REGION"
EC2_PUBLIC_IP=$(aws ec2 describe-instances \
  --instance-ids "$INSTANCE_ID" \
  --query "Reservations[0].Instances[0].PublicIpAddress" \
  --output text --region "$AWS_REGION")
info "EC2 public IP: $EC2_PUBLIC_IP"

# =============================================================================
# STEP 8 — Lambda authorizer
# =============================================================================
step "Lambda authorizer"

# Package
mkdir -p /tmp/lambda_auth
cp infra/lambda_authorizer.py /tmp/lambda_auth/lambda_function.py
pip install python-jose cryptography --target /tmp/lambda_auth/deps -q
cp -r /tmp/lambda_auth/deps/* /tmp/lambda_auth/
cd /tmp/lambda_auth && zip -r /tmp/authorizer.zip . -x "*.pyc" -x "__pycache__/*" > /dev/null
cd - > /dev/null

LAMBDA_ARN=$(aws lambda get-function --function-name "$LAMBDA_AUTHORIZER_NAME" \
  --region "$AWS_REGION" --query Configuration.FunctionArn --output text 2>/dev/null || true)

if [ -z "$LAMBDA_ARN" ]; then
  LAMBDA_ARN=$(aws lambda create-function \
    --function-name "$LAMBDA_AUTHORIZER_NAME" \
    --runtime python3.11 \
    --role "$LAMBDA_ROLE_ARN" \
    --handler lambda_function.handler \
    --zip-file fileb:///tmp/authorizer.zip \
    --timeout 10 \
    --environment "Variables={
      AWS_REGION=${AWS_REGION},
      COGNITO_USER_POOL_ID=${POOL_ID},
      COGNITO_CLIENT_ID=${CLIENT_ID}
    }" \
    --region "$AWS_REGION" \
    --query FunctionArn --output text)
  info "Lambda authorizer created: $LAMBDA_ARN"
else
  aws lambda update-function-code \
    --function-name "$LAMBDA_AUTHORIZER_NAME" \
    --zip-file fileb:///tmp/authorizer.zip \
    --region "$AWS_REGION" > /dev/null
  info "Lambda authorizer updated."
fi

# =============================================================================
# STEP 9 — API Gateway
# =============================================================================
step "API Gateway"

API_ID=$(aws apigateway get-rest-apis \
  --query "items[?name=='${APIGW_NAME}'].id" \
  --output text --region "$AWS_REGION")

if [ -z "$API_ID" ]; then
  API_ID=$(aws apigateway create-rest-api \
    --name "$APIGW_NAME" \
    --endpoint-configuration types=REGIONAL \
    --region "$AWS_REGION" \
    --query id --output text)
  info "API Gateway created: $API_ID"

  ROOT_ID=$(aws apigateway get-resources \
    --rest-api-id "$API_ID" \
    --query "items[?path=='/'].id" \
    --output text --region "$AWS_REGION")

  # Create proxy resource /{proxy+} → EC2
  PROXY_ID=$(aws apigateway create-resource \
    --rest-api-id "$API_ID" \
    --parent-id "$ROOT_ID" \
    --path-part "{proxy+}" \
    --region "$AWS_REGION" \
    --query id --output text)

  aws apigateway put-method \
    --rest-api-id "$API_ID" --resource-id "$PROXY_ID" \
    --http-method ANY --authorization-type CUSTOM \
    --authorizer-id "$(aws apigateway create-authorizer \
        --rest-api-id "$API_ID" \
        --name jwt-authorizer \
        --type TOKEN \
        --authorizer-uri "arn:aws:apigateway:${AWS_REGION}:lambda:path/2015-03-31/functions/${LAMBDA_ARN}/invocations" \
        --identity-source 'method.request.header.Authorization' \
        --authorizer-result-ttl-in-seconds 300 \
        --region "$AWS_REGION" \
        --query id --output text)" \
    --region "$AWS_REGION"

  aws apigateway put-integration \
    --rest-api-id "$API_ID" --resource-id "$PROXY_ID" \
    --http-method ANY --type HTTP_PROXY \
    --integration-http-method ANY \
    --uri "http://${EC2_PUBLIC_IP}:8000/{proxy}" \
    --region "$AWS_REGION"

  aws apigateway create-deployment \
    --rest-api-id "$API_ID" \
    --stage-name "$ENV" \
    --region "$AWS_REGION" > /dev/null
fi

API_URL="https://${API_ID}.execute-api.${AWS_REGION}.amazonaws.com/${ENV}"
info "API Gateway URL: $API_URL"

# =============================================================================
# STEP 10 — CloudFront distribution (for static site)
# =============================================================================
step "CloudFront distribution"

CF_ID=$(aws cloudfront list-distributions \
  --query "DistributionList.Items[?Comment=='${CF_COMMENT}'].Id" \
  --output text 2>/dev/null || true)

if [ -z "$CF_ID" ]; then
  CF_ID=$(aws cloudfront create-distribution \
    --distribution-config "{
      \"Comment\": \"${CF_COMMENT}\",
      \"DefaultCacheBehavior\": {
        \"TargetOriginId\": \"S3Origin\",
        \"ViewerProtocolPolicy\": \"redirect-to-https\",
        \"AllowedMethods\": {
          \"Quantity\": 2, \"Items\": [\"GET\",\"HEAD\"],
          \"CachedMethods\": {\"Quantity\": 2, \"Items\": [\"GET\",\"HEAD\"]}
        },
        \"ForwardedValues\": {
          \"QueryString\": false,
          \"Cookies\": {\"Forward\": \"none\"}
        },
        \"MinTTL\": 0
      },
      \"Origins\": {
        \"Quantity\": 1,
        \"Items\": [{
          \"Id\": \"S3Origin\",
          \"DomainName\": \"${S3_WEB_BUCKET}.s3.${AWS_REGION}.amazonaws.com\",
          \"S3OriginConfig\": {\"OriginAccessIdentity\": \"\"}
        }]
      },
      \"DefaultRootObject\": \"index.html\",
      \"Enabled\": true,
      \"CallerReference\": \"${APP_NAME}-$(date +%s)\",
      \"PriceClass\": \"PriceClass_100\",
      \"CustomErrorResponses\": {
        \"Quantity\": 1,
        \"Items\": [{
          \"ErrorCode\": 404,
          \"ResponsePagePath\": \"/index.html\",
          \"ResponseCode\": \"200\",
          \"ErrorCachingMinTTL\": 0
        }]
      }
    }" \
    --query Distribution.Id --output text)
  info "CloudFront distribution created: $CF_ID"
fi

CF_DOMAIN=$(aws cloudfront get-distribution \
  --id "$CF_ID" \
  --query Distribution.DomainName --output text)
info "CloudFront domain: $CF_DOMAIN"

# =============================================================================
# STEP 11 — Build React frontend
# =============================================================================
step "React frontend build"
cd frontend

# Write aws-exports.js
cat > src/aws-exports.js <<AWSEXPORTS
const awsconfig = {
  aws_project_region:               "${AWS_REGION}",
  aws_cognito_region:               "${AWS_REGION}",
  aws_user_pools_id:                "${POOL_ID}",
  aws_user_pools_web_client_id:     "${CLIENT_ID}",
  oauth: {},
};
export default awsconfig;
AWSEXPORTS

# Write .env
cat > .env <<ENVFILE
VITE_API_URL=${API_URL}
VITE_S3_BUCKET=${S3_DATA_BUCKET}
VITE_REGION=${AWS_REGION}
ENVFILE

npm ci --silent
npm run build
info "React build complete."
cd ..

# =============================================================================
# STEP 12 — Upload frontend to S3 (AWS CloudFront path)
# =============================================================================
step "Upload React build to S3"
aws s3 sync frontend/dist/ "s3://${S3_WEB_BUCKET}/" \
  --delete \
  --cache-control "public,max-age=31536000,immutable" \
  --region "$AWS_REGION"
# index.html: no-cache so new deployments are picked up immediately
aws s3 cp frontend/dist/index.html "s3://${S3_WEB_BUCKET}/index.html" \
  --cache-control "no-cache,no-store,must-revalidate" \
  --region "$AWS_REGION"
# Invalidate CloudFront cache
aws cloudfront create-invalidation \
  --distribution-id "$CF_ID" \
  --paths "/*" > /dev/null
info "Frontend deployed to S3 + CloudFront."

# =============================================================================
# STEP 13 — Deploy to cPanel external domain
# =============================================================================
step "cPanel / external domain deployment"

# ── 13a. Upload React build to cPanel public_html ────────────────────────────
info "Uploading React build to ${CPANEL_HOST}:${REMOTE_PUBLIC_HTML} …"
sshpass -p "$CPANEL_PASS" ssh -o StrictHostKeyChecking=no \
  -p "$CPANEL_SSH_PORT" "${CPANEL_USER}@${CPANEL_HOST}" \
  "rm -rf ${REMOTE_PUBLIC_HTML}/* && mkdir -p ${REMOTE_PUBLIC_HTML}"

sshpass -p "$CPANEL_PASS" scp -o StrictHostKeyChecking=no \
  -P "$CPANEL_SSH_PORT" -r \
  frontend/dist/* \
  "${CPANEL_USER}@${CPANEL_HOST}:${REMOTE_PUBLIC_HTML}/"

# ── 13b. Write .htaccess for React Router (SPA fallback) ─────────────────────
sshpass -p "$CPANEL_PASS" ssh -o StrictHostKeyChecking=no \
  -p "$CPANEL_SSH_PORT" "${CPANEL_USER}@${CPANEL_HOST}" \
  "cat > ${REMOTE_PUBLIC_HTML}/.htaccess <<'HTACCESS'
Options -MultiViews
RewriteEngine On
RewriteCond %{REQUEST_FILENAME} !-f
RewriteRule ^ index.html [QSA,L]

# Security headers
Header always set X-Content-Type-Options nosniff
Header always set X-Frame-Options SAMEORIGIN
Header always set X-XSS-Protection \"1; mode=block\"
Header always set Referrer-Policy strict-origin-when-cross-origin
Header always set Content-Security-Policy \"default-src 'self' https: data: 'unsafe-inline' 'unsafe-eval'\"

# Cache static assets
<FilesMatch \"\.(js|css|png|jpg|svg|woff2|ico)\$\">
  Header set Cache-Control \"public, max-age=31536000, immutable\"
</FilesMatch>
<FilesMatch \"index\\.html\$\">
  Header set Cache-Control \"no-cache, no-store, must-revalidate\"
</FilesMatch>
HTACCESS"
info "React app deployed to ${DOMAIN}"

# ── 13c. Deploy FastAPI backend as a reverse-proxied Node/Python app ──────────
info "Deploying API proxy config to cPanel …"
sshpass -p "$CPANEL_PASS" ssh -o StrictHostKeyChecking=no \
  -p "$CPANEL_SSH_PORT" "${CPANEL_USER}@${CPANEL_HOST}" \
  "mkdir -p ${REMOTE_API_DIR}"

# Write a lightweight reverse-proxy .htaccess for the api subdomain
# (cPanel subdomain document root → /home/user/public_html/api)
sshpass -p "$CPANEL_PASS" ssh -o StrictHostKeyChecking=no \
  -p "$CPANEL_SSH_PORT" "${CPANEL_USER}@${CPANEL_HOST}" \
  "cat > ${REMOTE_API_DIR}/.htaccess <<APIHTACCESS
RewriteEngine On
RewriteRule ^(.*)$ http://${EC2_PUBLIC_IP}:8000/\$1 [P,L]
ProxyPassReverse / http://${EC2_PUBLIC_IP}:8000/
Header always set Access-Control-Allow-Origin \"https://${DOMAIN}\"
Header always set Access-Control-Allow-Methods \"GET,POST,DELETE,OPTIONS\"
Header always set Access-Control-Allow-Headers \"Authorization,Content-Type\"
APIHTACCESS"

# ── 13d. Write environment info file ─────────────────────────────────────────
cat > deployment_info.txt <<DEPLOY
=== MultiOmics Deployment Info ===
Date:             $(date)
AWS Account:      ${AWS_ACCOUNT_ID}
Region:           ${AWS_REGION}
S3 Data:          s3://${S3_DATA_BUCKET}
S3 Web:           s3://${S3_WEB_BUCKET}
DynamoDB:         ${DYNAMO_TABLE}
SQS:              ${SQS_QUEUE_URL}
ECR Image:        ${ECR_URI}:${IMAGE_TAG}
EC2 Instance:     ${INSTANCE_ID}  (${EC2_PUBLIC_IP})
API Gateway:      ${API_URL}
CloudFront:       https://${CF_DOMAIN}
Cognito Pool:     ${POOL_ID}
Cognito Client:   ${CLIENT_ID}
Domain (cPanel):  https://${DOMAIN}
API Subdomain:    https://${API_SUBDOMAIN}
DEPLOY
cat deployment_info.txt

# =============================================================================
# DONE
# =============================================================================
echo ""
echo -e "${G}════════════════════════════════════════════════════════════════${N}"
echo -e "${G}  Deployment complete!${N}"
echo -e "${G}════════════════════════════════════════════════════════════════${N}"
echo ""
echo "  Frontend (CloudFront): https://${CF_DOMAIN}"
echo "  Frontend (cPanel):     https://${DOMAIN}"
echo "  API Gateway:           ${API_URL}"
echo "  API (cPanel proxy):    https://${API_SUBDOMAIN}"
echo ""
echo "  Next steps:"
echo "  1. Point your domain A-record to EC2 IP: ${EC2_PUBLIC_IP}"
echo "  2. Add SSL cert in cPanel (Let's Encrypt / AutoSSL)"
echo "  3. Set API subdomain document root to: ${REMOTE_API_DIR}"
echo "  4. Update Cognito callback URL to: https://${DOMAIN}"
echo "  5. Review deployment_info.txt for all resource IDs"
echo ""
