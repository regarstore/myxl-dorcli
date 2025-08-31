import json
import uuid
import requests
import time
import logging
from datetime import datetime, timezone, timedelta

from crypto_helper import (
    encryptsign_xdata, java_like_timestamp, ts_gmt7_without_colon,
    ax_api_signature, decrypt_xdata, API_KEY, make_x_signature_payment,
    build_encrypted_field
)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

BASE_URL = "https://api.myxl.xlaxiata.co.id"

class APIError(Exception):
    """Custom exception for API related errors."""
    pass

def validate_contact(contact: str) -> bool:
    """Validates the phone number format."""
    if not contact.startswith("628") or len(contact) > 14:
        return False
    return True

def get_otp(contact: str) -> str:
    """Requests an OTP for the given contact number."""
    if not validate_contact(contact):
        raise APIError("Invalid phone number format. It must start with '628'.")

    url = "https://gede.ciam.xlaxiata.co.id/realms/xl-ciam/auth/otp"
    querystring = {"contact": contact, "contactType": "SMS", "alternateContact": "false"}
    
    now = datetime.now(timezone(timedelta(hours=7)))
    headers = {
        "Accept-Encoding": "gzip, deflate, br",
        "Authorization": "Basic OWZjOTdlZDEtNmEzMC00OGQ1LTk1MTYtNjBjNTNjZTNhMTM1OllEV21GNExKajlYSUt3UW56eTJlMmxiMHRKUWIyOW8z",
        "Ax-Device-Id": "92fb44c0804233eb4d9e29f838223a14",
        "Ax-Fingerprint": "YmQLy9ZiLLBFAEVcI4Dnw9+NJWZcdGoQyewxMF/9hbfk/8GbKBgtZxqdiiam8+m2lK31E/zJQ7kjuPXpB3EE8naYL0Q8+0WLhFV1WAPl9Eg=",
        "Ax-Request-At": java_like_timestamp(now),
        "Ax-Request-Device": "samsung",
        "Ax-Request-Device-Model": "SM-N935F",
        "Ax-Request-Id": str(uuid.uuid4()),
        "Ax-Substype": "PREPAID",
        "Content-Type": "application/json",
        "Host": "gede.ciam.xlaxiata.co.id",
        "User-Agent": "myXL / 8.6.0(1179); com.android.vending; (samsung; SM-N935F; SDK 33; Android 13)"
    }

    logging.info(f"Requesting OTP for contact: {contact}")
    try:
        response = requests.get(url, headers=headers, params=querystring, timeout=30)
        response.raise_for_status()
        json_body = response.json()
        logging.debug(f"OTP Response Body: {json_body}")

        if "subscriber_id" not in json_body:
            error_msg = json_body.get("error_description", "Subscriber ID not found in OTP response.")
            logging.error(f"OTP request failed for {contact}: {error_msg}")
            raise APIError(error_msg)
        
        return json_body["subscriber_id"]
    except requests.RequestException as e:
        logging.error(f"Error requesting OTP for {contact}: {e}")
        raise APIError(f"Network error during OTP request: {e}")

def submit_otp(contact: str, code: str) -> dict:
    """Submits the OTP code to get tokens."""
    if not validate_contact(contact):
        raise APIError("Invalid phone number format.")
    if not code or len(code) != 6 or not code.isdigit():
        raise APIError("Invalid OTP code format. Must be 6 digits.")

    url = "https://gede.ciam.xlaxiata.co.id/realms/xl-ciam/protocol/openid-connect/token"

    now_gmt7 = datetime.now(timezone(timedelta(hours=7)))
    ts_for_sign = ts_gmt7_without_colon(now_gmt7)
    ts_header = ts_gmt7_without_colon(now_gmt7 - timedelta(minutes=5))
    signature = ax_api_signature(ts_for_sign, contact, code, "SMS")

    payload = f"contactType=SMS&code={code}&grant_type=password&contact={contact}&scope=openid"
    headers = {
        "Accept-Encoding": "gzip, deflate, br",
        "Authorization": "Basic OWZjOTdlZDEtNmEzMC00OGQ1LTk1MTYtNjBjNTNjZTNhMTM1OllEV21GNExKajlYSUt3UW56eTJlMmxiMHRKUWIyOW8z",
        "Ax-Api-Signature": signature,
        "Ax-Device-Id": "92fb44c0804233eb4d9e29f838223a14",
        "Ax-Fingerprint": "YmQLy9ZiLLBFAEVcI4Dnw9+NJWZcdGoQyewxMF/9hbfk/8GbKBgtZxqdiiam8+m2lK31E/zJQ7kjuPXpB3EE8naYL0Q8+0WLhFV1WAPl9Eg=",
        "Ax-Request-At": ts_header,
        "Ax-Request-Device": "samsung",
        "Ax-Request-Device-Model": "SM-N935F",
        "Ax-Request-Id": str(uuid.uuid4()),
        "Ax-Substype": "PREPAID",
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "myXL / 8.6.0(1179); com.android.vending; (samsung; SM-N935F; SDK 33; Android 13)",
    }

    logging.info(f"Submitting OTP for contact: {contact}")
    try:
        response = requests.post(url, data=payload, headers=headers, timeout=30)
        response.raise_for_status()
        json_body = response.json()

        if "error" in json_body:
            error_msg = json_body.get('error_description', 'Unknown error during OTP submission.')
            logging.error(f"OTP submission failed for {contact}: {error_msg}")
            raise APIError(error_msg)
        
        logging.info(f"Successfully logged in {contact}")
        return json_body
    except requests.RequestException as e:
        logging.error(f"Error submitting OTP for {contact}: {e}")
        raise APIError(f"Network error during OTP submission: {e}")

