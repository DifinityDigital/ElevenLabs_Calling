import os
import json
import time
import traceback
import logging
import asyncio
from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.exceptions import WebSocketException
from contextlib import asynccontextmanager
from twilio.twiml.voice_response import VoiceResponse, Connect
from twilio.rest import Client
from updatengrok import getURL

# --- ElevenLabs SDK imports ---
from elevenlabs import ElevenLabs
from elevenlabs.conversational_ai.conversation import Conversation, ConversationInitiationData
from twilio_audio_interface import TwilioAudioInterface

# --- Logging setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("voice_agent")

# --- Load environment variables ---
load_dotenv()
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")
URL = os.getenv("WEBHOOK_URL")
# URL = getURL()

# --- Store call configurations temporarily ---
call_configs = {}

# --- Background cleanup task ---
async def cleanup_old_configs():
    while True:
        await asyncio.sleep(180)  # Clean up every 3 minutes
        current_time = time.time()
        to_remove = []
        for call_sid, config in call_configs.items():
            if current_time - config["timestamp"] > 600:  # 10 minutes old
                to_remove.append(call_sid)
        for call_sid in to_remove:
            del call_configs[call_sid]
            logger.info(f"Cleaned up old config for {call_sid}")

# --- Lifespan event handler ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    cleanup_task = asyncio.create_task(cleanup_old_configs())
    yield
    cleanup_task.cancel()

app = FastAPI(lifespan=lifespan)

# --- Twilio Client ---
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

@app.get("/")
async def root():
    return {"message": "Twilio-ElevenLabs Outbound Call Server"}

@app.post("/twilio/outbound_call")
async def outbound_call(request: Request):
    data = await request.json()
    to_number = data.get("to")
    agent_id = data.get("agent_id")
    dynamic_vars = data.get("dynamic_variables", {})
    logger.info(f"Dynamic vars: {dynamic_vars}")

    if not to_number or not agent_id:
        return {"error": "Missing 'to' or 'agent_id'"}

    try:
        call = twilio_client.calls.create(
            to=to_number,
            from_=TWILIO_PHONE_NUMBER,
            url=f"https://{URL}/twilio/outbound_call_twiml"
        )
        call_configs[call.sid] = {
            "agent_id": agent_id,
            "dynamic_variables": dynamic_vars,
            "to_number": to_number,
            "timestamp": time.time()
        }
        logger.info(f"Call created with SID: {call.sid}")
        logger.info(f"Stored config for webhook: {call_configs[call.sid]}")
        return {"success": True, "call_sid": call.sid}
    except Exception as e:
        logger.error(f"Error creating call: {e}")
        return {"error": str(e)}

@app.post("/twilio/outbound_call_twiml")
async def outbound_twiml(request: Request):
    logger.info("TwiML endpoint called")
    try:
        content_type = request.headers.get("content-type", "")
        if "application/x-www-form-urlencoded" in content_type:
            form_data = await request.form()
            call_sid = form_data.get("CallSid")
            from_number = form_data.get("From")
            to_number = form_data.get("To")
        else:
            try:
                json_data = await request.json()
                call_sid = json_data.get("CallSid")
                from_number = json_data.get("From")
                to_number = json_data.get("To")
            except:
                call_sid = None
                from_number = None
                to_number = None
        logger.info(f"TwiML - Call SID: {call_sid}, From: {from_number}, To: {to_number}")
    except Exception as e:
        logger.error(f"Error parsing TwiML request: {e}")
        call_sid = None

    response = VoiceResponse()
    connect = Connect()
    connect.stream(url=f"wss://{URL}/media-stream")
    response.append(connect)
    return HTMLResponse(content=str(response), media_type="application/xml")

