# -*- coding: utf-8 -*-
"""
ChatGPT Chat History To Notion


Simple Usage:
1. pip install requests tqdm
2. Fill in your API key and database ID in the configuration section at the top of the script
3. python import_chatgpt_en.py

Detailed documentation: https://github.com/Pls-1q43/ChatGPT-Full-Log-To-Notion/
"""

import json
import requests
import datetime
import time
import os
import mimetypes
import sys
import tempfile
from tqdm import tqdm
import re

# --- Configuration Section ---
# Please fill in your configuration information below

# 1. Your Notion Integration Token (API Key)
# How to get: https://www.notion.so/my-integrations (a string starting with ntn_)
NOTION_API_KEY = ""

# 2. Your Notion Database ID  
# How to get: Copy from database URL (e.g., if URL is: https://www.notion.so/223ca795c956806f84b8da595d3647d6, then fill in 223ca795c956806f84b8da595d3647d6)
NOTION_DATABASE_ID = ""

# 3. ChatGPT Export Folder Path (optional, defaults to current directory)
CHATGPT_EXPORT_PATH = "./"

# === New: Image Upload Debug Switch ===
DEBUG_IMAGE_UPLOAD = False  # Set to True or use environment variable DEBUG_IMAGE_UPLOAD=1 to enable

# === New: Quick Test Mode Switch ===
QUICK_TEST_MODE = False  # Full import mode; for temporary debugging use environment variable QUICK_TEST=1
QUICK_TEST_LIMIT_PER_TYPE = 5  # Maximum number of items to process per type (image/Canvas)

def validate_config():
    """Validate that necessary configuration exists"""
    if not NOTION_API_KEY:
        print("❌ Error: Please fill in NOTION_API_KEY!")
        print("Please fill in your Notion API key in the configuration section at the top of the script")
        print("How to get: https://www.notion.so/my-integrations")
        return False
    
    if not NOTION_DATABASE_ID:
        print("❌ Error: Please fill in NOTION_DATABASE_ID!")
        print("Please fill in your Notion database ID in the configuration section at the top of the script")
        print("How to get: Copy the ID part from the database URL")
        return False
    
    if len(NOTION_API_KEY) < 10 or not NOTION_API_KEY.startswith(('ntn_', 'secret_')):
        print("❌ Error: NOTION_API_KEY format is incorrect!")
        print("API key should start with 'ntn_' or 'secret_'")
        return False
        
    if len(NOTION_DATABASE_ID) != 32:
        print("❌ Error: NOTION_DATABASE_ID format is incorrect!")
        print("Database ID should be a 32-character string")
        return False
    
    return True

def get_database_info(headers, database_id):
    """Get database information and check property structure"""
    try:
        response = requests.get(
            f"{NOTION_API_BASE_URL}/databases/{database_id}",
            headers=headers,
            timeout=30
        )
        response.raise_for_status()
        db_info = response.json()
        
        properties = db_info.get('properties', {})
        
        # Find various types of properties
        title_property = None
        created_time_property = None
        updated_time_property = None
        conversation_id_property = None
        conversation_id_type = None
        
        for prop_name, prop_info in properties.items():
            prop_type = prop_info.get('type')
            prop_name_lower = prop_name.lower()
            
            if prop_type == 'title':
                title_property = prop_name
            elif prop_type in ['date', 'created_time']:
                if 'created' in prop_name_lower or 'create' in prop_name_lower:
                    created_time_property = prop_name
                elif 'updated' in prop_name_lower or 'update' in prop_name_lower or 'modified' in prop_name_lower:
                    updated_time_property = prop_name
            elif prop_type in ['rich_text', 'number']:
                if ('conversation' in prop_name_lower and 'id' in prop_name_lower) or prop_name_lower == 'conversation id':
                    conversation_id_property = prop_name
                    conversation_id_type = prop_type
        
        return {
            'title_property': title_property or 'Title',
            'created_time_property': created_time_property,
            'updated_time_property': updated_time_property, 
            'conversation_id_property': conversation_id_property,
            'conversation_id_type': conversation_id_type,
            'properties': properties
        }
        
    except requests.exceptions.RequestException as e:
        error_msg = e.response.text if e.response else str(e)
        print(f"⚠️ Warning: Unable to get database information: {error_msg}")
        return {
            'title_property': 'Title',
            'created_time_property': None,
            'updated_time_property': None,
            'conversation_id_property': None,
            'properties': {}
        }

# --- Global Variables ---
CONVERSATIONS_JSON_PATH = os.path.join(CHATGPT_EXPORT_PATH, 'conversations.json')
NOTION_API_BASE_URL = "https://api.notion.com/v1"
PROCESSED_LOG_FILE = 'processed_ids.log'
MAX_TEXT_LENGTH = 1000  # Maximum text block length limit for Notion (reduced to avoid 400 errors)
MAX_TRAVERSE_DEPTH = 1000  # Maximum traversal depth to prevent infinite loops
DEBUG_FIRST_FAILURE = True  # Debug mode: show detailed information for first failed request
DEBUG_DETAILED_ERRORS = True  # New: detailed error analysis (disable for production, enable for debugging)

# New: Error analysis function
def analyze_request_payload(payload, title=""):
    """Analyze request payload to identify potential issues that could cause 400 errors"""
    issues = []
    payload_str = json.dumps(payload, ensure_ascii=False)
    
    # Check payload size - lowered threshold
    size = len(payload_str)
    if size > 400000:  # Reduced from 3000 to 2000
        issues.append(f"Payload too large: {size} characters")
    
    # Check for potentially problematic content patterns
    problematic_patterns = [
        (r'open_url\(', "Contains open_url function calls"),
        (r'search\(', "Contains search function calls"),
        (r'https?://[^\s<>"]{50,}', "Contains extra long URLs"),
        (r'["\']I don\'t know["\']', "Contains quoted phrases"),
        (r'["\'][^"\']{100,}["\']', "Contains extra long quoted strings"),
        (r'\\u[0-9a-fA-F]{4}', "Contains Unicode escape sequences"),
        (r'\{[^}]{200,}\}', "Contains extra long JSON objects"),
        (r'Fatal error:|Warning:|Exception:', "Contains error logs"),
        (r'👤|🤖|🔍|💬', "Contains emoji characters"),
    ]
    
    for pattern, description in problematic_patterns:
        if re.search(pattern, payload_str):
            matches = len(re.findall(pattern, payload_str))
            issues.append(f"{description} ({matches} occurrences)")
    
    # Check nesting depth
    if payload_str.count('{') > 20:
        issues.append(f"JSON nesting too deep: {payload_str.count('{')} levels")
    
    # Check special characters
    special_chars = ['"', "'", '\\', '\n', '\t']
    for char in special_chars:
        count = payload_str.count(char)
        if count > 50:
            issues.append(f"Too many special characters '{char}': {count} instances")
    
    return issues

