"use strict";
/*
 * Car relay
 * ---------
 * Fans out car structure/state between clients in the same Roblox server (job).
 * Every message is validated byte-for-byte before it is relayed, the relay stamps the
 * sender itself (clients cannot speak for each other), and every connection is rate and
 * size limited. Nothing a client sends is ever executed or interpreted beyond the schema.
 *
 * Wire format: text frames, first character is the type.
 *
 *  client -> relay
 *    J{"v":1,"u":<userId>,"j":"<jobId>"}  join (must be first, within 10 s)
 *    S<base64>                             car structure (see STRUCTURE below)
 *    T<base64>                             car state, exactly 81 bytes
 *    X                                     car removed
 *    P<1-9 digits>                         ping
 *
 *  relay -> client
 *    W{"v":1,"s":"<sid>","p":[["sid",uid],...]}   welcome + current peers
 *    A<sid><uid>      peer joined          L<sid>        peer left
 *    S<sid><base64>   structure            T<sid><base64> state
 *    X<sid>           car removed          Q<digits>      pong
 *    E<code>          error, connection closes after it
 *
 *  sid = 3 chars [0-9a-z], assigned by the relay, unique within a room.
 */

const express = require("express");
const http = require("http");
const WebSocket = require("ws");

// ---------------------------------------------------------------------------------
// Limits
// ---------------------------------------------------------------------------------

const LIMITS = {
	maxPayload: 8192,          // bytes per frame (largest legal structure is ~5.5 KB)
	maxClients: 400,           // whole relay
	maxPerIp: 6,
	maxPerRoom: 60,
	joinTimeoutMs: 10_000,
	heartbeatMs: 20_000,
	maxStrikes: 25,            // invalid/over-limit messages before disconnect
	maxParts: 48,
	maxPackName: 48,
};

// token buckets per message type: [refill per second, burst]
const RATES = {
	T: [25, 40],
	S: [0.5, 3],
	X: [1, 4],
	P: [1, 3],
};

// ---------------------------------------------------------------------------------
// Validation helpers
// ---------------------------------------------------------------------------------

