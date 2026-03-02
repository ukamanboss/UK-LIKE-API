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
from datetime import datetime

app = Flask(__name__)

# --- Configuration & Setup ---
TOKEN_BATCH_SIZE = 100
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

current_batch_indices = {}
batch_indices_lock = threading.Lock()

# --- LEVELS Dictionary ---
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

# --- Core Utility Functions ---
def format_num(num):
    return "{:,}".format(num)

def get_exp_for_level(level):
    try: return LEVELS.get(str(int(level)), 0)
    except: return 0

def calculate_level_progress(current_exp, current_level):
    try:
        current_level = int(current_level)
        if current_level >= 100: return {"current_level": 100, "progress_percentage": 100}
        exp_for_current = get_exp_for_level(current_level)
        exp_for_next = get_exp_for_level(current_level + 1)
        if exp_for_next == 0: return None
        exp_range = exp_for_next - exp_for_current
        progress = min(100, max(0, ((current_exp - exp_for_current) / exp_range) * 100)) if exp_range > 0 else 0
        return {"current_level": current_level, "current_exp": current_exp, "exp_needed": exp_for_next - current_exp, "progress_percentage": round(progress, 1)}
    except: return None

def encrypt_message(plaintext):
    key, iv = b'Yg&tc%DEuh6%Zc^8', b'6oyZDr22E3ychjM%'
    cipher = AES.new(key, AES.MODE_CBC, iv)
    return binascii.hexlify(cipher.encrypt(pad(plaintext, AES.block_size))).decode('utf-8')

def load_tokens(server_name, for_visit=False):
    prefix = "token_ind" if server_name == "IND" else "token_br" if server_name in {"BR", "US", "SAC", "NA"} else "token_bd"
    path = f"{prefix}_visit.json" if for_visit else f"{prefix}.json"
    try:
        with open(path, "r") as f:
            tokens = json.load(f)
            return tokens if isinstance(tokens, list) else []
    except: return []

# --- API Request Functions ---
async def send_single_like_request(enc_payload, token_dict, url):
    token = token_dict.get("token", "")
    headers = {'User-Agent': "Dalvik/2.1.0", 'Authorization': f"Bearer {token}", 'Content-Type': "application/x-www-form-urlencoded"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=bytes.fromhex(enc_payload), headers=headers, timeout=10) as resp:
                return resp.status
    except: return 500

def make_profile_check_request(uid, server, token_dict):
    token = token_dict.get("token", "")
    url = "https://client.ind.freefiremobile.com/GetPlayerPersonalShow" if server == "IND" else "https://client.us.freefiremobile.com/GetPlayerPersonalShow" if server in {"BR", "US", "SAC", "NA"} else "https://clientbp.ggblueshark.com/GetPlayerPersonalShow"
    msg = uid_generator_pb2.uid_generator()
    msg.krishna_, msg.teamXdarks = int(uid), 1
    enc_payload = encrypt_message(msg.SerializeToString())
    headers = {'User-Agent': "Dalvik/2.1.0", 'Authorization': f"Bearer {token}", 'Content-Type': "application/x-www-form-urlencoded"}
    try:
        res = requests.post(url, data=bytes.fromhex(enc_payload), headers=headers, verify=False, timeout=10)
        items = like_count_pb2.Info()
        items.ParseFromString(res.content)
        return items
    except: return None

# --- Main Routes ---
@app.route('/like', methods=['GET'])
def handle_like_and_level():
    uid = request.args.get("uid")
    server = request.args.get("server_name", "").upper()
    if not uid or not server: return jsonify({"error": "Missing params"}), 400

    v_tokens = load_tokens(server, True)
    v_token = v_tokens[0] if v_tokens else {}
    
    # 1. Check Profile BEFORE Likes
    profile = make_profile_check_request(uid, server, v_token)
    b_likes = int(getattr(profile.AccountInfo, 'Likes', 0)) if profile and hasattr(profile, 'AccountInfo') else 0

    # 2. Process Like Batch
    all_t = load_tokens(server, False)
    batch = random.sample(all_t, min(len(all_t), TOKEN_BATCH_SIZE))
    if batch:
        like_url = "https://client.ind.freefiremobile.com/LikeProfile" if server == "IND" else "https://client.us.freefiremobile.com/LikeProfile" if server in {"BR", "US", "SAC", "NA"} else "https://clientbp.ggblueshark.com/LikeProfile"
        like_msg = like_pb2.like()
        like_msg.uid, like_msg.region = int(uid), server
        enc_like_payload = encrypt_message(like_msg.SerializeToString())
        
        async def run_likes():
            tasks = [send_single_like_request(enc_like_payload, t, like_url) for t in batch]
            await asyncio.gather(*tasks)
        
        asyncio.run(run_likes())

    # 3. Check Profile AFTER & Get Level Info
    profile = make_profile_check_request(uid, server, v_token)
    a_likes = b_likes
    name, lvl, exp = "N/A", 0, 0
    if profile and hasattr(profile, 'AccountInfo'):
        a_likes = int(getattr(profile.AccountInfo, 'Likes', b_likes))
        name = str(getattr(profile.AccountInfo, 'PlayerNickname', 'N/A'))
        lvl = int(getattr(profile.AccountInfo, 'Level', 0))
        exp = int(getattr(profile.AccountInfo, 'Exp', 0))

    prog = calculate_level_progress(exp, lvl)
    
    return jsonify({
        "LikesGivenByAPI": a_likes - b_likes,
        "LikesafterCommand": a_likes,
        "LikesbeforeCommand": b_likes,
        "PlayerNickname": name,
        "UID": uid,
        "Level": lvl,
        "CurrentEXP": exp,
        "ExpProgress": f"{prog['progress_percentage']}%" if prog else "0%",
        "status": 1 if a_likes > b_likes else 2,
        "RemainingLikes": len(all_t),
        "TotalLimit": len(all_t)
    })

@app.route('/token_info')
def token_info():
    res = {}
    for s in ["IND", "BD", "BR", "US"]:
        res[s] = {"regular_tokens": len(load_tokens(s, False)), "visit_tokens": len(load_tokens(s, True))}
    return jsonify(res)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001)