# New: Failed payload analyzer
def debug_failed_payload(payload, error_response, title):
    """Analyze failed payload in detail"""
    if not DEBUG_DETAILED_ERRORS:
        return
    
    print(f"\n🔍 Detailed analysis of failed payload: {title}")
    
    # Analyze payload issues
    issues = analyze_request_payload(payload, title)
    if issues:
        print("   🚨 Issues found:")
        for i, issue in enumerate(issues[:10], 1):  # Show up to 10 issues
            print(f"      {i}. {issue}")
    
    # Analyze error response
    if error_response:
        try:
            error_detail = error_response.json()
            print("   📋 API error details:")
            print(f"      Status code: {error_response.status_code}")
            if 'message' in error_detail:
                print(f"      Message: {error_detail['message']}")
            if 'code' in error_detail:
                print(f"      Error code: {error_detail['code']}")
        except:
            print(f"   📋 Raw error: {error_response.text[:200]}...")
    
    # Extract and show problematic blocks
    if 'children' in payload:
        print("   📦 Problematic block analysis:")
        for i, block in enumerate(payload['children'][:3], 1):
            block_str = json.dumps(block, ensure_ascii=False)
            block_issues = analyze_request_payload({'block': block})
            print(f"      Block{i} ({len(block_str)} chars): {', '.join(block_issues) if block_issues else 'No issues found'}")
    
    print("   " + "="*50)

# --- Helper Functions ---
def load_processed_ids():
    """Load processed conversation IDs for resume functionality"""
    if not os.path.exists(PROCESSED_LOG_FILE):
        return set()
    try:
        with open(PROCESSED_LOG_FILE, 'r', encoding='utf-8') as f:
            return {line.strip() for line in f if line.strip()}
    except Exception as e:
        print(f"Warning: Unable to read log file: {e}")
        return set()

