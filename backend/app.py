"""
Multi-Omics Pipeline  —  FastAPI Backend
=========================================
Runs on EC2 (g4dn.xlarge) behind API Gateway.
Also packaged as a SageMaker Processing container for large batch jobs.

Endpoints
---------
  POST   /upload          Presigned S3 upload URL for omics files
  POST   /jobs            Submit a pipeline job (writes to DynamoDB + SQS)
  GET    /jobs/{job_id}   Poll job status from DynamoDB
  GET    /results/{job_id} Presigned S3 download URLs for outputs
  DELETE /jobs/{job_id}   Cancel / clean up a job
  GET    /health          ALB / API-GW health check

SQS worker (run_worker) is also in this file and started as a background
thread when MODE=worker.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import boto3
import botocore
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import uvicorn

log = logging.getLogger("multiomics.api")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")

# ── AWS config from environment (set by EC2 IAM role / ECS task role) ────────
AWS_REGION      = os.environ.get("AWS_REGION", "eu-west-2")
S3_DATA_BUCKET  = os.environ.get("S3_DATA_BUCKET", "multiomics-data")
S3_WEB_BUCKET   = os.environ.get("S3_WEB_BUCKET",  "multiomics-web")
DYNAMO_TABLE    = os.environ.get("DYNAMO_TABLE",    "MultiOmicsJobs")
SQS_QUEUE_URL   = os.environ.get("SQS_QUEUE_URL",  "")
SM_ROLE_ARN     = os.environ.get("SM_ROLE_ARN",     "")
SM_IMAGE_URI    = os.environ.get("SM_IMAGE_URI",    "")
ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "*").split(",")
MODE            = os.environ.get("MODE", "api")   # "api" | "worker"

# ── boto3 clients ─────────────────────────────────────────────────────────────
session  = boto3.Session(region_name=AWS_REGION)
s3       = session.client("s3")
dynamo   = session.resource("dynamodb").Table(DYNAMO_TABLE)
sqs      = session.client("sqs")
sm_client= session.client("sagemaker")

app = FastAPI(title="MultiOmics API", version="3.0.0", docs_url="/docs")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ══════════════════════════════════════════════════════════════════════════════
# MODELS
# ══════════════════════════════════════════════════════════════════════════════

class JobConfig(BaseModel):
    mode:            str   = Field("synthetic", description="synthetic|real|mixed")
    n_samples:       int   = Field(120,  ge=10,  le=50000)
    n_cells:         int   = Field(400,  ge=50,  le=200000)
    n_batches:       int   = Field(3,    ge=2,   le=20)
    n_perm:          int   = Field(200,  ge=50,  le=2000)
    use_sagemaker:   bool  = Field(False, description="Route large jobs to SageMaker")
    # S3 keys for uploaded input files (populated after /upload)
    s3_keys: Dict[str, str] = Field(default_factory=dict,
        description="modality → s3_key, e.g. {'transcriptomics':'uid/tx.csv'}")

class UploadRequest(BaseModel):
    user_id:  str
    modality: str   # transcriptomics | proteomics | metabolomics | ...
    filename: str
    content_type: str = "text/csv"

# ══════════════════════════════════════════════════════════════════════════════
# AUTH — lightweight Cognito JWT check via Authorization header
# ══════════════════════════════════════════════════════════════════════════════

def _get_user_id(authorization: Optional[str] = Header(None)) -> str:
    """
    In production API Gateway validates the Cognito JWT before the request
    reaches EC2. Here we extract the sub claim from the forwarded header
    x-amzn-oidc-identity or fall back to a mock for local dev.
    """
    if not authorization:
        return "dev-user"
    # API Gateway passes the decoded claim as x-amzn-oidc-data (base64 JSON)
    # For simplicity we trust the sub passed by API GW Lambda authorizer
    return authorization.split(":")[-1] if ":" in authorization else "anonymous"


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _dynamo_put(item: Dict):
    dynamo.put_item(Item=item)

def _dynamo_update(job_id: str, updates: Dict):
    expr    = "SET " + ", ".join(f"#{k} = :{k}" for k in updates)
    names   = {f"#{k}": k for k in updates}
    values  = {f":{k}": v for k, v in updates.items()}
    dynamo.update_item(
        Key={"job_id": job_id},
        UpdateExpression=expr,
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
    )

def _dynamo_get(job_id: str) -> Optional[Dict]:
    resp = dynamo.get_item(Key={"job_id": job_id})
    return resp.get("Item")

def _presign_upload(bucket: str, key: str, content_type: str,
                    expires: int = 900) -> str:
    return s3.generate_presigned_url(
        "put_object",
        Params={"Bucket": bucket, "Key": key, "ContentType": content_type},
        ExpiresIn=expires,
    )

def _presign_download(bucket: str, key: str, expires: int = 3600) -> str:
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=expires,
    )

def _list_result_keys(job_id: str) -> List[str]:
    paginator = s3.get_paginator("list_objects_v2")
    keys = []
    for page in paginator.paginate(Bucket=S3_DATA_BUCKET,
                                   Prefix=f"results/{job_id}/"):
        for obj in page.get("Contents", []):
            keys.append(obj["Key"])
    return keys


# ══════════════════════════════════════════════════════════════════════════════
# ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/health")
def health():
    return {"status": "ok", "ts": datetime.now(timezone.utc).isoformat()}


@app.post("/upload")
def request_upload(req: UploadRequest, user_id: str = Depends(_get_user_id)):
    """Return a presigned PUT URL so the browser uploads directly to S3."""
    key = f"uploads/{req.user_id}/{req.modality}/{req.filename}"
    url = _presign_upload(S3_DATA_BUCKET, key, req.content_type)
    return {"upload_url": url, "s3_key": key}


@app.post("/jobs", status_code=202)
def submit_job(cfg: JobConfig, user_id: str = Depends(_get_user_id)):
    """Enqueue a pipeline job."""
    job_id    = str(uuid.uuid4())
    submitted = datetime.now(timezone.utc).isoformat()

    item = {
        "job_id":      job_id,
        "user_id":     user_id,
        "status":      "QUEUED",
        "config":      json.dumps(cfg.dict()),
        "submitted_at": submitted,
        "updated_at":  submitted,
    }
    _dynamo_put(item)

    if cfg.use_sagemaker and SM_ROLE_ARN:
        _launch_sagemaker_job(job_id, cfg)
        _dynamo_update(job_id, {"status": "SAGEMAKER_SUBMITTED"})
    else:
        sqs.send_message(
            QueueUrl=SQS_QUEUE_URL,
            MessageBody=json.dumps({"job_id": job_id, "config": cfg.dict()}),
            MessageGroupId=user_id,
        )

    log.info(f"Job {job_id} queued for user {user_id}")
    return {"job_id": job_id, "status": "QUEUED"}


@app.get("/jobs/{job_id}")
def get_job(job_id: str, user_id: str = Depends(_get_user_id)):
    item = _dynamo_get(job_id)
    if not item:
        raise HTTPException(404, "Job not found")
    return {
        "job_id":      item["job_id"],
        "status":      item["status"],
        "submitted_at": item.get("submitted_at"),
        "updated_at":  item.get("updated_at"),
        "error":       item.get("error"),
        "progress":    item.get("progress", 0),
    }


@app.get("/results/{job_id}")
def get_results(job_id: str, user_id: str = Depends(_get_user_id)):
    item = _dynamo_get(job_id)
    if not item:
        raise HTTPException(404, "Job not found")
    if item["status"] != "COMPLETED":
        raise HTTPException(409, f"Job status: {item['status']}")

    keys = _list_result_keys(job_id)
    urls = {
        Path(k).name: _presign_download(S3_DATA_BUCKET, k)
        for k in keys
    }
    return {"job_id": job_id, "files": urls}


@app.delete("/jobs/{job_id}", status_code=204)
def cancel_job(job_id: str, user_id: str = Depends(_get_user_id)):
    _dynamo_update(job_id, {"status": "CANCELLED",
                             "updated_at": datetime.now(timezone.utc).isoformat()})


# ══════════════════════════════════════════════════════════════════════════════
# SAGEMAKER JOB LAUNCHER
# ══════════════════════════════════════════════════════════════════════════════

def _launch_sagemaker_job(job_id: str, cfg: JobConfig):
    """Submit a SageMaker Processing Job using the pipeline Docker image."""
    sm_client.create_processing_job(
        ProcessingJobName=f"multiomics-{job_id[:8]}",
        ProcessingResources={
            "ClusterConfig": {
                "InstanceCount": 1,
                "InstanceType": "ml.g4dn.xlarge",
                "VolumeSizeInGB": 100,
            }
        },
        AppSpecification={
            "ImageUri": SM_IMAGE_URI,
            "ContainerEntrypoint": ["python", "/opt/ml/code/run_job.py"],
            "ContainerArguments": [
                "--job-id",   job_id,
                "--mode",     cfg.mode,
                "--n-samples", str(cfg.n_samples),
                "--n-cells",   str(cfg.n_cells),
                "--n-perm",    str(cfg.n_perm),
            ],
        },
        ProcessingInputs=[{
            "InputName": "config",
            "S3Input": {
                "S3Uri":       f"s3://{S3_DATA_BUCKET}/uploads/",
                "LocalPath":   "/opt/ml/input/",
                "S3DataType":  "S3Prefix",
                "S3InputMode": "File",
            },
        }],
        ProcessingOutputConfig={
            "Outputs": [{
                "OutputName": "results",
                "S3Output": {
                    "S3Uri":        f"s3://{S3_DATA_BUCKET}/results/{job_id}/",
                    "LocalPath":    "/opt/ml/output/",
                    "S3UploadMode": "EndOfJob",
                },
            }]
        },
        RoleArn=SM_ROLE_ARN,
        Environment={
            "JOB_ID":          job_id,
            "S3_DATA_BUCKET":  S3_DATA_BUCKET,
            "DYNAMO_TABLE":    DYNAMO_TABLE,
            "AWS_REGION":      AWS_REGION,
        },
    )


# ══════════════════════════════════════════════════════════════════════════════
# SQS WORKER  (started as background thread when MODE=worker)
# ══════════════════════════════════════════════════════════════════════════════

def _run_pipeline_job(job_id: str, cfg_dict: Dict):
    """Execute the full pipeline and upload outputs to S3."""
    import sys
    sys.path.insert(0, "/opt/multiomics")
    from multiomics_reactome import run_pipeline, InputConfig   # noqa: F401

    output_dir = Path(f"/tmp/jobs/{job_id}")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Patch global OUTPUT_DIR
    import multiomics_reactome as mr
    mr.OUTPUT_DIR = output_dir

    # Download any real-data S3 inputs
    s3_keys = cfg_dict.get("s3_keys", {})
    local_paths: Dict[str, Path] = {}
    for modality, key in s3_keys.items():
        ext   = Path(key).suffix
        local = output_dir / f"{modality}{ext}"
        s3.download_file(S3_DATA_BUCKET, key, str(local))
        local_paths[modality] = local

    from pathlib import Path as P
    icfg = InputConfig(
        mode            = cfg_dict.get("mode", "synthetic"),
        n_samples       = cfg_dict.get("n_samples", 120),
        n_cells         = cfg_dict.get("n_cells", 400),
        n_batches       = cfg_dict.get("n_batches", 3),
        transcriptomics = local_paths.get("transcriptomics"),
        proteomics      = local_paths.get("proteomics"),
        metabolomics    = local_paths.get("metabolomics"),
        genomics        = local_paths.get("genomics"),
        sc_rna          = local_paths.get("sc_rna"),
        sc_atac         = local_paths.get("sc_atac"),
        spatial         = local_paths.get("spatial"),
        metadata        = local_paths.get("metadata"),
    )
    run_pipeline(icfg, n_perm=cfg_dict.get("n_perm", 200))

    # Upload results to S3
    for f in output_dir.iterdir():
        if f.is_file():
            s3.upload_file(
                str(f), S3_DATA_BUCKET, f"results/{job_id}/{f.name}",
                ExtraArgs={"ContentType": _content_type(f.suffix)},
            )
    log.info(f"Job {job_id} completed — results uploaded.")


def _content_type(suffix: str) -> str:
    return {
        ".png":  "image/png",
        ".html": "text/html",
        ".csv":  "text/csv",
        ".json": "application/json",
    }.get(suffix.lower(), "application/octet-stream")


def run_worker():
    """Long-poll SQS and process jobs sequentially."""
    log.info("SQS worker started.")
    while True:
        try:
            resp = sqs.receive_message(
                QueueUrl=SQS_QUEUE_URL,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=20,
                VisibilityTimeout=3600,
            )
            messages = resp.get("Messages", [])
            if not messages:
                continue
            msg  = messages[0]
            body = json.loads(msg["Body"])
            jid  = body["job_id"]
            cfg  = body["config"]

            log.info(f"Processing job {jid} …")
            _dynamo_update(jid, {"status": "RUNNING",
                                  "updated_at": datetime.now(timezone.utc).isoformat()})
            try:
                _run_pipeline_job(jid, cfg)
                _dynamo_update(jid, {
                    "status":     "COMPLETED",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "progress":   100,
                })
            except Exception as e:
                log.exception(f"Job {jid} failed: {e}")
                _dynamo_update(jid, {
                    "status":     "FAILED",
                    "error":      str(e)[:500],
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
            finally:
                sqs.delete_message(QueueUrl=SQS_QUEUE_URL,
                                   ReceiptHandle=msg["ReceiptHandle"])
        except Exception as e:
            log.error(f"Worker loop error: {e}")
            time.sleep(5)


# ══════════════════════════════════════════════════════════════════════════════
# ENTRYPOINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    if MODE == "worker":
        run_worker()
    else:
        if SQS_QUEUE_URL:
            t = threading.Thread(target=run_worker, daemon=True)
            t.start()
        uvicorn.run(app, host="0.0.0.0", port=8000,
                    workers=1, log_level="info")
