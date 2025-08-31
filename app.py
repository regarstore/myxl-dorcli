import os
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash

# Import the refactored API functions and custom exception
from api_request import get_otp, submit_otp, APIError, get_package, purchase_package
from util import get_user_data
from paket_xut import get_package_xut
from database import init_db, get_db_connection, get_all_packages
import logging

app = Flask(__name__)
# A secret key is required for session management
app.secret_key = os.urandom(24)
app.config['ADMIN_PHONE_NUMBERS'] = ['6281818988646'] # As requested by user

# Decorator to protect routes that require login
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'tokens' not in session:
            flash("You must be logged in to view this page.", "warning")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('user_data', {}).get('is_admin'):
            flash("You do not have permission to access this page.", "danger")
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def index():
    if 'tokens' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'tokens' in session:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        phone_number = request.form.get('phone_number')
        if not phone_number or not phone_number.startswith('628'):
            flash("Invalid phone number. It must be a valid XL number starting with 62.", "danger")
            return render_template('login.html')

        try:
            get_otp(phone_number)
            flash(f"An OTP has been sent to {phone_number}.", "success")
            # Store phone number in session to pass to OTP page
            session['phone_number_for_otp'] = phone_number
            return redirect(url_for('otp'))
        except APIError as e:
            flash(str(e), "danger")
            return render_template('login.html')

    return render_template('login.html')

@app.route('/otp', methods=['GET', 'POST'])
def otp():
    if 'tokens' in session:
        return redirect(url_for('dashboard'))

    phone_number = session.get('phone_number_for_otp')
    if not phone_number:
        flash("Please enter your phone number first.", "warning")
        return redirect(url_for('login'))

    if request.method == 'POST':
        otp_code = request.form.get('otp_code')
        phone_number_from_form = request.form.get('phone_number') # from hidden input

        if not otp_code or len(otp_code) != 6:
            flash("Invalid OTP format. It must be 6 digits.", "danger")
            return render_template('otp.html', phone_number=phone_number_from_form)

        try:
            tokens = submit_otp(phone_number_from_form, otp_code)
            session['tokens'] = tokens

            # Fetch user data from XL API
            api_user_data = get_user_data(tokens)
            phone_number = api_user_data['phone_number']

            # Connect to our local database
            conn = get_db_connection()
            db_user = conn.execute('SELECT * FROM users WHERE phone_number = ?', (phone_number,)).fetchone()

            if db_user is None:
                # New user, create an entry in our database
                conn.execute('INSERT INTO users (phone_number, balance) VALUES (?, ?)', (phone_number, 0))
                conn.commit()
                db_user = conn.execute('SELECT * FROM users WHERE phone_number = ?', (phone_number,)).fetchone()

            conn.close()

            # Store a combined user data object in the session
            session['user_data'] = {
                'phone_number': db_user['phone_number'],
                'balance': db_user['balance'],
                'is_admin': db_user['phone_number'] in app.config['ADMIN_PHONE_NUMBERS']
            }

            session.pop('phone_number_for_otp', None)
            flash("Login successful!", "success")
            return redirect(url_for('dashboard'))
        except APIError as e:
            flash(str(e), "danger")
            return render_template('otp.html', phone_number=phone_number_from_form)

    return render_template('otp.html', phone_number=phone_number)

@app.route('/logout')
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    # User data is fetched from the session
    user_data = session.get('user_data')
    # Packages are now fetched from our local database
    packages = get_all_packages()
    return render_template('dashboard.html', user_data=user_data, packages=packages)

@app.route('/purchase/<package_code>')
@login_required
def purchase_package_page(package_code):
    try:
        conn = get_db_connection()
        package_data = conn.execute('SELECT * FROM packages WHERE code = ?', (package_code,)).fetchone()
        conn.close()

        if not package_data:
            flash("Package not found.", "danger")
            return redirect(url_for('dashboard'))

        # Use admin_price if available, otherwise use original price
        display_price = package_data['admin_price'] if package_data['admin_price'] is not None else package_data['price']

        # For details, we still need to hit the API, as we don't store T&C
        try:
            package_details_raw = get_package(session['tokens'], package_code)
            detail_html = package_details_raw["package_option"]["tnc"]
            detail = detail_html.replace("<p>", "").replace("</p>", "<br>")
        except APIError as e:
            flash(f"Could not fetch package Terms & Conditions: {e}", "warning")
            detail = "Terms and Conditions could not be loaded."

        package_details = {
            "title": package_data['name'],
            "price": display_price,
            "detail": detail,
            "code": package_data['code'],
        }

        return render_template('purchase.html', package=package_details)

    except Exception as e:
        flash(f"An unexpected error occurred while fetching package details: {e}", "danger")
        return redirect(url_for('dashboard'))