def log_processed_id(conversation_id):
    """Log successfully processed conversation ID"""
    try:
        with open(PROCESSED_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(f"{conversation_id}\n")
    except Exception as e:
        print(f"Warning: Unable to write to log file: {e}")

def split_long_text(text, max_length=MAX_TEXT_LENGTH):
    """Split long text into chunks that comply with Notion limits"""
    if len(text) <= max_length:
        return [text]
    
    chunks = []
    current_pos = 0
    
    while current_pos < len(text):
        end_pos = current_pos + max_length
        if end_pos >= len(text):
            chunks.append(text[current_pos:])
            break
        
        # Try to split at sentence or paragraph boundaries
        best_split = end_pos
        for i in range(max(current_pos, end_pos - 100), end_pos):
            if text[i] in '.。\n!！?？':
                best_split = i + 1
                break
        
        chunks.append(text[current_pos:best_split])
        current_pos = best_split
    
    return chunks

def upload_file_to_notion(local_file_path, headers):
    """Upload files to Notion, supports images and other attachments (enhanced multi-path search)"""

    def find_local_file(path_or_name: str) -> str | None:
        """Find files in common subdirectories (images/ dalle-generations/)"""
        if os.path.isabs(path_or_name) and os.path.exists(path_or_name):
            return path_or_name

        # Remove possible prefix "./" and normalize path
        if path_or_name.startswith("./") or path_or_name.startswith(".\\"):
            path_or_name = path_or_name[2:]

        # Use normalized name for further processing
        abs_path = os.path.join(CHATGPT_EXPORT_PATH, path_or_name)
        if os.path.exists(abs_path):
            return abs_path

        # Common subdirectories
        basename_only = os.path.basename(path_or_name)
        for sub in ["images", "assets", "dalle-generations", "dalle_generations"]:
            candidate = os.path.join(CHATGPT_EXPORT_PATH, sub, basename_only)
            if os.path.exists(candidate):
                return candidate

        # First round: general rules for file- prefix
        if basename_only.startswith("file-"):
            prefix = basename_only.split('.')[0]  # file-XXXXXX
            for root, _dirs, files in os.walk(CHATGPT_EXPORT_PATH):
                for fname in files:
                    if fname.startswith(prefix):
                        return os.path.join(root, fname)

        # Second round: more general prefix matching (not limited to file- prefix),
        # to handle cases like "image-XXX.png" or "pic_XXX.jpg" in root directory
        generic_prefix = os.path.splitext(basename_only)[0]
        if len(generic_prefix) > 3:  # Avoid too short prefixes causing mismatches
            for root, _dirs, files in os.walk(CHATGPT_EXPORT_PATH):
                for fname in files:
                    if fname.startswith(generic_prefix):
                        return os.path.join(root, fname)

        # Third round: no extension -> try common image extensions
        if '.' not in basename_only:
            COMMON_EXTS = ['png', 'jpg', 'jpeg', 'webp', 'gif']
            for ext in COMMON_EXTS:
                candidate = os.path.join(CHATGPT_EXPORT_PATH, f"{basename_only}.{ext}")
                if os.path.exists(candidate):
                    return candidate
                # Also search in common subdirectories
                for sub in ["images", "assets", "dalle-generations", "dalle_generations"]:
                    candidate_sub = os.path.join(CHATGPT_EXPORT_PATH, sub, f"{basename_only}.{ext}")
                    if os.path.exists(candidate_sub):
                        return candidate_sub
        return None

    actual_path = find_local_file(local_file_path)
    if actual_path is None:
        tqdm.write(f"   ⚠️ Image file not found: {local_file_path}")
        return None

    local_file_path = actual_path

    file_name = os.path.basename(local_file_path)
    file_size = os.path.getsize(local_file_path)
    
    # ====== Premium version limit: 20 MB ======
    MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024  # 20MB
    if file_size > MAX_FILE_SIZE_BYTES:
        tqdm.write(f"   ⚠️ File too large (>20MB): {local_file_path}")
        return None

    # ====== MIME type determination ======
    content_type, _ = mimetypes.guess_type(local_file_path)
    # Extension to MIME supplementary mapping
    ext = os.path.splitext(local_file_path)[1].lower().lstrip('.')
    EXT_MIME_MAP = {
        'webp': 'image/webp',
        'heic': 'image/heic',
        'heif': 'image/heic',
        'wav': 'audio/wav',
        'webm': 'video/webm',
    }
    if not content_type and ext in EXT_MIME_MAP:
        content_type = EXT_MIME_MAP[ext]
    if not content_type:
        content_type = 'application/octet-stream'

    # ====== Magic bytes detection (handle files without extensions and supplement MIME) ======
    if content_type == 'application/octet-stream':
        try:
            with open(local_file_path, 'rb') as fb:
                header = fb.read(20)
            def _match(hdr: bytes, sig: bytes, offset: int = 0):
                return hdr.startswith(sig) if offset == 0 else hdr[offset:offset+len(sig)] == sig

            mime_ext = None
            if _match(header, b'\x89PNG'):
                content_type, mime_ext = 'image/png', 'png'
            elif _match(header, b'\xFF\xD8\xFF'):
                content_type, mime_ext = 'image/jpeg', 'jpg'
            elif header[:6] in (b'GIF87a', b'GIF89a'):
                content_type, mime_ext = 'image/gif', 'gif'
            elif header[:4] == b'RIFF' and b'WEBP' in header[8:16]:
                content_type, mime_ext = 'image/webp', 'webp'
            elif _match(header, b'%PDF'):
                content_type, mime_ext = 'application/pdf', 'pdf'
            elif header[:4] == b'RIFF' and b'WAVE' in header[8:16]:
                content_type, mime_ext = 'audio/wav', 'wav'
            elif header[4:8] == b'ftyp':
                content_type, mime_ext = 'video/mp4', 'mp4'

            # If filename has no extension and recognition succeeds, add extension (only affects upload filename, not disk file)
            if mime_ext and '.' not in file_name:
                file_name += f'.{mime_ext}'
        except Exception:
            pass

    # ====== Supported MIME whitelist ======
    ALLOWED_MIME = {
        # Images
        'image/jpeg','image/jpg','image/png','image/gif','image/webp','image/svg+xml','image/tiff','image/heic','image/vnd.microsoft.icon',
        # Documents
        'application/pdf','text/plain','application/json',
        # Audio
        'audio/mpeg','audio/mp4','audio/aac','audio/midi','audio/ogg','audio/wav','audio/x-ms-wma',
        # Video
        'video/mp4','video/webm','video/quicktime','video/x-msvideo','video/x-flv','video/mpeg','video/x-ms-asf','video/x-amv'
    }
    if content_type not in ALLOWED_MIME:
        tqdm.write(f"   ⚠️ Unsupported MIME type({content_type}), skipping: {file_name}")
        return None

    # Debug: show file preparation info
    if DEBUG_IMAGE_UPLOAD or os.getenv("DEBUG_IMAGE_UPLOAD") == "1":
        tqdm.write(f"   [DEBUG] Preparing upload: {file_name} | size={round(file_size/1024,1)}KB | mime={content_type}")

    # Step 1: Request upload URL from Notion
    upload_url = f"{NOTION_API_BASE_URL}/file_uploads"
    payload = {
        "filename": file_name,
        "content_type": content_type
    }
    
    try:
        response = requests.post(upload_url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        upload_data = response.json()
        
        # Debug: output upload return info
        if DEBUG_IMAGE_UPLOAD or os.getenv("DEBUG_IMAGE_UPLOAD") == "1":
            tqdm.write(f"   [DEBUG] Upload response: {json.dumps(upload_data, ensure_ascii=False)}")
        
        # Step 2: Upload file content to received URL
        with open(local_file_path, 'rb') as f:
            file_bytes = f.read()

        base_upload_headers = {
            "Content-Type": content_type,
            "Content-Length": str(file_size)
        }

        upload_url = upload_data["upload_url"]

        # If upload_url contains /send, use POST with authorization as required by Notion API
        if "/send" in upload_url:
            # Use multipart/form-data, requests automatically generates boundary and Content-Type
            upload_headers = {
                "Authorization": headers.get("Authorization", ""),
                "Notion-Version": headers.get("Notion-Version", "2022-06-28")
            }

            files = {
                "file": (file_name, file_bytes, content_type)
            }

            response = requests.post(
                upload_url,
                headers=upload_headers,
                files=files,
                timeout=120
            )
        else:
            # Pre-signed S3 URL, use PUT without authorization
            response = requests.put(
                upload_url,
                headers=base_upload_headers,
                data=file_bytes,
                timeout=120
            )
        response.raise_for_status()
        
        tqdm.write(f"   ✅ Image upload successful: {file_name}")

        if DEBUG_IMAGE_UPLOAD or os.getenv("DEBUG_IMAGE_UPLOAD") == "1":
            tqdm.write(f"   [DEBUG] FileUpload ID: {upload_data.get('id')}")
        return upload_data["id"]
        
    except requests.exceptions.RequestException as e:
        error_msg = e.response.text if e.response else str(e)
        tqdm.write(f"   ❌ File upload failed: {error_msg}")
        return None

def build_blocks_from_conversation(conversation_data, headers):
    """Build Notion blocks from conversation data with added safety protection"""
    mapping = conversation_data.get('mapping', {})
    if not mapping:
        return []

    # Find root node
    root_id = next((nid for nid, node in mapping.items() if not node.get('parent')), None)
    if not root_id:
        try:
            # If no clear root node, find earliest message as starting point
            root_id = min(mapping.keys(), 
                         key=lambda k: mapping[k].get('message', {}).get('create_time', float('inf')))
        except (ValueError, TypeError):
            return []

    blocks = []
    current_id = root_id
    visited = set()  # Prevent infinite loops
    depth = 0
    
    # Canvas document deduplication set (by textdoc_id)
    seen_canvas_docs = set()
    
    # Safe traversal of conversation tree
    while current_id in mapping and current_id not in visited and depth < MAX_TRAVERSE_DEPTH:
        visited.add(current_id)
        depth += 1
        
        node = mapping.get(current_id, {})
        message = node.get('message')

        if message and isinstance(message.get('metadata'), dict) and 'canvas' in message['metadata']:
            canvas_meta = message['metadata']['canvas']
            textdoc_id = canvas_meta.get('textdoc_id')
            if textdoc_id and textdoc_id not in seen_canvas_docs:
                seen_canvas_docs.add(textdoc_id)

                canvas_title = canvas_meta.get('title') or canvas_meta.get('textdoc_type', 'Canvas')
                canvas_type = canvas_meta.get('textdoc_type', 'document')
                canvas_version = canvas_meta.get('version')

                desc_lines = [f"Canvas Module -> Title: {canvas_title}"]
                desc_lines.append(f"Type: {canvas_type} | Version: {canvas_version} | ID: {textdoc_id}")

                desc_text = "\n".join(filter(None, desc_lines))

                for chunk in split_long_text(desc_text):
                    block = {
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [{"type": "text", "text": {"content": chunk}}]
                        }
                    }
                    validated_block = validate_block_content(block)
                    if validated_block:
                        blocks.append(validated_block)

        if message and message.get('content'):
            author_role = message.get('author', {}).get('role', 'unknown')
            
            # Role mapping
            speaker_map = {
                "user": "👤 User",
                "assistant": "🤖 Assistant", 
                "tool": f"🛠️ Tool ({message.get('author', {}).get('name', '')})",
                "system": "⚙️ System"
            }
            speaker_raw = speaker_map.get(author_role, "❓ Unknown")

            # Convert "👤 User" format to "[👤]User:" prefix
            def format_speaker_label(raw: str) -> str:
                if ' ' in raw:
                    emoji_part, name_part = raw.split(' ', 1)
                    return f"[{emoji_part}]{name_part}:"
                # fallback
                return f"[{raw}]:"

            speaker_label = format_speaker_label(speaker_raw)

            content = message['content']
            content_type = content.get('content_type')
            
            # Handle plain text content
            if content_type == 'text' and content.get('parts'):
                full_content = "".join(part for part in content['parts'] if isinstance(part, str))
                if full_content.strip():
                    # Handle long text splitting
                    text_chunks = split_long_text(f"{speaker_label}\n{full_content}")
                    for chunk in text_chunks:
                        block = {
                            "type": "paragraph",
                            "paragraph": {
                                "rich_text": [{"type": "text", "text": {"content": chunk}}]
                            }
                        }
                        validated_block = validate_block_content(block)
                        if validated_block:
                            blocks.append(validated_block)
            
            # Handle multimodal content (text + images)
            elif content_type == 'multimodal_text':
                # First handle text part
                prompt_text = "".join(part for part in content['parts'] if isinstance(part, str))
                if prompt_text.strip():
                    text_chunks = split_long_text(f"{speaker_label}\n{prompt_text}")
                    for chunk in text_chunks:
                        block = {
                            "type": "paragraph",
                            "paragraph": {
                                "rich_text": [{"type": "text", "text": {"content": chunk}}]
                            }
                        }
                        validated_block = validate_block_content(block)
                        if validated_block:
                            blocks.append(validated_block)
                
                # Handle image part
                for part in content['parts']:
                    if isinstance(part, dict) and part.get('content_type') == 'image_asset_pointer':
                        asset_pointer = part.get('asset_pointer', '')
                        if asset_pointer.startswith('file-service://'):
                            file_name = asset_pointer.split('/')[-1]
                            if file_name:
                                local_image_path = os.path.join(CHATGPT_EXPORT_PATH, file_name)
                                file_upload_id = upload_file_to_notion(local_image_path, headers)
                                if file_upload_id:
                                    if DEBUG_IMAGE_UPLOAD or os.getenv("DEBUG_IMAGE_UPLOAD") == "1":
                                        tqdm.write(f"   [DEBUG] Building image block, id={file_upload_id}")
                                    blocks.append({
                                        "type": "image",
                                        "image": {
                                            "type": "file_upload",
                                            "file_upload": {"id": file_upload_id}
                                        }
                                    })

            # Handle code blocks
            elif content_type == 'code' and content.get('text'):
                # Add speaker identification
                speaker_block = {
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"type": "text", "text": {"content": speaker_label}}]
                    }
                }
                validated_speaker_block = validate_block_content(speaker_block)
                if validated_speaker_block:
                    blocks.append(validated_speaker_block)
                
                # Handle long code splitting
                code_chunks = split_long_text(content['text'])
                for chunk in code_chunks:
                    code_block = {
                        "type": "code",
                        "code": {
                            "rich_text": [{"type": "text", "text": {"content": chunk}}],
                            "language": get_safe_language_type(content.get('language'))
                        }
                    }
                    validated_code_block = validate_block_content(code_block)
                    if validated_code_block:
                        blocks.append(validated_code_block)

            # Handle system errors
            elif content_type == 'system_error' and content.get('text'):
                error_text = f"{speaker_label}\n❗️ System Error: {content.get('text')}"
                text_chunks = split_long_text(error_text)
                for chunk in text_chunks:
                    error_block = {
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [{"type": "text", "text": {"content": chunk}}]
                        }
                    }
                    validated_error_block = validate_block_content(error_block)
                    if validated_error_block:
                        blocks.append(validated_error_block)

        # Move to next node
        children = node.get('children', [])
        current_id = children[0] if children and isinstance(children, list) else None
    
    # Warning: if maximum depth reached
    if depth >= MAX_TRAVERSE_DEPTH:
        tqdm.write(f"   ⚠️ Warning: Reached maximum traversal depth ({MAX_TRAVERSE_DEPTH}), conversation may be incomplete")
    
    return blocks

