const { onRequest } = require("firebase-functions/v2/https");
const { defineSecret } = require("firebase-functions/params");
const cors = require("cors")({ origin: true });
const { RoomServiceClient, AccessToken } = require("livekit-server-sdk");

// Secrets stored in Firebase — never exposed to the client
const LK_URL = defineSecret("LIVEKIT_URL");
const LK_API_KEY = defineSecret("LIVEKIT_API_KEY");
const LK_API_SECRET = defineSecret("LIVEKIT_API_SECRET");

/**
 * GET /api/rooms — List all active LiveKit rooms with participant info.
 * This is what the dashboard polls to show real-time call data.
 */
exports.api = onRequest(
  { secrets: [LK_URL, LK_API_KEY, LK_API_SECRET], cors: true },
  async (req, res) => {
    return cors(req, res, async () => {
      const path = req.path.replace(/^\/api/, "") || "/";

      try {
        const lkUrl = LK_URL.value();
        const apiKey = LK_API_KEY.value();
        const apiSecret = LK_API_SECRET.value();

        // Normalize URL for the SDK (needs http(s), not ws(s))
        const httpUrl = lkUrl
          .replace("wss://", "https://")
          .replace("ws://", "http://");

        const roomService = new RoomServiceClient(httpUrl, apiKey, apiSecret);

        // Route: GET /rooms
        if (path === "/rooms" || path === "/") {
          const rooms = await roomService.listRooms();

          // Enrich with participant data
          const enriched = await Promise.all(
            rooms.map(async (room) => {
              let participants = [];
              try {
                participants = await roomService.listParticipants(room.name);
              } catch {
                // Room may have closed between list and participant fetch
              }
              return {
                name: room.name,
                sid: room.sid,
                numParticipants: room.numParticipants,
                maxParticipants: room.maxParticipants,
                creationTime: Number(room.creationTime),
                metadata: room.metadata || "",
                participants: participants.map((p) => ({
                  identity: p.identity,
                  name: p.name,
                  state: p.state,
                  joinedAt: Number(p.joinedAt),
                  metadata: p.metadata || "",
                  tracks: (p.tracks || []).map((t) => ({
                    sid: t.sid,
                    type: t.type,
                    source: t.source,
                    muted: t.muted,
                  })),
                })),
              };
            })
          );

          return res.json({
            ok: true,
            rooms: enriched,
            count: enriched.length,
            activeCallCount: enriched.filter((r) => r.numParticipants > 0)
              .length,
            timestamp: Date.now(),
          });
        }

        // Route: GET /rooms/:name
        if (path.startsWith("/rooms/")) {
          const roomName = path.replace("/rooms/", "");
          const participants = await roomService.listParticipants(roomName);

          return res.json({
            ok: true,
            room: roomName,
            participants: participants.map((p) => ({
              identity: p.identity,
              name: p.name,
              state: p.state,
              joinedAt: Number(p.joinedAt),
              metadata: p.metadata || "",
            })),
          });
        }

        // Route: GET /health
        if (path === "/health") {
          // Quick check — can we reach LiveKit?
          const rooms = await roomService.listRooms();
          return res.json({
            ok: true,
            livekit: "connected",
            roomCount: rooms.length,
            timestamp: Date.now(),
          });
        }

        // Route: POST /token — Generate a monitor token (for LiveKit JS SDK)
        if (path === "/token" && req.method === "POST") {
          const token = new AccessToken(apiKey, apiSecret, {
            identity: "dashboard-monitor",
            name: "Dashboard",
          });
          token.addGrant({
            roomList: true,
            roomAdmin: false,
            canPublish: false,
            canSubscribe: true,
          });

          return res.json({
            ok: true,
            token: await token.toJwt(),
            url: lkUrl,
          });
        }

        return res.status(404).json({ ok: false, error: "Not found" });
      } catch (err) {
        console.error("API error:", err);
        return res
          .status(500)
          .json({ ok: false, error: err.message || "Internal error" });
      }
    });
  }
);
