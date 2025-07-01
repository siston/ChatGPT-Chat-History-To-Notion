# -*- coding: utf-8 -*-
"""
ChatGPT Chat History To Notion

极简使用方法:
1. pip install requests tqdm
2. 在脚本顶部的配置区域填入你的 API 密钥和数据库 ID
3. python import_chatgpt_fixed.py

详细文档：https://github.com/Pls-1q43/ChatGPT-Full-Log-To-Notion/
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

# --- 配置区域 ---
# 请在下方填入你的配置信息

# 1. 你的 Notion Integration Token (API 密钥)
# 获取方式: https://www.notion.so/my-integrations （一串以 ntn_ 开头的字符串）
NOTION_API_KEY = ""

# 2. 你的 Notion 数据库 ID  
# 获取方式: 从数据库URL中复制（比如，URL为：https://www.notion.so/223ca795c956806f84b8da595d3647d6，则填写223ca795c956806f84b8da595d3647d6）
NOTION_DATABASE_ID = ""

# 3. ChatGPT 导出文件夹路径 (可选，默认为当前目录)
CHATGPT_EXPORT_PATH = "./"

# === 新增：图片调试开关 ===
DEBUG_IMAGE_UPLOAD = False  # 设置为 True 或通过环境变量 DEBUG_IMAGE_UPLOAD=1 开启

# === 新增：快速测试模式开关 ===
QUICK_TEST_MODE = False  # 全量导入模式；临时调试可用环境变量 QUICK_TEST=1
QUICK_TEST_LIMIT_PER_TYPE = 5  # 每类(图片/Canvas)最多处理多少条

def validate_config():
    """验证必要的配置是否存在"""
    if not NOTION_API_KEY:
        print("❌ 错误: 请填写 NOTION_API_KEY!")
        print("请在脚本顶部的配置区域填入你的 Notion API 密钥")
        print("获取方式: https://www.notion.so/my-integrations")
        return False
    
    if not NOTION_DATABASE_ID:
        print("❌ 错误: 请填写 NOTION_DATABASE_ID!")
        print("请在脚本顶部的配置区域填入你的 Notion 数据库 ID")
        print("获取方式: 从数据库URL中复制ID部分")
        return False
    
    if len(NOTION_API_KEY) < 10 or not NOTION_API_KEY.startswith(('ntn_', 'secret_')):
        print("❌ 错误: NOTION_API_KEY 格式不正确!")
        print("API密钥应该以 'ntn_' 或 'secret_' 开头")
        return False
        
    if len(NOTION_DATABASE_ID) != 32:
        print("❌ 错误: NOTION_DATABASE_ID 格式不正确!")
        print("数据库ID应该是32位字符串")
        return False
    
    return True

def get_database_info(headers, database_id):
    """获取数据库信息，检查属性结构"""
    try:
        response = requests.get(
            f"{NOTION_API_BASE_URL}/databases/{database_id}",
            headers=headers,
            timeout=30
        )
        response.raise_for_status()
        db_info = response.json()
        
        properties = db_info.get('properties', {})
        
        # 查找各种类型的属性
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
        print(f"⚠️ 警告: 无法获取数据库信息: {error_msg}")
        return {
            'title_property': 'Title',
            'created_time_property': None,
            'updated_time_property': None,
            'conversation_id_property': None,
            'properties': {}
        }

# --- 全局变量 ---
CONVERSATIONS_JSON_PATH = os.path.join(CHATGPT_EXPORT_PATH, 'conversations.json')
NOTION_API_BASE_URL = "https://api.notion.com/v1"
PROCESSED_LOG_FILE = 'processed_ids.log'
MAX_TEXT_LENGTH = 1000  # Notion文本块最大长度限制（减少以避免400错误）
MAX_TRAVERSE_DEPTH = 1000  # 防止无限循环的最大遍历深度
DEBUG_FIRST_FAILURE = True  # 调试模式：显示第一个失败请求的详细信息
DEBUG_DETAILED_ERRORS = True  # 新增：详细错误分析（正式运行时关闭，调试时开启）

# 新增：错误分析函数
def analyze_request_payload(payload, title=""):
    """分析请求载荷，识别可能导致400错误的问题"""
    issues = []
    payload_str = json.dumps(payload, ensure_ascii=False)
    
    # 检查载荷大小 - 降低阈值
    size = len(payload_str)
    if size > 400000:  # 从3000降低到2000
        issues.append(f"载荷过大: {size} 字符")
    
    # 检查可能有问题的内容模式
    problematic_patterns = [
        (r'open_url\(', "包含open_url函数调用"),
        (r'search\(', "包含search函数调用"),
        (r'https?://[^\s<>"]{50,}', "包含超长URL"),
        (r'["\']我不知道["\']', "包含带引号的中文"),
        (r'["\'][^"\']{100,}["\']', "包含超长引号字符串"),
        (r'\\u[0-9a-fA-F]{4}', "包含Unicode转义序列"),
        (r'\{[^}]{200,}\}', "包含超长JSON对象"),
        (r'Fatal error:|Warning:|Exception:', "包含错误日志"),
        (r'👤|🤖|🔍|💬', "包含emoji字符"),
    ]
    
    for pattern, description in problematic_patterns:
        if re.search(pattern, payload_str):
            matches = len(re.findall(pattern, payload_str))
            issues.append(f"{description} ({matches}处)")
    
    # 检查嵌套深度
    if payload_str.count('{') > 20:
        issues.append(f"JSON嵌套过深: {payload_str.count('{')} 层")
    
    # 检查特殊字符
    special_chars = ['"', "'", '\\', '\n', '\t']
    for char in special_chars:
        count = payload_str.count(char)
        if count > 50:
            issues.append(f"特殊字符'{char}'过多: {count}个")
    
    return issues

# 新增：失败载荷分析器
def debug_failed_payload(payload, error_response, title):
    """详细分析失败的载荷"""
    if not DEBUG_DETAILED_ERRORS:
        return
    
    print(f"\n🔍 详细分析失败载荷: {title}")
    
    # 分析载荷问题
    issues = analyze_request_payload(payload, title)
    if issues:
        print("   🚨 发现的问题:")
        for i, issue in enumerate(issues[:10], 1):  # 最多显示10个问题
            print(f"      {i}. {issue}")
    
    # 分析错误响应
    if error_response:
        try:
            error_detail = error_response.json()
            print("   📋 API错误详情:")
            print(f"      状态码: {error_response.status_code}")
            if 'message' in error_detail:
                print(f"      消息: {error_detail['message']}")
            if 'code' in error_detail:
                print(f"      错误代码: {error_detail['code']}")
        except:
            print(f"   📋 原始错误: {error_response.text[:200]}...")
    
    # 提取并显示问题块
    if 'children' in payload:
        print("   📦 问题块分析:")
        for i, block in enumerate(payload['children'][:3], 1):
            block_str = json.dumps(block, ensure_ascii=False)
            block_issues = analyze_request_payload({'block': block})
            print(f"      块{i} ({len(block_str)}字符): {', '.join(block_issues) if block_issues else '未发现问题'}")
    
    print("   " + "="*50)

# --- 辅助函数 ---
def load_processed_ids():
    """加载已处理的对话ID，用于断点续传"""
    if not os.path.exists(PROCESSED_LOG_FILE):
        return set()
    try:
        with open(PROCESSED_LOG_FILE, 'r', encoding='utf-8') as f:
            return {line.strip() for line in f if line.strip()}
    except Exception as e:
        print(f"警告: 无法读取日志文件: {e}")
        return set()

def log_processed_id(conversation_id):
    """记录成功处理的对话ID"""
    try:
        with open(PROCESSED_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(f"{conversation_id}\n")
    except Exception as e:
        print(f"警告: 无法写入日志文件: {e}")

def split_long_text(text, max_length=MAX_TEXT_LENGTH):
    """将长文本分割成符合Notion限制的块"""
    if len(text) <= max_length:
        return [text]
    
    chunks = []
    current_pos = 0
    
    while current_pos < len(text):
        end_pos = current_pos + max_length
        if end_pos >= len(text):
            chunks.append(text[current_pos:])
            break
        
        # 尝试在句子或段落边界分割
        best_split = end_pos
        for i in range(max(current_pos, end_pos - 100), end_pos):
            if text[i] in '.。\n!！?？':
                best_split = i + 1
                break
        
        chunks.append(text[current_pos:best_split])
        current_pos = best_split
    
    return chunks

def upload_file_to_notion(local_file_path, headers):
    """上传文件到Notion，支持图片等附件 (增强多路径查找)"""

    def find_local_file(path_or_name: str) -> str | None:
        """在常见子目录(images/ dalle-generations/)中查找文件"""
        if os.path.isabs(path_or_name) and os.path.exists(path_or_name):
            return path_or_name

        # 去除可能的前缀 "./"，并规范化路径
        if path_or_name.startswith("./") or path_or_name.startswith(".\\"):
            path_or_name = path_or_name[2:]

        # 统一使用规范化后的名字做进一步处理
        abs_path = os.path.join(CHATGPT_EXPORT_PATH, path_or_name)
        if os.path.exists(abs_path):
            return abs_path

        # 常见子目录
        basename_only = os.path.basename(path_or_name)
        for sub in ["images", "assets", "dalle-generations", "dalle_generations"]:
            candidate = os.path.join(CHATGPT_EXPORT_PATH, sub, basename_only)
            if os.path.exists(candidate):
                return candidate

        # 第一轮：针对以 file- 开头的通用规则
        if basename_only.startswith("file-"):
            prefix = basename_only.split('.')[0]  # file-XXXXXX
            for root, _dirs, files in os.walk(CHATGPT_EXPORT_PATH):
                for fname in files:
                    if fname.startswith(prefix):
                        return os.path.join(root, fname)

        # 第二轮：更通用的前缀匹配（不限定 file- 前缀），
        # 以处理根目录下诸如 "image-XXX.png" 或 "pic_XXX.jpg" 等情况
        generic_prefix = os.path.splitext(basename_only)[0]
        if len(generic_prefix) > 3:  # 避免前缀过短造成误匹配
            for root, _dirs, files in os.walk(CHATGPT_EXPORT_PATH):
                for fname in files:
                    if fname.startswith(generic_prefix):
                        return os.path.join(root, fname)

        # 第三轮：无扩展名 -> 试探常见图片扩展
        if '.' not in basename_only:
            COMMON_EXTS = ['png', 'jpg', 'jpeg', 'webp', 'gif']
            for ext in COMMON_EXTS:
                candidate = os.path.join(CHATGPT_EXPORT_PATH, f"{basename_only}.{ext}")
                if os.path.exists(candidate):
                    return candidate
                # 亦在常见子目录中查找
                for sub in ["images", "assets", "dalle-generations", "dalle_generations"]:
                    candidate_sub = os.path.join(CHATGPT_EXPORT_PATH, sub, f"{basename_only}.{ext}")
                    if os.path.exists(candidate_sub):
                        return candidate_sub
        return None

    actual_path = find_local_file(local_file_path)
    if actual_path is None:
        tqdm.write(f"   ⚠️ 图片文件未找到: {local_file_path}")
        return None

    local_file_path = actual_path

    file_name = os.path.basename(local_file_path)
    file_size = os.path.getsize(local_file_path)
    
    # ====== 会员版限制：20 MB ======
    MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024  # 20MB
    if file_size > MAX_FILE_SIZE_BYTES:
        tqdm.write(f"   ⚠️ 文件过大 (>20MB): {local_file_path}")
        return None

    # ====== MIME 类型判定 ======
    content_type, _ = mimetypes.guess_type(local_file_path)
    # 扩展名到 MIME 的补充映射
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

    # ====== magic bytes 检测（处理无扩展名文件并补MIME） ======
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

            # 如文件名无扩展且识别成功，补上扩展名 (仅影响上传文件名，不改磁盘文件)
            if mime_ext and '.' not in file_name:
                file_name += f'.{mime_ext}'
        except Exception:
            pass

    # ====== 支持的 MIME 白名单 ======
    ALLOWED_MIME = {
        # 图片
        'image/jpeg','image/jpg','image/png','image/gif','image/webp','image/svg+xml','image/tiff','image/heic','image/vnd.microsoft.icon',
        # 文档
        'application/pdf','text/plain','application/json',
        # 音频
        'audio/mpeg','audio/mp4','audio/aac','audio/midi','audio/ogg','audio/wav','audio/x-ms-wma',
        # 视频
        'video/mp4','video/webm','video/quicktime','video/x-msvideo','video/x-flv','video/mpeg','video/x-ms-asf','video/x-amv'
    }
    if content_type not in ALLOWED_MIME:
        tqdm.write(f"   ⚠️ 不支持的 MIME 类型({content_type})，跳过: {file_name}")
        return None

    # 调试：显示文件准备信息
    if DEBUG_IMAGE_UPLOAD or os.getenv("DEBUG_IMAGE_UPLOAD") == "1":
        tqdm.write(f"   [DEBUG] 准备上传: {file_name} | size={round(file_size/1024,1)}KB | mime={content_type}")

    # 第一步：向Notion请求上传URL
    upload_url = f"{NOTION_API_BASE_URL}/file_uploads"
    payload = {
        "filename": file_name,
        "content_type": content_type
    }
    
    try:
        response = requests.post(upload_url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        upload_data = response.json()
        
        # 调试: 输出上传返回信息
        if DEBUG_IMAGE_UPLOAD or os.getenv("DEBUG_IMAGE_UPLOAD") == "1":
            tqdm.write(f"   [DEBUG] 上传返回: {json.dumps(upload_data, ensure_ascii=False)}")
        
        # 第二步：上传文件内容到获取的URL
        with open(local_file_path, 'rb') as f:
            file_bytes = f.read()

        base_upload_headers = {
            "Content-Type": content_type,
            "Content-Length": str(file_size)
        }

        upload_url = upload_data["upload_url"]

        # 如果 upload_url 包含 /send，按 Notion API 需要带授权使用 POST
        if "/send" in upload_url:
            # 使用 multipart/form-data, requests 自动生成 boundary 与 Content-Type
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
            # 预签名 S3 URL，使用 PUT 无需授权
            response = requests.put(
                upload_url,
                headers=base_upload_headers,
                data=file_bytes,
                timeout=120
            )
        response.raise_for_status()
        
        tqdm.write(f"   ✅ 图片上传成功: {file_name}")

        if DEBUG_IMAGE_UPLOAD or os.getenv("DEBUG_IMAGE_UPLOAD") == "1":
            tqdm.write(f"   [DEBUG] FileUpload ID: {upload_data.get('id')}")
        return upload_data["id"]
        
    except requests.exceptions.RequestException as e:
        error_msg = e.response.text if e.response else str(e)
        tqdm.write(f"   ❌ 文件上传失败: {error_msg}")
        return None

def build_blocks_from_conversation(conversation_data, headers):
    """从对话数据构建Notion块，增加了安全保护"""
    mapping = conversation_data.get('mapping', {})
    if not mapping:
        return []

    # 找到根节点
    root_id = next((nid for nid, node in mapping.items() if not node.get('parent')), None)
    if not root_id:
        try:
            # 如果没有明确的根节点，找最早的消息作为起点
            root_id = min(mapping.keys(), 
                         key=lambda k: mapping[k].get('message', {}).get('create_time', float('inf')))
        except (ValueError, TypeError):
            return []

    blocks = []
    current_id = root_id
    visited = set()  # 防止无限循环
    depth = 0
    
    # Canvas 文档去重集合（按 textdoc_id）
    seen_canvas_docs = set()
    
    # 安全遍历对话树
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

                desc_lines = [f"Canvas 模块 -> 标题: {canvas_title}"]
                desc_lines.append(f"类型: {canvas_type} | 版本: {canvas_version} | ID: {textdoc_id}")

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
            
            # 角色映射
            speaker_map = {
                "user": "👤 用户",
                "assistant": "🤖 助手", 
                "tool": f"🛠️ 工具 ({message.get('author', {}).get('name', '')})",
                "system": "⚙️ 系统"
            }
            speaker_raw = speaker_map.get(author_role, "❓ 未知")

            # 将 "👤 用户" 形式转换为 "[👤]用户:"  前缀
            def format_speaker_label(raw: str) -> str:
                if ' ' in raw:
                    emoji_part, name_part = raw.split(' ', 1)
                    return f"[{emoji_part}]{name_part}:"
                # fallback
                return f"[{raw}]:"

            speaker_label = format_speaker_label(speaker_raw)

            content = message['content']
            content_type = content.get('content_type')
            
            # 处理纯文本内容
            if content_type == 'text' and content.get('parts'):
                full_content = "".join(part for part in content['parts'] if isinstance(part, str))
                if full_content.strip():
                    # 处理长文本分割
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
            
            # 处理多模态内容（文本+图片）
            elif content_type == 'multimodal_text':
                # 先处理文本部分
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
                
                # 处理图片部分
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
                                        tqdm.write(f"   [DEBUG] 构建 image block, id={file_upload_id}")
                                    blocks.append({
                                        "type": "image",
                                        "image": {
                                            "type": "file_upload",
                                            "file_upload": {"id": file_upload_id}
                                        }
                                    })

            # 处理代码块
            elif content_type == 'code' and content.get('text'):
                # 添加说话者标识
                speaker_block = {
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"type": "text", "text": {"content": speaker_label}}]
                    }
                }
                validated_speaker_block = validate_block_content(speaker_block)
                if validated_speaker_block:
                    blocks.append(validated_speaker_block)
                
                # 处理长代码分割
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

            # 处理系统错误
            elif content_type == 'system_error' and content.get('text'):
                error_text = f"{speaker_label}\n❗️ 系统错误: {content.get('text')}"
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

        # 移动到下一个节点
        children = node.get('children', [])
        current_id = children[0] if children and isinstance(children, list) else None
    
    # 警告：如果达到最大深度
    if depth >= MAX_TRAVERSE_DEPTH:
        tqdm.write(f"   ⚠️ 警告: 达到最大遍历深度 ({MAX_TRAVERSE_DEPTH})，对话可能不完整")
    
    return blocks

def import_conversation_to_notion(title, create_time, update_time, conversation_id, all_blocks, headers, database_id, db_info):
    """导入单个对话到Notion数据库"""
    if not all_blocks:
        tqdm.write(f"   - 跳过空内容对话: {title}")
        return True

    # 限制标题长度，避免Notion API错误
    if len(title) > 100:
        title = title[:97] + "..."
    
    # 清理标题内容
    title = clean_text_content(title)

    # 验证和清理所有块内容
    cleaned_blocks = []
    for block in all_blocks:
        validated_block = validate_block_content(block)
        if validated_block:
            # 额外检查：如果单个块的JSON表示太大，进一步分割而不是跳过
            block_json_size = len(json.dumps(validated_block, ensure_ascii=False))
            if block_json_size > 1000:  # 需要进一步分割的块
                tqdm.write(f"   - 🔄 分割过大的块 ({block_json_size} 字符)")
                
                # 获取块的文本内容进行分割
                if validated_block['type'] == 'paragraph':
                    original_content = validated_block['paragraph']['rich_text'][0]['text']['content']
                    # 将内容分割成更小的块
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
                    # 将代码分割成更小的块
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
                    # 其他类型的块直接添加，如图片块
                    cleaned_blocks.append(validated_block)
            else:
                cleaned_blocks.append(validated_block)
    
    if not cleaned_blocks:
        tqdm.write(f"   - 跳过空内容对话（清理后无有效块）: {title}")
        return True

    # 调试信息：显示清理前后的块数量
    tqdm.write(f"   - 调试: 原始块数 {len(all_blocks)} -> 清理后块数 {len(cleaned_blocks)}")

    # ========== 新策略：先创建空页面，再追加所有块 ==========
    # 页面创建时不携带 children，可大幅降低 400 报错概率
    initial_blocks: list = []  # 保持空列表
    remaining_blocks: list = cleaned_blocks  # 全量内容稍后分批追加

    # 将剩余 blocks 分成更小的批次（最多 20 个/批）
    block_chunks = [remaining_blocks[i:i + 20] for i in range(0, len(remaining_blocks), 20)]
    initial_payload_size = 0  # 空载荷
    tqdm.write(f"   - 分块策略: 创建空页面，后续 {len(block_chunks)} 批次追加")

    # 使用检测到的属性名称
    title_property = db_info.get('title_property', 'Title')
    created_time_property = db_info.get('created_time_property')
    updated_time_property = db_info.get('updated_time_property')
    conversation_id_property = db_info.get('conversation_id_property')
    conversation_id_type = db_info.get('conversation_id_type')

    # 创建页面载荷 - 使用检测到的完整属性结构
    properties = {
        title_property: {"title": [{"type": "text", "text": {"content": title}}]}
    }

    # 仅当属性真正是可写的 "date" 类型时才写入，避免修改 "created_time" / "last_edited_time" 只读字段
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

    # 添加对话ID属性（如果存在）
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

    # 创建页面
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
        tqdm.write(f"   - ✅ 页面创建成功: {title}")
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
        
        tqdm.write(f"   - ❌ 页面创建失败: {title}")
        tqdm.write(f"   - HTTP状态码: {e.response.status_code if e.response else 'N/A'}")
        tqdm.write(f"   - 详细错误: {error_msg}")
        
        # 🎯 新增：使用新的错误分析器
        debug_failed_payload(create_payload, e.response, title)
        
        # 调试模式：显示第一个失败请求的完整载荷
        if DEBUG_FIRST_FAILURE:
            tqdm.write(f"   - 🐛 调试载荷 (第一次失败):")
            tqdm.write(f"     标题: {title}")
            tqdm.write(f"     块数量: {len(initial_blocks)}")
            
            # 显示前3个块的结构
            for i, block in enumerate(initial_blocks[:3]):
                tqdm.write(f"     块 {i+1}: {json.dumps(block, ensure_ascii=False, indent=4)}")
            
            if len(initial_blocks) > 3:
                tqdm.write(f"     ... 还有 {len(initial_blocks)-3} 个块")
            
            # 显示完整的properties部分
            tqdm.write(f"     Properties: {json.dumps(properties, ensure_ascii=False, indent=4)}")
            
            DEBUG_FIRST_FAILURE = False  # 只显示第一次失败的详细信息
        elif len(str(create_payload)) < 2000:  # 避免输出过长的载荷
            tqdm.write(f"   - 请求载荷: {json.dumps(create_payload, indent=2, ensure_ascii=False)}")
        else:
            tqdm.write(f"   - 载荷大小: {len(str(create_payload))} 字符 (过长，已省略)")
            tqdm.write(f"   - 块数量: {len(initial_blocks)}")
        
        # 尝试创建简化版本（只有标题，无内容块）
        try:
            tqdm.write(f"   - 🔄 尝试创建简化版本（仅标题）...")
            
            # 进一步简化标题，移除可能有问题的字符
            safe_title = re.sub(r'[^\w\s\-\u4e00-\u9fff]', '', title)  # 只保留字母数字中文和基本符号
            if len(safe_title.strip()) < 2:
                safe_title = f"对话_{conversation_id[:8]}"  # 如果标题被清理得太干净，使用对话ID
            
            safe_properties = {
                title_property: {"title": [{"type": "text", "text": {"content": safe_title}}]}
            }
            
            # 尝试不添加时间和对话ID，只创建最基本的页面
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
            tqdm.write(f"   - ✅ 简化版本创建成功: {safe_title}")
            
            # 之后再尝试更新属性（分开请求降低失败风险）
            try:
                time.sleep(0.3)
                update_properties = {}
                
                # 逐个添加属性，失败了也不影响其他的
                if created_time_property:
                    try:
                        update_properties[created_time_property] = {
                            "date": {"start": datetime.datetime.fromtimestamp(create_time).isoformat() + "Z"}
                        }
                    except:
                        pass
                
                if conversation_id_property and conversation_id_type == 'number':
                    try:
                        number_value = abs(hash(conversation_id)) % (10**8)  # 更小的数字
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
                pass  # 更新属性失败也没关系，至少页面创建了
            
            # 尝试添加一个简单的说明块
            try:
                time.sleep(0.3)
                note_block = {
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"type": "text", "text": {"content": "原始内容导入时遇到格式问题，已创建空白页面。"}}]
                    }
                }
                
                requests.patch(
                    f"{NOTION_API_BASE_URL}/blocks/{page_id}/children",
                    headers=headers,
                    data=json.dumps({"children": [note_block]}),
                    timeout=30
                )
                
            except:
                pass  # 说明块失败也没关系
            
            return True  # 简化版本算成功
            
        except requests.exceptions.RequestException as e:
            error_msg = e.response.text if e.response else str(e)
            tqdm.write(f"   - ❌ 简化版本也创建失败: {error_msg}")
            return False

    # 如果还有剩余内容块，分批追加
    if block_chunks and any(block_chunks):  # 检查是否有非空的块组
        tqdm.write(f"   - 💬 检测到长对话，正在追加剩余内容 ({len(block_chunks)} 批次)...")
        append_url = f"{NOTION_API_BASE_URL}/blocks/{page_id}/children"
        
        for i, chunk in enumerate(block_chunks):
            if not chunk:  # 跳过空的块组
                continue
            
            # 验证批次内容
            validated_chunk = []
            chunk_json_size = 0
            
            for block in chunk:
                # 重新验证每个块
                validated_block = validate_block_content(block)
                if validated_block:
                    block_size = len(json.dumps(validated_block, ensure_ascii=False))
                    
                    # 如果单个块太大，分割它而不是跳过
                    if block_size > 1000:
                        tqdm.write(f"   -   ...🔄 分割过大块 ({block_size} 字符)")
                        
                        # 分割逻辑
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
                                    if (chunk_json_size + smaller_size) <= 50000:  # 进一步降低
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
                                    if (chunk_json_size + smaller_size) <= 50000:  # 进一步降低
                                        validated_chunk.append(smaller_block)
                                        chunk_json_size += smaller_size
                        else:
                            # 其他类型（如图片）直接添加，但检查总大小
                            if (chunk_json_size + block_size) <= 50000:  # 进一步降低
                                validated_chunk.append(validated_block)
                                chunk_json_size += block_size
                    else:
                        # 块大小合适，检查是否会超出批次限制
                        if (chunk_json_size + block_size) <= 50000:  # 进一步降低
                            validated_chunk.append(validated_block)
                            chunk_json_size += block_size
            
            if not validated_chunk:
                tqdm.write(f"   -   ...⚠️ 批次 {i+1} 清理后为空，跳过")
                continue
                
            try:
                time.sleep(0.5)  # 稍微增加延迟
                payload = {"children": validated_chunk}
                payload_size = len(json.dumps(payload, ensure_ascii=False))
                
                # 🎯 进一步降低批次大小限制
                if payload_size > 400000:  # 从2500降低到1500
                    tqdm.write(f"   -   ...⚠️ 批次 {i+1} 载荷过大 ({payload_size} 字符)，跳过")
                    continue
                
                response = requests.patch(
                    append_url,
                    headers=headers,
                    data=json.dumps(payload),
                    timeout=30
                )
                response.raise_for_status()
                tqdm.write(f"   -   ...追加批次 {i+1}/{len(block_chunks)} 成功 ({len(validated_chunk)} 个块, {payload_size} 字符)")
            except requests.exceptions.RequestException as e:
                error_msg = e.response.text if e.response else str(e)
                tqdm.write(f"   -   ...❌ 追加批次 {i+1}/{len(block_chunks)} 失败: {error_msg}")
                
                # 🎯 新增：分析追加失败的原因
                debug_failed_payload(payload, e.response, f"{title} - 批次{i+1}")
                
                # ========== 新增回退：逐块尝试插入，保留能成功的 ==========
                tqdm.write(f"   -   ...⚙️ 回退到单块追加模式，逐块重试")
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
                        # ⚠️ 如果单块仍然失败，尝试将其再次分割为更小文本（300字）
                        # 仅处理 paragraph / code
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
                                        # 如果最小块还失败，就彻底放弃
                                        pass
                                if tiny_success:
                                    successful_blocks += tiny_success  # 统计成功数
                        except Exception:
                            pass
                        continue
                tqdm.write(f"   -   ...单块追加完成，成功 {successful_blocks}/{len(validated_chunk)} 块")
                # 不因单批失败而停止整体流程
                continue

    return True

def clean_text_content(text):
    """清理文本内容，移除可能导致API错误的字符"""
    if not isinstance(text, str):
        return str(text)
    
    # 移除激进简化：不再因关键字或长度直接返回占位文本，而是尝试完整保留内容，后续若因 Notion 限制失败，
    # 将由上层逻辑（逐块拆分 / code block / txt 附件）兜底处理。
    # 保留该 if 仅用于标记，可针对极端长文本进行基础截断，但默认保留全部。
    # （如确有需要，可在此处启用 soft_truncate 逻辑。）
    # if len(text) > VERY_LONG_LIMIT: text = text[:VERY_LONG_LIMIT] + "..."
    
    # 移除控制字符（除了换行、制表符和回车）
    cleaned = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]', '', text)
    
    # 标准化换行符
    cleaned = cleaned.replace('\r\n', '\n').replace('\r', '\n')
    
    # 处理可能有问题的URL和特殊字符
    # 替换可能导致API问题的特殊字符
    cleaned = cleaned.replace('\u2028', '\n').replace('\u2029', '\n\n')  # 行分隔符和段落分隔符
    
    # 新增：清理PHP错误日志和技术错误信息
    # 移除PHP Fatal error和Warning信息
    if 'PHP Fatal error:' in cleaned or 'PHP Warning:' in cleaned or 'PHP Notice:' in cleaned:
        lines = cleaned.split('\n')
        cleaned_lines = []
        skip_next = False
        
        for line in lines:
            # 跳过PHP错误行
            if any(error_type in line for error_type in ['PHP Fatal error:', 'PHP Warning:', 'PHP Notice:', 'Stack trace:', 'thrown in']):
                skip_next = True
                continue
            # 跳过错误堆栈的后续行
            elif skip_next and (line.startswith('#') or line.startswith('  ')):
                continue
            else:
                skip_next = False
                cleaned_lines.append(line)
        
        cleaned = '\n'.join(cleaned_lines)
    
    # 新增：清理WordPress HTML内容
    # 移除WordPress块注释
    cleaned = re.sub(r'<!-- wp:[^>]+ -->', '', cleaned)
    cleaned = re.sub(r'<!-- /wp:[^>]+ -->', '', cleaned)
    
    # 清理HTML标签中的复杂属性
    cleaned = re.sub(r'<([a-zA-Z]+)[^>]*class="[^"]*"[^>]*>', r'<\1>', cleaned)
    cleaned = re.sub(r'<([a-zA-Z]+)[^>]*>', r'<\1>', cleaned)
    
    # 新增：处理文件路径信息
    # 移除Linux/Unix文件路径
    cleaned = re.sub(r'/[a-zA-Z0-9_/.-]+\.php', '[路径已清理]', cleaned)
    cleaned = re.sub(r'/home/[a-zA-Z0-9_/.-]+', '[目录已清理]', cleaned)
    
    # 新增：清理过长的URL
    # 将超长URL替换为简化版本
    def replace_long_url(match):
        url = match.group(0)
        if len(url) > 100:
            return url[:50] + '...[URL已截断]'
        return url
    
    cleaned = re.sub(r'https?://[^\s<>"]+', replace_long_url, cleaned)
    
    # 新增：移除过多的重复字符
    # 移除过多连续的相同字符（可能是错误输出）
    cleaned = re.sub(r'(.)\1{10,}', r'\1\1\1[重复内容已清理]', cleaned)
    
    # 新增：清理搜索结果内容
    # 移除ChatGPT搜索结果的特殊格式 # [0]Title - Website [url]
    cleaned = re.sub(r'# \[\d+\].*?\n', '', cleaned)
    
    # 清理metadata_list结构（搜索结果的重复元数据）
    if '"metadata_list":' in cleaned and cleaned.count('"title":') > 5:
        # 如果包含太多重复的搜索结果元数据，进行简化
        lines = cleaned.split('\n')
        cleaned_lines = []
        in_metadata = False
        
        for line in lines:
            if '"metadata_list":' in line:
                in_metadata = True
                cleaned_lines.append('搜索结果元数据已简化...')
                continue
            elif in_metadata and (line.strip().startswith('}') or line.strip() == ']'):
                in_metadata = False
                continue
            elif not in_metadata:
                cleaned_lines.append(line)
        
        cleaned = '\n'.join(cleaned_lines)
    
    # 新增：清理搜索结果的重复内容
    # 移除Visible字段后的重复搜索结果
    if 'Visible' in cleaned:
        parts = cleaned.split('Visible')
        if len(parts) > 1:
            # 保留第一部分，后面的重复搜索结果简化
            cleaned = parts[0] + '\n[重复搜索结果已清理]'
    
    # 新增：清理Unicode转义序列
    # 移除\u形式的Unicode转义序列（如果过多）
    unicode_count = len(re.findall(r'\\u[0-9a-fA-F]{4}', cleaned))
    if unicode_count > 10:  # 如果Unicode转义太多，说明可能是技术错误信息
        cleaned = re.sub(r'\\u[0-9a-fA-F]{4}', '[Unicode已清理]', cleaned)
    
    # 新增：清理特殊的搜索结果分隔符
    cleaned = re.sub(r'\u2020+', '|', cleaned)  # 替换†符号
    cleaned = re.sub(r'\u2019', "'", cleaned)   # 替换特殊引号
    cleaned = re.sub(r'\u201c|\u201d', '"', cleaned)  # 替换特殊双引号
    
    # 🎯 处理emoji和特殊字符：保留常见聊天角色emoji（👤 🤖 🛠️），仅对 Notion 可能拒绝的罕见 emoji 做替换
    emoji_replacements = {
        '🔍': '[搜索]',
        '💬': '[对话]',
        '📝': '[笔记]'
    }
    for em, repl in emoji_replacements.items():
        cleaned = cleaned.replace(em, repl)
    
    # 处理可能有问题的标点组合
    cleaned = cleaned.replace('：', ':')  # 中文冒号转英文冒号
    cleaned = cleaned.replace('。"', '.')  # 句号+引号的组合
    cleaned = cleaned.replace('"。', '.')  # 引号+句号的组合
    
    # 新增：清理过长的技术错误信息行
    lines = cleaned.split('\n')
    cleaned_lines = []
    
    for line in lines:
        # 如果行太长且包含技术关键词，进行截断
        if len(line) > 200 and any(keyword in line.lower() for keyword in [
            'error', 'warning', 'exception', 'failed', 'uncaught', 'require', 'include'
        ]):
            cleaned_lines.append(line[:100] + '...[错误信息已截断]')
        else:
            cleaned_lines.append(line)
    
    cleaned = '\n'.join(cleaned_lines)
    
    # 移除过多的连续空白字符
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)  # 最多保留两个连续换行
    cleaned = re.sub(r' {3,}', '  ', cleaned)      # 最多保留两个连续空格
    
    # 限制文本长度
    if len(cleaned) > MAX_TEXT_LENGTH:
        cleaned = cleaned[:MAX_TEXT_LENGTH-3] + "..."
    
    return cleaned.strip()

def get_safe_language_type(language):
    """获取安全的代码语言类型，确保Notion API支持"""
    if not language or language == 'unknown':
        return 'text'
    
    # Notion支持的主要语言类型
    supported_languages = {
        'javascript', 'typescript', 'python', 'java', 'c', 'cpp', 'c++', 'c#', 'csharp',
        'php', 'ruby', 'go', 'rust', 'swift', 'kotlin', 'scala', 'r', 'matlab',
        'sql', 'html', 'css', 'scss', 'sass', 'xml', 'json', 'yaml', 'yml',
        'markdown', 'bash', 'shell', 'powershell', 'dockerfile', 'makefile',
        'text', 'plain_text', 'plaintext'
    }
    
    language_lower = language.lower().strip()
    
    # 直接匹配
    if language_lower in supported_languages:
        return language_lower
    
    # 常见别名映射
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
    
    # 如果都不匹配，返回text
    return 'text'

def validate_block_content(block):
    """验证并清理块内容"""
    if not isinstance(block, dict):
        return None
    
    try:
        # 验证基本结构
        if 'type' not in block:
            return None
        
        block_type = block['type']
        
        # 处理段落块
        if block_type == 'paragraph' and 'paragraph' in block:
            paragraph = block['paragraph']
            if 'rich_text' in paragraph:
                cleaned_rich_text = []
                for text_obj in paragraph['rich_text']:
                    if isinstance(text_obj, dict) and 'text' in text_obj and 'content' in text_obj['text']:
                        content = clean_text_content(text_obj['text']['content'])
                        
                        # 🎯 新增：针对特殊内容的激进清理
                        if any(pattern in content for pattern in ['[函数调用已清理]', 'open_url', 'search(', '1q43.blog']):
                            content = "内容包含可能导致API错误的特殊字符，已进行简化处理。"
                        
                        if content.strip():  # 只保留非空内容
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
        
        # 处理代码块
        elif block_type == 'code' and 'code' in block:
            code = block['code']
            if 'rich_text' in code:
                cleaned_rich_text = []
                for text_obj in code['rich_text']:
                    if isinstance(text_obj, dict) and 'text' in text_obj and 'content' in text_obj['text']:
                        content = clean_text_content(text_obj['text']['content'])
                        
                        # 🎯 新增：代码块的激进清理
                        if any(pattern in content for pattern in ['[函数调用已清理]', 'open_url', 'search(', '1q43.blog']):
                            content = "# 代码内容包含函数调用，已简化\n# 原始代码可能包含API调用等复杂内容"
                        
                        # 特殊处理：如果代码块包含可能有问题的URL，进行额外清理
                        elif any(domain in content for domain in ['1q43.blog', 'github.com', 'docs.']) and len(content) > 200:
                            # 将复杂的代码块简化为注释
                            content = f"# 代码内容包含复杂URL，已简化\n# 原始内容长度: {len(content)} 字符"
                        
                        if content.strip():  # 只保留非空内容
                            cleaned_rich_text.append({
                                "type": "text", 
                                "text": {"content": content}
                            })
                
                if cleaned_rich_text:
                    # 确保语言类型安全，对可能有问题的代码块强制使用text
                    original_language = code.get('language', 'text')
                    language = get_safe_language_type(original_language)
                    
                    # 如果原始内容可能有问题，强制使用text语言
                    content_text = cleaned_rich_text[0]['text']['content'] if cleaned_rich_text else ''
                    if any(keyword in content_text for keyword in ['函数调用', 'open_url', 'search(', '# [', '1q43.blog']):
                        language = 'text'
                    
                    return {
                        "type": "code",
                        "code": {
                            "rich_text": cleaned_rich_text,
                            "language": language
                        }
                    }
        
        # 处理图片块
        elif block_type == 'image':
            return block
        
        return None
        
    except Exception as e:
        print(f"   ⚠️ 警告: 清理块内容时出错: {e}")
        return None

def main():
    """主执行函数"""
    print("🚀 启动 ChatGPT 到 Notion 导入器")
    
    # 验证配置
    if not validate_config():
        print("\n💡 提示: 请按照以下步骤设置:")
        print("1. 获取Notion API密钥: https://www.notion.so/my-integrations")
        print("2. 获取数据库ID: 从数据库URL中复制")
        print("3. 在脚本顶部的配置区域填入这些信息")
        sys.exit(1)
    
    # 设置API请求头
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json"
    }
    
    # 检测数据库结构
    print("🔍 检测数据库结构...")
    db_info = get_database_info(headers, NOTION_DATABASE_ID)
    
    if not db_info['properties']:
        print("⚠️ 警告: 无法获取数据库属性信息，可能是权限问题")
        print("请确保:")
        print("1. 你的集成有该数据库的访问权限")  
        print("2. 数据库至少有一个'标题'类型的属性")
    else:
        print(f"✅ 数据库检测结果:")
        print(f"   📝 标题属性: {db_info['title_property']}")
        if db_info['created_time_property']:
            print(f"   📅 创建时间属性: {db_info['created_time_property']}")
        if db_info['updated_time_property']:
            print(f"   🔄 更新时间属性: {db_info['updated_time_property']}")
        if db_info['conversation_id_property']:
            print(f"   🆔 对话ID属性: {db_info['conversation_id_property']} ({db_info['conversation_id_type']}类型)")
        print(f"   📊 总共发现 {len(db_info['properties'])} 个属性")
    
    # 验证对话文件存在
    if not os.path.exists(CONVERSATIONS_JSON_PATH):
        print(f"❌ 错误: 找不到对话文件 '{CONVERSATIONS_JSON_PATH}'")
        print(f"请检查 CHATGPT_EXPORT_PATH 设置: {CHATGPT_EXPORT_PATH}")
        print("确保conversations.json文件在指定目录中")
        sys.exit(1)

    # 读取对话数据
    try:
        with open(CONVERSATIONS_JSON_PATH, 'r', encoding='utf-8') as f:
            all_conversations = json.load(f)
        print(f"✅ 成功读取对话文件")
    except Exception as e:
        print(f"❌ 错误: 无法读取 conversations.json: {e}")
        sys.exit(1)

    # ====== 快速测试模式：仅挑选包含图片或 Canvas 的对话 ======
    if QUICK_TEST_MODE:
        print("🚧 QUICK_TEST 模式已启用：仅导入包含图片或 Canvas 的对话…")

        image_convs, canvas_convs = [], []

        def inspect_conversation(conv):
            has_image, has_canvas = False, False
            mapping = conv.get('mapping', {}) or {}
            for node in mapping.values():
                msg = node.get('message') or {}
                # 图片检测
                content = msg.get('content') or {}
                if content.get('content_type') == 'multimodal_text':
                    for part in content.get('parts', []):
                        if isinstance(part, dict) and part.get('content_type') == 'image_asset_pointer':
                            has_image = True
                            break
                # Canvas 检测
                if isinstance(msg.get('metadata'), dict) and 'canvas' in msg['metadata']:
                    has_canvas = True
            return has_image, has_canvas

        for conv in all_conversations:
            img, cvs = inspect_conversation(conv)
            if img and len(image_convs) < QUICK_TEST_LIMIT_PER_TYPE:
                image_convs.append(conv)
            if cvs and len(canvas_convs) < QUICK_TEST_LIMIT_PER_TYPE:
                canvas_convs.append(conv)
            # 退出早，节省时间
            if len(image_convs) >= QUICK_TEST_LIMIT_PER_TYPE and len(canvas_convs) >= QUICK_TEST_LIMIT_PER_TYPE:
                break

        # 合并并去重
        quick_list = {conv['id']: conv for conv in (image_convs + canvas_convs)}.values()
        conversations_to_process = list(quick_list)
        print(f"🔍 QUICK_TEST 选中对话数: {len(conversations_to_process)} (图片 {len(image_convs)}, Canvas {len(canvas_convs)})")

    # 加载已处理的对话ID
    processed_ids = load_processed_ids()

    if QUICK_TEST_MODE:
        # conversations_to_process 已在 QUICK_TEST 逻辑中生成，这里仅过滤已处理过的
        conversations_to_process = [
            conv for conv in conversations_to_process  # type: ignore  # 已定义于 QUICK_TEST
            if conv.get('id') not in processed_ids
        ]
    else:
        conversations_to_process = [
            conv for conv in all_conversations 
            if conv.get('id') not in processed_ids and 'title' in conv and 'mapping' in conv
        ]
    
    # 统计信息
    total_all = len(all_conversations)
    total_to_process = len(conversations_to_process)
    
    print(f"📊 统计信息:")
    print(f"   总对话数: {total_all}")
    print(f"   已处理: {len(processed_ids)} (将跳过)")
    print(f"   待处理: {total_to_process}")

    if total_to_process == 0:
        print("✅ 所有对话已处理完成，无需执行")
        return

    print(f"\n▶️ 开始处理 {total_to_process} 个新对话...")
    success_count, fail_count = 0, 0
    
    # 按时间倒序处理，最新的对话优先导入
    for conversation in tqdm(reversed(conversations_to_process), 
                           total=total_to_process, 
                           desc="导入进度", 
                           unit="对话"):
        conv_id = conversation['id']
        conv_title = conversation.get('title', 'Untitled')
        
        try:
            # 构建Notion块
            blocks = build_blocks_from_conversation(conversation, headers)
            
            # 导入到Notion
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
                log_processed_id(conv_id)  # 只有成功才记录
            else:
                fail_count += 1
                tqdm.write(f"❌ 导入失败: '{conv_title}' (下次运行时将重试)")

        except Exception as e:
            fail_count += 1
            tqdm.write(f"❌ 处理 '{conv_title}' 时发生意外错误: {e}")

        # 避免API速率限制
        time.sleep(0.4)

    # 输出最终结果
    print("\n" + "="*50)
    print("🎉 导入完成! 结果统计:")
    print(f"🟢 成功导入: {success_count} 个对话")
    if fail_count > 0:
        print(f"🔴 导入失败: {fail_count} 个对话")
        print("   💡 失败的对话将在下次运行时重试")
    print(f"⏭️  跳过 (已处理): {len(processed_ids)} 个对话")
    
    if success_count > 0:
        print(f"\n✨ 请到你的Notion数据库查看导入的 {success_count} 个对话!")

if __name__ == "__main__":
    main() 
