"use strict";
// End-to-end checks for the relay: run with `npm test` (starts the server on a test port).
process.env.PORT = "10123";
const { server } = require("./server");
const WebSocket = require("ws");

const URL = "ws://127.0.0.1:10123/ws";
const JOB = "6b1f0d2c-1111-4aaa-9bbb-123456789abc";
let failures = 0;

function check(name, ok) {
	console.log((ok ? "  ok   " : "  FAIL ") + name);
	if (!ok) failures++;
}

function client() {
	return new Promise((resolve) => {
		const ws = new WebSocket(URL);
		ws.inbox = [];
		ws.closed = null;
		ws.on("message", (d) => ws.inbox.push(d.toString()));
		ws.on("close", (code) => (ws.closed = code));
		ws.on("open", () => resolve(ws));
	});
}

const wait = (ms) => new Promise((r) => setTimeout(r, ms));

function state(x = 10, rpm = 800) {
	const b = Buffer.alloc(81);
	b.writeUInt32LE(1234, 0);
	b.writeFloatLE(x, 4);
	b.writeFloatLE(2, 8);
	b.writeFloatLE(-5, 12);
	b.writeUInt16LE(rpm, 39);
	b.writeInt8(1, 38);
	return b;
}

function structure(parts = 3, opts = {}) {
	const head = Buffer.alloc(2 + 36);
	head.writeUInt8(1, 0);
	[-7.6, 6.5, 7.6, 7.2, -2.3, 1.6, 1.6, 1.3, 1.3].forEach((v, i) => head.writeFloatLE(v, 2 + i * 4));
	const on = Buffer.from(opts.pack || "bmw_m3_e30_drift_p#loop", "latin1");
	const off = Buffer.from("bmw_m3_e30_drift_f#loop", "latin1");
	const tail = Buffer.alloc(6);
	tail.writeUInt8(100, 0);
	tail.writeUInt16LE(800, 1);
	tail.writeUInt16LE(7500, 3);
	tail.writeUInt8(parts, 5);
	const list = [];
	for (let i = 0; i < parts; i++) {
		const p = Buffer.alloc(82);
		p.writeUInt8(i === 0 ? 0 : 2, 0);
		p.writeUInt8(i === 0 ? 255 : (i - 1) % 4, 1);
		p.writeUInt8(5, 2);
		p.writeDoubleLE(opts.meshId ?? 106343343162810, 3);
		for (let j = 0; j < 3; j++) {
			p.writeFloatLE(opts.scale ?? 3.5, 19 + j * 4);
			p.writeFloatLE(1, 43 + j * 4);
		}
		p.writeUInt16LE(256, 61);
		list.push(p);
	}
	return Buffer.concat([head, Buffer.from([on.length]), on, Buffer.from([off.length]), off, tail, ...list]);
}

(async () => {
	console.log("relay tests");
	const a = await client();
	const b = await client();
	a.send("J" + JSON.stringify({ v: 1, u: 111, j: JOB }));
	await wait(80);
	b.send("J" + JSON.stringify({ v: 1, u: 222, j: JOB }));
	await wait(120);
	const wa = a.inbox.find((m) => m[0] === "W");
	const wb = b.inbox.find((m) => m[0] === "W");
	check("both receive a welcome", !!wa && !!wb);
	const sidA = JSON.parse(wa.slice(1)).s;
	const sidB = JSON.parse(wb.slice(1)).s;
	check("B's welcome lists A", JSON.parse(wb.slice(1)).p.some(([s, u]) => s === sidA && u === 111));
	check("A is told B joined", a.inbox.includes("A" + sidB + "222"));

	// valid traffic relays with the relay-assigned sid
	a.send("S" + structure().toString("base64"));
	a.send("T" + state().toString("base64"));
	await wait(120);
	check("structure relayed and stamped", b.inbox.some((m) => m.startsWith("S" + sidA)));
	check("state relayed and stamped", b.inbox.some((m) => m.startsWith("T" + sidA)));
	check("sender does not get its own echo", !a.inbox.some((m) => m.startsWith("T")));

	// late joiner gets the cached car
	const c = await client();
	c.send("J" + JSON.stringify({ v: 1, u: 333, j: JOB }));
	await wait(120);
	check("late joiner receives structure + state", c.inbox.some((m) => m.startsWith("S" + sidA)) && c.inbox.some((m) => m.startsWith("T" + sidA)));

	// hostile input never reaches peers
	const before = b.inbox.length;
	const bad = [
		"T" + Buffer.alloc(80).toString("base64"), // wrong size
		"T" + state(NaN).toString("base64"), // NaN position
		"T" + state(1e9).toString("base64"), // absurd position
		"T" + state(10, 65000).toString("base64"), // rpm out of range
		"T" + "!!!!" + state().toString("base64").slice(4), // not base64
		"S" + structure(0).toString("base64"), // no parts
		"S" + structure(60).toString("base64"), // too many parts
		"S" + structure(3, { scale: 5000 }).toString("base64"), // giant mesh
		"S" + structure(3, { meshId: 1.5 }).toString("base64"), // non-integer asset id
		"S" + structure(3, { pack: "<script>" }).toString("base64"), // bad characters
		"Zhello",
		"Xextra",
	];
	for (const m of bad) a.send(m);
	await wait(150);
	check("all malformed messages dropped", b.inbox.length === before);

	// spoofing: a client cannot pretend to be another sid
	const spoof = "T" + sidB + state().toString("base64");
	a.send(spoof);
	await wait(80);
	check("embedded sid is not trusted", !b.inbox.some((m) => m === "T" + sidA + sidB + state().toString("base64")) && !c.inbox.some((m) => m.startsWith("T" + sidB)));

	// duplicate uid is refused and cannot hijack
	const dup = await client();
	dup.send("J" + JSON.stringify({ v: 1, u: 111, j: JOB }));
	await wait(100);
	check("duplicate uid rejected", dup.inbox.includes("Euid") && dup.closed !== null);

	// bad joins
	const bj = await client();
	bj.send("J" + JSON.stringify({ v: 1, u: "111; drop", j: "../../etc" }));
	await wait(100);
	check("malformed join closed", bj.closed === 1008);
	const nj = await client();
	nj.send("T" + state().toString("base64"));
	await wait(100);
	check("traffic before join closed", nj.closed === 1008);

	// ping
	a.send("P42");
	await wait(60);
	check("ping answered", a.inbox.includes("Q42"));

	// flooding gets throttled and eventually disconnected
	const flood = await client();
	flood.send("J" + JSON.stringify({ v: 1, u: 444, j: JOB }));
	await wait(80);
	const seenBefore = b.inbox.filter((m) => m[0] === "T").length;
	for (let i = 0; i < 400; i++) flood.send("T" + state(i).toString("base64"));
	await wait(250);
	const relayed = b.inbox.filter((m) => m[0] === "T").length - seenBefore;
	check(`flood throttled (${relayed} of 400 relayed)`, relayed <= 45);
	check("flooder disconnected", flood.closed === 1008);

	// oversize frame
	const big = await client();
	big.send("J" + JSON.stringify({ v: 1, u: 555, j: JOB }));
	await wait(60);
	big.send("S" + "A".repeat(20000));
	await wait(120);
	check("oversized frame closes the socket", big.closed !== null);

	// leaving
	a.close();
	await wait(100);
	check("peers told when someone leaves", b.inbox.includes("L" + sidA));

	for (const ws of [b, c]) ws.close();
	await wait(50);
	server.close();
	console.log(failures === 0 ? "all relay tests passed" : failures + " relay test(s) FAILED");
	process.exit(failures === 0 ? 0 : 1);
})();
