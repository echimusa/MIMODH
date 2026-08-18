"""
API Gateway Lambda Authorizer
Validates Cognito JWT and returns an IAM policy.
Deploy as a Lambda function and attach to API Gateway as TOKEN authorizer.

Environment variables
---------------------
  COGNITO_USER_POOL_ID   e.g. eu-west-2_XXXXXXXXX
  COGNITO_CLIENT_ID      App client ID
  AWS_REGION             e.g. eu-west-2
"""

import json
import os
import urllib.request
from functools import lru_cache
from typing import Dict

import boto3
from jose import jwk, jwt
from jose.utils import base64url_decode

REGION        = os.environ["AWS_REGION"]
USER_POOL_ID  = os.environ["COGNITO_USER_POOL_ID"]
CLIENT_ID     = os.environ["COGNITO_CLIENT_ID"]
JWKS_URL      = (f"https://cognito-idp.{REGION}.amazonaws.com/"
                 f"{USER_POOL_ID}/.well-known/jwks.json")


@lru_cache(maxsize=1)
def _get_jwks() -> Dict:
    with urllib.request.urlopen(JWKS_URL) as r:
        return json.loads(r.read())


def _verify_token(token: str) -> Dict:
    jwks = _get_jwks()
    headers = jwt.get_unverified_headers(token)
    kid     = headers["kid"]
    key     = next((k for k in jwks["keys"] if k["kid"] == kid), None)
    if not key:
        raise ValueError("Public key not found")
    public_key = jwk.construct(key)
    message, encoded_sig = token.rsplit(".", 1)
    decoded_sig = base64url_decode(encoded_sig.encode())
    if not public_key.verify(message.encode(), decoded_sig):
        raise ValueError("Signature verification failed")
    claims = jwt.get_unverified_claims(token)
    if claims["aud"] != CLIENT_ID:
        raise ValueError("Token not issued for this client")
    return claims


def _policy(principal: str, effect: str, arn: str, context: Dict = None) -> Dict:
    doc = {
        "Version": "2012-10-17",
        "Statement": [{"Action": "execute-api:Invoke",
                        "Effect": effect, "Resource": arn}],
    }
    resp = {"principalId": principal, "policyDocument": doc}
    if context:
        resp["context"] = context
    return resp


def handler(event, context):
    token   = event.get("authorizationToken", "").replace("Bearer ", "")
    method_arn = event["methodArn"]
    try:
        claims = _verify_token(token)
        sub    = claims["sub"]
        email  = claims.get("email", "")
        return _policy(sub, "Allow", method_arn,
                       context={"user_id": sub, "email": email})
    except Exception as e:
        print(f"Auth failed: {e}")
        return _policy("anonymous", "Deny", method_arn)
