import os
import google.auth
from google.auth.transport.requests import Request
import urllib.request
import json

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "/home/ashish-bhardwaj/onlearn-monorepo/llm-app/secrets/gcp-sa.json"

credentials, project = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
credentials.refresh(Request())

url = f"https://serviceusage.googleapis.com/v1beta1/projects/{project}/services/aiplatform.googleapis.com/consumerQuotaMetrics"

req = urllib.request.Request(url, headers={"Authorization": f"Bearer {credentials.token}"})
try:
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read().decode())
        for metric in data.get("metrics", []):
            name = metric.get("metric")
            if "generate_content" in name or "gemini" in name or "tokens" in name or "requests" in name:
                print(f"--- Metric: {name} ---")
                for quota in metric.get("consumerQuotaLimits", []):
                    print(f"  Limit Name: {quota.get('name')}")
                    print(f"  Quota Buckets: {json.dumps(quota.get('quotaBuckets', []), indent=2)}")
except Exception as e:
    print(f"Error: {e}")
    if hasattr(e, 'read'):
        print(e.read().decode())