def import_conversation_to_notion(title, create_time, update_time, conversation_id, all_blocks, headers, database_id, db_info):
    """Import single conversation to Notion database"""
    if not all_blocks:
        tqdm.write(f"   - Skipping empty conversation: {title}")
        return True

    # Limit title length to avoid Notion API errors
    if len(title) > 100:
        title = title[:97] + "..."
    
    # Clean title content
    title = clean_text_content(title)

    # Validate and clean all block content
    cleaned_blocks = []
    for block in all_blocks:
        validated_block = validate_block_content(block)
        if validated_block:
            # Additional check: if single block JSON representation is too large, split further instead of skipping
            block_json_size = len(json.dumps(validated_block, ensure_ascii=False))
            if block_json_size > 1000:  # Blocks that need further splitting
                tqdm.write(f"   - 🔄 Splitting oversized block ({block_json_size} characters)")
                
                # Get block text content for splitting
                if validated_block['type'] == 'paragraph':
                    original_content = validated_block['paragraph']['rich_text'][0]['text']['content']
                    # Split content into smaller blocks
                    smaller_chunks = split_long_text(original_content, max_length=800)
                    for chunk in smaller_chunks:
                        if chunk.strip():
                            smaller_block = {
                                "type": "paragraph",
                                "paragraph": {
                                    "rich_text": [{"type": "text", "text": {"content": chunk}}]
                                }
                            }
                            cleaned_blocks.append(smaller_block)
                elif validated_block['type'] == 'code':
                    original_content = validated_block['code']['rich_text'][0]['text']['content']
                    language = validated_block['code']['language']
                    # Split code into smaller blocks
                    smaller_chunks = split_long_text(original_content, max_length=800)
                    for chunk in smaller_chunks:
                        if chunk.strip():
                            smaller_block = {
                                "type": "code",
                                "code": {
                                    "rich_text": [{"type": "text", "text": {"content": chunk}}],
                                    "language": language
                                }
                            }
                            cleaned_blocks.append(smaller_block)
                else:
                    # Other types like image blocks are added directly
                    cleaned_blocks.append(validated_block)
            else:
                cleaned_blocks.append(validated_block)
    
    if not cleaned_blocks:
        tqdm.write(f"   - Skipping empty conversation (no valid blocks after cleaning): {title}")
        return True

    # Debug info: show block count before and after cleaning
    tqdm.write(f"   - Debug: Original blocks {len(all_blocks)} -> Cleaned blocks {len(cleaned_blocks)}")

    # ========== New strategy: Create empty page first, then append all blocks ==========
    # No children when creating page, greatly reduces 400 error probability
    initial_blocks: list = []  # Keep empty list
    remaining_blocks: list = cleaned_blocks  # All content to be appended later in batches

    # Split remaining blocks into smaller batches (max 20 per batch)
    block_chunks = [remaining_blocks[i:i + 20] for i in range(0, len(remaining_blocks), 20)]
    initial_payload_size = 0  # Empty payload
    tqdm.write(f"   - Chunking strategy: Create empty page, then {len(block_chunks)} batches to append")

    # Use detected property names
    title_property = db_info.get('title_property', 'Title')
    created_time_property = db_info.get('created_time_property')
    updated_time_property = db_info.get('updated_time_property')
    conversation_id_property = db_info.get('conversation_id_property')
    conversation_id_type = db_info.get('conversation_id_type')

    # Create page payload - use detected complete property structure
    properties = {
        title_property: {"title": [{"type": "text", "text": {"content": title}}]}
    }

    # Only write when property is truly writable "date" type, avoid modifying "created_time" / "last_edited_time" read-only fields
    if created_time_property:
        prop_info = db_info.get('properties', {}).get(created_time_property, {})
        if prop_info.get('type') == 'date':
            properties[created_time_property] = {
                "date": {"start": datetime.datetime.fromtimestamp(create_time).isoformat() + "Z"}
            }
    if updated_time_property:
        prop_info = db_info.get('properties', {}).get(updated_time_property, {})
        if prop_info.get('type') == 'date':
            properties[updated_time_property] = {
                "date": {"start": datetime.datetime.fromtimestamp(update_time).isoformat() + "Z"}
            }

    # Add conversation ID property (if exists)
    if conversation_id_property:
        if conversation_id_type == 'number':
            try:
                if conversation_id.replace('-', '').isdigit():
                    number_value = int(conversation_id.replace('-', ''))
                else:
                    number_value = abs(hash(conversation_id)) % (10 ** 10)
                properties[conversation_id_property] = {"number": number_value}
            except (ValueError, TypeError):
                number_value = abs(hash(conversation_id)) % (10 ** 10)
                properties[conversation_id_property] = {"number": number_value}
        else:
            properties[conversation_id_property] = {
                "rich_text": [{"type": "text", "text": {"content": conversation_id}}]
            }

    create_payload = {
        "parent": {"database_id": database_id},
        "properties": properties
    }

    # Create page
    try:
        response = requests.post(
            f"{NOTION_API_BASE_URL}/pages",
            headers=headers,
            data=json.dumps(create_payload),
            timeout=30
        )
        response.raise_for_status()
        page_data = response.json()
        page_id = page_data["id"]
        tqdm.write(f"   - ✅ Page created successfully: {title}")
    except requests.exceptions.RequestException as e:
        global DEBUG_FIRST_FAILURE
        error_msg = ""
        if e.response:
            try:
                error_detail = e.response.json()
                error_msg = json.dumps(error_detail, indent=2, ensure_ascii=False)
            except:
                error_msg = e.response.text
        else:
            error_msg = str(e)
        
        tqdm.write(f"   - ❌ Page creation failed: {title}")
        tqdm.write(f"   - HTTP status code: {e.response.status_code if e.response else 'N/A'}")
        tqdm.write(f"   - Detailed error: {error_msg}")
        
        # 🎯 New: Use new error analyzer
        debug_failed_payload(create_payload, e.response, title)
        
        # Debug mode: show complete payload for first failed request
        if DEBUG_FIRST_FAILURE:
            tqdm.write(f"   - 🐛 Debug payload (first failure):")
            tqdm.write(f"     Title: {title}")
            tqdm.write(f"     Block count: {len(initial_blocks)}")
            
            # Show structure of first 3 blocks
            for i, block in enumerate(initial_blocks[:3]):
                tqdm.write(f"     Block {i+1}: {json.dumps(block, ensure_ascii=False, indent=4)}")
            
            if len(initial_blocks) > 3:
                tqdm.write(f"     ... {len(initial_blocks)-3} more blocks")
            
            # Show complete properties section
            tqdm.write(f"     Properties: {json.dumps(properties, ensure_ascii=False, indent=4)}")
            
            DEBUG_FIRST_FAILURE = False  # Only show detailed info for first failure
        elif len(str(create_payload)) < 2000:  # Avoid outputting too long payloads
            tqdm.write(f"   - Request payload: {json.dumps(create_payload, indent=2, ensure_ascii=False)}")
        else:
            tqdm.write(f"   - Payload size: {len(str(create_payload))} characters (too long, omitted)")
            tqdm.write(f"   - Block count: {len(initial_blocks)}")
        
        # Try creating simplified version (title only, no content blocks)
        try:
            tqdm.write(f"   - 🔄 Trying to create simplified version (title only)...")
            
            # Further simplify title, remove potentially problematic characters
            safe_title = re.sub(r'[^\w\s\-\u4e00-\u9fff]', '', title)  # Only keep alphanumeric, Chinese, and basic symbols
            if len(safe_title.strip()) < 2:
                safe_title = f"Conversation_{conversation_id[:8]}"  # Use conversation ID if title cleaned too much
            
            safe_properties = {
                title_property: {"title": [{"type": "text", "text": {"content": safe_title}}]}
            }
            
            # Try not adding time and conversation ID, only create most basic page
            simple_payload = {
                "parent": {"database_id": database_id},
                "properties": safe_properties
            }
            
            response = requests.post(
                f"{NOTION_API_BASE_URL}/pages",
                headers=headers,
                data=json.dumps(simple_payload),
                timeout=30
            )
            response.raise_for_status()
            page_data = response.json()
            page_id = page_data["id"]
            tqdm.write(f"   - ✅ Simplified version created successfully: {safe_title}")
            
            # Then try updating properties (separate request reduces failure risk)
            try:
                time.sleep(0.3)
                update_properties = {}
                
                # Add properties one by one, failure doesn't affect others
                if created_time_property:
                    try:
                        update_properties[created_time_property] = {
                            "date": {"start": datetime.datetime.fromtimestamp(create_time).isoformat() + "Z"}
                        }
                    except:
                        pass
                
                if conversation_id_property and conversation_id_type == 'number':
                    try:
                        number_value = abs(hash(conversation_id)) % (10**8)  # Smaller number
                        update_properties[conversation_id_property] = {"number": number_value}
                    except:
                        pass
                
                if update_properties:
                    requests.patch(
                        f"{NOTION_API_BASE_URL}/pages/{page_id}",
                        headers=headers,
                        data=json.dumps({"properties": update_properties}),
                        timeout=30
                    )
            except:
                pass  # Property update failure is ok, at least page was created
            
            # Try adding a simple note block
            try:
                time.sleep(0.3)
                note_block = {
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"type": "text", "text": {"content": "Original content encountered formatting issues during import, empty page created."}}]
                    }
                }
                
                requests.patch(
                    f"{NOTION_API_BASE_URL}/blocks/{page_id}/children",
                    headers=headers,
                    data=json.dumps({"children": [note_block]}),
                    timeout=30
                )
                
            except:
                pass  # Note block failure is ok too
            
            return True  # Simplified version counts as success
            
        except requests.exceptions.RequestException as e:
            error_msg = e.response.text if e.response else str(e)
            tqdm.write(f"   - ❌ Simplified version also failed: {error_msg}")
            return False

    # If there are remaining content blocks, append in batches
    if block_chunks and any(block_chunks):  # Check if there are non-empty block groups
        tqdm.write(f"   - 💬 Detected long conversation, appending remaining content ({len(block_chunks)} batches)...")
        append_url = f"{NOTION_API_BASE_URL}/blocks/{page_id}/children"
        
        for i, chunk in enumerate(block_chunks):
            if not chunk:  # Skip empty block groups
                continue
            
            # Validate batch content
            validated_chunk = []
            chunk_json_size = 0
            
            for block in chunk:
                # Re-validate each block
                validated_block = validate_block_content(block)
                if validated_block:
                    block_size = len(json.dumps(validated_block, ensure_ascii=False))
                    
                    # If single block too large, split it instead of skipping
                    if block_size > 1000:
                        tqdm.write(f"   -   ...🔄 Splitting oversized block ({block_size} characters)")
                        
                        # Splitting logic
                        if validated_block['type'] == 'paragraph':
                            original_content = validated_block['paragraph']['rich_text'][0]['text']['content']
                            smaller_chunks = split_long_text(original_content, max_length=600)
                            for small_chunk in smaller_chunks:
                                if small_chunk.strip():
                                    smaller_block = {
                                        "type": "paragraph",
                                        "paragraph": {
                                            "rich_text": [{"type": "text", "text": {"content": small_chunk}}]
                                        }
                                    }
                                    smaller_size = len(json.dumps(smaller_block, ensure_ascii=False))
                                    if (chunk_json_size + smaller_size) <= 50000:  # Further reduced
                                        validated_chunk.append(smaller_block)
                                        chunk_json_size += smaller_size
                        elif validated_block['type'] == 'code':
                            original_content = validated_block['code']['rich_text'][0]['text']['content']
                            language = validated_block['code']['language']
                            smaller_chunks = split_long_text(original_content, max_length=600)
                            for small_chunk in smaller_chunks:
                                if small_chunk.strip():
                                    smaller_block = {
                                        "type": "code",
                                        "code": {
                                            "rich_text": [{"type": "text", "text": {"content": small_chunk}}],
                                            "language": language
                                        }
                                    }
                                    smaller_size = len(json.dumps(smaller_block, ensure_ascii=False))
                                    if (chunk_json_size + smaller_size) <= 50000:  # Further reduced
                                        validated_chunk.append(smaller_block)
                                        chunk_json_size += smaller_size
                        else:
                            # Other types (like images) add directly, but check total size
                            if (chunk_json_size + block_size) <= 50000:  # Further reduced
                                validated_chunk.append(validated_block)
                                chunk_json_size += block_size
                    else:
                        # Block size is appropriate, check if it would exceed batch limit
                        if (chunk_json_size + block_size) <= 50000:  # Further reduced
                            validated_chunk.append(validated_block)
                            chunk_json_size += block_size
            
            if not validated_chunk:
                tqdm.write(f"   -   ...⚠️ Batch {i+1} empty after cleaning, skipping")
                continue
                
            try:
                time.sleep(0.5)  # Slightly increase delay
                payload = {"children": validated_chunk}
                payload_size = len(json.dumps(payload, ensure_ascii=False))
                
                # 🎯 Further reduce batch size limit
                if payload_size > 400000:  # Reduced from 2500 to 1500
                    tqdm.write(f"   -   ...⚠️ Batch {i+1} payload too large ({payload_size} characters), skipping")
                    continue
                
                response = requests.patch(
                    append_url,
                    headers=headers,
                    data=json.dumps(payload),
                    timeout=30
                )
                response.raise_for_status()
                tqdm.write(f"   -   ...Batch {i+1}/{len(block_chunks)} appended successfully ({len(validated_chunk)} blocks, {payload_size} characters)")
            except requests.exceptions.RequestException as e:
                error_msg = e.response.text if e.response else str(e)
                tqdm.write(f"   -   ...❌ Batch {i+1}/{len(block_chunks)} append failed: {error_msg}")
                
                # 🎯 New: Analyze append failure reason
                debug_failed_payload(payload, e.response, f"{title} - Batch{i+1}")
                
                # ========== New fallback: try inserting block by block, keep successful ones ==========
                tqdm.write(f"   -   ...⚙️ Fallback to single-block append mode, retrying block by block")
                successful_blocks = 0
                for k, single_block in enumerate(validated_chunk):
                    single_payload = {"children": [single_block]}
                    try:
                        time.sleep(0.4)
                        requests.patch(
                            append_url,
                            headers=headers,
                            data=json.dumps(single_payload),
                            timeout=30
                        ).raise_for_status()
                        successful_blocks += 1
                    except requests.exceptions.RequestException:
                        # ⚠️ If single block still fails, try splitting it into even smaller text (300 chars)
                        # Only handle paragraph / code
                        try:
                            if single_block.get('type') in ('paragraph', 'code'):
                                txt_key = 'paragraph' if single_block['type'] == 'paragraph' else 'code'
                                original_txt = single_block[txt_key]['rich_text'][0]['text']['content']
                                tiny_chunks = split_long_text(original_txt, max_length=300)
                                tiny_success = 0
                                for tiny in tiny_chunks:
                                    tiny_block = {
                                        "type": single_block['type'],
                                        txt_key: {
                                            "rich_text": [{"type": "text", "text": {"content": tiny}}]
                                        }
                                    }
                                    try:
                                        time.sleep(0.2)
                                        requests.patch(
                                            append_url,
                                            headers=headers,
                                            data=json.dumps({"children": [tiny_block]}),
                                            timeout=30
                                        ).raise_for_status()
                                        tiny_success += 1
                                    except requests.exceptions.RequestException:
                                        # If minimal block still fails, give up completely
                                        pass
                                if tiny_success:
                                    successful_blocks += tiny_success  # Count successes
                        except Exception:
                            pass
                        continue
                tqdm.write(f"   -   ...Single-block append completed, successful {successful_blocks}/{len(validated_chunk)} blocks")
                # Don't stop overall flow because of single batch failure
                continue

    return True

