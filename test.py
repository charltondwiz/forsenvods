import asyncio
import base64
import hmac
import hashlib
import time
from aiortc import RTCIceServer, RTCIceGatherer

# === CONFIGURATION ===
TURN_SERVER = "turn:turn.firstshot.ai:5349?transport=tcp"
SHARED_SECRET_B64 = "6FzCzifixhKg0CjwE5WLaqrcXnbBWHSo8WOu+9GCfcg="
USER_ID = 1234
TTL_SECONDS = 3600

# === HMAC TURN CREDENTIAL GENERATOR ===
def generate_turn_credentials():
    expiry = int(time.time()) + TTL_SECONDS
    username = f"{expiry}:{USER_ID}"
    shared_secret = base64.b64decode(SHARED_SECRET_B64)  # 🔐 Match Go behavior: decode base64 to raw bytes

    h = hmac.new(shared_secret, username.encode('utf-8'), hashlib.sha1)
    password = base64.b64encode(h.digest()).decode('utf-8')

    return username, password

# === TURN Validation ===
async def validate_turn():
    username, credential = generate_turn_credentials()

    ice_server = RTCIceServer(
        urls=[TURN_SERVER],
        username=username,
        credential=credential
    )

    print("Connecting to TURN server with:")
    print(f"  Username: {username}")
    print(f"  Credential: {credential}")

    try:
        gatherer = RTCIceGatherer(iceServers=[ice_server])
        await gatherer.gather()

        candidates = gatherer.getLocalCandidates()
        if any(cand for cand in candidates if cand.type == "relay"):
            print("✅ Success! TURN credentials are valid and relay candidate was gathered.")
        else:
            print("❌ Failed: No relay candidates returned. Check TURN server config, logs, or if it's reachable.")
    except Exception as e:
        print(f"❌ Error during TURN authentication: {e}")

# === Run It ===
asyncio.run(validate_turn())
