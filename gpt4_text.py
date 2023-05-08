import os
from twilio.rest import Client
from flask import Flask, request
import asyncio
from datetime import datetime
import gpt_functions

for environ_name in ["TWILIO_PHONE_NUMBER", "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "CUSTOM_SYSTEM_PROMPT"]:
    if environ_name not in os.environ:
        raise ValueError(f"Required environment variable {environ_name} is not set.")
twilio_client = Client(os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"])
app = Flask(__name__)
locks, message_histories = {}, {}
    
@app.route("/sms", methods=["POST"])
async def receive_sms():
    user_prompt_content = request.form["Body"].strip()
    if user_prompt_content != "":
        from_number = request.form["From"]
        if from_number not in locks:
            locks[from_number] = asyncio.Lock()
        async with locks[from_number]:
            message_history = message_histories.get(from_number, [])
            message_history.append({"role": "user", "content": user_prompt_content})
            current_date = datetime.now().strftime("%B %d, %Y")
            system_prompt_content = f"{os.environ['CUSTOM_SYSTEM_PROMPT']}\nKnowledge cutoff: Sep 2021. Current date: {current_date}"
            system_prompt = [{"role": "system", "content": system_prompt_content}]
            gpt_response = await gpt_functions.generate_response(system_prompt, message_history)
            message_history.append({"role": "assistant", "content": gpt_response})
            message_histories[from_number] = message_history
            response_chunks = gpt_functions.split_response(gpt_response, 960)
            for chunk in response_chunks:
                twilio_client.messages.create(
                    body=chunk,
                    from_=os.environ["TWILIO_PHONE_NUMBER"],
                    to=from_number,
                )
            print(f"Sent response to {from_number}")
            
    return("", 204)

app.run()