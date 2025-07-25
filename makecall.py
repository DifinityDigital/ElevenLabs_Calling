from twilio.rest import Client
from dotenv import load_dotenv
from updatengrok import getURL
import os
import requests
# load_dotenv()

load_dotenv(dotenv_path=r"C:\Users\akshay.k\Documents\ElevenLabs\.env")
# URL = getURL()
URL = os.getenv("WEBHOOK_URL")
print(URL)

# Replace with your actual Twilio credentials
account_sid = os.getenv("TWILIO_ACCOUNT_SID")
auth_token = os.getenv("TWILIO_AUTH_TOKEN")

twilio_number = os.getenv("TWILIO_PHONE_NUMBER") # Your Twilio number
candidate_number = "+919446529912"  # Number to call

client = Client(account_sid, auth_token)

call = client.calls.create(
    to=candidate_number,
    from_=twilio_number,
    url= f"https://{URL}/twilio/outbound_call_twiml"  # Must be HTTPS + public
)
print(f"📞 Outbound call initiated. Call SID: {call.sid}")

#<------------------------------------------------------------------------------------------------------------------------------------------->

# url = os.getenv("WEBHOOK_URLTT")
# url = getURL()

# BASE_URL = f"https://{url}"

# numbers_to_call = [
#     {
#         "to": "+919961692470",
#         "agent_id": os.getenv("AGENT_1"),
#         "dynamic_variables": {
#             "name": "Nirmal Kumar",
#         }
#     },
#     {
#         "to": "+919567721009",
#         "agent_id": os.getenv("AGENT_2"),
#         "dynamic_variables": {
#             "name": "Manu",
#         }
#     }
# ]

# for call_data in numbers_to_call:
#     response = requests.post(f"{BASE_URL}/twilio/outbound_call", json=call_data)
#     # print(response.json())
#     if response.headers.get("Content-Type", "").startswith("application/json"):
#         print(response.json())
#     else:
#         print("Non-JSON response received:")
#         print(response.text)
