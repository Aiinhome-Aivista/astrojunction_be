import os
import uuid
import json
import razorpay
from dotenv import load_dotenv
from database.db_connection import get_db_connection

load_dotenv()


def get_razorpay_client():
    key_id = (os.getenv("RAZORPAY_KEY_ID") or "").strip()
    key_secret = (os.getenv("RAZORPAY_KEY_SECRET") or "").strip()
    return razorpay.Client(auth=(key_id, key_secret))


def create_order(user_id: str, amount: float, currency: str = "INR", item_type: str = None, item_id: str = None):

    """
    Creates a Razorpay Order and logs an initial pending transaction in the database.
    Amount should be in major units (e.g., 499.00 for ₹499). Razorpay expects amount in paise.
    """
    amount_in_paise = int(round(amount * 100))
    tx_id = str(uuid.uuid4())

    order_payload = {
        "amount": amount_in_paise,
        "currency": currency.upper(),
        "receipt": f"receipt_{tx_id[:12]}",
        "notes": {
            "user_id": user_id,
            "item_type": item_type or "general",
            "item_id": item_id or "",
            "tx_id": tx_id
        }
    }

    try:
        rzp_client = get_razorpay_client()
        razorpay_order = rzp_client.order.create(data=order_payload)
    except Exception as e:
        print(f"[Razorpay Error] Order creation failed: {e}")
        raise ValueError(f"Razorpay order creation failed: {str(e)}")

    razorpay_order_id = razorpay_order.get("id")

    conn = get_db_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        query = """
            INSERT INTO transactions (
                id, user_id, amount, currency, status, payment_method, 
                razorpay_order_id, item_type, item_id, raw_response
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        cursor.execute(query, (
            tx_id,
            user_id,
            amount,
            currency.upper(),
            'pending',
            'razorpay',
            razorpay_order_id,
            item_type,
            item_id,
            json.dumps(razorpay_order)
        ))
        conn.commit()
        cursor.close()
    finally:
        conn.close()

    return {
        "tx_id": tx_id,
        "order_id": razorpay_order_id,
        "amount": amount,
        "amount_paise": amount_in_paise,
        "currency": currency.upper(),
        "item_type": item_type,
        "item_id": item_id
    }


def verify_payment(razorpay_order_id: str, razorpay_payment_id: str, razorpay_signature: str, user_id: str = None):
    """
    Verifies Razorpay HMAC signature and updates transaction status to success.
    Also triggers fulfillment for purchased item.
    """
    params_dict = {
        "razorpay_order_id": razorpay_order_id,
        "razorpay_payment_id": razorpay_payment_id,
        "razorpay_signature": razorpay_signature
    }

    try:
        rzp_client = get_razorpay_client()
        rzp_client.utility.verify_payment_signature(params_dict)
        is_valid = True
    except razorpay.errors.SignatureVerificationError as err:
        print(f"[Razorpay Signature Verification Failed] {err}")
        is_valid = False
    except Exception as err:
        print(f"[Razorpay Verification Error] {err}")
        is_valid = False


    conn = get_db_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        # Fetch transaction record
        cursor.execute(
            "SELECT * FROM transactions WHERE razorpay_order_id = %s", (razorpay_order_id,)
        )
        tx = cursor.fetchone()

        if not tx:
            raise ValueError(f"No transaction found for order ID: {razorpay_order_id}")

        new_status = 'success' if is_valid else 'failed'

        update_query = """
            UPDATE transactions 
            SET status = %s, razorpay_payment_id = %s, razorpay_signature = %s 
            WHERE razorpay_order_id = %s
        """
        cursor.execute(update_query, (new_status, razorpay_payment_id, razorpay_signature, razorpay_order_id))
        conn.commit()

        # Fulfill feature if payment verified successfully
        if is_valid:
            _fulfill_purchase(conn, tx)

        cursor.close()
    finally:
        conn.close()

    return {
        "verified": is_valid,
        "status": new_status,
        "order_id": razorpay_order_id,
        "payment_id": razorpay_payment_id
    }


def process_webhook(body_bytes: bytes, signature: str):
    """
    Processes Razorpay server webhooks for asynchronous status confirmation.
    """
    webhook_secret = RAZORPAY_WEBHOOK_SECRET or RAZORPAY_KEY_SECRET
    try:
        client.utility.verify_webhook_signature(body_bytes.decode('utf-8'), signature, webhook_secret)
    except Exception as e:
        print(f"[Razorpay Webhook Invalid Signature] {e}")
        return False, "Invalid signature"

    payload = json.loads(body_bytes)
    event = payload.get("event")
    payment_entity = payload.get("payload", {}).get("payment", {}).get("entity", {})

    razorpay_order_id = payment_entity.get("order_id")
    razorpay_payment_id = payment_entity.get("id")

    if event in ["payment.captured", "order.paid"]:
        conn = get_db_connection()
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM transactions WHERE razorpay_order_id = %s", (razorpay_order_id,))
            tx = cursor.fetchone()
            if tx and tx["status"] != "success":
                cursor.execute(
                    "UPDATE transactions SET status = 'success', razorpay_payment_id = %s WHERE razorpay_order_id = %s",
                    (razorpay_payment_id, razorpay_order_id)
                )
                conn.commit()
                _fulfill_purchase(conn, tx)
            cursor.close()
        finally:
            conn.close()

    elif event == "payment.failed":
        conn = get_db_connection()
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "UPDATE transactions SET status = 'failed', razorpay_payment_id = %s WHERE razorpay_order_id = %s",
                (razorpay_payment_id, razorpay_order_id)
            )
            conn.commit()
            cursor.close()
        finally:
            conn.close()

    return True, "Webhook processed"


def get_user_transactions(user_id: str):
    """
    Fetches past transaction records for a user.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id, amount, currency, status, payment_method, 
                   razorpay_order_id, razorpay_payment_id, item_type, item_id, created_at
            FROM transactions 
            WHERE user_id = %s 
            ORDER BY created_at DESC
            """,
            (user_id,)
        )
        rows = cursor.fetchall()
        cursor.close()

        # Format dates
        for r in rows:
            if hasattr(r.get("created_at"), "isoformat"):
                r["created_at"] = r["created_at"].isoformat()

        return rows
    finally:
        conn.close()


def _fulfill_purchase(conn, tx: dict):
    """
    Helper function to fulfill service when payment succeeds.
    e.g. Setting is_premium = 1 on user's profile.
    """
    item_type = tx.get("item_type")
    user_id = tx.get("user_id")

    if item_type in ["premium", "subscription"]:
        cursor = conn.cursor()
        cursor.execute("UPDATE user_profiles SET is_premium = 1 WHERE user_id = %s", (user_id,))
        conn.commit()
        cursor.close()
