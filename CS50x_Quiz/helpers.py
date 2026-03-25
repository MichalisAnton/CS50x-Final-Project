from flask import request, session, make_response, redirect
from string import ascii_uppercase, digits
from secrets import choice, token_urlsafe


def generate_room_code():
    # Alternative one-line version: "".join(choice(ascii_uppercase + digits) for _ in range(6))
    code = ""
    for _ in range(6):
        char = choice(ascii_uppercase + digits)
        code += char
    return code


def generate_reconnect_token():
    # Generate a random token for securely restoring a player's session.
    return token_urlsafe(32)


def generate_unique_reconnect_token(db):
    # Keep generating tokens until one is not already assigned to a player.
    reconnect_token = generate_reconnect_token()
    while db.execute("SELECT id FROM players WHERE reconnect_token = ?", reconnect_token):
        reconnect_token = generate_reconnect_token()
    return reconnect_token


def restore_session(db):
    # First try restoring IDs from the Flask session.
    # Use "get" because it is safer when keys may be missing.
    player_id = session.get("player_id")
    room_id = session.get("room_id")

    # If the session is missing, try to restore from the reconnect_token cookie.
    if player_id is None or room_id is None:
        reconnect_token = request.cookies.get("reconnect_token")
        if reconnect_token is None:
            return False

        player = db.execute(
            "SELECT id, room_id FROM players WHERE reconnect_token = ?", reconnect_token)
        if not player:
            session.clear()
            return False

        player_id = player[0]["id"]
        room_id = player[0]["room_id"]

    # Check that the room and player actually exist in the database.
    room = db.execute("SELECT id FROM rooms WHERE id = ?", room_id)
    player = db.execute("SELECT id, room_id FROM players WHERE id = ?", player_id)

    # If the player or room is missing, clear the session.
    if not room or not player:
        session.clear()
        return False

    # Make sure the player belongs to the room.
    if player[0]["room_id"] != room_id:
        session.clear()
        return False

    # Restore the validated values back into the Flask session.
    session["player_id"] = player_id
    session["room_id"] = room_id
    return True


def get_player(db, player_id):
    # Return a single player row for the given player_id.
    rows = db.execute("SELECT * FROM players WHERE id = ?", player_id)
    if not rows:
        return None
    return rows[0]


def get_room(db, room_id):
    # Return a single room row.
    rows = db.execute("SELECT * FROM rooms WHERE id = ?", room_id)
    if not rows:
        return None
    return rows[0]


def get_current_round(db, room_id):
    # Return the latest round for a room.
    rows = db.execute(
        "SELECT * FROM rounds WHERE room_id = ? ORDER BY round_number DESC LIMIT 1", room_id)
    if not rows:
        return None
    return rows[0]


def generate_unique_room_code(db):
    # Keep generating codes until one is not already used by another room.
    room_code = generate_room_code()
    while db.execute("SELECT id FROM rooms WHERE room_code = ?", room_code):
        room_code = generate_room_code()
    return room_code


def get_room_by_code(db, room_code):
    # Return a single room given its room code.
    rows = db.execute("SELECT * FROM rooms WHERE room_code = ?", room_code)
    if not rows:
        return None
    return rows[0]


def clear_session_and_cookies():
    # Clear the session and cookies.
    session.clear()
    resp = make_response(redirect("/"))
    resp.delete_cookie("reconnect_token")

    return resp