def clean_text_content(text):
    """Clean text content, remove characters that might cause API errors"""
    if not isinstance(text, str):
        return str(text)
    
    # Remove control characters (except newline, tab, and carriage return)
    cleaned = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]', '', text)
    
    # Normalize line breaks
    cleaned = cleaned.replace('\r\n', '\n').replace('\r', '\n')
    
    # Handle potentially problematic URLs and special characters
    # Replace special characters that might cause API issues
    cleaned = cleaned.replace('\u2028', '\n').replace('\u2029', '\n\n')  # Line separator and paragraph separator
    
    # New: Clean PHP error logs and technical error information
    # Remove PHP Fatal error and Warning messages
    if 'PHP Fatal error:' in cleaned or 'PHP Warning:' in cleaned or 'PHP Notice:' in cleaned:
        lines = cleaned.split('\n')
        cleaned_lines = []
        skip_next = False
        
        for line in lines:
            # Skip PHP error lines
            if any(error_type in line for error_type in ['PHP Fatal error:', 'PHP Warning:', 'PHP Notice:', 'Stack trace:', 'thrown in']):
                skip_next = True
                continue
            # Skip subsequent error stack lines
            elif skip_next and (line.startswith('#') or line.startswith('  ')):
                continue
            else:
                skip_next = False
                cleaned_lines.append(line)
        
        cleaned = '\n'.join(cleaned_lines)
    
    # New: Clean WordPress HTML content
    # Remove WordPress block comments
    cleaned = re.sub(r'<!-- wp:[^>]+ -->', '', cleaned)
    cleaned = re.sub(r'<!-- /wp:[^>]+ -->', '', cleaned)
    
    # Clean complex attributes in HTML tags
    cleaned = re.sub(r'<([a-zA-Z]+)[^>]*class="[^"]*"[^>]*>', r'<\1>', cleaned)
    cleaned = re.sub(r'<([a-zA-Z]+)[^>]*>', r'<\1>', cleaned)
    
    # New: Handle file path information
    # Remove Linux/Unix file paths
    cleaned = re.sub(r'/[a-zA-Z0-9_/.-]+\.php', '[Path cleaned]', cleaned)
    cleaned = re.sub(r'/home/[a-zA-Z0-9_/.-]+', '[Directory cleaned]', cleaned)
    
    # New: Clean extra long URLs
    # Replace extra long URLs with simplified version
    def replace_long_url(match):
        url = match.group(0)
        if len(url) > 100:
            return url[:50] + '...[URL truncated]'
        return url
    
    cleaned = re.sub(r'https?://[^\s<>"]+', replace_long_url, cleaned)
    
    # New: Remove too many repeated characters
    # Remove excessive consecutive same characters (might be error output)
    cleaned = re.sub(r'(.)\1{10,}', r'\1\1\1[Repeated content cleaned]', cleaned)
    
    # New: Clean search result content
    # Remove ChatGPT search result special format # [0]Title - Website [url]
    cleaned = re.sub(r'# \[\d+\].*?\n', '', cleaned)
    
    # Clean metadata_list structure (search result repeated metadata)
    if '"metadata_list":' in cleaned and cleaned.count('"title":') > 5:
        # If contains too much repeated search result metadata, simplify
        lines = cleaned.split('\n')
        cleaned_lines = []
        in_metadata = False
        
        for line in lines:
            if '"metadata_list":' in line:
                in_metadata = True
                cleaned_lines.append('Search result metadata simplified...')
                continue
            elif in_metadata and (line.strip().startswith('}') or line.strip() == ']'):
                in_metadata = False
                continue
            elif not in_metadata:
                cleaned_lines.append(line)
        
        cleaned = '\n'.join(cleaned_lines)
    
    # New: Clean repeated search result content
    # Remove repeated search results after Visible field
    if 'Visible' in cleaned:
        parts = cleaned.split('Visible')
        if len(parts) > 1:
            # Keep first part, simplify subsequent repeated search results
            cleaned = parts[0] + '\n[Repeated search results cleaned]'
    
    # New: Clean Unicode escape sequences
    # Remove \u form Unicode escape sequences (if too many)
    unicode_count = len(re.findall(r'\\u[0-9a-fA-F]{4}', cleaned))
    if unicode_count > 10:  # If too many Unicode escapes, likely technical error info
        cleaned = re.sub(r'\\u[0-9a-fA-F]{4}', '[Unicode cleaned]', cleaned)
    
    # New: Clean special search result separators
    cleaned = re.sub(r'\u2020+', '|', cleaned)  # Replace † symbol
    cleaned = re.sub(r'\u2019', "'", cleaned)   # Replace special apostrophe
    cleaned = re.sub(r'\u201c|\u201d', '"', cleaned)  # Replace special double quotes
    
    # 🎯 Handle emoji and special characters: keep common chat role emoji (👤 🤖 🛠️), only replace rare emoji that Notion might reject
    emoji_replacements = {
        '🔍': '[Search]',
        '💬': '[Chat]',
        '📝': '[Note]'
    }
    for em, repl in emoji_replacements.items():
        cleaned = cleaned.replace(em, repl)
    
    # Handle potentially problematic punctuation combinations
    cleaned = cleaned.replace('：', ':')  # Chinese colon to English colon
    cleaned = cleaned.replace('。"', '.')  # Period + quote combination
    cleaned = cleaned.replace('"。', '.')  # Quote + period combination
    
    # New: Clean extra long technical error info lines
    lines = cleaned.split('\n')
    cleaned_lines = []
    
    for line in lines:
        # If line too long and contains technical keywords, truncate
        if len(line) > 200 and any(keyword in line.lower() for keyword in [
            'error', 'warning', 'exception', 'failed', 'uncaught', 'require', 'include'
        ]):
            cleaned_lines.append(line[:100] + '...[Error message truncated]')
        else:
            cleaned_lines.append(line)
    
    cleaned = '\n'.join(cleaned_lines)
    
    # Remove excessive consecutive whitespace
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)  # Keep max two consecutive newlines
    cleaned = re.sub(r' {3,}', '  ', cleaned)      # Keep max two consecutive spaces
    
    # Limit text length
    if len(cleaned) > MAX_TEXT_LENGTH:
        cleaned = cleaned[:MAX_TEXT_LENGTH-3] + "..."
    
    return cleaned.strip()