def send_api_request(path: str, payload_dict: dict, id_token: str, method: str = "POST") -> dict:
    """Sends a signed and encrypted request to the MyXL API."""
    encrypted_payload = encryptsign_xdata(method=method, path=path, id_token=id_token, payload=payload_dict)
    
    xtime = int(encrypted_payload["encrypted_body"]["xtime"])
    now = datetime.now(timezone.utc).astimezone()
    sig_time_sec = (xtime // 1000)
    body = encrypted_payload["encrypted_body"]
    x_sig = encrypted_payload["x_signature"]
    
    headers = {
        "host": "api.myxl.xlaxiata.co.id",
        "content-type": "application/json; charset=utf-8",
        "user-agent": "myXL / 8.6.0(1179); com.android.vending; (samsung; SM-N935F; SDK 33; Android 13)",
        "x-api-key": API_KEY,
        "authorization": f"Bearer {id_token}",
        "x-hv": "v3",
        "x-signature-time": str(sig_time_sec),
        "x-signature": x_sig,
        "x-request-id": str(uuid.uuid4()),
        "x-request-at": java_like_timestamp(now),
        "x-version-app": "8.6.0",
    }

    url = f"{BASE_URL}/{path}"
    logging.info(f"Sending API request to {url}")
    try:
        resp = requests.post(url, headers=headers, data=json.dumps(body), timeout=30)
        resp.raise_for_status()
        decrypted_body = decrypt_xdata(resp.json())
        return decrypted_body
    except requests.RequestException as e:
        logging.error(f"API request to {url} failed: {e}")
        raise APIError(f"Network error during API request: {e}")
    except Exception as e:
        logging.error(f"Failed to decrypt response from {url}: {e}")
        raise APIError("Failed to process API response.")

def get_profile(access_token: str, id_token: str) -> dict:
    """Fetches user profile information."""
    path = "api/v8/profile"
    raw_payload = {"access_token": access_token, "app_version": "8.6.0", "is_enterprise": False, "lang": "en"}
    logging.info("Fetching profile...")
    res = send_api_request(path, raw_payload, id_token, "POST")
    if res.get("status") != "SUCCESS" or "data" not in res:
        raise APIError(res.get("message", "Failed to fetch profile."))
    return res["data"]

def get_balance(id_token: str) -> dict:
    """Fetches user balance information."""
    path = "api/v8/packages/balance-and-credit"
    raw_payload = {"is_enterprise": False, "lang": "en"}
    logging.info("Fetching balance...")
    res = send_api_request(path, raw_payload, id_token, "POST")
    if res.get("status") != "SUCCESS" or "data" not in res or "balance" not in res["data"]:
        raise APIError(res.get("message", "Failed to fetch balance."))
    return res["data"]["balance"]

def get_family(tokens: dict, family_code: str) -> dict:
    """Fetches a family of packages."""
    path = "api/v8/xl-stores/options/list"
    id_token = tokens.get("id_token")
    payload_dict = {
        "is_show_tagging_tab": True, "is_dedicated_event": True, "is_transaction_routine": False,
        "migration_type": "", "package_family_code": family_code, "is_autobuy": False,
        "is_enterprise": False, "is_pdlp": True, "referral_code": "", "is_migration": False, "lang": "en"
    }
    logging.info(f"Fetching package family: {family_code}")
    res = send_api_request(path, payload_dict, id_token, "POST")
    if res.get("status") != "SUCCESS" or "data" not in res:
        raise APIError(f"Failed to get package family {family_code}")
    return res["data"]

def get_package(tokens: dict, package_option_code: str) -> dict:
    """Fetches details for a specific package."""
    path = "api/v8/xl-stores/options/detail"
    raw_payload = {
        "is_transaction_routine": False, "migration_type": "", "package_family_code": "",
        "family_role_hub": "", "is_autobuy": False, "is_enterprise": False, "is_shareable": False,
        "is_migration": False, "lang": "en", "package_option_code": package_option_code,
        "is_upsell_pdp": False, "package_variant_code": ""
    }
    logging.info(f"Fetching package details for: {package_option_code}")
    res = send_api_request(path, raw_payload, tokens["id_token"], "POST")
    if res.get("status") != "SUCCESS" or "data" not in res:
        raise APIError(res.get("message", "Failed to get package details."))
    return res["data"]

def send_payment_request(payload_dict: dict, access_token: str, id_token: str, token_payment: str, ts_to_sign: int):
    """Sends the final payment settlement request."""
    path = "payments/api/v8/settlement-balance"
    package_code = payload_dict["items"][0]["item_code"]
    
    encrypted_payload = encryptsign_xdata(method="POST", path=path, id_token=id_token, payload=payload_dict)
    
    xtime = int(encrypted_payload["encrypted_body"]["xtime"])
    sig_time_sec = (xtime // 1000)
    x_requested_at = datetime.fromtimestamp(sig_time_sec, tz=timezone.utc).astimezone()
    payload_dict["timestamp"] = ts_to_sign
    
    body = encrypted_payload["encrypted_body"]
    x_sig2 = make_x_signature_payment(access_token, ts_to_sign, package_code, token_payment)
    
    headers = {
        "host": "api.myxl.xlaxiata.co.id",
        "content-type": "application/json; charset=utf-8",
        "user-agent": "myXL / 8.6.0(1179); com.android.vending; (samsung; SM-N935F; SDK 33; Android 13)",
        "x-api-key": API_KEY,
        "authorization": f"Bearer {id_token}",
        "x-hv": "v3",
        "x-signature-time": str(sig_time_sec),
        "x-signature": x_sig2,
        "x-request-id": str(uuid.uuid4()),
        "x-request-at": java_like_timestamp(x_requested_at),
        "x-version-app": "8.6.0",
    }
    
    url = f"{BASE_URL}/{path}"
    logging.info(f"Sending payment request to {url}")
    try:
        resp = requests.post(url, headers=headers, data=json.dumps(body), timeout=30)
        resp.raise_for_status()
        decrypted_body = decrypt_xdata(resp.json())
        return decrypted_body
    except requests.RequestException as e:
        logging.error(f"Payment request to {url} failed: {e}")
        raise APIError(f"Network error during payment request: {e}")
    except Exception as e:
        logging.error(f"Failed to decrypt payment response from {url}: {e}")
        raise APIError("Failed to process payment response.")

def purchase_package(tokens: dict, package_option_code: str) -> dict:
    """Handles the full package purchase flow."""
    package_details_data = get_package(tokens, package_option_code)
    
    token_confirmation = package_details_data["token_confirmation"]
    payment_target = package_details_data["package_option"]["package_option_code"]
    price = package_details_data["package_option"]["price"]
    
    # Step 1: Initiate Payment to get payment token
    payment_path = "payments/api/v8/payment-methods-option"
    payment_payload = {
        "payment_type": "PURCHASE", "is_enterprise": False, "payment_target": payment_target,
        "lang": "en", "is_referral": False, "token_confirmation": token_confirmation
    }
    
    logging.info("Initiating payment...")
    payment_res = send_api_request(payment_path, payment_payload, tokens["id_token"], "POST")
    if payment_res.get("status") != "SUCCESS":
        raise APIError(payment_res.get("message", "Failed to initiate payment."))
    
    token_payment = payment_res["data"]["token_payment"]
    ts_to_sign = payment_res["data"]["timestamp"]
    
    # Step 2: Send Settlement Request
    settlement_payload = {
        "total_discount": 0, "is_enterprise": False, "payment_token": "", "token_payment": token_payment,
        "activated_autobuy_code": "", "cc_payment_type": "", "is_myxl_wallet": False, "pin": "",
        "ewallet_promo_id": "", "members": [], "total_fee": 0, "fingerprint": "",
        "autobuy_threshold_setting": {"label": "", "type": "", "value": 0},
        "is_use_point": False, "lang": "en", "payment_method": "BALANCE", "timestamp": int(time.time()),
        "points_gained": 0, "can_trigger_rating": False, "akrab_members": [], "akrab_parent_alias": "",
        "referral_unique_code": "", "coupon": "", "payment_for": "BUY_PACKAGE", "with_upsell": False,
        "topup_number": "", "stage_token": "", "authentication_id": "",
        "encrypted_payment_token": build_encrypted_field(urlsafe_b64=True), "token": "",
        "token_confirmation": "", "access_token": tokens["access_token"], "wallet_number": "",
        "encrypted_authentication_id": build_encrypted_field(urlsafe_b64=True),
        "additional_data": {}, "total_amount": price, "is_using_autobuy": False,
        "items": [{"item_code": payment_target, "product_type": "", "item_price": price, "item_name": "", "tax": 0}]
    }
    
    logging.info("Processing purchase...")
    purchase_result = send_payment_request(
        settlement_payload, tokens["access_token"], tokens["id_token"], token_payment, ts_to_sign
    )
    
    logging.info(f"Purchase result: {json.dumps(purchase_result, indent=2)}")
    
    if purchase_result.get("status") != "SUCCESS":
        raise APIError(purchase_result.get("message", "Package purchase failed."))

    return purchase_result

    