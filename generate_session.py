import os
import sys
from telethon.sessions import StringSession
from telethon import TelegramClient
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

api_id = os.getenv('API_ID')
api_hash = os.getenv('API_HASH')

if not api_id or not api_hash:
    print("Error: API_ID and API_HASH must be set in .env file")
    sys.exit(1)

try:
    api_id = int(api_id)
except ValueError:
    print("Error: API_ID must be a number")
    sys.exit(1)

print("Generating Telegram session...")
print("You will need to enter your phone number and verification code")

with TelegramClient(StringSession(), api_id, api_hash) as client:
    session_string = client.session.save()
    print("\n" + "="*50)
    print("SESSION GENERATED SUCCESSFULLY!")
    print("="*50)
    print("Add this to your .env file as SESSION_STRING:")
    print(f"SESSION_STRING={session_string}")
    print("="*50)