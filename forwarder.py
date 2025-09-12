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
from destinations_config import DESTINATIONS, INTERVAL_MINUTES, LAST_MESSAGES_LIMIT
import threading

# Load environment variables from .env file
load_dotenv()

# Minimal HTTP server for Render health checks
app = Flask(__name__)


@app.route("/")
def health_check():
    return "Service is Running", 200


@app.route("/health")
def health():
    return "OK", 200


def run_web_server():
    """Run a simple HTTP server on port 8000"""
    print("Starting HTTP server on port 8000...")
    serve(app, host="0.0.0.0", port=8000)


# Start HTTP server in background thread

web_thread = threading.Thread(target=run_web_server, daemon=True)
web_thread.start()


def get_env_var(name, required=True):
    value = os.getenv(name)
    if required and value is None:
        print(f"Error: Environment variable {name} is required but not set")
        sys.exit(1)
    return value


# Get configuration
api_id = int(get_env_var("API_ID"))
api_hash = get_env_var("API_HASH")
session_string = get_env_var("SESSION_STRING")

print("🔧 Configuration loaded:")
print(f"   API ID: {api_id}")
print(f"   Check Interval: {INTERVAL_MINUTES} minutes")
print(f"   Monitoring {len(DESTINATIONS)} destinations:")

# Create mapping structures
all_sources = {}
destination_sources = {}

# Pre-compute destination id -> name for fast lookup
DEST_ID_TO_NAME = {info["DESTINATION"]: name for name, info in DESTINATIONS.items()}

for dest_name, dest_info in DESTINATIONS.items():
    dest_id = dest_info["DESTINATION"]
    print(f"     • {dest_name}: {len(dest_info['SOURCES'])} sources")

    for source_name, source_info in dest_info["SOURCES"].items():
        source_id = source_info["SOURCE"]
        # Initialize source entry if not present
        if source_id not in all_sources:
            all_sources[source_id] = {
                "source_name": source_name,
                # Map destination id -> list of keywords (case preserved for reporting, lowercased for matching later)
                "dest_keywords": {},
                # Cached lowercased keywords per destination for matching
                "dest_keywords_lower": {},
            }
        # Append/merge destination-specific keywords
        all_sources[source_id]["dest_keywords"][dest_id] = list(
            source_info["KEYWORDS"]
        )  # copy list
        all_sources[source_id]["dest_keywords_lower"][dest_id] = [
            kw.lower() for kw in source_info["KEYWORDS"]
        ]
        print(f"       - {source_name}: {len(source_info['KEYWORDS'])} keywords")

# Create Telegram client
client = TelegramClient(StringSession(session_string), api_id, api_hash)

# Track last processed message ID per source
last_message_ids = {source_id: 0 for source_id in all_sources.keys()}


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
        return getattr(sender, "title", "Unknown Channel/Chat")

    return "Unknown Sender"


def get_sender_username(sender):
    """Get username if available"""
    if isinstance(sender, User):
        return getattr(sender, "username", None)
    return None


def contains_keyword(message_text, keywords_list):
    """Check if message contains any of the keywords (case-insensitive)"""
    if not message_text:
        return []

    message_lower = message_text.lower()
    matched_keywords = []

    for keyword in keywords_list:
        # For multi-word keywords, check if all words are present
        if " " in keyword:
            keyword_words = keyword.split()
            if all(word in message_lower for word in keyword_words):
                matched_keywords.append(keyword)
        # For single-word keywords, simple contains check
        elif keyword in message_lower:
            matched_keywords.append(keyword)

    return matched_keywords


async def copy_message_content(
    message, dest_chat_id, source_chat_name, sender_name, sender_username=None
):
    """Copy message content instead of forwarding"""
    try:
        # Build the message header with source chat info
        if sender_username:
            header = f"**From {sender_name} (@{sender_username}) in {source_chat_name}:**\n\n"
        else:
            header = f"**From {sender_name} in {source_chat_name}:**\n\n"

        message_text = message.text or (getattr(message, "caption", None) or "")
        full_message = header + message_text

        # Send as a new message (copy)
        await client.send_message(dest_chat_id, full_message, link_preview=False)
        return True

    except Exception as e:
        print(f"   ❌ Error copying message: {e}")
        return False


