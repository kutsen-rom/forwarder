import os
import asyncio
import sys
from datetime import datetime
from flask import Flask
from waitress import serve
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import User, Channel, Chat
from dotenv import load_dotenv
from sources_config import SOURCES, get_all_sources, get_keywords_for_source, get_source_name, INTERVAL

# Load environment variables from .env file
load_dotenv()

# Minimal HTTP server for Render health checks
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Service is Running", 200

@app.route('/health')
def health():
    return "OK", 200

def run_web_server():
    """Run a simple HTTP server on port 8000"""
    print("Starting HTTP server on port 8000...")
    serve(app, host='0.0.0.0', port=8000)

# Start HTTP server in background thread
import threading
web_thread = threading.Thread(target=run_web_server, daemon=True)
web_thread.start()

def get_env_var(name, required=True):
    value = os.getenv(name)
    if required and value is None:
        print(f"Error: Environment variable {name} is required but not set")
        sys.exit(1)
    return value

# Get configuration
api_id = int(get_env_var('API_ID'))
api_hash = get_env_var('API_HASH')
dest_group_id = int(get_env_var('DEST_GROUP_ID'))
session_string = get_env_var('SESSION_STRING')

# Get sources from config
source_chat_ids = get_all_sources()

print("🔧 Configuration loaded:")
print(f"   API ID: {api_id}")
print(f"   Destination Group: {dest_group_id}")
print(f"   Monitoring {len(SOURCES)} sources:")
print(f"   Check Interval: {INTERVAL} minutes")

for source_name, source_info in SOURCES.items():
    keywords = source_info["KEYWORDS"]
    print(f"     • {source_name}: {len(keywords)} keywords")

# Create Telegram client
client = TelegramClient(StringSession(session_string), api_id, api_hash)

# Track last processed message ID per source
last_message_ids = {source_info["SOURCE"]: 0 for source_info in SOURCES.values()}

def get_sender_name(sender):
    """Get the appropriate name for different sender types"""
    if isinstance(sender, User):
        if sender.first_name and sender.last_name:
            return f"{sender.first_name} {sender.last_name}"
        elif sender.first_name:
            return sender.first_name
        elif sender.username:
            return f"@{sender.username}"
        else:
            return "Unknown User"
    
    elif isinstance(sender, Channel) or isinstance(sender, Chat):
        return getattr(sender, 'title', 'Unknown Channel/Chat')
    
    return "Unknown Sender"

def get_sender_username(sender):
    """Get username if available"""
    if isinstance(sender, User):
        return getattr(sender, 'username', None)
    return None

def contains_keyword(message_text, keywords_list):
    """Check if message contains any of the keywords (case-insensitive)"""
    if not message_text:
        return []
        
    message_lower = message_text.lower()
    matched_keywords = []
    
    for keyword in keywords_list:
        # For multi-word keywords, check if all words are present
        if ' ' in keyword:
            keyword_words = keyword.split()
            if all(word in message_lower for word in keyword_words):
                matched_keywords.append(keyword)
        # For single-word keywords, simple contains check
        elif keyword in message_lower:
            matched_keywords.append(keyword)
    
    return matched_keywords

async def copy_message_content(message, dest_chat_id, source_chat_name, sender_name, sender_username=None):
    """Copy message content instead of forwarding"""
    try:
        # Build the message header with source chat info
        if sender_username:
            header = f"**From {sender_name} (@{sender_username}) in {source_chat_name}:**\n\n"
        else:
            header = f"**From {sender_name} in {source_chat_name}:**\n\n"
        
        message_text = message.text or (getattr(message, 'caption', None) or "")
        full_message = header + message_text
        
        # Send as a new message (copy)
        await client.send_message(
            dest_chat_id,
            full_message,
            link_preview=False
        )
        return True
        
    except Exception as e:
        print(f"   ❌ Error copying message: {e}")
        return False

