import os
import time
import json
import urllib.request
import urllib.error

# Load .env manually
env_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
if os.path.exists(env_file):
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ[k] = v.strip("'").strip('"')

api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    print("No API key found in .env.")
    exit(1)

base_text = "The quick brown fox jumps over the lazy dog. Here is some more filler text to increase the context size without adding too much complexity to the actual generation task. We just want to measure the input processing time of the model. "
large_input = base_text * 1000

prompt = f"Please read the following long text and summarize it in exactly one short sentence. Ignore the repetitive filler and just say what it talks about:\n\n{large_input}"

model_name = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash-latest")
url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
headers = {'Content-Type': 'application/json'}
data = {
    "contents": [{"parts": [{"text": prompt}]}]
}
json_data = json.dumps(data).encode('utf-8')

print(f"Testing Gemini latency with large input...")
print(f"Payload size: {len(prompt):,} characters.")

start_time = time.time()
print("Waiting for response...")

req = urllib.request.Request(url, data=json_data, headers=headers)
try:
    with urllib.request.urlopen(req) as response:
        resp_data = response.read()
        elapsed = time.time() - start_time
        res_json = json.loads(resp_data)
        
        try:
            content = res_json['candidates'][0]['content']['parts'][0]['text']
        except KeyError:
            content = str(res_json)
        
        print(f"\n--- SUCCESS ---")
        print(f"Time Taken: {elapsed:.2f} seconds")
        print(f"Response:\n{content}")
except urllib.error.HTTPError as e:
    elapsed = time.time() - start_time
    err_body = e.read().decode('utf-8')
    print(f"\n--- FAILED ---")
    print(f"Time taken before failure: {elapsed:.2f} seconds")
    print(f"HTTP Error {e.code}: {e.reason}")
    print(f"Response Body: {err_body}")
except Exception as e:
    elapsed = time.time() - start_time
    print(f"\n--- FAILED ---")
    print(f"Time taken before failure: {elapsed:.2f} seconds")
    print(f"Error: {e}")
