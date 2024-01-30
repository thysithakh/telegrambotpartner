import logging
import os
import time
import threading
import sys
from pyrogram import Client, filters
import firebase_admin
from firebase_admin import credentials, firestore
import requests
import qrcode
import threading
from datetime import datetime
import pytz


logging.basicConfig(level=logging.INFO)

URL_TOPUP = 'https://dev.api.elitedias.com/elitedias_reseller_topup_api'
URL_PAYMENT = 'https://bakong-endpoiny.ngrok.app/run_js'
CHECK_TRANSACTION_URL = 'https://api-bakong.nbc.gov.kh/v1/check_transaction_by_md5'
HEADERS = {'Content-Type': 'application/json'}
API_KEY_TOPUP = 'Zf2brRi9y1B88gnMfRjB6jXLLTHZRY4iEmqSem9VInQgsvmavbHkqlZRprdQA4SBdnbr7c3VrFKMdpUnpPkAn7z8sSwuEFxI3Ut5f8UaK0Ev8QxBAc-D-WSVje6K2UFGdZ8c5tE48ytW0Bw1NrcG3YeVVa7cOIpkAiQTVkdmpsNOK7eY7tic-8uaTo1NPOoXGwLsuiEaes_a7PqVpvYZmOThnapwPZPF03eNHahA8rurf21QTjTw4aN1AMwaFbNaTIC5QXjD6iuAqUQdRg6WbQg0xIqBzeEUu_66UKb-v3Gx5QO17W4My0DcHl2WReXauCkqKrGcChx8VdnGAwCVcQ'
BEARER_TOKEN_PAYMENT = 'eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJleHAiOjE3MTIyMDY4NDIsImlhdCI6MTcwNDE3MTY0MiwiZGF0YSI6eyJpZCI6IjM2Mjg1YTI4MzhkYzRmZSJ9fQ.7nEuufKrxetaaT1iYMX3pVxc3xYOyrNm3QFM-4VNaws'  # Replace with your actual bearer token
try:
    cred = credentials.Certificate("database.json")
    firebase_admin.initialize_app(cred)
    db = firestore.client()
except firebase_admin.exceptions.FirebaseError as firebase_error:
    logging.error(f"Firebase initialization error: {firebase_error}")
    sys.exit(1)

DENOM_CHARGES = {}


def get_denom_charges():
    denom_charges_ref = db.collection('config').document('denom_charges')
    denom_charges_data = denom_charges_ref.get().to_dict()
    return denom_charges_data if denom_charges_data else {}



def get_game_payloads():
    game_payloads_ref = db.collection('config').document('game_payloads')
    game_payloads_data = game_payloads_ref.get().to_dict()
    return game_payloads_data if game_payloads_data else {}

def on_denom_charges_change(doc_snapshot, changes, read_time):
    global DENOM_CHARGES
    for change in changes:
        if change.type.name == 'MODIFIED':
            DENOM_CHARGES = change.document.to_dict()
            logging.info(f'Denom charges updated: {DENOM_CHARGES}')

# Add an event listener for 'config/denom_charges'
denom_charges_ref = db.collection('config').document('denom_charges')
denom_charges_watch = denom_charges_ref.on_snapshot(on_denom_charges_change)

# Fetch initial denom charges (optional)
DENOM_CHARGES = get_denom_charges()

api_id = "3910389"
api_hash = "86f861352f0ab76a251866059a6adbd6"
bot_token = "6782301967:AAHTf1hzlj7PE9XUE7R3D30mtF_MYe-7XV8"
app = Client("ResellerBots", api_id=api_id, api_hash=api_hash, bot_token=bot_token)

addfund_state = {}

