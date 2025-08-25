import os, json
import sys

from api_request import *
from ui import *

def load_token():
    if os.path.exists("tokens.json"):
        with open("tokens.json", "r", encoding="utf8") as f:
            tokens = json.load(f)
        print("Tokens loaded successfully.")
        
        refresh_token = tokens.get("refresh_token")
        tokens = get_new_token(refresh_token)
        
        id_token = tokens.get("id_token")
        access_token = tokens.get("access_token")
        
        profile = get_profile(access_token, id_token)
        if not profile:
            print("Failed to fetch profile. Please check your tokens.")
            sys.exit(1)
        
        phone_number = profile.get("profile").get("msisdn")
        
        balance = get_balance(id_token)
        balance_remaining = balance.get("remaining")
        balance_expired_at = balance.get("expired_at")
        
        return {
            "tokens": tokens,
            "is_logged_in": True,
            "phone_number": phone_number,
            "balance": balance_remaining,
            "balance_expired_at": balance_expired_at,
        }
    
    return None