@app.route('/confirm_purchase/<package_code>', methods=['POST'])
@login_required
def confirm_purchase(package_code):
    conn = get_db_connection()

    # Get package details from our DB
    package_data = conn.execute('SELECT * FROM packages WHERE code = ?', (package_code,)).fetchone()
    if not package_data:
        flash("Package not found.", "danger")
        conn.close()
        return redirect(url_for('dashboard'))

    # Get user details from our DB
    user_phone = session['user_data']['phone_number']
    user = conn.execute('SELECT * FROM users WHERE phone_number = ?', (user_phone,)).fetchone()

    # Determine the price
    price = package_data['admin_price'] if package_data['admin_price'] is not None else package_data['price']

    # Check for sufficient balance
    if user['balance'] < price:
        flash(f"Insufficient balance. You need Rp {price:,.0f} but only have Rp {user['balance']:,.0f}.", "danger")
        conn.close()
        return redirect(url_for('dashboard'))

    # If balance is sufficient, deduct and proceed
    new_balance = user['balance'] - price
    try:
        # 1. Deduct balance from our database
        conn.execute('UPDATE users SET balance = ? WHERE phone_number = ?', (new_balance, user_phone))

        # 2. Attempt to purchase from provider
        result = purchase_package(session['tokens'], package_code)

        # 3. If both are successful, commit the transaction
        conn.commit()

        # 4. Update session and flash success
        session['user_data']['balance'] = new_balance
        session.modified = True # Mark session as modified
        flash(f"Successfully purchased {package_data['name']}! Transaction ID: {result.get('data', {}).get('transaction_id', 'N/A')}", "success")

    except APIError as e:
        # If API purchase fails, roll back the DB change
        conn.rollback()
        flash(f"Purchase failed at provider level: {e}. Your balance has not been charged.", "danger")
    except Exception as e:
        # If any other error occurs, roll back
        conn.rollback()
        flash(f"An unexpected error occurred during purchase: {e}. Your balance has not been charged.", "danger")
    finally:
        conn.close()

    return redirect(url_for('dashboard'))


def sync_packages_from_api(tokens: dict):
    """
    Fetches packages from the API and upserts them into the local database.
    Preserves existing admin_price.
    """
    logging.info("Starting package sync from API...")
    try:
        api_packages = get_package_xut(tokens)
        conn = get_db_connection()
        cursor = conn.cursor()

        for pkg in api_packages:
            cursor.execute("SELECT * FROM packages WHERE code = ?", (pkg['code'],))
            existing_pkg = cursor.fetchone()

            if existing_pkg:
                # Update name and original price, but keep admin_price
                cursor.execute("""
                    UPDATE packages
                    SET name = ?, price = ?
                    WHERE code = ?
                """, (pkg['name'], pkg['price'], pkg['code']))
            else:
                # Insert new package, admin_price is NULL by default
                cursor.execute("""
                    INSERT INTO packages (code, name, price)
                    VALUES (?, ?, ?)
                """, (pkg['code'], pkg['name'], pkg['price']))

        conn.commit()
        conn.close()
        logging.info(f"Package sync complete. Processed {len(api_packages)} packages.")
        return len(api_packages)
    except APIError as e:
        logging.error(f"API Error during package sync: {e}")
        raise
    except Exception as e:
        logging.error(f"An unexpected error occurred during package sync: {e}")
        raise

# ADMIN ROUTES #

@app.route('/admin')
@login_required
@admin_required
def admin_panel():
    conn = get_db_connection()
    users = conn.execute('SELECT * FROM users ORDER BY phone_number').fetchall()
    packages = conn.execute('SELECT * FROM packages ORDER BY name').fetchall()
    conn.close()
    return render_template('admin.html', users=users, packages=packages)

@app.route('/admin/sync_packages', methods=['POST'])
@login_required
@admin_required
def admin_sync_packages():
    try:
        count = sync_packages_from_api(session['tokens'])
        flash(f"Successfully synced {count} packages from the provider.", "success")
    except APIError as e:
        flash(f"Failed to sync packages: {e}", "danger")
    return redirect(url_for('admin_panel'))

@app.route('/admin/update_balance', methods=['POST'])
@login_required
@admin_required
def admin_update_balance():
    phone_number = request.form.get('phone_number')
    balance = request.form.get('balance')

    if not phone_number or balance is None:
        flash("Missing phone number or balance.", "danger")
        return redirect(url_for('admin_panel'))

    try:
        balance_val = int(balance)
        conn = get_db_connection()
        conn.execute('UPDATE users SET balance = ? WHERE phone_number = ?', (balance_val, phone_number))
        conn.commit()
        conn.close()
        flash(f"Successfully updated balance for {phone_number}.", "success")
    except ValueError:
        flash("Invalid balance amount. Please enter a number.", "danger")
    except Exception as e:
        flash(f"An error occurred: {e}", "danger")

    return redirect(url_for('admin_panel'))

@app.route('/admin/update_price', methods=['POST'])
@login_required
@admin_required
def admin_update_price():
    package_code = request.form.get('package_code')
    admin_price = request.form.get('admin_price')

    if not package_code or admin_price is None:
        flash("Missing package code or price.", "danger")
        return redirect(url_for('admin_panel'))

    try:
        price_val = int(admin_price)
        if price_val < 0:
            flash("Price cannot be negative.", "danger")
            return redirect(url_for('admin_panel'))

        conn = get_db_connection()
        conn.execute('UPDATE packages SET admin_price = ? WHERE code = ?', (price_val, package_code))
        conn.commit()
        conn.close()
        flash(f"Successfully updated price for package {package_code}.", "success")
    except ValueError:
        flash("Invalid price amount. Please enter a number.", "danger")
    except Exception as e:
        flash(f"An error occurred: {e}", "danger")

    return redirect(url_for('admin_panel'))


if __name__ == '__main__':
    # Initialize the database
    init_db()
    # Use 0.0.0.0 to make it accessible from the host machine
    # debug=False is important for production, but True is fine for development
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)