const B64 = /^[A-Za-z0-9+/]*={0,2}$/;
const JOB = /^[A-Za-z0-9-]{1,64}$/;
const PACK = /^[A-Za-z0-9_#.\- ]*$/;

function decode64(text) {
	if (text.length === 0 || text.length % 4 !== 0 || !B64.test(text)) return null;
	const buf = Buffer.from(text, "base64");
	// reject non-canonical encodings so the relayed text is exactly what was checked
	if (buf.toString("base64") !== text) return null;
	return buf;
}

const finite = (x) => Number.isFinite(x);
const within = (x, limit) => Number.isFinite(x) && Math.abs(x) <= limit;

const STATE_BYTES = 81;

function validState(buf) {
	if (buf.length !== STATE_BYTES) return false;
	const px = buf.readFloatLE(4), py = buf.readFloatLE(8), pz = buf.readFloatLE(12);
	if (!within(px, 1e6) || !within(py, 1e6) || !within(pz, 1e6)) return false;
	const rpm = buf.readUInt16LE(39);
	if (rpm > 30000) return false;
	const gear = buf.readInt8(38);
	if (gear < -1 || gear > 12) return false;
	if (buf.readUInt8(37) > 0x3f) return false; // only 6 flag bits are defined
	return true;
}

/*
 * STRUCTURE (little endian)
 *   u8 version(=1) u8 flags
 *   f32 x9 layout: frontZ rearZ trackFront trackRear wheelY radiusF radiusR widthF widthR
 *   u8 n + n bytes  on-throttle sound pack     u8 n + n bytes  off-throttle sound pack
 *   u8 volume*100   u16 idleRpm   u16 redlineRpm   u8 partCount
 *   part (82 bytes):
 *     u8 role(0 body,1 detail,2 tire,3 rim,4 wheel) u8 corner(0-3, 255) u8 meshType
 *     f64 meshId f64 textureId f32x3 scale f32x3 offset f32x3 size
 *     u8x3 color u8x3 vertexColor*100 u16 material u8 transparency*255
 *     f32x3 position relative to body  u16x3 rotation (smallest three)
 */
const PART_BYTES = 82;

function validAssetId(x) {
	return Number.isInteger(x) && x >= 0 && x <= 9007199254740991;
}

function validStructure(buf) {
	if (buf.length < 47 || buf.length > 47 + 2 * LIMITS.maxPackName + LIMITS.maxParts * PART_BYTES) return false;
	let o = 0;
	if (buf.readUInt8(o) !== 1) return false;
	o += 2;
	const layout = [];
	for (let i = 0; i < 9; i++) {
		const v = buf.readFloatLE(o);
		if (!within(v, 200)) return false;
		layout.push(v);
		o += 4;
	}
	// radii and widths must be positive and sane
	for (let i = 5; i < 9; i++) if (layout[i] <= 0.05 || layout[i] > 20) return false;
	if (layout[2] <= 0 || layout[3] <= 0 || layout[1] - layout[0] <= 0.5) return false;

	for (let k = 0; k < 2; k++) {
		const n = buf.readUInt8(o);
		o += 1;
		if (n > LIMITS.maxPackName || o + n > buf.length) return false;
		const name = buf.toString("latin1", o, o + n);
		if (!PACK.test(name)) return false;
		o += n;
	}
	if (o + 6 > buf.length) return false;
	if (buf.readUInt8(o) > 200) return false;
	const idle = buf.readUInt16LE(o + 1), redline = buf.readUInt16LE(o + 3);
	if (idle < 100 || redline <= idle || redline > 30000) return false;
	const count = buf.readUInt8(o + 5);
	o += 6;
	if (count < 1 || count > LIMITS.maxParts) return false;
	if (buf.length !== o + count * PART_BYTES) return false;

	let bodies = 0;
	for (let i = 0; i < count; i++, o += PART_BYTES) {
		const role = buf.readUInt8(o), corner = buf.readUInt8(o + 1), meshType = buf.readUInt8(o + 2);
		if (role > 4 || meshType > 20) return false;
		if (role === 0) bodies++;
		if (role >= 2 ? corner > 3 : corner !== 255) return false;
		if (!validAssetId(buf.readDoubleLE(o + 3)) || !validAssetId(buf.readDoubleLE(o + 11))) return false;
		for (let j = 0; j < 3; j++) {
			const scale = buf.readFloatLE(o + 19 + j * 4);
			const offset = buf.readFloatLE(o + 31 + j * 4);
			const size = buf.readFloatLE(o + 43 + j * 4);
			const pos = buf.readFloatLE(o + 64 + j * 4);
			if (!within(scale, 64) || !within(offset, 64) || !finite(size) || size < 0.001 || size > 64 || !within(pos, 64)) return false;
		}
		if (buf.readUInt16LE(o + 61) > 4096) return false;
	}
	return bodies === 1;
}

// ---------------------------------------------------------------------------------
// Relay
// ---------------------------------------------------------------------------------

const app = express();
app.disable("x-powered-by");
app.get("/", (_, res) => res.type("text/plain").send("Relay online"));
app.get("/health", (_, res) => res.json({ ok: true, clients: clientCount, rooms: rooms.size }));

const server = http.createServer(app);
const wss = new WebSocket.Server({
	server,
	path: "/ws",
	maxPayload: LIMITS.maxPayload,
	perMessageDeflate: false,
	clientTracking: false,
});

const rooms = new Map(); // job -> Map(sid -> client)
const perIp = new Map();
let clientCount = 0;

function ipOf(req) {
	const fwd = req.headers["x-forwarded-for"];
	const first = typeof fwd === "string" ? fwd.split(",")[0].trim() : "";
	return first || req.socket.remoteAddress || "?";
}

function newSid(room) {
	for (let i = 0; i < 200; i++) {
		const sid = Math.floor(Math.random() * 46656).toString(36).padStart(3, "0");
		if (!room.has(sid)) return sid;
	}
	return null;
}

function send(ws, text) {
	if (ws.readyState === WebSocket.OPEN) ws.send(text);
}

function broadcast(room, from, text) {
	for (const client of room.values()) {
		if (client.ws !== from) send(client.ws, text);
	}
}

function bucketTake(client, type) {
	const rate = RATES[type];
	const now = Date.now();
	let b = client.buckets[type];
	if (!b) b = client.buckets[type] = { tokens: rate[1], at: now };
	b.tokens = Math.min(rate[1], b.tokens + ((now - b.at) / 1000) * rate[0]);
	b.at = now;
	if (b.tokens < 1) return false;
	b.tokens -= 1;
	return true;
}

function strike(client, reason) {
	client.strikes += 1;
	if (client.strikes >= LIMITS.maxStrikes) {
		send(client.ws, "E" + reason);
		client.ws.close(1008, "policy");
	}
}

wss.on("connection", (ws, req) => {
	const ip = ipOf(req);
	if (clientCount >= LIMITS.maxClients || (perIp.get(ip) || 0) >= LIMITS.maxPerIp) {
		send(ws, "Ebusy");
		ws.close(1013, "busy");
		return;
	}
	clientCount++;
	perIp.set(ip, (perIp.get(ip) || 0) + 1);

	const client = {
		ws,
		ip,
		sid: null,
		uid: null,
		job: null,
		room: null,
		alive: true,
		strikes: 0,
		buckets: {},
		lastS: null,
		lastT: null,
	};
	ws.client = client;

	const joinTimer = setTimeout(() => {
		if (!client.room) ws.close(1008, "join timeout");
	}, LIMITS.joinTimeoutMs);

	ws.on("pong", () => {
		client.alive = true;
	});

	ws.on("message", (data, isBinary) => {
		if (isBinary) return strike(client, "binary");
		const text = data.toString("utf8");
		if (text.length === 0) return strike(client, "empty");
		const type = text[0];

		if (!client.room) {
			if (type !== "J") return ws.close(1008, "join first");
			let msg;
			try {
				msg = JSON.parse(text.slice(1));
			} catch {
				return ws.close(1008, "bad join");
			}
			const uid = msg && msg.u;
			const job = msg && msg.j;
			if (!msg || msg.v !== 1 || !Number.isSafeInteger(uid) || uid < 1 || typeof job !== "string" || !JOB.test(job)) {
				send(ws, "Ejoin");
				return ws.close(1008, "bad join");
			}
			let room = rooms.get(job);
			if (!room) {
				room = new Map();
				rooms.set(job, room);
			}
			if (room.size >= LIMITS.maxPerRoom) {
				send(ws, "Efull");
				return ws.close(1013, "room full");
			}
			for (const other of room.values()) {
				if (other.uid === uid) {
					send(ws, "Euid");
					return ws.close(1008, "uid in use");
				}
			}
			const sid = newSid(room);
			if (!sid) return ws.close(1013, "busy");
			clearTimeout(joinTimer);
			client.sid = sid;
			client.uid = uid;
			client.job = job;
			client.room = room;

			const peers = [];
			for (const other of room.values()) peers.push([other.sid, other.uid]);
			room.set(sid, client);
			send(ws, "W" + JSON.stringify({ v: 1, s: sid, p: peers }));
			// bring the newcomer up to date
			for (const other of room.values()) {
				if (other === client) continue;
				if (other.lastS) send(ws, other.lastS);
				if (other.lastT) send(ws, other.lastT);
			}
			broadcast(room, ws, "A" + sid + uid);
			return;
		}

		if (!RATES[type]) return strike(client, "type");
		if (!bucketTake(client, type)) return strike(client, "rate");

		switch (type) {
			case "T": {
				const buf = decode64(text.slice(1));
				if (!buf || !validState(buf)) return strike(client, "state");
				const out = "T" + client.sid + text.slice(1);
				client.lastT = out;
				broadcast(client.room, ws, out);
				return;
			}
			case "S": {
				const buf = decode64(text.slice(1));
				if (!buf || !validStructure(buf)) return strike(client, "structure");
				const out = "S" + client.sid + text.slice(1);
				client.lastS = out;
				client.lastT = null;
				broadcast(client.room, ws, out);
				return;
			}
			case "X": {
				if (text.length !== 1) return strike(client, "x");
				client.lastS = null;
				client.lastT = null;
				broadcast(client.room, ws, "X" + client.sid);
				return;
			}
			case "P": {
				const digits = text.slice(1);
				if (!/^[0-9]{1,9}$/.test(digits)) return strike(client, "ping");
				send(ws, "Q" + digits);
				return;
			}
		}
	});

	ws.on("close", () => {
		clearTimeout(joinTimer);
		clientCount--;
		const n = (perIp.get(ip) || 1) - 1;
		if (n <= 0) perIp.delete(ip);
		else perIp.set(ip, n);
		if (client.room) {
			client.room.delete(client.sid);
			broadcast(client.room, ws, "L" + client.sid);
			if (client.room.size === 0) rooms.delete(client.job);
		}
	});

	ws.on("error", () => {});
});

// drop connections that stop answering pings (also frees Render's idle sockets)
const heartbeat = setInterval(() => {
	for (const room of rooms.values()) {
		for (const client of room.values()) {
			if (!client.alive) {
				client.ws.terminate();
				continue;
			}
			client.alive = false;
			try {
				client.ws.ping();
			} catch {}
		}
	}
}, LIMITS.heartbeatMs);
wss.on("close", () => clearInterval(heartbeat));

const PORT = Number(process.env.PORT) || 10000;
server.listen(PORT, "0.0.0.0", () => console.log("relay listening on " + PORT));

module.exports = { server, validState, validStructure, decode64 };
