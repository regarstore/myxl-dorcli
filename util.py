from api_request import get_profile, get_balance, APIError
from datetime import datetime

def get_user_data(tokens: dict) -> dict:
    """
    Fetches user profile and balance using the provided tokens.
    This function is designed for use in a web context.
    """
    if not tokens or "access_token" not in tokens or "id_token" not in tokens:
        raise APIError("Invalid or missing tokens.")

    id_token = tokens.get("id_token")
    access_token = tokens.get("access_token")

    try:
        profile_data = get_profile(access_token, id_token)
        if not profile_data or "profile" not in profile_data:
            raise APIError("Failed to parse profile data.")
        
        phone_number = profile_data.get("profile", {}).get("msisdn")

        balance_data = get_balance(id_token)
        balance_remaining = balance_data.get("remaining")
        balance_expired_at_ts = balance_data.get("expired_at")
        
        # Convert timestamp to a readable string
        if balance_expired_at_ts:
            balance_expired_at = datetime.fromtimestamp(balance_expired_at_ts).strftime("%d %B %Y")
        else:
            balance_expired_at = "N/A"

        return {
            "is_logged_in": True,
            "phone_number": phone_number,
            "balance": balance_remaining,
            "balance_expired_at": balance_expired_at,
        }
    except APIError as e:
        # Re-raise the APIError to be handled by the Flask route
        raise e
    except Exception as e:
        # Catch any other unexpected errors
        raise APIError(f"An unexpected error occurred while fetching user data: {e}")