@app.on_message(filters.private)
def handle_message(client, message):
    try:
        user_id = message.from_user.id
        text = message.text.lower()

        # Check if the user's Telegram ID exists in the database
        if not is_telegram_id_exists(user_id):
            client.send_message(message.chat.id, "You are not authorized to use this bot.")
            return

        if text == '/start':
            create_user_balance(client, message, user_id)
        elif text.startswith('/addfund'):
            addfund_state[user_id] = True
            client.send_message(message.chat.id, "Please enter the amount in USD:")
        elif text.startswith('/credit'):
            process_credit_command(client, message, user_id)
        elif len(text.split()) == 3 and all(part.isdigit() for part in text.split()):
            process_topup_command(client, message, user_id, text)
        elif text.lower().endswith(' weekly'):
            # Directly process the top-up request for messages ending with 'weekly'
            process_topup_command(client, message, user_id, text)
        # Check if /addfund state is active
        elif user_id in addfund_state and addfund_state[user_id]:
            process_addfund_input(client, message, user_id)
        # Placeholder for default message handling (modify as needed)
        else:
            client.send_message(message.chat.id, "Sorry, I didn't understand that.")

    except Exception as e:
        logging.error(f"Error handling message: {e}", exc_info=True)

# Function to check if the user's Telegram ID exists in the database
def is_telegram_id_exists(user_id):
    user_ref = db.collection('balances').document(str(user_id))
    user_data = user_ref.get().to_dict()
    return user_data is not None

def create_user_balance(client, message, user_id):
    user_ref = db.collection('balances').document(str(user_id))
    user_data = user_ref.get().to_dict()

    if not user_data:
        user_ref.set({'balance': 0})
        client.send_message(message.chat.id, "Balance created successfully.")
    else:
        client.send_message(message.chat.id, "Balance already exists.")

def process_credit_command(client, message, user_id):
    user_ref = db.collection('balances').document(str(user_id))
    user_data = user_ref.get().to_dict()
    balance = user_data.get('balance', 0) if user_data else 0
    formatted_balance = format_currency(balance)
    client.send_message(message.chat.id, f"Your balance / ប្រាក់របស់អ្នក : <code>{formatted_balance}</code>")

def process_topup_command(client, message, user_id, text):
    try:
        parts = text.split()

        if len(parts) < 2:
            client.send_message(message.chat.id, "Invalid command format. Please use the format: /topup userid serverid denom")
            return

        userid, serverid = map(str, parts[:2])

        # Combine the remaining parts as the denomination, handling both text and numeric input
        denom_parts = parts[2:]
        denom = ' '.join(denom_parts)

        # Check if the entire denom is a valid denomination
        charge = DENOM_CHARGES.get(denom)

        # If the entire denom is not valid, try combining the parts and check again
        if charge is None and denom_parts:
            combined_denom = ''.join(denom_parts)
            charge = DENOM_CHARGES.get(combined_denom)

        # If the entire denom and combined denom are not valid, try extracting the numeric part
        if charge is None:
            numeric_part = ''.join(filter(str.isdigit, denom))
            remaining_denom = ''.join(filter(lambda x: not x.isdigit(), denom))

            # Check if the numeric part is a valid denomination
            charge = DENOM_CHARGES.get(numeric_part)

            # If the numeric part is still not valid, check if the remaining denom is valid
            if charge is None and remaining_denom:
                charge = DENOM_CHARGES.get(remaining_denom)

        # Check if the denom is a valid denomination
        if charge is not None:
            user_ref = db.collection('balances').document(str(user_id))
            user_data = user_ref.get().to_dict()

            if not user_data:
                user_ref.set({'balance': 0})

            if user_data and user_data.get('balance', 0) >= charge:
                new_balance = user_data['balance'] - charge
                user_ref.set({'balance': new_balance}, merge=True)
                process_post_request(client, message, user_id, userid, serverid, denom)
            else:
                client.send_message(message.chat.id, "Insufficient balance.")
        else:
            client.send_message(message.chat.id, "Invalid denomination. No charge applied.")

    except Exception as e:
        logging.error(f"Error processing top-up command: {e}")
        client.send_message(message.chat.id, "An error occurred while processing your top-up request. Please try again later.")


      

TIMEOUT_SECONDS = 600  


