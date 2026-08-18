# Deployment Guide — MultiOmics-Reactome v3.0

Covers AWS cloud deployment, custom domain setup, TLS, CI/CD, and costs.

---

## Contents

- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Interactive deployment](#interactive-deployment)
- [Custom domain and TLS](#custom-domain-and-tls)
- [CI/CD with GitHub Actions](#cicd-with-github-actions)
- [Local development stack](#local-development-stack)
- [Cost estimates](#cost-estimates)
- [Monitoring and logs](#monitoring-and-logs)
- [Teardown](#teardown)
- [Troubleshooting](#troubleshooting)

---

## Architecture

```
                          ┌─────────────┐
    Browser ───HTTPS────▶ │ CloudFront  │  TLS via ACM
                          │  (CDN)      │
                          └──────┬──────┘
                                 │ origin
                          ┌──────▼──────┐
                          │  S3 (web)   │  React SPA, immutable assets
                          └─────────────┘

    Browser ───HTTPS────▶ ┌─────────────┐
                          │ API Gateway │  JWT verified by Lambda authorizer
                          └──────┬──────┘
                                 │
                          ┌──────▼──────┐
                          │  FastAPI    │  EC2 or ECS Fargate
                          │  (Docker)   │  image from ECR
                          └──┬───────┬──┘
                             │       │
                  ┌──────────▼─┐  ┌──▼──────────┐
                  │  DynamoDB  │  │  SQS FIFO   │
                  │ job state  │  │  job queue  │
                  └────────────┘  └──┬──────────┘
                                     │ poll
                              ┌──────▼──────────┐
                              │  Worker (EC2)   │
                              │  runs pipeline  │
                              └──────┬──────────┘
                                     │
                              ┌──────▼──────────┐
                              │  S3 (data)      │  inputs + results
                              │  AES256, versioned │  + mimodh_record.xml
                              └─────────────────┘

    Auth: Cognito user pool ──▶ JWT ──▶ Lambda authorizer ──▶ API Gateway
```

**Resources created**

| Service | Resource | Purpose |
|---|---|---|
| S3 | `<app>-<stage>-data-<account>` | Input files, results, MIMODH XML. Encrypted, versioned, private. |
| S3 | `<app>-<stage>-web-<account>` | React SPA static assets |
| DynamoDB | `<app>-<stage>-jobs` | Job state (PAY_PER_REQUEST) |
| SQS | `<app>-<stage>-jobs.fifo` | Job queue, 1 h visibility timeout |
| Cognito | `<app>-<stage>-users` | Auth, 12-char password policy |
| ECR | `<app>-<stage>-pipeline` | Container image, scan-on-push |
| CloudFront | distribution | CDN + TLS termination |
| ACM | certificate (us-east-1) | TLS for your domain |

---

## Prerequisites

| Tool | Version | Install |
|---|---|---|
| aws-cli | v2 | [docs](https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html) |
| docker | 20+ | [docs](https://docs.docker.com/get-docker) |
| node | 20+ | [nodejs.org](https://nodejs.org) |
| jq | any | `apt install jq` / `brew install jq` (optional) |

```bash
aws configure                    # set key, secret, region
aws sts get-caller-identity      # verify — should print your account
```

**IAM permissions needed:** `s3:*`, `dynamodb:*`, `sqs:*`, `cognito-idp:*`,
`ecr:*`, `cloudfront:*`, `acm:*`, `iam:PassRole`, `ec2:*` on the resources
above. `AdministratorAccess` works for a first deployment; scope it down after.

---

## Interactive deployment

```bash
./scripts/deploy_aws.sh --dry-run   # preview, changes nothing
./scripts/deploy_aws.sh             # deploy
```

Prompts:

| Prompt | Default | Notes |
|---|---|---|
| AWS region | your CLI region | e.g. `eu-west-2` |
| Application name | `multiomics` | prefixes all resource names |
| Stage | `prod` | `prod` / `staging` / `dev` |
| **Your domain** | *(blank)* | blank = use the CloudFront URL |
| EC2 instance type | `t3.large` | `g4dn.xlarge` for GPU NMF |
| Admin email | *(blank)* | creates first Cognito user, emails a temp password |

Answers are written to `deploy_<stage>.env`:

```bash
./scripts/deploy_aws.sh --config deploy_prod.env    # reproducible re-run
./scripts/deploy_aws.sh --config deploy_prod.env -y # no prompts at all
```

The script is **idempotent** — safe to re-run. It skips resources that already
exist and only updates what changed. Each run writes
`deployment_<stage>_<timestamp>.txt` with all resource IDs and the DNS records
you need to create.

**Windows:** run it from WSL2 or Git Bash:
```bash
wsl bash scripts/deploy_aws.sh
# or
& "C:\Program Files\Git\bin\bash.exe" scripts/deploy_aws.sh
```

---

## Custom domain and TLS

### 1. Provide your domain during deployment

When prompted, enter your domain (e.g. `mimodh.example.org`). The script then:

- requests an ACM certificate in **us-east-1** (required by CloudFront) for
  `example.org` and `*.example.org`
- prints the DNS validation records you must create
- configures the S3 CORS policy to allow only `https://<your-domain>`
- builds the frontend with `VITE_API_URL=https://api.<your-domain>`

### 2. Create the DNS validation records

The script prints a table like:

```
| Name                              | Type  | Value                              |
|-----------------------------------|-------|------------------------------------|
| _abc123.example.org               | CNAME | _xyz789.acm-validations.aws        |
```

Add that CNAME at your registrar. ACM validates within minutes to a few hours.
Check status:

```bash
aws acm describe-certificate --region us-east-1 \
  --certificate-arn <ARN> --query 'Certificate.Status'
# ISSUED = ready
```

### 3. Create the application DNS records

| Record | Type | Value |
|---|---|---|
| `example.org` | CNAME (or ALIAS) | `d1234abcd.cloudfront.net` |
| `api.example.org` | CNAME | `ec2-1-2-3-4.compute.amazonaws.com` |

**Route 53** — use an **A record with Alias** targeting the CloudFront
distribution (free, faster than CNAME, works at the zone apex).

**Other registrars** (Cloudflare, GoDaddy, Namecheap) — use CNAME. Note that
CNAME at a zone apex is not valid DNS; either use a registrar that supports
`ALIAS`/`ANAME` flattening, or serve the app from `www.example.org`.

### 4. Attach the certificate to CloudFront

Once ACM shows `ISSUED`:

1. CloudFront console → your distribution → **Settings** → **Edit**
2. **Alternate domain names (CNAMEs)**: `example.org`
3. **Custom SSL certificate**: select your ACM certificate
4. Save and wait for the distribution to redeploy (~5–15 min)

Re-run `./scripts/deploy_aws.sh --config deploy_prod.env` afterwards so the
frontend is rebuilt with the final URLs and the CloudFront cache is invalidated.

### 5. Verify

```bash
curl -I https://example.org                 # 200, CloudFront headers
curl    https://api.example.org/health      # {"status":"ok","version":"3.0.0"}
openssl s_client -connect example.org:443 -servername example.org </dev/null \
  2>/dev/null | openssl x509 -noout -dates  # certificate validity
```

---

## CI/CD with GitHub Actions

### Required secrets

Add at `https://github.com/<user>/<repo>/settings/secrets/actions`, or run:

```bash
./scripts/push_to_github.sh --secrets        # Linux/macOS
.\scripts\push_to_github.ps1 -Secrets        # Windows
```

| Secret | Where to find it |
|---|---|
| `AWS_ACCESS_KEY_ID` | IAM user for CI |
| `AWS_SECRET_ACCESS_KEY` | IAM user for CI |
| `AWS_REGION` | deployment summary |
| `ECR_REPO` | deployment summary |
| `S3_DATA_BUCKET` | deployment summary |
| `S3_WEB_BUCKET` | deployment summary |
| `COGNITO_USER_POOL_ID` | deployment summary |
| `COGNITO_CLIENT_ID` | deployment summary |
| `VITE_API_URL` | `https://api.<your-domain>` |
| `CODECOV_TOKEN` | app.codecov.io (optional) |

All values are printed in `deployment_<stage>_<timestamp>.txt`.

### Workflows

**`ci.yml`** — on push to `main`/`dev`/`staging` and on PRs to `main`:
lint → syntax → tests (3.10, 3.11) → test-data validation → MIMODH XSD →
desktop import → frontend build → docker build.

**`deploy.yml`** — on push to `main`, or manual dispatch:
builds and pushes the Docker image to ECR, builds the frontend, syncs to S3.

Manual deploy to staging:
```bash
gh workflow run deploy.yml -f environment=staging
```

---

## Local development stack

No AWS account required — LocalStack emulates S3, SQS and DynamoDB.

```bash
docker compose up --build
```

| Service | URL |
|---|---|
| FastAPI (Swagger) | http://localhost:8000/docs |
| Frontend (Vite dev) | http://localhost:5173 |
| LocalStack | http://localhost:4566 |

```bash
docker compose logs -f api      # follow API logs
docker compose down -v          # stop and remove volumes
```

---

## Cost estimates

Light usage — 10 jobs/day, 100 GB stored, `eu-west-2`, on-demand:

| Service | Monthly (USD) |
|---|---|
| EC2 `t3.large` (API, 24/7) | ~$60 |
| EC2 `t3.large` (worker, ~4 h/day) | ~$10 |
| S3 (100 GB + requests) | ~$3 |
| DynamoDB (PAY_PER_REQUEST) | <$1 |
| SQS | <$1 |
| CloudFront (50 GB egress) | ~$5 |
| Cognito (<50 k MAU) | Free |
| ECR (5 GB) | ~$0.50 |
| **Total** | **≈ $80/month** |

**Reducing cost**

- ECS Fargate Spot for the worker — up to 70% cheaper
- Stop the worker when idle; SQS holds jobs for up to 14 days
- S3 lifecycle rule: transition results to Glacier after 90 days
- Reserved Instances or Savings Plans — up to 60% off EC2

**GPU option:** `g4dn.xlarge` is ~$390/month if run 24/7. Use it only for the
worker, started on demand, or keep the CPU NMF fallback.

---

## Monitoring and logs

```bash
# Container logs
aws logs tail /aws/ecs/multiomics-prod --follow --region eu-west-2

# Job queue depth
aws sqs get-queue-attributes --queue-url <URL> \
  --attribute-names ApproximateNumberOfMessages --region eu-west-2

# Recent job states
aws dynamodb scan --table-name multiomics-prod-jobs \
  --max-items 20 --region eu-west-2

# API health
curl https://api.example.org/health
```

**Suggested CloudWatch alarms**

| Metric | Threshold |
|---|---|
| SQS `ApproximateAgeOfOldestMessage` | > 3600 s (worker stalled) |
| EC2 `CPUUtilization` | > 90% for 15 min |
| API Gateway `5XXError` | > 1% of requests |
| DynamoDB `ThrottledRequests` | > 0 |

---

## Teardown

```bash
./scripts/deploy_aws.sh --config deploy_prod.env --destroy
```

You must type the stage name to confirm. This deletes S3 buckets (including all
objects), the DynamoDB table, SQS queue, and ECR repository.

**Not deleted automatically** (to protect against accidents):

- EC2 instances — terminate in the console
- Cognito user pool — deleting it removes all user accounts
- CloudFront distribution — must be disabled first, then deleted
- ACM certificate — free to keep

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `credentials not configured` | No AWS profile | `aws configure` |
| `BucketAlreadyExists` | Name taken globally | Use a different `APP_NAME` |
| Certificate stuck `PENDING_VALIDATION` | DNS record missing/wrong | Re-check the CNAME; allow up to 1 h |
| CloudFront 403 on refresh | SPA routing | Add a custom error response: 403 → `/index.html` (200) |
| CORS error in browser | Origin mismatch | Re-run deploy so the S3 CORS rule matches your domain |
| `docker push` denied | ECR login expired | `aws ecr get-login-password ... \| docker login ...` |
| Worker not picking up jobs | Queue URL mismatch | Check `SQS_QUEUE_URL` in the worker environment |
| 502 from API Gateway | Container not running | `docker compose logs api` / check ECS task status |

---

## Security checklist

- [ ] Data bucket has public access **blocked** (the script enforces this)
- [ ] Data bucket encryption **AES256** and versioning **enabled**
- [ ] CORS allows only your domain, not `*`
- [ ] Cognito password policy ≥ 12 chars with symbols
- [ ] CI IAM user scoped to the specific resources, not `AdministratorAccess`
- [ ] `deploy_*.env` and `*.pem` are in `.gitignore` (they are by default)
- [ ] Rotate the CI access keys every 90 days
- [ ] CloudTrail enabled in the deployment region
