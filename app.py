from flask import Flask, request, jsonify
import json
import asyncio
import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
import binascii
import aiohttp
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

app = Flask(__name__)

# ==========================================
# LEVEL INFO LOGIC (Independent)
# ==========================================
def format_num(num):
    return "{:,}".format(num)

LEVELS = {
    "1": 0, "2": 48, "3": 202, "4": 544, "5": 1012, "6": 1844, "7": 2792, "8": 3800,
    "9": 4870, "10": 6004, "11": 7192, "12": 8448, "13": 9776, "14": 11140, "15": 12566,
    "16": 14060, "17": 15610, "18": 17224, "19": 18902, "20": 20632, "21": 22424,
    "22": 24728, "23": 26192, "24": 28166, "25": 30200, "26": 32294, "27": 34448,
    "28": 37804, "29": 41174, "30": 44870, "31": 48852, "32": 53334, "33": 58566,
    "34": 64096, "35": 69994, "36": 76460, "37": 83108, "38": 91128, "39": 99322,
    "40": 108092, "41": 120144, "42": 133266, "43": 147472, "44": 162760, "45": 179126,
    "46": 196572, "47": 215368, "48": 235516, "49": 257010, "50": 279860, "51": 304056,
    "52": 348318, "53": 394982, "54": 444044, "55": 495508, "56": 549364, "57": 633756,
    "58": 721744, "59": 813336, "60": 908522, "61": 1041438, "62": 1180352, "63": 1325256,
    "64": 1476184, "65": 1634300, "66": 1840946, "67": 2056594, "68": 2281242, "69": 2514880,
    "70": 2757530, "71": 3059506, "72": 3372284, "73": 3699456, "74": 4041030, "75": 4397020,
    "76": 4829104, "77": 5282204, "78": 5756304, "79": 6251404, "80": 6767504, "81": 7381324,
    "82": 8043154, "83": 8752952, "84": 9510808, "85": 10316638, "86": 11277190, "87": 12360748,
    "88": 13360304, "89": 14482858, "90": 15659418, "91": 17026708, "92": 18453688, "93": 19941280,
    "94": 21488570, "95": 23095858, "96": 24763138, "97": 26490138, "98": 28277708, "99": 30124996,
    "100": 32032284,
}

def get_exp_for_level(level):
    try:
        level_str = str(int(level))
        return LEVELS.get(level_str, 0)
    except:
        return 0

def calculate_level_progress(current_exp, current_level):
    try:
        current_level = int(current_level)
        if current_level >= 100:
            return {
                "current_level": 100, "current_exp": current_exp,
                "exp_for_current_level": LEVELS["100"], "exp_for_next_level": LEVELS["100"],
                "exp_needed": 0, "progress_percentage": 100
            }
        
        exp_for_current = get_exp_for_level(current_level)
        exp_for_next = get_exp_for_level(current_level + 1)
        if exp_for_next == 0 or exp_for_current == 0: return None
        
        exp_needed = exp_for_next - current_exp
        exp_range_for_level = exp_for_next - exp_for_current
        progress_percentage = min(100, max(0, ((current_exp - exp_for_current) / exp_range_for_level) * 100)) if exp_range_for_level > 0 else 0
        
        return {
            "current_level": current_level, "current_exp": current_exp,
            "exp_for_current_level": exp_for_current, "exp_for_next_level": exp_for_next,
            "exp_needed": exp_needed, "progress_percentage": round(progress_percentage, 1)
        }
    except Exception as e:
        print(f"Error in level progress: {e}")
        return None

# ==========================================
# LIKE API & PROFILE LOGIC
# ==========================================
def get_next_batch_tokens(server_name, all_tokens):
    if not all_tokens: return []
    total_tokens = len(all_tokens)
    if total_tokens <= TOKEN_BATCH_SIZE: return all_tokens
    with batch_indices_lock:
        if server_name not in current_batch_indices: current_batch_indices[server_name] = 0
        current_index = current_batch_indices[server_name]
        end_index = current_index + TOKEN_BATCH_SIZE
        if end_index > total_tokens:
            batch_tokens = all_tokens[current_index:total_tokens] + all_tokens[0:(end_index - total_tokens)]
        else:
            batch_tokens = all_tokens[current_index:end_index]
        current_batch_indices[server_name] = (current_index + TOKEN_BATCH_SIZE) % total_tokens
        return batch_tokens

