import os
import asyncio
from datetime import datetime
from flask import Flask, request
from twilio.rest import Client
from gpt4_functions import gpt4_functions

REQUIRED_ENV_VARS = ["TWILIO_PHONE_NUMBER", "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "CUSTOM_SYSTEM_PROMPT"]
if (missing_env_vars := [var for var in REQUIRED_ENV_VARS if var not in os.environ]):
    raise ValueError(f"Required environment variables are not set: {', '.join(missing_env_vars)}")

twilio_client = Client(os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"])
app = Flask(__name__)
user_sessions = {}

class MsgNode:
    def __init__(self, msg):
        self.msg = msg
        self.tokens = gpt4_functions.count_tokens(msg)

class UserSession:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.message_history = []
        self.total_tokens = 0

    def append_to_history(self, msg_node):
        self.message_history.append(msg_node)
        self.total_tokens += msg_node.tokens
    
    def pop_from_history(self, index):
        popped_msg_node = self.message_history.pop(index)
        self.total_tokens -= popped_msg_node.tokens

def send_sms(body, from_number, to_number):
    twilio_client.messages.create(body=body, from_=from_number, to=to_number)

@app.route("/sms", methods=["POST"])
async def receive_sms():
    user_prompt_content = request.form["Body"].strip()

    if user_prompt_content:
        from_number = request.form["From"]
        user_session = user_sessions.setdefault(from_number, UserSession())
        
        async with user_session.lock:
            user_msg = MsgNode({"role": "user", "content": user_prompt_content})
            user_session.append_to_history(user_msg)

            current_date = datetime.now().strftime("%B %d, %Y")
            system_prompt_content = f"{os.environ['CUSTOM_SYSTEM_PROMPT']}\nKnowledge cutoff: Sep 2021. Current date: {current_date}"
            system_prompt = MsgNode({"role": "system", "content": system_prompt_content})

            while user_session.total_tokens + system_prompt.tokens > gpt4_functions.MAX_PROMPT_TOKENS:
                if len(user_session.message_history) > 1:
                    user_session.pop_from_history(0)
                else:
                    send_sms("Sorry, an error occurred. Please try again.", os.environ["TWILIO_PHONE_NUMBER"], from_number)
                    return

            gpt_response = await gpt4_functions.generate_response(system_prompt.msg, [msg.msg for msg in user_session.message_history])
            response_msg = MsgNode({"role": "assistant", "content": gpt_response})
            user_session.append_to_history(response_msg)

            response_chunks = gpt4_functions.split_response(gpt_response, 960)
            for chunk in response_chunks:
                send_sms(chunk, os.environ["TWILIO_PHONE_NUMBER"], from_number)
            
            print(f"Sent response to {from_number}")

    return("", 204)

if __name__ == "__main__":
    app.run()