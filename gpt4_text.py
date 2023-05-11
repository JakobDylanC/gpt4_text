import os
import asyncio
from datetime import datetime
from flask import Flask, request
from twilio.rest import Client
from gpt4_functions import gpt4_functions

REQUIRED_ENV_VARS = ["TWILIO_PHONE_NUMBER", "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "CUSTOM_SYSTEM_PROMPT"]
missing_env_vars = [var for var in REQUIRED_ENV_VARS if var not in os.environ]
if missing_env_vars:
    raise ValueError(f"Required environment variables are not set: {', '.join(missing_env_vars)}")

twilio_client = Client(os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"])
app = Flask(__name__)
user_sessions = {}

class MessageNode:
    def __init__(self, message):
        self.message = message
        self.tokens = gpt4_functions.count_tokens(message)

class UserSession:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.message_history = []
        self.total_tokens = 0

def send_sms(body, from_number, to_number):
    twilio_client.messages.create(body=body, from_=from_number, to=to_number)

@app.route("/sms", methods=["POST"])
async def receive_sms():
    user_prompt_content = request.form["Body"].strip()

    if user_prompt_content:
        from_number = request.form["From"]
        user_session = user_sessions.setdefault(from_number, UserSession())
        
        async with user_session.lock:
            new_msg = MessageNode({"role": "user", "content": user_prompt_content})
            user_session.message_history.append(new_msg)
            user_session.total_tokens += new_msg.tokens

            current_date = datetime.now().strftime("%B %d, %Y")
            system_prompt_content = f"{os.environ['CUSTOM_SYSTEM_PROMPT']}\nKnowledge cutoff: Sep 2021. Current date: {current_date}"
            system_prompt = MessageNode({"role": "system", "content": system_prompt_content})

            while user_session.total_tokens + system_prompt.tokens > gpt4_functions.MAX_PROMPT_TOKENS:
                if len(user_session.message_history) > 1:
                    removed_msg = user_session.message_history.pop(0)
                    user_session.total_tokens -= removed_msg.tokens
                else:
                    send_sms("Sorry, an error occurred. Please try again.", os.environ["TWILIO_PHONE_NUMBER"], from_number)
                    return

            gpt_response = await gpt4_functions.generate_response(system_prompt.message, [msg.message for msg in user_session.message_history])
            response_node = MessageNode({"role": "assistant", "content": gpt_response})
            user_session.message_history.append(response_node)
            user_session.total_tokens += response_node.tokens

            response_chunks = gpt4_functions.split_response(gpt_response, 960)
            for chunk in response_chunks:
                send_sms(chunk, os.environ["TWILIO_PHONE_NUMBER"], from_number)
            
            print(f"Sent response to {from_number}")

    return("", 204)

if __name__ == "__main__":
    app.run()