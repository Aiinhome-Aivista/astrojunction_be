import os
import time
import requests
import concurrent.futures
from typing import Dict, Any, Optional
from database.db_connection import get_db_connection

# In-memory settings cache: {key: (value, timestamp)}
_CACHE: Dict[str, tuple[str, float]] = {}
CACHE_TTL = 30.0  # seconds
_LAST_BULK_LOAD: float = 0.0


def init_settings_table():
    """Ensures the system_settings table exists in MySQL."""
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS system_settings (
                setting_key VARCHAR(100) PRIMARY KEY,
                setting_value TEXT NOT NULL,
                description VARCHAR(255) NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                updated_by VARCHAR(100) DEFAULT 'admin'
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """
        )
        conn.commit()
    except Exception as e:
        print(f"[SettingsService] Warning: Could not initialize system_settings table: {e}")
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


def load_all_settings(force: bool = False):
    """Loads all settings in ONE single query to avoid multiple remote DB roundtrips."""
    global _LAST_BULK_LOAD
    now = time.time()
    if not force and (now - _LAST_BULK_LOAD < CACHE_TTL):
        return

    _LAST_BULK_LOAD = now
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT setting_key, setting_value FROM system_settings")
        rows = cursor.fetchall()
        for r in rows:
            if r.get("setting_key") and r.get("setting_value") is not None:
                _CACHE[r["setting_key"]] = (str(r["setting_value"]), now)
    except Exception as e:
        print(f"[SettingsService] Bulk load settings warning: {e}")
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

# Initialize table & warm up settings cache on import
try:
    init_settings_table()
    load_all_settings(force=True)
except Exception:
    pass


def get_setting(key: str, default: Optional[str] = None) -> str:
    """
    Retrieves a setting value.
    Priority:
    1. In-memory cache (if not expired)
    2. MySQL system_settings table (bulk loaded)
    3. os.getenv(key, default)
    """
    now = time.time()
    if key in _CACHE:
        val, ts = _CACHE[key]
        if now - ts < CACHE_TTL:
            return val

    # Bulk reload if TTL expired
    load_all_settings()

    if key in _CACHE:
        val, ts = _CACHE[key]
        return val

    # Fallback to .env / os.getenv and cache it to prevent repeated misses
    fallback_val = os.getenv(key, default or "")
    _CACHE[key] = (fallback_val, now)
    return fallback_val


def set_setting(key: str, value: str, updated_by: str = "admin", description: Optional[str] = None) -> bool:
    """Sets a setting in the database and updates cache."""
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO system_settings (setting_key, setting_value, updated_by, description)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                setting_value = VALUES(setting_value),
                updated_by = VALUES(updated_by),
                description = COALESCE(VALUES(description), description)
            """,
            (key, str(value), updated_by, description),
        )
        conn.commit()
        _CACHE[key] = (str(value), time.time())
        return True
    except Exception as e:
        print(f"[SettingsService] Error saving setting {key}: {e}")
        # Even if DB fails, update local in-memory cache so process can function
        _CACHE[key] = (str(value), time.time())
        return False
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


def set_settings_bulk(settings: Dict[str, str], updated_by: str = "admin") -> bool:
    """
    Saves multiple settings in a single database roundtrip and updates in-memory cache instantly.
    This replaces multiple sequential remote database connections with one batched query.
    """
    if not settings:
        return True

    # 1. Update in-memory cache instantly so subsequent reads are immediate (0ms)
    now = time.time()
    for k, v in settings.items():
        _CACHE[k] = (str(v), now)

    # 2. Persist to MySQL in a single roundtrip
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        query = """
            INSERT INTO system_settings (setting_key, setting_value, updated_by)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE
                setting_value = VALUES(setting_value),
                updated_by = VALUES(updated_by)
        """
        data = [(k, str(v), updated_by) for k, v in settings.items()]
        cursor.executemany(query, data)
        conn.commit()
        return True
    except Exception as e:
        print(f"[SettingsService] Error in set_settings_bulk: {e}")
        return False
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


def mask_key(k: str) -> str:
    """Masks secret API key for safe UI display (e.g. AIzaSy...ABCD)."""
    if not k:
        return ""
    if len(k) <= 8:
        return "****"
    return f"{k[:6]}...{k[-4:]}"


