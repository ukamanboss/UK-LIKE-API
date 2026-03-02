from flask import Flask, request, jsonify
import asyncio
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
import binascii
import aiohttp
import requests
import json
import like_pb2
import like_count_pb2
import uid_generator_pb2
import threading
import urllib3
import random

# Configuration
TOKEN_BATCH_SIZE = 100
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Global State for Batch Management
current_batch_indices = {}
batch_indices_lock = threading.Lock()

def get_next_batch_tokens(server_name, all_tokens):
    if not all_tokens:
        return []
    total_tokens = len(all_tokens)
    if total_tokens <= TOKEN_BATCH_SIZE:
        return all_tokens
    with batch_indices_lock:
        if server_name not in current_batch_indices:
            current_batch_indices[server_name] = 0
        current_index = current_batch_indices[server_name]
        start_index = current_index
        end_index = start_index + TOKEN_BATCH_SIZE
        if end_index > total_tokens:
            remaining = end_index - total_tokens
            batch_tokens = all_tokens[start_index:total_tokens] + all_tokens[0:remaining]
        else:
            batch_tokens = all_tokens[start_index:end_index]
        next_index = (current_index + TOKEN_BATCH_SIZE) % total_tokens
        current_batch_indices[server_name] = next_index
        return batch_tokens

def get_random_batch_tokens(server_name, all_tokens):
    if not all_tokens:
        return []
    if len(all_tokens) <= TOKEN_BATCH_SIZE:
        return all_tokens.copy()
    return random.sample(all_tokens, TOKEN_BATCH_SIZE)

def load_tokens(server_name, for_visit=False):
    if for_visit:
        if server_name == "IND":
            path = "token_ind_visit.json"
        elif server_name in {"BR", "US", "SAC", "NA"}:
            path = "token_br_visit.json"
        else:
            path = "token_bd_visit.json"
    else:
        if server_name == "IND":
            path = "token_ind.json"
        elif server_name in {"BR", "US", "SAC", "NA"}:
            path = "token_br.json"
        else:
            path = "token_bd.json"
    try:
        with open(path, "r") as f:
            tokens = json.load(f)
            return tokens if isinstance(tokens, list) and all("token" in t for t in tokens) else []
    except:
        return []

def encrypt_message(plaintext):
    key, iv = b'Yg&tc%DEuh6%Zc^8', b'6oyZDr22E3ychjM%'
    cipher = AES.new(key, AES.MODE_CBC, iv)
    return binascii.hexlify(cipher.encrypt(pad(plaintext, AES.block_size))).decode('utf-8')

def create_protobuf_message(user_id, region):
    message = like_pb2.like()
    message.uid, message.region = int(user_id), region
    return message.SerializeToString()

def create_protobuf_for_profile_check(uid):
    message = uid_generator_pb2.uid_generator()
    message.krishna_, message.teamXdarks = int(uid), 1
    return message.SerializeToString()

async def send_single_like_request(encrypted_like_payload, token_dict, url):
    token_value = token_dict.get("token", "")
    headers = {
        'User-Agent': "Dalvik/2.1.0",
        'Authorization': f"Bearer {token_value}",
        'Content-Type': "application/x-www-form-urlencoded"
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=bytes.fromhex(encrypted_like_payload), headers=headers, timeout=10) as response:
                return response.status
    except:
        return 500

async def send_likes_with_token_batch(uid, region, like_api_url, tokens):
    payload = encrypt_message(create_protobuf_message(uid, region))
    tasks = [send_single_like_request(payload, t, like_api_url) for t in tokens]
    return await asyncio.gather(*tasks, return_exceptions=True)

def make_profile_check_request(uid, server_name, token_dict):
    token_value = token_dict.get("token", "")
    url = "https://client.ind.freefiremobile.com/GetPlayerPersonalShow" if server_name == "IND" else "https://client.us.freefiremobile.com/GetPlayerPersonalShow" if server_name in {"BR", "US", "SAC", "NA"} else "https://clientbp.ggblueshark.com/GetPlayerPersonalShow"
    
    payload = encrypt_message(create_protobuf_for_profile_check(uid))
    headers = {'User-Agent': "Dalvik/2.1.0", 'Authorization': f"Bearer {token_value}", 'Content-Type': "application/x-www-form-urlencoded"}
    try:
        response = requests.post(url, data=bytes.fromhex(payload), headers=headers, verify=False, timeout=10)
        items = like_count_pb2.Info()
        items.ParseFromString(response.content)
        return items
    except:
        return None

app = Flask(__name__)

@app.route('/like', methods=['GET'])
def handle_requests():
    uid_param = request.args.get("uid")
    server_name = request.args.get("server_name", "").upper()
    use_random = request.args.get("random", "false").lower() == "true"

    if not uid_param or not server_name:
        return jsonify({"error": "UID and server_name are required"}), 400

    visit_tokens = load_tokens(server_name, for_visit=True)
    visit_token = visit_tokens[0] if visit_tokens else None
    all_available_tokens = load_tokens(server_name, for_visit=False)
    
    if not all_available_tokens:
        return jsonify({"error": "No tokens available"}), 500

    # Before Info
    before_info = make_profile_check_request(uid_param, server_name, visit_token)
    before_likes = int(getattr(before_info.AccountInfo, 'Likes', 0)) if before_info and hasattr(before_info, 'AccountInfo') else 0

    # Sending Likes
    tokens_to_use = get_random_batch_tokens(server_name, all_available_tokens) if use_random else get_next_batch_tokens(server_name, all_available_tokens)
    
    like_url = "https://client.ind.freefiremobile.com/LikeProfile" if server_name == "IND" else "https://client.us.freefiremobile.com/LikeProfile" if server_name in {"BR", "US", "SAC", "NA"} else "https://clientbp.ggblueshark.com/LikeProfile"

    if tokens_to_use:
        asyncio.run(send_likes_with_token_batch(uid_param, server_name, like_url, tokens_to_use))
        
    # After Info
    after_info = make_profile_check_request(uid_param, server_name, visit_token)
    after_likes = before_likes
    nickname = "N/A"
    
    if after_info and hasattr(after_info, 'AccountInfo'):
        after_likes = int(after_info.AccountInfo.Likes)
        nickname = str(after_info.AccountInfo.PlayerNickname)

    likes_inc = after_likes - before_likes
    
    return jsonify({
        "LikesGivenByAPI": likes_inc,
        "LikesafterCommand": after_likes,
        "LikesbeforeCommand": before_likes,
        "PlayerNickname": nickname,
        "UID": uid_param,
        "status": 1 if likes_inc > 0 else 2,
        "RemainingLikes": len(all_available_tokens),
        "TotalLimit": len(all_available_tokens)
    })

@app.route('/token_info', methods=['GET'])
def token_info():
    servers = ["IND", "BD", "BR", "US", "SAC", "NA"]
    info = {}
    for server in servers:
        info[server] = {"regular_tokens": len(load_tokens(server, False)), "visit_tokens": len(load_tokens(server, True))}
    return jsonify(info)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001)
