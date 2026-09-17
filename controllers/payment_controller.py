from flask import request, jsonify
from utils.security import require_auth
from services import payment_service


def create_order():
    """
    POST /api/payment/create-order
    Body: { "amount": 499, "currency": "INR", "itemType": "full_report", "itemId": "report_123" }
    """
    body = request.get_json(silent=True) or {}
    amount = body.get("amount")
    currency = body.get("currency", "INR")
    item_type = body.get("itemType")
    item_id = body.get("itemId")

    if not amount or not isinstance(amount, (int, float)) or amount <= 0:
        return jsonify({
            "status": "error",
            "message": "Valid payment amount is required",
            "error_code": "INVALID_AMOUNT"
        }), 400

    user_id = getattr(request, "user_id", None)
    if not user_id:
        return jsonify({
            "status": "error",
            "message": "User context missing",
            "error_code": "AUTH_REQUIRED"
        }), 401

    try:
        order_info = payment_service.create_order(
            user_id=user_id,
            amount=float(amount),
            currency=currency,
            item_type=item_type,
            item_id=item_id
        )
        return jsonify({
            "status": "success",
            "data": order_info
        }), 201
    except Exception as e:
        print(f"[PaymentController Error] {e}")
        return jsonify({
            "status": "error",
            "message": str(e),
            "error_code": "CREATE_ORDER_FAILED"
        }), 500


def verify_payment():
    """
    POST /api/payment/verify
    Body: {
      "razorpay_order_id": "order_xxx",
      "razorpay_payment_id": "pay_xxx",
      "razorpay_signature": "sig_xxx"
    }
    """
    body = request.get_json(silent=True) or {}
    order_id = body.get("razorpay_order_id")
    payment_id = body.get("razorpay_payment_id")
    signature = body.get("razorpay_signature")

    if not order_id or not payment_id or not signature:
        return jsonify({
            "status": "error",
            "message": "Missing required Razorpay verification parameters",
            "error_code": "VALIDATION_ERROR"
        }), 400

    user_id = getattr(request, "user_id", None)

    try:
        res = payment_service.verify_payment(
            razorpay_order_id=order_id,
            razorpay_payment_id=payment_id,
            razorpay_signature=signature,
            user_id=user_id
        )
        if res.get("verified"):
            return jsonify({
                "status": "success",
                "message": "Payment verified and processed successfully",
                "data": res
            }), 200
        else:
            return jsonify({
                "status": "error",
                "message": "Payment signature verification failed",
                "error_code": "PAYMENT_VERIFICATION_FAILED",
                "data": res
            }), 400
    except Exception as e:
        print(f"[PaymentVerify Error] {e}")
        return jsonify({
            "status": "error",
            "message": str(e),
            "error_code": "VERIFICATION_ERROR"
        }), 500


def webhook_callback():
    """
    POST /api/payment/webhook
    Header: X-Razorpay-Signature
    Raw Body bytes needed for signature verification
    """
    signature = request.headers.get("X-Razorpay-Signature", "")
    body_bytes = request.get_data()

    if not signature:
        return jsonify({"status": "error", "message": "Missing Razorpay webhook signature"}), 400

    success, message = payment_service.process_webhook(body_bytes, signature)
    if success:
        return jsonify({"status": "success", "message": message}), 200
    else:
        return jsonify({"status": "error", "message": message}), 400


def get_transactions():
    """
    GET /api/payment/history
    """
    user_id = getattr(request, "user_id", None)
    if not user_id:
        return jsonify({"status": "error", "message": "Auth required"}), 401

    try:
        tx_list = payment_service.get_user_transactions(user_id)
        return jsonify({
            "status": "success",
            "data": tx_list
        }), 200
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e),
            "error_code": "FETCH_FAILED"
        }), 500