def get_safe_language_type(language):
    """Get safe code language type, ensure Notion API support"""
    if not language or language == 'unknown':
        return 'text'
    
    # Main language types supported by Notion
    supported_languages = {
        'javascript', 'typescript', 'python', 'java', 'c', 'cpp', 'c++', 'c#', 'csharp',
        'php', 'ruby', 'go', 'rust', 'swift', 'kotlin', 'scala', 'r', 'matlab',
        'sql', 'html', 'css', 'scss', 'sass', 'xml', 'json', 'yaml', 'yml',
        'markdown', 'bash', 'shell', 'powershell', 'dockerfile', 'makefile',
        'text', 'plain_text', 'plaintext'
    }
    
    language_lower = language.lower().strip()
    
    # Direct match
    if language_lower in supported_languages:
        return language_lower
    
    # Common alias mapping
    language_mappings = {
        'js': 'javascript',
        'ts': 'typescript',
        'py': 'python',
        'rb': 'ruby',
        'sh': 'bash',
        'ps1': 'powershell',
        'cs': 'csharp',
        'htm': 'html',
        'jsonl': 'json',
        'yml': 'yaml',
        'md': 'markdown',
        'txt': 'text',
        'c++': 'cpp',
        'objective-c': 'c',
        'objc': 'c'
    }
    
    if language_lower in language_mappings:
        return language_mappings[language_lower]
    
    # If no match, return text
    return 'text'

