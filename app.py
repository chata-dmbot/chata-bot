from flask import Flask, request
import requests

app = Flask(__name__)

VERIFY_TOKEN = "chata_verify_token"
ACCESS_TOKEN = "EAAUpDddy4TkBPB51vIZBnoq5YgZAOufErizbc9383Toz0oTab94K3y4PwuxZACPTT3FGwtXNsxCJrp4q8pCZCterXrHdrTkbpUUs4ZB1ldJFGJxQ0C4nBoJaCluTQZBsRgC0fiiX5SuvqZAcE3Jy3WA0wFTgho3ELK2dLnVIqqxcixnnsQmzYgeibSZA7wzZCkC7ZAfVLzIGsIVkio70rZBH9ZBqOsxmFK1rfTwi60ZCGc0i5vUhW5vfsUHF2RxkZD"
INSTAGRAM_USER_ID = "745508148639483"

@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        # Verification challenge from Meta
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        if mode == "subscribe" and token == VERIFY_TOKEN:
            print("WEBHOOK VERIFIED!")
            return challenge, 200
        else:
            return "Forbidden", 403

    elif request.method == "POST":
        print("Webhook received POST:", request.json)
        data = request.json

        # Basic check for Instagram messaging events
        if 'entry' in data:
            for entry in data['entry']:
                if 'messaging' in entry:
                    for event in entry['messaging']:
                        sender_id = event['sender']['id']
                        if 'message' in event and 'text' in event['message']:
                            message_text = event['message']['text']
                            print(f"Received a message from {sender_id}: {message_text}")

                            # Prepare your reply
                            reply_text = "👋 Hello from Chata bot! This is an automated reply."
                            url = f"https://graph.facebook.com/v18.0/{INSTAGRAM_USER_ID}/messages?access_token={ACCESS_TOKEN}"
                            payload = {
                                "recipient": {"id": sender_id},
                                "message": {"text": reply_text}
                            }

                            # Send the reply using requests
                            r = requests.post(url, json=payload)
                            print("Sent reply:", r.text)
        return "EVENT_RECEIVED", 200

if __name__ == "__main__":
    app.run(port=5000)