@app.post("/elevenlabs/conversation-config")
async def elevenlabs_conversation_config(request: Request):
    """
    ElevenLabs will call this webhook to get conversation initiation data.
    The request will contain call information from Twilio.
    """
    try:
        webhook_data = await request.json()
        logger.info(f"ElevenLabs webhook data: {json.dumps(webhook_data, indent=2)}")
        call_sid = webhook_data.get("call_sid") or webhook_data.get("callSid")
        caller_number = webhook_data.get("from") or webhook_data.get("caller")
        called_number = webhook_data.get("to") or webhook_data.get("called")
        logger.info(f"Looking for call config with SID: {call_sid}")
        logger.info(f"Available configs: {list(call_configs.keys())}")
        call_config = None
        if call_sid and call_sid in call_configs:
            call_config = call_configs[call_sid]
            logger.info(f"Found config by Call SID: {call_config}")
        else:
            for sid, config in call_configs.items():
                if config.get("to_number") == called_number:
                    call_config = config
                    logger.info(f"Found config by phone number match: {call_config}")
                    break
        if not call_config:
            logger.warning("No matching call config found, using default")
            return JSONResponse({
                "agent_id": os.getenv("AGENT_1"),
                "dynamic_variables": {}
            })
        response_data = {
            "agent_id": call_config["agent_id"],
            "dynamic_variables": call_config["dynamic_variables"]
        }
        logger.info(f"Returning config to ElevenLabs: {response_data}")
        return JSONResponse(response_data)
    except Exception as e:
        logger.error(f"Error in ElevenLabs webhook: {e}")
        traceback.print_exc()
        return JSONResponse({
            "agent_id": os.getenv("AGENT_1"),
            "dynamic_variables": {}
        })

@app.websocket("/media-stream")
async def handle_media_stream(websocket: WebSocket):
    await websocket.accept()
    logger.info("WebSocket connection opened")
    audio_interface = TwilioAudioInterface(websocket)
    eleven_labs_client = ElevenLabs(api_key=ELEVENLABS_API_KEY)
    conversation = None
    call_sid = None
    call_config = None

    try:
        async for message_text in websocket.iter_text():
            if not message_text:
                continue
            msg_data = json.loads(message_text)
            if msg_data.get("event") == "start":
                start_data = msg_data.get("start", {})
                call_sid = start_data.get("callSid")
                called_number = start_data.get("to")
                if call_sid and call_sid in call_configs:
                    call_config = call_configs[call_sid]
                    logger.info(f"Found call config by SID: {call_config}")
                else:
                    for sid, config in call_configs.items():
                        if config.get("to_number") == called_number:
                            call_config = config
                            call_sid = sid
                            logger.info(f"Found config by phone number match: {call_config}")
                            break
                # if not call_config:
                #     logger.warning("No call config found, using defaults")
                #     call_config = {
                #         "agent_id": os.getenv("AGENT_1"),
                #         "dynamic_variables": {}
                #     }
                # --- Pass dynamic variables to ElevenLabs agent prompt ---
                config_obj = ConversationInitiationData(
                    dynamic_variables=call_config["dynamic_variables"]
                )
                conversation = Conversation(
                    client=eleven_labs_client,
                    agent_id=call_config["agent_id"],
                    requires_auth=True,
                    config=config_obj,
                    audio_interface=audio_interface,
                    callback_agent_response=lambda text: logger.info(f"Agent: {text}"),
                    callback_user_transcript=lambda text: logger.info(f"User: {text}"),
                )
                conversation.start_session()
                logger.info(f"Conversation started with agent {call_config['agent_id']} and variables: {call_config['dynamic_variables']}")
                await audio_interface.handle_twilio_message(msg_data)
            elif conversation:
                await audio_interface.handle_twilio_message(msg_data)
            else:
                logger.info(f"Received message before conversation started: {msg_data.get('event', 'unknown')}")
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error(f"Error in WebSocket handler: {e}")
        traceback.print_exc()
        await websocket.close(code=1011, reason="Internal server error")
    finally:
        try:
            if conversation:
                conversation.end_session()
                conversation.wait_for_session_end()
                logger.info("Conversation ended")
        except Exception as e:
            logger.error(f"Error ending conversation session: {e}")
            traceback.print_exc()
        finally:
            if call_sid and call_sid in call_configs:
                del call_configs[call_sid]
                logger.info(f"Cleaned up config for call {call_sid}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
