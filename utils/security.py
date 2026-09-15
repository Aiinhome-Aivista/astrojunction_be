import os
import jwt
import datetime
from functools import wraps
from flask import request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash

JWT_SECRET = os.getenv("JWT_SECRET", "change-this-secret")
JWT_ALGO = "HS256"
JWT_EXPIRY_HOURS = 24 * 7  # 7 days


def hash_password(plain_password: str) -> str:
    return generate_password_hash(plain_password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    return check_password_hash(password_hash, plain_password)


def issue_token(user_id: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "role": role,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=JWT_EXPIRY_HOURS),
        "iat": datetime.datetime.utcnow(),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def decode_token(token: str):
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])


def require_auth(f):
    """Decorator: rejects the request unless a valid Bearer token is present.
    Injects `request.user_id` and `request.user_role` on success."""

    @wraps(f)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({
                "status": "error",
                "message": "Missing or invalid Authorization header",
                "error_code": "AUTH_REQUIRED",
            }), 401

        token = auth_header.split(" ", 1)[1]
        try:
            payload = decode_token(token)
        except jwt.ExpiredSignatureError:
            return jsonify({
                "status": "error",
                "message": "Session expired, please log in again",
                "error_code": "TOKEN_EXPIRED",
            }), 401
        except jwt.InvalidTokenError:
            return jsonify({
                "status": "error",
                "message": "Invalid authentication token",
                "error_code": "TOKEN_INVALID",
            }), 401

        request.user_id = payload["sub"]
        request.user_role = payload.get("role", "user")
        return f(*args, **kwargs)

    return wrapper


def require_admin(f):
    """Stacks on top of require_auth-protected routes to also require role=admin."""

    @wraps(f)
    def wrapper(*args, **kwargs):
        if getattr(request, "user_role", None) != "admin":
            return jsonify({
                "status": "error",
                "message": "Admin privileges required",
                "error_code": "FORBIDDEN",
            }), 403
        return f(*args, **kwargs)

    return wrapper