def validate_block_content(block):
    """Validate and clean block content"""
    if not isinstance(block, dict):
        return None
    
    try:
        # Validate basic structure
        if 'type' not in block:
            return None
        
        block_type = block['type']
        
        # Handle paragraph blocks
        if block_type == 'paragraph' and 'paragraph' in block:
            paragraph = block['paragraph']
            if 'rich_text' in paragraph:
                cleaned_rich_text = []
                for text_obj in paragraph['rich_text']:
                    if isinstance(text_obj, dict) and 'text' in text_obj and 'content' in text_obj['text']:
                        content = clean_text_content(text_obj['text']['content'])
                        
                        # 🎯 New: Aggressive cleaning for special content
                        if any(pattern in content for pattern in ['[Function call cleaned]', 'open_url', 'search(', '1q43.blog']):
                            content = "Content contains special characters that might cause API errors, simplified processing applied."
                        
                        if content.strip():  # Only keep non-empty content
                            cleaned_rich_text.append({
                                "type": "text",
                                "text": {"content": content}
                            })
                
                if cleaned_rich_text:
                    return {
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": cleaned_rich_text
                        }
                    }
        
        # Handle code blocks
        elif block_type == 'code' and 'code' in block:
            code = block['code']
            if 'rich_text' in code:
                cleaned_rich_text = []
                for text_obj in code['rich_text']:
                    if isinstance(text_obj, dict) and 'text' in text_obj and 'content' in text_obj['text']:
                        content = clean_text_content(text_obj['text']['content'])
                        
                        # 🎯 New: Aggressive cleaning for code blocks
                        if any(pattern in content for pattern in ['[Function call cleaned]', 'open_url', 'search(', '1q43.blog']):
                            content = "# Code content contains function calls, simplified\n# Original code may contain API calls and other complex content"
                        
                        # Special handling: if code block contains potentially problematic URLs, additional cleaning
                        elif any(domain in content for domain in ['1q43.blog', 'github.com', 'docs.']) and len(content) > 200:
                            # Simplify complex code blocks to comments
                            content = f"# Code content contains complex URLs, simplified\n# Original content length: {len(content)} characters"
                        
                        if content.strip():  # Only keep non-empty content
                            cleaned_rich_text.append({
                                "type": "text", 
                                "text": {"content": content}
                            })
                
                if cleaned_rich_text:
                    # Ensure language type is safe, force problematic code blocks to use text
                    original_language = code.get('language', 'text')
                    language = get_safe_language_type(original_language)
                    
                    # If original content might have issues, force text language
                    content_text = cleaned_rich_text[0]['text']['content'] if cleaned_rich_text else ''
                    if any(keyword in content_text for keyword in ['Function call', 'open_url', 'search(', '# [', '1q43.blog']):
                        language = 'text'
                    
                    return {
                        "type": "code",
                        "code": {
                            "rich_text": cleaned_rich_text,
                            "language": language
                        }
                    }
        
        # Handle image blocks
        elif block_type == 'image':
            return block
        
        return None
        
    except Exception as e:
        print(f"   ⚠️ Warning: Error while cleaning block content: {e}")
        return None

