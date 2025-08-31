import logging
from api_request import get_family, APIError

PACKAGE_FAMILY_CODE = "08a3b1e6-8e78-4e45-a540-b40f06871cfe"

def get_package_xut(tokens: dict):
    """Fetches and formats a specific family of packages (XUT)."""
    packages = []
    
    try:
        logging.info("Fetching XUT package family...")
        data = get_family(tokens, PACKAGE_FAMILY_CODE)

        if not data or "package_variants" not in data:
            logging.warning("XUT package data is missing 'package_variants'.")
            return []

        package_variants = data["package_variants"]
        start_number = 1
        for variant in package_variants:
            if variant.get("name") == "For Xtra Combo":
                for option in variant.get("package_options", []):
                    if option.get("name", "").lower() in ["vidio", "iflix", "basic"]:
                        friendly_name = option["name"]

                        if friendly_name.lower() == "basic":
                            friendly_name = "Xtra Combo Unli Turbo Basic"
                        elif friendly_name.lower() == "vidio":
                            friendly_name = "Unli Turbo Vidio 30 Hari"
                        elif friendly_name.lower() == "iflix":
                            friendly_name = "Unli Turbo Iflix 30 Hari"

                        packages.append({
                            "number": start_number,
                            "name": friendly_name,
                            "price": option.get("price", 0),
                            "code": option.get("package_option_code")
                        })
                        
                        start_number += 1
        logging.info(f"Found and formatted {len(packages)} XUT packages.")
        return packages
    except APIError as e:
        logging.error(f"API Error while fetching XUT packages: {e}")
        raise  # Re-raise the exception to be handled by the caller
    except Exception as e:
        logging.error(f"An unexpected error occurred in get_package_xut: {e}")
        raise APIError("An unexpected error occurred while formatting packages.")