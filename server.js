const express = require("express");
const http = require("http");
const WebSocket = require("ws");

const app = express();
const server = http.createServer(app);

const wss = new WebSocket.Server({
    server,
    path: "/ws"
});

const rooms = new Map();

app.get("/", (_, res) => {
    res.send("Relay online");
});

wss.on("connection", (ws) => {

    ws.uid = null;
    ws.job = null;

    ws.on("message", raw => {

        let data;

        try {
            data = JSON.parse(raw);
        } catch {
            return;
        }

        if (data.type === "join") {

            ws.uid = data.uid;
            ws.job = data.job;

            if (!rooms.has(ws.job))
                rooms.set(ws.job, new Map());

            rooms.get(ws.job).set(ws.uid, ws);

            return;
        }

        if (!ws.job) return;

        const room = rooms.get(ws.job);
        if (!room) return;

        for (const [uid, client] of room) {

            if (client !== ws && client.readyState === WebSocket.OPEN)
                client.send(raw);

        }

    });

    ws.on("close", () => {

        if (!ws.job) return;

        const room = rooms.get(ws.job);

        if (!room) return;

        room.delete(ws.uid);

        if (room.size === 0)
            rooms.delete(ws.job);

    });

});

server.listen(process.env.PORT || 10000, "0.0.0.0");
