import requests
import re

# 1. Get the current ngrok public HTTPS URL
def getURL():
    res = requests.get("http://127.0.0.1:4040/api/tunnels")
    data = res.json()
    https_url = next(t['public_url'] for t in data['tunnels'] if t['public_url'].startswith("https://"))
    domain = https_url.replace("https://", "")

    # 2. Update .env file
    env_path = ".env"
    with open(env_path, "r") as f:
        lines = f.readlines()

    with open(env_path, "w") as f:
        for line in lines:
            if line.startswith("WEBHOOK_URL="):
                f.write(f"WEBHOOK_URL={domain}\n")
            else:
                f.write(line)

    print(f"✅ Updated .env with ngrok URL: {domain}")
    return domain
