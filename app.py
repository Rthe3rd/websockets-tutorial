import asyncio
import json
import os
import secrets
from http import HTTPStatus
from pathlib import Path
from urllib.parse import urlparse

from websockets.asyncio.server import broadcast, serve
from websockets.exceptions import ConnectionClosedOK, ConnectionClosedError

from connect4 import PLAYER1, PLAYER2, Connect4

ROOT_DIR = Path(__file__).parent

JOIN = {}
WATCH = {}


async def error(websocket, message):
    event = {
        "type": "error",
        "message": message,
    }
    await websocket.send(json.dumps(event))


async def replay(websocket, game):
    # Make a copy to avoid an exception if game.moves changes while iteration
    # is in progress. If a move is played while replay is running, moves will
    # be sent out of order but each move will be sent once and eventually the
    # UI will be consistent.
    for player, column, row in game.moves.copy():
        event = {
            "type": "play",
            "player": player,
            "column": column,
            "row": row,
        }
        await websocket.send(json.dumps(event))


async def play(websocket, game, player, connected):
    try:
        async for message in websocket:
            event = json.loads(message)
            if event.get("type") != "play":
                await error(websocket, "Unsupported event type.")
                continue

            column = event["column"]

            try:
                # Play the move on the python side
                row = game.play(player, column)
            except ValueError as exc:
                # Send an "error" event if the move was illegal.
                await error(websocket, str(exc))
                continue

            # Build the play event
            payload = {
                "type": "play",
                "player": player,
                "column": column,
                "row": row,
            }

            # Send the "play event" to UI
            broadcast(connected, json.dumps(payload))

            # If the last move won
            if game.winner is not None:
                broadcast(
                    connected,
                    json.dumps(
                        {
                            "type": "win",
                            "player": game.winner,
                        }
                    ),
                )
    except (ConnectionClosedOK, ConnectionClosedError):
        pass


async def join(websocket, join_key):
    # Find the Connect Four game.
    try:
        game, connected = JOIN[join_key]
    except KeyError:
        await error(websocket, "Game not found")
        return

    # Register to receive moves from this game
    connected.add(websocket)
    try:
        # Send the first move, in case the first player already played it.
        await replay(websocket, game)
        # Receive and process moves from the second player.
        await play(websocket, game, PLAYER2, connected)
    finally:
        connected.discard(websocket)


async def watch(websocket, watch_key):
    # Find the Connect Four game.
    try:
        game, connected = WATCH[watch_key]
    except KeyError:
        await error(websocket, "Game not found")
        return

    connected.add(websocket)
    try:
        await replay(websocket, game)
        async for _ in websocket:
            # Spectators should not send messages; ignore anything that arrives.
            continue
    except (ConnectionClosedOK, ConnectionClosedError):
        pass
    finally:
        connected.discard(websocket)


async def start(websocket):
    # Initialize a Connect Four game, the set of websocket connections receiving moves from the game
    # and secret access tokens for joining or watching.
    game = Connect4()
    connected = {websocket}

    join_key = secrets.token_urlsafe(12)
    watch_key = secrets.token_urlsafe(12)
    JOIN[join_key] = game, connected
    WATCH[watch_key] = game, connected

    try:
        # Send the secret access token to the browser of the first player,
        # where it'll be used for building "join" and "watch" links.
        event = {
            "type": "init",
            "join": join_key,
            "watch": watch_key,
        }
        await websocket.send(json.dumps(event))

        await play(websocket, game, PLAYER1, connected)
    finally:
        JOIN.pop(join_key, None)
        WATCH.pop(watch_key, None)
        connected.discard(websocket)


async def handler(websocket):
    # Receive and parse the "init" event from the UI.
    try:
        message = await websocket.recv()
    except (ConnectionClosedOK, ConnectionClosedError):
        return

    event = json.loads(message)
    if event.get("type") != "init":
        await error(websocket, "Expected init event")
        return

    if "join" in event:
        # Second player joins existing game.
        await join(websocket, event["join"])
    elif "watch" in event:
        await watch(websocket, event["watch"])
    else:
        # First player starts a new game
        await start(websocket)


def _resolve_static_path(path):
    from urllib.parse import unquote

    static_map = {
        "/": ROOT_DIR / "index.html",
        "/index.html": ROOT_DIR / "index.html",
        "/main.js": ROOT_DIR / "main.js",
        "/connect4.js": ROOT_DIR / "connect4.js",
        "/connect4.css": ROOT_DIR / "connect4.css",
    }

    decoded_path = unquote(path)
    return static_map.get(decoded_path)


async def process_request(path, request_headers):
    # Let websocket upgrade requests pass through to the handler.
    if request_headers.get("Upgrade", "").lower() == "websocket":
        return None

    parsed_path = urlparse(path).path
    file_path = _resolve_static_path(parsed_path)

    if file_path is None or not file_path.exists():
        body = b"Not Found"
        return HTTPStatus.NOT_FOUND, [("Content-Type", "text/plain")], body

    mime_type = file_path.suffix
    if mime_type == ".css":
        content_type = "text/css"
    elif mime_type == ".js":
        content_type = "application/javascript"
    else:
        content_type = "text/html; charset=utf-8"

    body = file_path.read_bytes()
    headers = [
        ("Content-Type", content_type),
        ("Content-Length", str(len(body))),
        ("Cache-Control", "no-cache"),
    ]
    return HTTPStatus.OK, headers, body


async def main():
    port = int(os.environ.get("PORT", "8001"))
    try:
        async with serve(
            handler,
            host="0.0.0.0",
            port=port,
            process_request=process_request,
        ) as server:
            await server.serve_forever()
    except asyncio.CancelledError:
        print("Context cancelled, shutting down gracefully...")


if __name__ == "__main__":
    asyncio.run(main())