def process_post_request(client, message, user_id, userid, serverid, denom):
    try:
        game_payloads = get_game_payloads()
        if str(denom) in game_payloads:
            game = game_payloads[str(denom)]
            payload = {'api_key': API_KEY_TOPUP, 'game': game, 'userid': str(userid), 'serverid': str(serverid), 'denom': str(denom)}
            logging.info(f"Payload for POST request: {payload}")

            # Update headers to include 'Origin'
            updated_headers = HEADERS.copy()
            updated_headers['Origin'] = 'dev.api.elitedias.com'

            try:
                response = requests.post(URL_TOPUP, headers=updated_headers, json=payload, timeout=TIMEOUT_SECONDS)
                
                response.raise_for_status()  # Raise an HTTPError for bad responses (4xx or 5xx)
                
                response_json = response.json() if response.headers.get('content-type') == 'application/json' else None

                logging.info(f"JSON Response from POST request: {response_json}")

                if response.status_code == 200 and response_json.get('status') == 'success':
                    handle_successful_transaction(client, message, user_id, response_json, denom, payload)
                else:
                    handle_transaction_failure(client, message, user_id, response_json, denom, payload)

            except requests.Timeout:
                handle_timeout(client, message, user_id, denom)

        else:
            client.send_message(message.chat.id, "Invalid denomination.")

    except (requests.RequestException, ValueError) as e:
        logging.error(f"Request or JSON error: {e}")
        handle_request_error(client, message, user_id, e, denom)

def handle_timeout(client, message, user_id, denom):
    logging.info(f"Refunding user_id={user_id} due to timeout")

    charge = DENOM_CHARGES.get(str(denom), 0)

    if charge > 0:
        update_user_balance(user_id, charge)

    status_message = (
        "Transaction timed out. Refunding amount.\n"
        f"Refunded {charge}$ to user_id={user_id}."
    )

    client.send_message(message.chat.id, status_message)


def store_transaction_details(user_id, payload_userid, payload_serverid, denom, price, status, order_id):
    try:
        user_ref = db.collection('balances').document(str(user_id))
        transactions_collection_ref = user_ref.collection('transactions')

        # Create 'transactions' collection if it doesn't exist
        transactions_collection_ref.add({})

        # Add transaction details to the 'transactions' subcollection
        transaction_ref = transactions_collection_ref.add({
            'UserID': payload_userid,
            'ServerID': payload_serverid,
            'Denom': denom,
            'Price_of_denom': price,
            'Status_Topup': status,
            'TransationID': order_id,
            'Timestamp': firestore.SERVER_TIMESTAMP
        })

        logging.info(f"Transaction details stored in Firestore: {transaction_ref.id}")
    except Exception as e:
        logging.error(f"Error storing transaction details: {e}")

def handle_successful_transaction(client, message, user_id, response_json, denom, payload):
    payload_userid, payload_serverid, payload_denom = map(str, (payload.get('userid', 'N/A'), payload.get('serverid', 'N/A'), payload.get('denom', 'N/A')))
    order_id, price = response_json.get('order_id', 'N/A'), format_currency(DENOM_CHARGES.get(str(denom), 0))

    # Storing transaction details in Firebase
    store_transaction_details(user_id, payload_userid, payload_serverid, denom, price, 'success', order_id)

    custom_message = f"<b>New Order Sucessfully ❇️</b>\nUserID: <code>{payload_userid}</code>\nServerID: <code>{payload_serverid}</code>\nDiamond / កញ្ចប់: <code>{payload_denom}</code>\nPrice / តម្លៃ : {price}\nStatus / ស្ថានភាព : Sccessfully ✅"
    client.send_message(message.chat.id, custom_message)