def get_llm_config() -> Dict[str, Any]:
    """Returns the complete LLM configuration with masked credentials."""
    active_llm = get_setting("ACTIVE_LLM", "mistral_local")
    mistral_local_url = get_setting("MISTRAL_LOCAL_URL", "")
    mistral_model = get_setting("MISTRAL_MODEL", "mistral:latest")

    mistral_cloud_url = get_setting("MISTRAL_CLOUD_URL", "https://api.mistral.ai")
    mistral_cloud_key = get_setting("MISTRAL_CLOUD_API_KEY", "")

    gemini_api_key = get_setting("GEMINI_API_KEY", "")
    gemini_model = get_setting("GEMINI_MODEL", "gemini-2.0-flash")

    openai_api_key = get_setting("OPENAI_API_KEY", "")
    openai_model = get_setting("OPENAI_MODEL", "gpt-4o-mini")
    openai_base_url = get_setting("OPENAI_BASE_URL", "https://api.openai.com/v1")

    # High-Availability & Tuning parameters
    enable_failover = get_setting("ENABLE_AUTO_FAILOVER", "true")
    fallback_llm = get_setting("FALLBACK_LLM", "gemini")
    llm_timeout = get_setting("LLM_TIMEOUT", "30")
    llm_temperature = get_setting("LLM_TEMPERATURE", "0.7")
    llm_max_tokens = get_setting("LLM_MAX_TOKENS", "2048")

    return {
        # Flat format matching LLMConfig TypeScript interface:
        "ACTIVE_LLM": active_llm,
        "MISTRAL_LOCAL_URL": mistral_local_url,
        "MISTRAL_MODEL": mistral_model,
        "GEMINI_API_KEY": mask_key(gemini_api_key),
        "GEMINI_MODEL": gemini_model,
        "MISTRAL_CLOUD_URL": mistral_cloud_url,
        "MISTRAL_CLOUD_API_KEY": mask_key(mistral_cloud_key),
        "OPENAI_API_KEY": mask_key(openai_api_key),
        "OPENAI_MODEL": openai_model,
        "OPENAI_BASE_URL": openai_base_url,
        "ENABLE_AUTO_FAILOVER": enable_failover,
        "FALLBACK_LLM": fallback_llm,
        "LLM_TIMEOUT": llm_timeout,
        "LLM_TEMPERATURE": llm_temperature,
        "LLM_MAX_TOKENS": llm_max_tokens,
        "is_configured": {
            "mistral_local": bool(mistral_local_url and mistral_local_url.strip()),
            "gemini": bool(gemini_api_key and gemini_api_key.strip()),
            "mistral_cloud": bool(mistral_cloud_key and mistral_cloud_key.strip()),
            "openai": bool(openai_api_key and openai_api_key.strip()),
        },
        # Nested format for backward compatibility:
        "active_llm": active_llm,
        "mistral_local": {
            "url": mistral_local_url,
            "model": mistral_model,
        },
        "mistral_cloud": {
            "url": mistral_cloud_url,
            "model": mistral_model,
            "is_configured": bool(mistral_cloud_key),
            "masked_key": mask_key(mistral_cloud_key),
        },
        "gemini": {
            "model": gemini_model,
            "is_configured": bool(gemini_api_key),
            "masked_key": mask_key(gemini_api_key),
        },
        "openai": {
            "base_url": openai_base_url,
            "model": openai_model,
            "is_configured": bool(openai_api_key),
            "masked_key": mask_key(openai_api_key),
        },
        "available_providers": ["mistral_local", "gemini", "mistral_cloud", "openai"],
    }