def main():
    """Main execution function"""
    print("🚀 Starting ChatGPT to Notion Importer...")
    
    # Validate configuration
    if not validate_config():
        print("\n💡 Tip: Please follow these steps to set up:")
        print("1. Get Notion API key: https://www.notion.so/my-integrations")
        print("2. Get database ID: Copy from database URL")
        print("3. Fill in this information in the configuration section at the top of the script")
        sys.exit(1)
    
    # Set up API request headers
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json"
    }
    
    # Detect database structure
    print("🔍 Detecting database structure...")
    db_info = get_database_info(headers, NOTION_DATABASE_ID)
    
    if not db_info['properties']:
        print("⚠️ Warning: Unable to get database property information, might be a permissions issue")
        print("Please ensure:")
        print("1. Your integration has access permissions to this database")  
        print("2. Database has at least one 'Title' type property")
    else:
        print(f"✅ Database detection results:")
        print(f"   📝 Title property: {db_info['title_property']}")
        if db_info['created_time_property']:
            print(f"   📅 Created time property: {db_info['created_time_property']}")
        if db_info['updated_time_property']:
            print(f"   🔄 Updated time property: {db_info['updated_time_property']}")
        if db_info['conversation_id_property']:
            print(f"   🆔 Conversation ID property: {db_info['conversation_id_property']} ({db_info['conversation_id_type']} type)")
        print(f"   📊 Total {len(db_info['properties'])} properties found")
    
    # Verify conversation file exists
    if not os.path.exists(CONVERSATIONS_JSON_PATH):
        print(f"❌ Error: Cannot find conversation file '{CONVERSATIONS_JSON_PATH}'")
        print(f"Please check CHATGPT_EXPORT_PATH setting: {CHATGPT_EXPORT_PATH}")
        print("Ensure conversations.json file is in the specified directory")
        sys.exit(1)

    # Read conversation data
    try:
        with open(CONVERSATIONS_JSON_PATH, 'r', encoding='utf-8') as f:
            all_conversations = json.load(f)
        print(f"✅ Successfully read conversation file")
    except Exception as e:
        print(f"❌ Error: Unable to read conversations.json: {e}")
        sys.exit(1)

    # ====== Quick test mode: only select conversations with images or Canvas ======
    if QUICK_TEST_MODE:
        print("🚧 QUICK_TEST mode enabled: Only importing conversations with images or Canvas...")

        image_convs, canvas_convs = [], []

        def inspect_conversation(conv):
            has_image, has_canvas = False, False
            mapping = conv.get('mapping', {}) or {}
            for node in mapping.values():
                msg = node.get('message') or {}
                # Image detection
                content = msg.get('content') or {}
                if content.get('content_type') == 'multimodal_text':
                    for part in content.get('parts', []):
                        if isinstance(part, dict) and part.get('content_type') == 'image_asset_pointer':
                            has_image = True
                            break
                # Canvas detection
                if isinstance(msg.get('metadata'), dict) and 'canvas' in msg['metadata']:
                    has_canvas = True
            return has_image, has_canvas

        for conv in all_conversations:
            img, cvs = inspect_conversation(conv)
            if img and len(image_convs) < QUICK_TEST_LIMIT_PER_TYPE:
                image_convs.append(conv)
            if cvs and len(canvas_convs) < QUICK_TEST_LIMIT_PER_TYPE:
                canvas_convs.append(conv)
            # Exit early to save time
            if len(image_convs) >= QUICK_TEST_LIMIT_PER_TYPE and len(canvas_convs) >= QUICK_TEST_LIMIT_PER_TYPE:
                break

        # Merge and deduplicate
        quick_list = {conv['id']: conv for conv in (image_convs + canvas_convs)}.values()
        conversations_to_process = list(quick_list)
        print(f"🔍 QUICK_TEST selected conversations: {len(conversations_to_process)} (Images {len(image_convs)}, Canvas {len(canvas_convs)})")

    # Load processed conversation IDs
    processed_ids = load_processed_ids()

    if QUICK_TEST_MODE:
        # conversations_to_process already generated in QUICK_TEST logic, only filter already processed ones here
        conversations_to_process = [
            conv for conv in conversations_to_process  # type: ignore  # Already defined in QUICK_TEST
            if conv.get('id') not in processed_ids
        ]
    else:
        conversations_to_process = [
            conv for conv in all_conversations 
            if conv.get('id') not in processed_ids and 'title' in conv and 'mapping' in conv
        ]
    
    # Statistics
    total_all = len(all_conversations)
    total_to_process = len(conversations_to_process)
    
    print(f"📊 Statistics:")
    print(f"   Total conversations: {total_all}")
    print(f"   Already processed: {len(processed_ids)} (will skip)")
    print(f"   To process: {total_to_process}")

    if total_to_process == 0:
        print("✅ All conversations have been processed, no execution needed")
        return

    print(f"\n▶️ Starting to process {total_to_process} new conversations...")
    success_count, fail_count = 0, 0
    
    # Process in reverse chronological order, newest conversations imported first
    for conversation in tqdm(reversed(conversations_to_process), 
                           total=total_to_process, 
                           desc="Import Progress", 
                           unit="conversations"):
        conv_id = conversation['id']
        conv_title = conversation.get('title', 'Untitled')
        
        try:
            # Build Notion blocks
            blocks = build_blocks_from_conversation(conversation, headers)
            
            # Import to Notion
            success = import_conversation_to_notion(
                title=conv_title,
                create_time=conversation.get('create_time', time.time()),
                update_time=conversation.get('update_time', time.time()),
                conversation_id=conv_id,
                all_blocks=blocks,
                headers=headers,
                database_id=NOTION_DATABASE_ID,
                db_info=db_info
            )

            if success:
                success_count += 1
                log_processed_id(conv_id)  # Only log if successful
            else:
                fail_count += 1
                tqdm.write(f"❌ Import failed: '{conv_title}' (will retry in next run)")

        except Exception as e:
            fail_count += 1
            tqdm.write(f"❌ Unexpected error while processing '{conv_title}': {e}")

        # Avoid API rate limiting
        time.sleep(0.4)

    # Output final results
    print("\n" + "="*50)
    print("🎉 Import completed! Result statistics:")
    print(f"🟢 Successfully imported: {success_count} conversations")
    if fail_count > 0:
        print(f"🔴 Import failed: {fail_count} conversations")
        print("   💡 Failed conversations will be retried in next run")
    print(f"⏭️  Skipped (already processed): {len(processed_ids)} conversations")
    
    if success_count > 0:
        print(f"\n✨ Please check your Notion database to view the imported {success_count} conversations!")

if __name__ == "__main__":
    main() 