async def check_and_forward_messages():
    """Check all sources for new messages and forward if keywords match"""
    print(f"🕒 Checking for new messages at {datetime.now().strftime('%H:%M:%S')}...")
    
    processed_count = 0
    
    for source_name, source_info in SOURCES.items():
        chat_id = source_info["SOURCE"]
        keywords = source_info["KEYWORDS"]
        keywords_lower = [kw.lower() for kw in keywords]
        
        try:
            # Get new messages since last check
            messages = await client.get_messages(
                chat_id, 
                min_id=last_message_ids[chat_id],
                limit=50  # Limit to avoid too many messages
            )
            
            if not messages:
                continue
            
            print(f"   📨 Found {len(messages)} new messages in {source_name}")
            
            # Process each new message
            for message in messages:
                # Skip outgoing messages (our own)
                if message.out:
                    continue
                
                # Get message text from text or caption
                if message.text:
                    message_text = message.text
                elif hasattr(message, 'caption') and message.caption:
                    message_text = message.caption
                else:
                    message_text = ""
                
                # Check for keywords
                matched_keywords = contains_keyword(message_text, keywords_lower)
                
                if matched_keywords:
                    print(f"   ✅ Message with keywords in {source_name}: {matched_keywords}")
                    
                    # Get sender info
                    sender = await message.get_sender()
                    sender_name = get_sender_name(sender)
                    sender_username = get_sender_username(sender)
                    source_display_name = get_source_name(chat_id)
                    
                    # Try to forward
                    try:
                        await client.forward_messages(dest_group_id, message)
                        print(f"   ✅ Message forwarded successfully!")
                        processed_count += 1
                        
                    except Exception as forward_error:
                        print(f"   ⚠️ Forward failed: {forward_error}")
                        # Try to copy instead
                        copy_success = await copy_message_content(
                            message, dest_group_id, source_display_name, sender_name, sender_username
                        )
                        if copy_success:
                            print(f"   ✅ Message content copied successfully!")
                            processed_count += 1
                        else:
                            print(f"   ❌ Both forwarding and copying failed!")
                
                # Update last processed message ID
                last_message_ids[chat_id] = max(last_message_ids[chat_id], message.id)
            
            # Mark chat as read after processing
            await client.send_read_acknowledge(chat_id)
            print(f"   ✅ Marked {source_name} as read")
            
        except Exception as e:
            print(f"   ❌ Error processing {source_name}: {e}")
    
    if processed_count > 0:
        print(f"✅ Processed {processed_count} messages")
    else:
        print("✅ No new matching messages found")

async def periodic_message_checker():
    """Check for new messages at the specified interval"""
    while True:
        try:
            await check_and_forward_messages()
            # Wait for the specified interval
            await asyncio.sleep(INTERVAL)
        except Exception as e:
            print(f"❌ Error in periodic checker: {e}")
            await asyncio.sleep(60)  # Wait 1 minute on error before retrying

async def main():
    print("🚀 Starting message forwarder...")
    print(f"🔍 Monitoring {len(SOURCES)} sources every {INTERVAL} seconds")
    
    try:
        await client.start()
        
        # Verify connection and permissions
        me = await client.get_me()
        me_name = get_sender_name(me)
        print(f"✅ Logged in as: {me_name}")
        
        # Verify destination group access
        try:
            dest_entity = await client.get_entity(dest_group_id)
            dest_name = get_sender_name(dest_entity)
            print(f"✅ Destination group: {dest_name}")
        except Exception as e:
            print(f"❌ Cannot access destination group: {e}")
            return

               
        # Verify source chats access and collect info for startup message
        source_info_list = []
        inaccessible_sources = []
        
        # Initialize last message IDs with current latest messages
        for source_name, source_info in SOURCES.items():
            chat_id = source_info["SOURCE"]
            try:
                chat_entity = await client.get_entity(chat_id)
                chat_display_name = get_sender_name(chat_entity)
                keywords = source_info["KEYWORDS"]
                
                source_info_list.append({
                    'config_name': source_name,
                    'display_name': chat_display_name,
                    'keywords': keywords,
                    'keyword_count': len(keywords)
                })

                messages = await client.get_messages(chat_id, limit=1)
                if messages:
                    last_message_ids[chat_id] = messages[0].id
                    print(f"✅ Source: {source_name} - Last message ID: {last_message_ids[chat_id]}")
                else:
                    print(f"✅ Source: {source_name} - No messages yet")
            except Exception as e:
                print(f"❌ Cannot access source {source_name} ({chat_id}): {e}")
        
        # Send startup message
        try:
            startup_message = f"🤖 Forwarder bot is now online!\n\nMonitoring **{len(SOURCES)} sources** every **{INTERVAL//60} minutes**\n\nI will forward or copy messages containing your keywords.\n\n"
            startup_message += f"📝 **Monitoring {len(source_info_list)} sources:**\n"
            
            for source in source_info_list:
                startup_message += f"• {source['display_name']}\n"
            
            startup_message += "\n"
            
            for source in source_info_list:
                keyword_sample = ", ".join(source['keywords'])
                
                startup_message += f"✅ **{source['display_name']} Keywords:** {keyword_sample}\n"
                startup_message += f"**Total Keywords:** {source['keyword_count']}\n\n"
            
            if inaccessible_sources:
                startup_message += f"⚠️ **Unable to access:** {', '.join(inaccessible_sources)}\n\n"
            await client.send_message(dest_group_id, startup_message)
            print("✅ Startup message sent to destination group")
        except Exception as e:
            print(f"⚠️ Could not send startup message: {e}")
        
        # Start the periodic message checker
        print("✅ Bot is running and ready to check for messages!")
        await periodic_message_checker()
        
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    asyncio.run(main())