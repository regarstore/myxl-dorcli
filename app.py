import os
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash
import logging

# Import application modules
from api_request import get_otp, submit_otp, APIError, get_package, purchase_package
from util import get_user_data
from paket_xut import get_package_xut
from database import init_db, get_db_connection, get_all_packages

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['ADMIN_PHONE_NUMBERS'] = ['6281818988646']

# Decorators
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'tokens' not in session:
            flash("You must be logged in to view this page.", "warning")
            return redirect(url_for('login'))
        if 'api_key' not in session:
            flash("API Key not found in session. Please enter it again.", "warning")
            return redirect(url_for('index'))
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

# --- Main App Routes ---
@app.route('/')
def index():
    if 'tokens' in session and 'api_key' in session:
        return redirect(url_for('dashboard'))
    if 'api_key' in session:
        return redirect(url_for('login'))
    return render_template('api_key.html')

@app.route('/save_key', methods=['POST'])
def save_key():
    api_key = request.form.get('api_key')
    if not api_key:
        flash("API Key is required.", "danger")
        return redirect(url_for('index'))
    session['api_key'] = api_key
    flash("API Key saved for this session.", "success")
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'tokens' in session:
        return redirect(url_for('dashboard'))
    if 'api_key' not in session:
        flash("Please enter your API key first.", "warning")
        return redirect(url_for('index'))

    if request.method == 'POST':
        phone_number = request.form.get('phone_number')
        if not phone_number or not phone_number.startswith('628'):
            flash("Invalid phone number. It must be a valid XL number starting with 62.", "danger")
            return render_template('login.html')

        try:
            get_otp(phone_number)
            flash(f"An OTP has been sent to {phone_number}.", "success")
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
    api_key = session.get('api_key')
    if not phone_number or not api_key:
        flash("Session expired or API key is missing. Please start over.", "warning")
        return redirect(url_for('index'))

    if request.method == 'POST':
        otp_code = request.form.get('otp_code')
        try:
            tokens = submit_otp(api_key, phone_number, otp_code)
            session['tokens'] = tokens

            api_user_data = get_user_data(api_key, tokens)
            db_phone_number = api_user_data['phone_number']

            conn = get_db_connection()
            db_user = conn.execute('SELECT * FROM users WHERE phone_number = ?', (db_phone_number,)).fetchone()
            if db_user is None:
                conn.execute('INSERT INTO users (phone_number, balance) VALUES (?, ?)', (db_phone_number, 0))
                conn.commit()
                db_user = conn.execute('SELECT * FROM users WHERE phone_number = ?', (db_phone_number,)).fetchone()
            conn.close()

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
            return render_template('otp.html', phone_number=phone_number)

    return render_template('otp.html', phone_number=phone_number)

@app.route('/logout')
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    user_data = session.get('user_data')
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

        display_price = package_data['admin_price'] if package_data['admin_price'] is not None else package_data['price']

        detail = "Terms and Conditions could not be loaded."
        try:
            package_details_raw = get_package(session['api_key'], session['tokens'], package_code)
            detail_html = package_details_raw["package_option"]["tnc"]
            detail = detail_html.replace("<p>", "").replace("</p>", "<br>")
        except APIError as e:
            flash(f"Could not fetch package Terms & Conditions: {e}", "warning")

        package_details = { "title": package_data['name'], "price": display_price, "detail": detail, "code": package_data['code'] }
        return render_template('purchase.html', package=package_details)
    except Exception as e:
        flash(f"An unexpected error occurred: {e}", "danger")
        return redirect(url_for('dashboard'))

@app.route('/confirm_purchase/<package_code>', methods=['POST'])
@login_required
def confirm_purchase(package_code):
    conn = get_db_connection()
    try:
        package_data = conn.execute('SELECT * FROM packages WHERE code = ?', (package_code,)).fetchone()
        if not package_data:
            flash("Package not found.", "danger")
            return redirect(url_for('dashboard'))

        user_phone = session['user_data']['phone_number']
        user = conn.execute('SELECT * FROM users WHERE phone_number = ?', (user_phone,)).fetchone()
        price = package_data['admin_price'] if package_data['admin_price'] is not None else package_data['price']

        if user['balance'] < price:
            flash(f"Insufficient balance. You need Rp {price:,.0f} but only have Rp {user['balance']:,.0f}.", "danger")
            return redirect(url_for('dashboard'))

        new_balance = user['balance'] - price
        conn.execute('UPDATE users SET balance = ? WHERE phone_number = ?', (new_balance, user_phone))

        result = purchase_package(session['api_key'], session['tokens'], package_code)

        conn.commit()

        session['user_data']['balance'] = new_balance
        session.modified = True
        flash(f"Successfully purchased {package_data['name']}! Transaction ID: {result.get('data', {}).get('transaction_id', 'N/A')}", "success")
    except APIError as e:
        conn.rollback()
        flash(f"Purchase failed at provider level: {e}. Your balance has not been charged.", "danger")
    except Exception as e:
        conn.rollback()
        flash(f"An unexpected error occurred during purchase: {e}. Your balance has not been charged.", "danger")
    finally:
        if conn:
            conn.close()
    return redirect(url_for('dashboard'))

# --- Admin Routes ---
def sync_packages_from_api(api_key: str, tokens: dict):
    logging.info("Starting package sync from API...")
    try:
        api_packages = get_package_xut(api_key, tokens)
        conn = get_db_connection()
        for pkg in api_packages:
            conn.execute("INSERT OR REPLACE INTO packages (code, name, price, admin_price) VALUES (?, ?, ?, (SELECT admin_price FROM packages WHERE code = ?))",
                         (pkg['code'], pkg['name'], pkg['price'], pkg['code']))
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
        count = sync_packages_from_api(session['api_key'], session['tokens'])
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
    try:
        balance_val = int(balance)
        conn = get_db_connection()
        conn.execute('UPDATE users SET balance = ? WHERE phone_number = ?', (balance_val, phone_number))
        conn.commit()
        conn.close()
        flash(f"Successfully updated balance for {phone_number}.", "success")
    except (ValueError, TypeError):
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
    try:
        price_val = int(admin_price)
        if price_val < 0:
            raise ValueError("Price cannot be negative.")
        conn = get_db_connection()
        conn.execute('UPDATE packages SET admin_price = ? WHERE code = ?', (price_val, package_code))
        conn.commit()
        conn.close()
        flash(f"Successfully updated price for package {package_code}.", "success")
    except (ValueError, TypeError):
        flash("Invalid price amount. Please enter a number.", "danger")
    except Exception as e:
        flash(f"An error occurred: {e}", "danger")
    return redirect(url_for('admin_panel'))

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)
