import os
import json
import traceback
from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import HTMLResponse
from twilio.twiml.voice_response import VoiceResponse, Connect
from elevenlabs import ElevenLabs
from elevenlabs.conversational_ai.conversation import Conversation
from twilio_audio_interface import TwilioAudioInterface
from starlette.websockets import WebSocketDisconnect
from twilio.rest import Client
from elevenlabs.conversational_ai.conversation import Conversation, ConversationInitiationData
from updatengrok import getURL


load_dotenv(dotenv_path=r"C:\Users\akshay.k\Documents\ElevenLabs\.env")
# URL = getURL()
URL = os.getenv("WEBHOOK_URL")
print(URL)

ELEVEN_LABS_AGENT_ID = os.getenv("HR_Agent")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")

app = FastAPI()

# Twilio Client
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

dynamic_vars = {
    "name": "Megha",
    # "loan_amount":"100000",
    # "interest_rate":"9",
}



config = ConversationInitiationData(
    dynamic_variables=dynamic_vars
)

@app.get("/")
async def root():
    return {"message": "Twilio-ElevenLabs Outbound Call Server"}

# ✅ Outbound call trigger route
@app.post("/twilio/outbound_call")
async def outbound_call(request: Request):
    data = await request.json()
    to_number = data.get("to")
    if not to_number:
        return {"error": "Missing 'to' number"}

    try:
        call = twilio_client.calls.create(
            to=to_number,
            from_=TWILIO_PHONE_NUMBER,
            url=f"https://{URL}/twilio/outbound_call_twiml"
        )
        return {
            "success": True,
            "message": "Call initiated",
            "call_sid": call.sid
        }
    except Exception as e:
        print("Error initiating outbound call:", e)
        return {"error": str(e)}

# ✅ TwiML response for outbound call
@app.post("/twilio/outbound_call_twiml")
async def outbound_twiml(request: Request):
    response = VoiceResponse()
    connect = Connect()
    connect.stream(url=f"wss://{URL}/media-stream")
    response.append(connect)
    return HTMLResponse(content=str(response), media_type="application/xml")

# ✅ Shared WebSocket for both inbound/outbound
@app.websocket("/media-stream")
async def handle_media_stream(websocket: WebSocket):
    await websocket.accept()
    print("WebSocket connection opened")

    audio_interface = TwilioAudioInterface(websocket)
    eleven_labs_client = ElevenLabs(api_key=ELEVENLABS_API_KEY)

    try:
        conversation = Conversation(
            client=eleven_labs_client,
            agent_id=ELEVEN_LABS_AGENT_ID,
            requires_auth=True,
            config=config,
            audio_interface=audio_interface,
            callback_agent_response=lambda text: print(f"Agent: {text}"),
            callback_user_transcript=lambda text: print(f"User: {text}"),
        )

        conversation.start_session()
        print("Conversation started")

        async for message in websocket.iter_text():
            if not message:
                continue
            await audio_interface.handle_twilio_message(json.loads(message))

    except WebSocketDisconnect:
        print("WebSocket disconnected")
    except Exception:
        print("Error in WebSocket handler:")
        traceback.print_exc()
    finally:
        try:
            conversation.end_session()
            conversation.wait_for_session_end()
            print("Conversation ended")
        except Exception:
            print("Error ending conversation session:")
            traceback.print_exc()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
