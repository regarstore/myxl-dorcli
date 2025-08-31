print("Starting import test...")
try:
    print("Importing os...")
    import os
    print("Importing functools...")
    from functools import wraps
    print("Importing flask...")
    from flask import Flask, render_template, request, redirect, url_for, session, flash
    print("Importing api_request...")
    from api_request import get_otp, submit_otp, APIError, get_package, purchase_package
    print("Importing util...")
    from util import get_user_data
    print("Importing paket_xut...")
    from paket_xut import get_package_xut
    print("Importing database...")
    from database import init_db, get_db_connection, get_all_packages
    print("Importing logging...")
    import logging
    print("All imports successful!")
except Exception as e:
    import traceback
    print(f"An error occurred during import: {e}")
    traceback.print_exc()
