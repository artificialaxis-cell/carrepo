const express = require("express");
const http = require("http");
const WebSocket = require("ws");

const app = express();
const server = http.createServer(app);

const PORT = process.env.PORT || 10000;

const wss = new WebSocket.Server({
    server,
    path: "/ws"
});

app.get("/", (req, res) => {
    res.send("Car relay online");
});

wss.on("connection", (ws) => {
    console.log("Client connected");

    ws.on("message", (message) => {
        for (const client of wss.clients) {
            if (client !== ws && client.readyState === WebSocket.OPEN) {
                client.send(message.toString());
            }
        }
    });

    ws.on("close", () => {
        console.log("Client disconnected");
    });
});

server.listen(PORT, "0.0.0.0", () => {
    console.log(`Server running on port ${PORT}`);
});
