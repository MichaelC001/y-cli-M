import json
import hashlib
import os
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional
from .cli.models import Chat, Message
from chat.file_repository import FileRepository
from .config import DATA_FILE, OPENROUTER_IMPORT_DIR, OPENROUTER_IMPORT_HISTORY

def format_timestamp(ts: str) -> str:
    """Format timestamp to ISO 8601 format with UTC+8 timezone."""
    # Parse timestamp and ensure it has timezone info
    dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    # Convert to UTC+8
    tz_offset = timedelta(hours=8)
    dt = dt.astimezone(timezone(tz_offset))
    return dt.strftime('%Y-%m-%dT%H:%M:%S%z').replace('+0800', '+08:00')

def generate_short_id(timestamp: str) -> str:
    """Generate a 6-digit shasum from timestamp."""
    sha = hashlib.sha1(timestamp.encode()).hexdigest()
    return sha[:6]

def calculate_file_md5(filepath: str) -> str:
    """Calculate MD5 hash of a file."""
    md5_hash = hashlib.md5()
    with open(filepath, "rb", encoding="utf-8") as f:
        # Read file in chunks to handle large files
        for chunk in iter(lambda: f.read(4096), b""):
            md5_hash.update(chunk)
    return md5_hash.hexdigest()

def read_import_history() -> Dict[str, str]:
    """Read import history from file."""
    history = {}
    if os.path.exists(OPENROUTER_IMPORT_HISTORY):
        with open(OPENROUTER_IMPORT_HISTORY, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    try:
                        entry = json.loads(line)
                        history[entry['filename']] = entry['md5']
                    except (json.JSONDecodeError, KeyError):
                        continue
    return history

def write_import_history(filename: str, md5_hash: str) -> None:
    """Write import history entry."""
    entry = {
        'filename': filename,
        'md5': md5_hash,
        'imported_at': datetime.now(timezone.utc).isoformat()
    }
    os.makedirs(os.path.dirname(OPENROUTER_IMPORT_HISTORY), exist_ok=True)
    with open(OPENROUTER_IMPORT_HISTORY, 'a', encoding='utf-8') as f:
        json.dump(entry, f, ensure_ascii=False)
        f.write('\n')

def is_file_processed(filename: str, md5_hash: str) -> bool:
    """Check if file was already processed with same hash."""
    history = read_import_history()
    return filename in history and history[filename] == md5_hash

def list_import_files() -> List[str]:
    """List all JSON files in import directory."""
    if not os.path.exists(OPENROUTER_IMPORT_DIR):
        return []
    files = []
    for entry in os.scandir(OPENROUTER_IMPORT_DIR):
        if entry.is_file() and entry.name.endswith('.json'):
            files.append(entry.path)
    return files

def extract_new_chats(input_file: str) -> List[Chat]:
    """Convert OpenRouter export JSON to Chat objects."""
    repo = FileRepository()
    existing_ids = {chat.id for chat in repo._read_chats()}
    output_chats = []
    with open(input_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    input_list = data.get('openrouter:playground:v1', [])
    for item in input_list:
        # skip if "key": "chat:threads"
        if 'key' in item and item['key'] == 'chat:threads':
            continue
        if 'value' not in item:
            continue

        # Skip if only 1 message and user content is empty
        if len(item['value'].items()) == 1:
            msg_id, msg_data = next(iter(item['value'].items()))
            if msg_data.get('characterId', '').startswith('char-') == False and not msg_data.get('content', ''):
                continue

        # Get timestamps from messages
        timestamps = []
        for msg_id, msg_data in item['value'].items():
            if 'updatedAt' in msg_data:
                timestamps.append(msg_data['updatedAt'])

        # Use earliest timestamp for thread
        thread_timestamp = min(timestamps) if timestamps else None
        if not thread_timestamp:
            print(item)
            print("No timestamp found for thread, skipping.")
            continue

        # Create thread ID using timestamp
        thread_id = generate_short_id(thread_timestamp)

        # Process messages in the thread
        messages = []
        for msg_id, msg_data in item['value'].items():
            message = {
                "timestamp": format_timestamp(msg_data.get('updatedAt')),
                "role": "assistant" if msg_data.get('characterId', '').startswith('char-') else "user",
                "content": msg_data.get('content', ''),
                "id": msg_id
            }

            # Add provider and model from metadata if present for assistant messages
            if message['role'] == 'assistant' and 'metadata' in msg_data:
                metadata = msg_data['metadata']
                if 'provider' in metadata:
                    message['provider'] = metadata['provider']
                if 'variantSlug' in metadata:
                    message['model'] = metadata['variantSlug']

            messages.append(message)

        # Sort messages by timestamp in ascending order
        messages.sort(key=lambda x: x['timestamp'])

        # Create Chat object
        chat = Chat(
            id=thread_id,
            create_time=format_timestamp(thread_timestamp),
            update_time=format_timestamp(max(timestamps)),
            messages=[Message(**msg) for msg in messages]
        )

        # Skip if thread ID already exists
        if chat.id in existing_ids:
            continue

        output_chats.append(chat)

    return output_chats

def process_import_files() -> None:
    """Process all files in import directory."""
    repo = FileRepository()
    existing_chats = repo._read_chats()
    processed_count = 0
    skipped_count = 0

    for import_file in list_import_files():
        filename = os.path.basename(import_file)
        md5 = calculate_file_md5(import_file)

        if is_file_processed(filename, md5):
            skipped_count += 1
            continue

        new_chats = extract_new_chats(import_file)
        existing_chats.extend(new_chats)
        processed_count += len(new_chats)

        # Record successful import
        write_import_history(filename, md5)

    if processed_count > 0:
        # Sort all chats by create_time
        existing_chats.sort(key=lambda x: x.create_time)
        # Write back to data file
        repo._write_chats(existing_chats)

    print(f"Import completed. Processed {processed_count} new chats, skipped {skipped_count} files.")

if __name__ == '__main__':
    process_import_files()