def get_random_batch_tokens(server_name, all_tokens):
    if not all_tokens: return []
    if len(all_tokens) <= TOKEN_BATCH_SIZE: return all_tokens.copy()
    return random.sample(all_tokens, TOKEN_BATCH_SIZE)

def load_tokens(server_name, for_visit=False):
    path = "token_ind" if server_name == "IND" else "token_br" if server_name in {"BR", "US", "SAC", "NA"} else "token_bd"
    path += "_visit.json" if for_visit else ".json"
    try:
        with open(path, "r") as f:
            tokens = json.load(f)
            return tokens if isinstance(tokens, list) and all("token" in t for t in tokens) else []
    except:
        return []

def encrypt_message(plaintext):
    cipher = AES.new(b'Yg&tc%DEuh6%Zc^8', AES.MODE_CBC, b'6oyZDr22E3ychjM%')
    return binascii.hexlify(cipher.encrypt(pad(plaintext, AES.block_size))).decode('utf-8')

def create_protobuf_message(uid, region):
    msg = like_pb2.like()
    msg.uid, msg.region = int(uid), region
    return msg.SerializeToString()

def enc_profile_check_payload(uid):
    msg = uid_generator_pb2.uid_generator()
    msg.krishna_, msg.teamXdarks = int(uid), 1
    return encrypt_message(msg.SerializeToString())