def update_llm_config(data: Dict[str, Any], updated_by: str = "admin") -> bool:
    """Updates the LLM configuration in database in a single fast batch operation."""
    settings_to_save: Dict[str, str] = {}

    # Local Mistral
    mistral_url = data.get("MISTRAL_LOCAL_URL") or data.get("mistral_local_url")
    if mistral_url is not None and str(mistral_url).strip():
        settings_to_save["MISTRAL_LOCAL_URL"] = str(mistral_url).strip()
    mistral_model = data.get("MISTRAL_MODEL") or data.get("mistral_model")
    if mistral_model:
        settings_to_save["MISTRAL_MODEL"] = str(mistral_model).strip()

    # Mistral Cloud
    mc_url = data.get("MISTRAL_CLOUD_URL") or data.get("mistral_cloud_url")
    if mc_url:
        settings_to_save["MISTRAL_CLOUD_URL"] = str(mc_url).strip()
    mc_key = data.get("MISTRAL_CLOUD_API_KEY") or data.get("mistral_cloud_api_key")
    if mc_key and not mc_key.startswith("***") and "..." not in mc_key:
        settings_to_save["MISTRAL_CLOUD_API_KEY"] = str(mc_key).strip()

    # Gemini
    gem_key = data.get("GEMINI_API_KEY") or data.get("gemini_api_key")
    if gem_key and not gem_key.startswith("***") and "..." not in gem_key:
        settings_to_save["GEMINI_API_KEY"] = str(gem_key).strip()
    gem_model = data.get("GEMINI_MODEL") or data.get("gemini_model")
    if gem_model:
        settings_to_save["GEMINI_MODEL"] = str(gem_model).strip()

    # OpenAI
    oa_key = data.get("OPENAI_API_KEY") or data.get("openai_api_key")
    if oa_key and not oa_key.startswith("***") and "..." not in oa_key:
        settings_to_save["OPENAI_API_KEY"] = str(oa_key).strip()
    oa_model = data.get("OPENAI_MODEL") or data.get("openai_model")
    if oa_model:
        settings_to_save["OPENAI_MODEL"] = str(oa_model).strip()
    oa_base = data.get("OPENAI_BASE_URL") or data.get("openai_base_url")
    if oa_base:
        settings_to_save["OPENAI_BASE_URL"] = str(oa_base).strip()

    # Failover & Runtime parameters
    if "ENABLE_AUTO_FAILOVER" in data:
        val = "true" if str(data["ENABLE_AUTO_FAILOVER"]).lower() in ("true", "1", "yes") else "false"
        settings_to_save["ENABLE_AUTO_FAILOVER"] = val
    if "FALLBACK_LLM" in data and data["FALLBACK_LLM"]:
        settings_to_save["FALLBACK_LLM"] = str(data["FALLBACK_LLM"]).strip()
    if "LLM_TIMEOUT" in data and str(data["LLM_TIMEOUT"]).strip():
        settings_to_save["LLM_TIMEOUT"] = str(data["LLM_TIMEOUT"]).strip()
    if "LLM_TEMPERATURE" in data and data["LLM_TEMPERATURE"]:
        settings_to_save["LLM_TEMPERATURE"] = str(data["LLM_TEMPERATURE"]).strip()
    if "LLM_MAX_TOKENS" in data and data["LLM_MAX_TOKENS"]:
        settings_to_save["LLM_MAX_TOKENS"] = str(data["LLM_MAX_TOKENS"]).strip()

    # Active LLM
    current_active = get_setting("ACTIVE_LLM", "mistral_local")
    active_llm = data.get("ACTIVE_LLM") or data.get("active_llm")

    if active_llm:
        provider = str(active_llm).strip().lower()
        if provider == "gemini":
            current_key = settings_to_save.get("GEMINI_API_KEY") or get_setting("GEMINI_API_KEY", "")
            if not current_key or not current_key.strip():
                raise ValueError("Google Gemini cannot be activated without an API Key. Please enter a valid Gemini API Key first.")
        elif provider == "openai":
            current_key = settings_to_save.get("OPENAI_API_KEY") or get_setting("OPENAI_API_KEY", "")
            if not current_key or not current_key.strip():
                raise ValueError("OpenAI cannot be activated without an API Key. Please enter a valid OpenAI API Key first.")
        elif provider == "mistral_cloud":
            current_key = settings_to_save.get("MISTRAL_CLOUD_API_KEY") or get_setting("MISTRAL_CLOUD_API_KEY", "")
            if not current_key or not current_key.strip():
                raise ValueError("Mistral Cloud cannot be activated without an API Key. Please enter a valid Mistral Cloud API Key first.")
        elif provider == "mistral_local":
            current_url = settings_to_save.get("MISTRAL_LOCAL_URL") or get_setting("MISTRAL_LOCAL_URL", "")
            if not current_url or not current_url.strip():
                raise ValueError("Mistral Local cannot be activated without a Server Endpoint URL. Please configure the URL first.")
        else:
            raise ValueError(f"Unknown LLM provider: {provider}")

        # If the provider is actively changing, perform a rapid live ping test
        if provider != current_active:
            test_res = test_llm_connection(provider, config=data, timeout=(2.5, 3.5))
            if not test_res.get("success"):
                err_msg = test_res.get("message", "Authentication check failed.")
                raise ValueError(f"Verification Failed: {err_msg}")

        settings_to_save["ACTIVE_LLM"] = provider

    # Perform ONE single bulk update to save all settings instantly
    return set_settings_bulk(settings_to_save, updated_by=updated_by)