def handle_transaction_failure(client, message, user_id, response_json, denom, payload):
    charge = DENOM_CHARGES.get(str(denom), 0)
    logging.info(f"Refunding user_id={user_id}, charge={charge}")

    if charge > 0:
        update_user_balance(user_id, charge)

    status = response_json.get('status') if response_json and 'status' in response_json else "None"
    payload_userid, payload_serverid, payload_denom = map(str, (payload.get('userid', 'N/A'), payload.get('serverid', 'N/A'), payload.get('denom', 'N/A')))

    if response_json.get('code') == '200':
        order_id, price = response_json.get('order_id', 'N/A'), format_currency(DENOM_CHARGES.get(str(denom), 0))
        custom_message = f"UserID: {payload_userid}\nServerid: {payload_serverid}\nDiamond: {payload_denom}\nprice: {price}\nstatus: Successfully ✅"
    elif response_json.get('code') == '400' and response_json.get('message') == 'Invalid product':
        custom_message = f"UserID: {payload_userid}\nServerid: {payload_serverid}\nDiamond: {payload_denom}\nstatus: {status}\nMessage: Invalid product ❌"
    elif response_json.get('code') == '400' and response_json.get('message') == 'Invalid user':
        custom_message = f"UserID: {payload_userid}\nServerid: {payload_serverid}\nDiamond: {payload_denom}\nstatus: {status}\nMessage: Invalid user ❌"
    elif response_json.get('code') == '400' and response_json.get('message') == 'There may be missing attributes in your request':
        custom_message = f"UserID: {payload_userid}\nServerid: {payload_serverid}\nDiamond: {payload_denom}\nstatus: {status}\nMessage: There may be missing attributes in your request ❌"
    elif response_json.get('code') == '403' and response_json.get('message') == 'Invalid request':
        custom_message = f"UserID: {payload_userid}\nServerid: {payload_serverid}\nDiamond: {payload_denom}\nstatus: {status}\nMessage: Invalid request ❌"
    elif response_json.get('code') == '403' and response_json.get('message') == 'Insufficient balance':
        custom_message = f"UserID: {payload_userid}\nServerid: {payload_serverid}\nDiamond: {payload_denom}\nstatus: {status}\nMessage: Admin OutStock ❌"
    elif response_json.get('code') == '403' and response_json.get('message') == 'Partner API is down':
        custom_message = f"UserID: {payload_userid}\nServerid: {payload_serverid}\nDiamond : {payload_denom}\nstatus: {status}\nMessage: API DOWN Try Again ❌"
    else:
        custom_message = f"Transaction failed. Status: {status}"

    client.send_message(message.chat.id, custom_message)

def update_user_balance(user_id, amount):
    user_ref = db.collection('balances').document(str(user_id))
    user_data = user_ref.get().to_dict()

    if user_data:
        new_balance = user_data.get('balance', 0) + amount
        user_ref.set({'balance': new_balance}, merge=True)
    else:
        logging.error(f"User with ID {user_id} not found in the database.")

def format_currency(amount):
    return f"${amount:.2f}"


def process_addfund_input(client, message, user_id):
    try:
        amount_usd = float(message.text)

        # Create the POST data
        POST_DATA = {
            'amount_usd': amount_usd,
            'bakongid': 'nimol_nhen@trmc',
            'store_name': 'VIBOLSTORE PARTNER'
        }

        # Create the headers with the bearer token
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {BEARER_TOKEN_PAYMENT}'
        }

        # Make the POST request with a reasonable timeout
        response = requests.post(URL_PAYMENT, headers=headers, json=POST_DATA, timeout=1)

        # Check for successful HTTP status code
        response.raise_for_status()

        # Print the response in the terminal
        logging.info(f"Response from POST request: {response.text}")

        # Extract the md5 from the response
        md5 = response.json().get('md5', '')

        # Start a background thread to check transaction status every 2 seconds
        if md5:
            thread = threading.Thread(target=check_transaction_periodically, args=(user_id, md5, client))
            thread.start()

            # Convert qr_string to QR code image and send it to the user
            qr_string = response.json().get('qr_string', '')
            if qr_string:
                send_qr_image(user_id, qr_string, client)

        # Reset the state
        addfund_state[user_id] = False

    except requests.exceptions.RequestException as req_err:
        # Handle HTTP request exceptions
        logging.error(f"HTTP request error: {req_err}")
        client.send_message(user_id, "Error processing your request. Please try again later.")

    except ValueError as value_err:
        # Handle conversion to float exceptions
        logging.error(f"Error converting amount to float: {value_err}")
        client.send_message(user_id, "Invalid input. Please enter a valid amount.")

    except Exception as e:
        # Handle other unexpected exceptions
        logging.error(f"Error handling /addfund input: {e}")
        client.send_message(user_id, "An unexpected error occurred. Please try again later.")