async def send_single_like_request(enc_payload, token_dict, url):
    token = token_dict.get("token", "")
    headers = {'User-Agent': "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)", 'Authorization': f"Bearer {token}", 'Content-Type': "application/x-www-form-urlencoded", 'X-Unity-Version': "2018.4.11f1"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=bytes.fromhex(enc_payload), headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                return resp.status
    except: return 997

async def send_likes_with_token_batch(uid, region, url, tokens):
    enc_payload = encrypt_message(create_protobuf_message(uid, region))
    tasks = [send_single_like_request(enc_payload, t, url) for t in tokens]
    return await asyncio.gather(*tasks, return_exceptions=True)

def make_profile_check_request(enc_payload, server, token_dict):
    token = token_dict.get("token", "")
    url = "https://client.ind.freefiremobile.com/GetPlayerPersonalShow" if server == "IND" else "https://client.us.freefiremobile.com/GetPlayerPersonalShow" if server in {"BR", "US", "SAC", "NA"} else "https://clientbp.ggblueshark.com/GetPlayerPersonalShow"
    headers = {'User-Agent': "Dalvik/2.1.0", 'Authorization': f"Bearer {token}", 'Content-Type': "application/x-www-form-urlencoded", 'X-Unity-Version': "2018.4.11f1"}
    try:
        res = requests.post(url, data=bytes.fromhex(enc_payload), headers=headers, verify=False, timeout=10)
        items = like_count_pb2.Info()
        items.ParseFromString(res.content)
        return items
    except: return None

# ==========================================
# ROUTES
# ==========================================

@app.route('/like', methods=['GET'])
def handle_requests():
    uid_param = request.args.get("uid")
    server_name = request.args.get("server_name", "").upper()
    use_random = request.args.get("random", "false").lower() == "true"

    if not uid_param or not server_name:
        return jsonify({"error": "UID and server_name required"}), 400

    visit_tokens = load_tokens(server_name, for_visit=True)
    visit_token = visit_tokens[0] if visit_tokens else None
    
    all_tokens = load_tokens(server_name, for_visit=False)
    tokens_to_use = get_random_batch_tokens(server_name, all_tokens) if use_random else get_next_batch_tokens(server_name, all_tokens)
    
    enc_payload = enc_profile_check_payload(uid_param)
    
    # Check Profile BEFORE Likes
    before_info = make_profile_check_request(enc_payload, server_name, visit_token)
    before_likes = int(getattr(before_info.AccountInfo, 'Likes', 0)) if before_info and hasattr(before_info, 'AccountInfo') else 0

    like_api_url = "https://client.ind.freefiremobile.com/LikeProfile" if server_name == "IND" else "https://client.us.freefiremobile.com/LikeProfile" if server_name in {"BR", "US", "SAC", "NA"} else "https://clientbp.ggblueshark.com/LikeProfile"

    # Send Likes
    if tokens_to_use:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(send_likes_with_token_batch(uid_param, server_name, like_api_url, tokens_to_use))
        loop.close()

    # Check Profile AFTER Likes (Garena se sidha data le rahe hain)
    after_info = make_profile_check_request(enc_payload, server_name, visit_token)
    
    after_likes = before_likes
    nickname = "N/A"
    current_level = 0
    current_exp = 0
    
    # 🌟 Garena ke data (Protobuf) se Profile, Level, EXP sab nikalna 🌟
    if after_info and hasattr(after_info, 'AccountInfo'):
        try:
            after_likes = int(getattr(after_info.AccountInfo, 'Likes', before_likes))
            nickname = str(getattr(after_info.AccountInfo, 'PlayerNickname', 'N/A'))
            current_level = int(getattr(after_info.AccountInfo, 'Level', 0))
            current_exp = int(getattr(after_info.AccountInfo, 'Exp', 0))
        except Exception as e:
            print(f"Data extract karne me error: {e}")

    likes_inc = after_likes - before_likes
    status = 1 if likes_inc > 0 else (2 if likes_inc == 0 else 3)

    # Calculate EXP Progress
    level_data = {"current_level": current_level, "current_exp": current_exp, "progress_percentage": 0}
    if current_level > 0:
        prog = calculate_level_progress(current_exp, current_level)
        if prog: level_data = prog

    return jsonify({
        "LikesGivenByAPI": likes_inc,
        "LikesafterCommand": after_likes,
        "LikesbeforeCommand": before_likes,
        "PlayerNickname": nickname,
        "UID": uid_param,
        "Level": level_data.get("current_level", "N/A"),
        "CurrentEXP": level_data.get("current_exp", "N/A"),
        "ExpProgress": f"{level_data.get('progress_percentage', 0)}%",
        "status": status,
        "RemainingLikes": len(all_tokens), 
        "TotalLimit": len(all_tokens)
    })

@app.route('/token_info', methods=['GET'])
def token_info():
    servers = ["IND", "BD", "BR", "US", "SAC", "NA"]
    return jsonify({s: {"regular_tokens": len(load_tokens(s, False)), "visit_tokens": len(load_tokens(s, True))} for s in servers})

# Independent Level Route (Ye bhi Garena ka server use karega directly)
@app.route('/level/<uid>')
def get_level_info(uid):
    if request.args.get('key') not in ["Flash", "DENGER"]:
        return jsonify({"success": False, "message": "Invalid Key"}), 401
    
    server_name = request.args.get("server_name", "IND").upper()
    visit_tokens = load_tokens(server_name, for_visit=True)
    visit_token = visit_tokens[0] if visit_tokens else None

    if not visit_token:
        return jsonify({"success": False, "message": "No visit tokens available to check profile"}), 500

    enc_payload = enc_profile_check_payload(uid)
    profile_info = make_profile_check_request(enc_payload, server_name, visit_token)
    
    if profile_info and hasattr(profile_info, 'AccountInfo'):
        current_level = int(getattr(profile_info.AccountInfo, 'Level', 0))
        current_exp = int(getattr(profile_info.AccountInfo, 'Exp', 0))
        nickname = str(getattr(profile_info.AccountInfo, 'PlayerNickname', 'N/A'))
        
        prog = calculate_level_progress(current_exp, current_level)
        if not prog: return jsonify({"success": False, "message": "Calculation error"})
        
        return jsonify({"success": True, "uid": uid, "nickname": nickname, **prog})
    else:
        return jsonify({"success": False, "message": "Error fetching data from Free Fire server"})

@app.route('/levels')
def get_all_levels():
    return jsonify({"success": True, "total_levels": 100, "levels": LEVELS})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True, use_reloader=False)
