#!/usr/bin/env bash
# Configure Twilio SIP Trunk to point to LiveKit's SIP bridge.
# Requires: TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, LIVEKIT_SIP_URI env vars.
set -euo pipefail

: "${TWILIO_ACCOUNT_SID:?Set TWILIO_ACCOUNT_SID}"
: "${TWILIO_AUTH_TOKEN:?Set TWILIO_AUTH_TOKEN}"
: "${LIVEKIT_SIP_URI:?Set LIVEKIT_SIP_URI (e.g., sip:your-project.sip.livekit.cloud)}"

BASE_URL="https://trunking.twilio.com/v1/Trunks"
AUTH="-u ${TWILIO_ACCOUNT_SID}:${TWILIO_AUTH_TOKEN}"

echo "==> Creating Twilio SIP Trunk..."
TRUNK_SID=$(curl -s -X POST "$BASE_URL" \
  $AUTH \
  -d "FriendlyName=LiveKit Voice Agent" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['sid'])")

echo "    Trunk SID: $TRUNK_SID"

echo "==> Setting origination URI..."
curl -s -X POST "${BASE_URL}/${TRUNK_SID}/OriginationUrls" \
  $AUTH \
  -d "FriendlyName=LiveKit SIP Bridge" \
  -d "SipUrl=${LIVEKIT_SIP_URI}" \
  -d "Priority=1" \
  -d "Weight=100" \
  -d "Enabled=true" > /dev/null

echo "==> Trunk configured successfully."
echo ""
echo "Next steps:"
echo "  1. Assign a Twilio phone number to trunk ${TRUNK_SID}"
echo "  2. Configure LiveKit SIP trunk with: lk sip trunk create infra/sip-trunk-config.json"
echo "  3. Create dispatch rule with: lk sip dispatch create infra/sip-trunk-config.json"