def process_payment_response(user_id, response, client):
    try:
        # Extract relevant information from the response data
        transaction_data = response.json().get('data', {})
        hash_value = transaction_data.get('hash', '')
        from_account_id = transaction_data.get('fromAccountId', '')
        to_account_id = transaction_data.get('toAccountId', '')
        currency = transaction_data.get('currency', '')
        amount_paid = transaction_data.get('amount', 0)

        # Check if the required fields are present to infer payment success
        if hash_value and from_account_id and to_account_id and currency and amount_paid:
            # Update the user's balance in the database
            update_user_balance(user_id, amount_paid)

            # Get user information from Pyrogram
            user_info = app.get_chat(user_id)

            # Extract username and ID from user_info
            username = user_info.username if user_info.username else "N/A"
            telegram_id = user_info.id

            cambodia_timezone = pytz.timezone('Asia/Phnom_Penh')
            current_time = datetime.now(cambodia_timezone).strftime('%d/%m/%Y %H:%M')

            # Customize the message structure here
            message = (
                "<b>Automated Deposit System ⚙</b>\n\n"
                f"<b>Currency / រូបិយប័ណ្ណ :</b>{currency} 💰\n"
                f"<b>\nBalance Added / ទឹកប្រាក់បន្ថែម :</b> <code>\n{amount_paid}$</code> ✅\n"
                "<b>\nFee Applied / សេវ៉ាប្រតិប្តការ :</b> \n<code>0.00%</code>\n\n"
                f"<b>Time Now / ពេលវេលាឥឡូវនេះ :</b> \n<code>{current_time}</code> ⏰\n"
                f"<b>\nPAYMENT / ទូរទាត់ជាមួយ :</b> \n<code>KHQR PAYMENT SCAN</code>\n"
                f"<b>\nTelegram : </b> @{username} "
                f"<b>\nTelegram ID :</b> <code>{telegram_id}</code>"
            )


            # You can call send_final_message here if needed
            send_final_message(user_id, message)
            return True

    except Exception as e:
        logging.error(f"Error processing payment response: {e}")

        # If qr_string is available, convert it to QR code image and send it to the user
        qr_string = response.json().get('qr_string', '')
        if qr_string:
            send_qr_image(user_id, qr_string, client)

    except Exception as e:
        logging.error(f"Error processing payment response: {e}")

    return False

def check_transaction_periodically(user_id, md5, client):
    try:
        # Define the body parameter as md5 hash of some data
        body = {"md5": md5}

        # Define the header parameter with Authorization and Content-Type for the second endpoint
        header = {
            "Authorization": f"Bearer {BEARER_TOKEN_PAYMENT}",
            "Content-Type": "application/json"
        }

        start_time = time.time()
        timeout = 15 * 60  # 15 minutes timeout

        while time.time() - start_time < timeout:
            # Make the POST request and get the response
            response = requests.post(CHECK_TRANSACTION_URL, json=body, headers=header)

            # Print the status code and the response text
            logging.info(f"Check Transaction Status Code: {response.status_code}")
            logging.info(f"Check Transaction Response: {response.text}")

            if response.status_code == 403:
                # If status code is 403 Forbidden, log the information and continue checking
                logging.warning("Received 403 Forbidden response. Retrying...")
            else:
                # Process the payment response
                if process_payment_response(user_id, response, client):
                    break  # Break out of the loop if payment is confirmed

            # Wait for 2 seconds before the next check
            time.sleep(2)

        else:
            # If the loop completes without breaking (timeout reached), send a timeout message
            client.send_message(user_id, "Payment timed out. Please check again later /addfund.")

    except requests.exceptions.RequestException as e:
        # Print the error message
        logging.error(f"Error checking transaction: {e}")


def send_final_message(user_id, message):
    # Send a final message to the user
    app.send_message(user_id, message)
    app.send_message('NotificationBakong',message)
   

def send_qr_image(user_id, qr_string, client):
    try:
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(qr_string)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")

        img_path = f"qrcode_{user_id}.png"
        img.save(img_path)

        app.send_photo(user_id, photo=img_path, caption="Here is your payment QR code")

        os.remove(img_path)

    except Exception as e:
        logging.error(f"Error sending QR code image: {e}")

app.run()
