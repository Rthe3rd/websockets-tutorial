import asyncio
import json
import secrets
import os
import http
from pathlib import Path

from websockets.asyncio.server import serve
from websockets import broadcast as ws_broadcast
from websockets.http import Headers
from websockets.server import Response
from connect4 import PLAYER1, PLAYER2, Connect4

import logging

JOIN = {}
WATCH = {}

async def error(websocket, message):
    event = {
        "type": "error",
        "message": message,
    }
    await websocket.send(json.dumps(event))

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
        connected.remove(websocket)

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

async def watch(websocket, watch_key):
    # Find the Connect Four game.
    try:
        game, connected = JOIN[watch_key]
    except KeyError:
        await error(websocket, "Game not found")
        return

    # Register to receive moves from this game
    connected.add(websocket)
    try:
        # Get game moves that have already happened
        await replay(websocket, game)
        # Wait until the websocket is closed
        await websocket.wait_closed()

    finally:
        connected.remove(websocket)

async def start(websocket):
    # Initialize a Connect Four game, the set of websocket connections receiving moves from the game
    # and secret acces token or identifier
    game = Connect4()
    connected = {websocket}

    join_key = secrets.token_urlsafe(12)
    JOIN[join_key] = game, connected

    watch_key = secrets.token_urlsafe(12)
    JOIN[watch_key] = game, connected

    try:
        # Send the secret access token to the browser of the first player,
        # where it'll be used for building a "join" link.
        event = {
            "type": "init",
            "join": join_key,
            "watch": watch_key,
        }
        await websocket.send(json.dumps(event))

        await play(websocket, game, PLAYER1, connected)

    finally:
        del JOIN[join_key]
        del WATCH[watch_key]

async def play(websocket, game, player, connected):
    async for message in websocket:
        # Parse play event from UI
        event = json.loads(message)
        assert event['type'] == 'play'
        column = event['column']

        try:
            # Play the move on the python side
            row = game.play(player, column)
        except ValueError as e:
            # Send an "error" event if the move was illegal.
            await error(websocket, str(e))  
            continue

        # Set your event fields
        event['type'] = 'play'
        event['player'] = player
        event['row'] = row

        # Send the "play event" to UI using websockets broadcast
        ws_broadcast(connected, json.dumps(event))

        # If the last move won
        if game.winner is not None:
            event = {
                "type": "win",
                "player": game.winner,
            }
            ws_broadcast(connected, json.dumps(event))


async def handler(websocket):
    # Receive and parse the "init" event from the UI.
    message = await websocket.recv()
    event = json.loads(message)
    assert event["type"] == "init"

    if "join" in event:
        # second player joins existing game.
        await join(websocket, event['join'])
    elif "watch" in event:
        await watch(websocket, event['watch'])
    else:
        # First player starts a new game
        await start(websocket)


def process_request(connection, request):
    """Handle HTTP requests for static files"""
    base_dir = Path(__file__).parent
    
    # Extract path from request object
    path = request.path
    
    # Serve index.html for root path
    if path == '/' or path == '':
        html_path = base_dir / "index.html"
        if html_path.exists():
            content = html_path.read_bytes()
            return Response(
                status_code=200,
                reason_phrase="OK",
                headers=Headers([("Content-Type", "text/html")]),
                body=content
            )
        else:
            # Return 404 if index.html doesn't exist
            return Response(
                status_code=404,
                reason_phrase="Not Found",
                headers=Headers([("Content-Type", "text/plain")]),
                body=b"Not Found"
            )
    
    # Remove leading slash for file lookup
    filename = path.lstrip('/')
    
    # Only serve .js and .css files for security
    if not (filename.endswith('.js') or filename.endswith('.css')):
        # Return 404 for non-JS/CSS files
        return Response(
            status_code=404,
            reason_phrase="Not Found",
            headers=Headers([("Content-Type", "text/plain")]),
            body=b"Not Found"
        )
    
    file_path = base_dir / filename
    
    if not file_path.exists() or not file_path.is_file():
        # Return 404 if file doesn't exist
        return Response(
            status_code=404,
            reason_phrase="Not Found",
            headers=Headers([("Content-Type", "text/plain")]),
            body=b"Not Found"
        )
    
    # Set appropriate content type
    content_type = "text/javascript" if filename.endswith(".js") else "text/css"
    
    return Response(
        status_code=200,
        reason_phrase="OK",
        headers=Headers([("Content-Type", content_type)]),
        body=file_path.read_bytes()
    )


async def main():
    # Get port from environment variable (Heroku sets this)
    port = int(os.environ.get('PORT', 8001))
    
    # Suppress connection errors from health checks
    logging.getLogger("websockets.server").setLevel(logging.WARNING)
    
    try:
        async with serve(
            handler, 
            "0.0.0.0", 
            port, 
            process_request=process_request,
            # Suppress errors from connections that close immediately
            logger=logging.getLogger("websockets")
        ) as server:
            print(f'Server started on port {port}')
            await server.serve_forever()
    except asyncio.CancelledError:
        print('Context cancelled, shutting down gracefully...')

if __name__ == "__main__":
    asyncio.run(main())
