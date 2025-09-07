import os
import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession
from dotenv import load_dotenv

load_dotenv()

api_id = int(os.getenv('API_ID'))
api_hash = os.getenv('API_HASH')
session_string = os.getenv('SESSION_STRING')
source_group_id = int(os.getenv('SOURCE_GROUP_ID'))
dest_group_id = int(os.getenv('DEST_GROUP_ID'))

client = TelegramClient(StringSession(session_string), api_id, api_hash)

async def debug():
    await client.start()
    
    # Test connection
    me = await client.get_me()
    print(f"✓ Connected as: {me.first_name} (@{me.username})")
    
    # Test if we can access source group
    try:
        source_entity = await client.get_entity(source_group_id)
        print(f"✓ Source group access: {source_entity.title}")
    except Exception as e:
        print(f"✗ Cannot access source group: {e}")
    
    # Test if we can access destination group
    try:
        dest_entity = await client.get_entity(dest_group_id)
        print(f"✓ Destination group access: {dest_entity.title}")
    except Exception as e:
        print(f"✗ Cannot access destination group: {e}")
    
    # Test sending a message
    try:
        await client.send_message(dest_group_id, "🤖 Bot is working! Debug message.")
        print("✓ Successfully sent test message to destination group")
    except Exception as e:
        print(f"✗ Cannot send message to destination: {e}")
    
    await client.disconnect()

asyncio.run(debug())