async def check_and_forward_messages():
    """Check all sources for new messages and forward if keywords match"""
    print(f"🕒 Checking for new messages at {datetime.now().strftime('%H:%M:%S')}...")

    processed_count = 0

    for source_id, source_info in all_sources.items():
        source_name = source_info["source_name"]
        # Use precomputed lowercased keywords per destination for matching
        dest_keywords_lower = source_info["dest_keywords_lower"]

        try:
            # Get new messages since last check
            messages = await client.get_messages(
                source_id,
                min_id=last_message_ids[source_id],
                limit=LAST_MESSAGES_LIMIT,  # Limit to avoid too many messages
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
                elif hasattr(message, "caption") and message.caption:
                    message_text = message.caption
                else:
                    message_text = ""

                # Check for keywords per destination and forward to all matches
                any_destination_matched = False
                # Get sender info once if any destination matches later
                sender = None
                sender_name = None
                sender_username = None

                for dest_id, kw_list_lower in dest_keywords_lower.items():
                    matched_keywords = contains_keyword(message_text, kw_list_lower)
                    if not matched_keywords:
                        continue

                    if not any_destination_matched:
                        print(f"   ✅ Message in {source_name} matched keywords")
                        any_destination_matched = True
                        sender = await message.get_sender()
                        sender_name = get_sender_name(sender)
                        sender_username = get_sender_username(sender)

                    dest_name = DEST_ID_TO_NAME.get(dest_id, "Unknown")

                    try:
                        await client.forward_messages(dest_id, message)
                        print(
                            f"   ✅ Forwarded to {dest_name} (matched: {matched_keywords})"
                        )
                        processed_count += 1
                    except Exception as forward_error:
                        print(f"   ⚠️ Forward to {dest_name} failed: {forward_error}")
                        copy_success = await copy_message_content(
                            message,
                            dest_id,
                            source_name,
                            sender_name or "Unknown Sender",
                            sender_username,
                        )
                        if copy_success:
                            print(
                                f"   ✅ Copied to {dest_name} (matched: {matched_keywords})"
                            )
                            processed_count += 1
                        else:
                            print(
                                f"   ❌ Both forwarding and copying to {dest_name} failed!"
                            )

                # Update last processed message ID
                last_message_ids[source_id] = max(
                    last_message_ids[source_id], message.id
                )

            # Mark chat as read after processing
            await client.send_read_acknowledge(source_id)
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
            await asyncio.sleep(INTERVAL_MINUTES * 60)
        except Exception as e:
            print(f"❌ Error in periodic checker: {e}")
            await asyncio.sleep(60)  # Wait 1 minute on error before retrying


async def main():
    print("🚀 Starting message forwarder...")
    print(
        f"🔍 Monitoring {len(all_sources)} sources across {len(DESTINATIONS)} destinations every {INTERVAL_MINUTES} minutes"
    )

    try:
        await client.start()

        # Verify connection and permissions
        me = await client.get_me()
        me_name = get_sender_name(me)
        print(f"✅ Logged in as: {me_name}")

        # Verify destination access and collect info for startup messages
        destination_info = {}
        inaccessible_destinations = []

        for dest_name, dest_info in DESTINATIONS.items():
            dest_id = dest_info["DESTINATION"]
            try:
                dest_entity = await client.get_entity(dest_id)
                dest_display_name = get_sender_name(dest_entity)
                destination_info[dest_id] = {
                    "name": dest_name,
                    "display_name": dest_display_name,
                    "source_count": len(dest_info["SOURCES"]),
                }
                print(f"✅ Destination: {dest_name} ({dest_display_name})")
            except Exception as e:
                print(f"❌ Cannot access destination {dest_name} ({dest_id}): {e}")
                inaccessible_destinations.append(dest_name)

        # Verify source access and initialize last message IDs
        inaccessible_sources = []
        for source_id, source_info in all_sources.items():
            source_name = source_info["source_name"]
            try:
                source_entity = await client.get_entity(source_id)
                source_display_name = get_sender_name(source_entity)
                source_info["display_name"] = source_display_name
                # Cache source link to avoid repeated lookups later
                source_link = (
                    f"https://t.me/{getattr(source_entity, 'username', '')}"
                    if hasattr(source_entity, "username") and source_entity.username
                    else (
                        f"https://t.me/c/{str(source_id)[4:]}"
                        if str(source_id).startswith("-100")
                        else f"https://t.me/{source_id}"
                    )
                )
                source_info["link"] = source_link

                messages = await client.get_messages(source_id, limit=1)
                if messages:
                    last_message_ids[source_id] = messages[0].id
                    print(
                        f"✅ Source: {source_name} - Last message ID: {last_message_ids[source_id]}"
                    )
                else:
                    print(f"✅ Source: {source_name} - No messages yet")
            except Exception as e:
                print(f"❌ Cannot access source {source_name} ({source_id}): {e}")
                inaccessible_sources.append(source_name)

        # Send startup messages to each destination
        for dest_id, dest_info in destination_info.items():
            try:
                startup_message = f"🤖 Forwarder bot is now online!\n\nMonitoring **{dest_info['source_count']} sources** every **{INTERVAL_MINUTES} minutes**\n\nI will forward or copy messages containing your keywords.\n\n"

                # Add sources for this destination
                dest_sources = DESTINATIONS[dest_info["name"]]["SOURCES"]
                startup_message += f"📝 **Monitoring {len(dest_sources)} sources:**\n"

                for source_name, source_info in dest_sources.items():
                    source_id = source_info["SOURCE"]
                    if (
                        source_id in all_sources
                        and "display_name" in all_sources[source_id]
                    ):
                        startup_message += f"• **[{all_sources[source_id]['display_name']}]({all_sources[source_id].get('link', '')})**\n"

                startup_message += "\n"

                for source_name, source_info in dest_sources.items():
                    source_id = source_info["SOURCE"]
                    if (
                        source_id in all_sources
                        and "display_name" in all_sources[source_id]
                    ):
                        display_name = all_sources[source_id]["display_name"]
                        keyword_sample = ", ".join(source_info["KEYWORDS"])
                        startup_message += f"✅ **[{display_name}]({all_sources[source_id].get('link', '')}) Keywords:** {keyword_sample}\n"
                        startup_message += (
                            f"**Total Keywords:** {len(source_info['KEYWORDS'])}\n\n"
                        )

                await client.send_message(dest_id, startup_message)
                print(f"✅ Startup message sent to {dest_info['name']}")
            except Exception as e:
                print(f"⚠️ Could not send startup message to {dest_info['name']}: {e}")

        # Start the periodic message checker
        print("✅ Bot is running and ready to check for messages!")
        await periodic_message_checker()

    except Exception as e:
        print(f"❌ Fatal error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