def test_all_providers() -> Dict[str, Any]:
    """Runs concurrent health checks on all supported LLM providers."""
    providers = ["mistral_local", "gemini", "mistral_cloud", "openai"]
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        future_to_prov = {executor.submit(test_llm_connection, p, None, (2.5, 3.5)): p for p in providers}
        for future in concurrent.futures.as_completed(future_to_prov):
            prov = future_to_prov[future]
            try:
                res = future.result()
                results[prov] = {
                    "provider": prov,
                    "status": "ok" if res.get("success") else "error",
                    "message": res.get("message", ""),
                    "latency_ms": res.get("latency_ms", 0),
                }
            except Exception as e:
                results[prov] = {
                    "provider": prov,
                    "status": "error",
                    "message": str(e),
                    "latency_ms": 0,
                }
    return results


def test_llm_connection(
    provider: str,
    config: Optional[Dict[str, Any]] = None,
    timeout: tuple = (2.5, 3.5),
) -> Dict[str, Any]:
    """Tests a single fast ping connection to the specified LLM provider."""
    if config is None:
        config = {}

    start_time = time.time()
    test_prompt = "Respond with 'OK' only."

    resp = None
    try:
        if provider == "mistral_local":
            base_url = (
                config.get("MISTRAL_LOCAL_URL")
                or config.get("url")
                or get_setting("MISTRAL_LOCAL_URL", "")
            ).rstrip("/")
            model = (
                config.get("MISTRAL_MODEL")
                or config.get("model")
                or get_setting("MISTRAL_MODEL", "mistral:latest")
            )
            if not base_url:
                return {"success": False, "message": "Local Mistral URL is empty"}

            endpoint = f"{base_url}/api/generate"
            print(f"\n{'='*60}")
            print(f"[LLM TEST CALL] Provider: mistral_local | Model/Version: {model} | URL: {endpoint}")
            print(f"{'='*60}\n")
            try:
                resp = requests.post(
                    endpoint,
                    headers={"Connection": "close"},
                    json={"model": model, "prompt": test_prompt, "stream": False},
                    timeout=(2.0, 3.0),
                )
            except Exception:
                # Fallback to OpenAI-compatible /v1/chat/completions
                print(f"[LLM TEST FALLBACK CALL] Provider: mistral_local | Model/Version: {model} | URL: {base_url}/v1/chat/completions")
                resp = requests.post(
                    f"{base_url}/v1/chat/completions",
                    headers={"Connection": "close"},
                    json={"model": model, "messages": [{"role": "user", "content": test_prompt}]},
                    timeout=(2.0, 3.0),
                )

            latency = int((time.time() - start_time) * 1000)
            if resp.status_code == 200:
                try:
                    resolved_model = resp.json().get("model", model)
                except Exception:
                    resolved_model = model
                print(f"[LLM TEST RESPONSE] Provider: mistral_local | Resolved Model/Version: {resolved_model}")
                return {"success": True, "latency_ms": latency, "message": f"Connected to {model} successfully ({latency}ms)"}
            return {"success": False, "latency_ms": latency, "message": f"Server error (HTTP {resp.status_code}): {resp.text[:150]}"}

        elif provider == "gemini":
            api_key = (
                config.get("GEMINI_API_KEY")
                or config.get("api_key")
                or get_setting("GEMINI_API_KEY", "")
            )
            model = (
                config.get("GEMINI_MODEL")
                or config.get("model")
                or get_setting("GEMINI_MODEL", "gemini-2.0-flash")
            )
            if not api_key or api_key.startswith("***") or "..." in api_key:
                api_key = get_setting("GEMINI_API_KEY", "")
            if not api_key:
                return {"success": False, "message": "Gemini API key is required"}

            api_version = "v1beta"
            url = f"https://generativelanguage.googleapis.com/{api_version}/models/{model}:generateContent?key={api_key}"
            print(f"\n{'='*60}")
            print(f"[LLM TEST CALL] Provider: gemini | Model: {model} | API Version: {api_version} | Endpoint: generativelanguage.googleapis.com/{api_version}/models/{model}")
            print(f"{'='*60}\n")
            resp = requests.post(
                url,
                headers={"Connection": "close"},
                json={"contents": [{"parts": [{"text": test_prompt}]}]},
                timeout=timeout,
            )
            latency = int((time.time() - start_time) * 1000)
            if resp.status_code == 200:
                try:
                    resolved_version = resp.json().get("modelVersion", model)
                except Exception:
                    resolved_version = model
                print(f"[LLM TEST RESPONSE] Provider: gemini | Configured Model: {model} | Resolved Version: {resolved_version}")
                return {"success": True, "latency_ms": latency, "message": f"Connected to Gemini ({model}) successfully ({latency}ms)"}
            try:
                err_data = resp.json()
                clean_msg = err_data.get("error", {}).get("message") or resp.text[:150]
            except Exception:
                clean_msg = resp.text[:150]
            return {"success": False, "latency_ms": latency, "message": f"Gemini API key invalid ({resp.status_code}): {clean_msg}"}

        elif provider == "mistral_cloud":
            base_url = (
                config.get("MISTRAL_CLOUD_URL")
                or config.get("url")
                or get_setting("MISTRAL_CLOUD_URL", "https://api.mistral.ai")
            ).rstrip("/")
            api_key = (
                config.get("MISTRAL_CLOUD_API_KEY")
                or config.get("api_key")
                or get_setting("MISTRAL_CLOUD_API_KEY", "")
            )
            model = (
                config.get("MISTRAL_MODEL")
                or config.get("model")
                or get_setting("MISTRAL_MODEL", "mistral-large-latest")
            )
            if not api_key or api_key.startswith("***") or "..." in api_key:
                api_key = get_setting("MISTRAL_CLOUD_API_KEY", "")
            if not api_key:
                return {"success": False, "message": "Mistral Cloud API key is required"}

            print(f"\n{'='*60}")
            print(f"[LLM TEST CALL] Provider: mistral_cloud | Model/Version: {model} | URL: {base_url}/v1/chat/completions")
            print(f"{'='*60}\n")
            resp = requests.post(
                f"{base_url}/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Connection": "close"},
                json={"model": model, "messages": [{"role": "user", "content": test_prompt}]},
                timeout=timeout,
            )
            latency = int((time.time() - start_time) * 1000)
            if resp.status_code == 200:
                try:
                    resolved_model = resp.json().get("model", model)
                except Exception:
                    resolved_model = model
                print(f"[LLM TEST RESPONSE] Provider: mistral_cloud | Resolved Model/Version: {resolved_model}")
                return {"success": True, "latency_ms": latency, "message": f"Connected to Mistral Cloud ({model}) successfully ({latency}ms)"}
            try:
                err_data = resp.json()
                clean_msg = err_data.get("detail") or err_data.get("message") or resp.text[:150]
            except Exception:
                clean_msg = resp.text[:150]
            return {"success": False, "latency_ms": latency, "message": f"Mistral Cloud key invalid ({resp.status_code}): {clean_msg}"}

        elif provider == "openai":
            base_url = (
                config.get("OPENAI_BASE_URL")
                or config.get("base_url")
                or get_setting("OPENAI_BASE_URL", "https://api.openai.com/v1")
            ).rstrip("/")
            api_key = (
                config.get("OPENAI_API_KEY")
                or config.get("api_key")
                or get_setting("OPENAI_API_KEY", "")
            )
            model = (
                config.get("OPENAI_MODEL")
                or config.get("model")
                or get_setting("OPENAI_MODEL", "gpt-4o-mini")
            )
            if not api_key or api_key.startswith("***") or "..." in api_key:
                api_key = get_setting("OPENAI_API_KEY", "")
            if not api_key:
                return {"success": False, "message": "OpenAI API key is required"}

            print(f"\n{'='*60}")
            print(f"[LLM TEST CALL] Provider: openai | Model/Version: {model} | URL: {base_url}/chat/completions")
            print(f"{'='*60}\n")
            resp = requests.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Connection": "close"},
                json={"model": model, "messages": [{"role": "user", "content": test_prompt}]},
                timeout=timeout,
            )
            latency = int((time.time() - start_time) * 1000)
            if resp.status_code == 200:
                try:
                    resolved_model = resp.json().get("model", model)
                except Exception:
                    resolved_model = model
                print(f"[LLM TEST RESPONSE] Provider: openai | Resolved Model/Version: {resolved_model}")
                return {"success": True, "latency_ms": latency, "message": f"Connected to OpenAI ({model}) successfully ({latency}ms)"}
            try:
                err_data = resp.json()
                clean_msg = err_data.get("error", {}).get("message") or resp.text[:150]
            except Exception:
                clean_msg = resp.text[:150]
            return {"success": False, "latency_ms": latency, "message": f"OpenAI API key invalid ({resp.status_code}): {clean_msg}"}

        else:
            return {"success": False, "message": f"Unknown provider: {provider}"}

    except requests.exceptions.Timeout:
        return {"success": False, "latency_ms": int((time.time() - start_time) * 1000), "message": f"Connection timed out. Server at {provider} is unreachable."}
    except requests.exceptions.ConnectionError:
        return {"success": False, "latency_ms": int((time.time() - start_time) * 1000), "message": f"Connection refused. Could not establish connection to {provider}."}
    except Exception as e:
        return {"success": False, "latency_ms": int((time.time() - start_time) * 1000), "message": f"Connection error: {str(e)}"}
    finally:
        if resp is not None:
            resp.close()
