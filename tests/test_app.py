import os
import sys
from pathlib import Path
import tempfile
from cs50 import SQL

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pytest
import app as quiz_app


@pytest.fixture
def client():
    # Create a temporary SQLite database so the real project database is not modified
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    # Connect the app to the temporary database
    test_db = SQL(f"sqlite:///{db_path}")
    # Enable foreign key checks
    test_db.execute("PRAGMA foreign_keys = ON")

    # Recreate the quiz.db schema in the temporary database
    # Starting with rooms table creation
    test_db.execute("""
            CREATE TABLE rooms(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_code TEXT NOT NULL UNIQUE,
                room_name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Lobby',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                rounds INTEGER NOT NULL DEFAULT 1
            )
        """)

    # Player table creation
    test_db.execute("""
            CREATE TABLE players (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id INTEGER NOT NULL REFERENCES rooms(id),
                name TEXT NOT NULL,
                join_order INTEGER NOT NULL,
                score INTEGER NOT NULL DEFAULT 0,
                reconnect_token TEXT NOT NULL UNIQUE
            )
        """)

    # Rounds table creation
    test_db.execute("""
            CREATE TABLE rounds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                round_number INTEGER NOT NULL,
                room_id INTEGER NOT NULL REFERENCES rooms(id),
                leader_id INTEGER NOT NULL REFERENCES players(id),
                question TEXT,
                phase TEXT NOT NULL DEFAULT 'Question',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

    # Answers table creation
    test_db.execute("""
            CREATE TABLE answers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                round_id INTEGER NOT NULL REFERENCES rounds(id),
                player_id INTEGER NOT NULL REFERENCES players(id),
                answer TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(round_id, player_id)
            )
        """)

    # Votes table creation
    test_db.execute("""
            CREATE TABLE votes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                round_id INTEGER NOT NULL REFERENCES rounds(id),
                voter_id INTEGER NOT NULL REFERENCES players(id),
                answer_id INTEGER NOT NULL REFERENCES answers(id),
                UNIQUE(round_id, voter_id)
            )
        """)

    # Replace the app's database connection with the temporary test database for testing
    quiz_app.db = test_db
    quiz_app.app.config["TESTING"] = True

    # Finalize and yield the Flask test client
    with quiz_app.app.test_client() as client:
        yield client

    # After the test is run, delete the temporary database
    os.unlink(db_path)


def test_index_route_returns_200(client):
    # Test that routing to index returns 200, runs correctly
    response = client.get("/")

    assert response.status_code == 200


def test_results_redirects_when_not_in_session(client):
    # Test that when trying to access a session they don't belong, error code 302 is returned meaning redirected
    response = client.get("/results")

    assert response.status_code == 302


def test_results_redirects_to_home_when_not_in_session(client):
    # Test the above but make sure they get redirected to index "/"
    response = client.get("/results")

    assert response.status_code == 302
    location = response.headers["Location"]
    # Flask may return a full url instead of just "/", for my set up both work but making it modular
    assert location == "/" or location.endswith("/")


def test_create_room_redirects_to_lobby_on_success(client):
    # Test the redirect to the lobby after a successful POST request
    response = client.post("/create-room", data={
        "room_name": "QuizRoom",
        "host_name": "Alice",
        "rounds": "2"
    })

    assert response.status_code == 302
    location = response.headers["Location"]
    assert location == "/lobby" or location.endswith("/lobby")


def test_create_room_rejects_short_room_name(client):
    # Test that app.py will reject a short room name and redirect back to create room
    response = client.post("/create-room", data={
        "room_name": "abc",
        "host_name": "Alice",
        "rounds": "2"
    })

    assert response.status_code == 302
    location = response.headers["Location"]
    assert location.endswith("/create-room")


def test_create_room_creates_room_and_host_in_database(client):
    # Submit a POST request and verify that the room and host were inserted into the database
    client.post("/create-room", data={
        "room_name": "QuizRoomDB",
        "host_name": "AliceDB",
        "rounds": "2"
    })

    rooms = quiz_app.db.execute(
        "SELECT * FROM rooms WHERE room_name = ?",
        "QuizRoomDB"
    )
    players = quiz_app.db.execute(
        "SELECT * FROM players WHERE name = ?",
        "AliceDB"
    )

    assert len(rooms) == 1
    assert len(players) == 1
    # The temporary test database should contain exactly one matching row
    assert players[-1]["join_order"] == 0


def test_create_room_does_not_execute_sql_from_room_name(client):
    # Malicious input should be stored as data, not executed as SQL
    response = client.post("/create-room", data={
        "room_name": "Quiz'); DROP TABLE rooms; --",
        "host_name": "Alice",
        "rounds": "2"
    })

    assert response.status_code == 302

    rooms = quiz_app.db.execute("SELECT * FROM rooms")
    assert len(rooms) == 1


def test_host_leaving_lobby_promotes_next_player_to_host(client):
    # Create a room and host player through the normal route.
    client.post("/create-room", data={
        "room_name": "QuizRoom",
        "host_name": "Alice",
        "rounds": "1"
    })

    room = quiz_app.db.execute("SELECT * FROM rooms")[0]
    host = quiz_app.db.execute(
        "SELECT * FROM players WHERE room_id = ? AND join_order = 0",
        room["id"]
    )[0]

    # Add two more players to the lobby.
    bob_id = quiz_app.db.execute(
        "INSERT INTO players (room_id, name, join_order, reconnect_token) VALUES (?, ?, ?, ?)",
        room["id"], "Bob", 1, "token_bob"
    )
    cara_id = quiz_app.db.execute(
        "INSERT INTO players (room_id, name, join_order, reconnect_token) VALUES (?, ?, ?, ?)",
        room["id"], "Cara", 2, "token_cara"
    )

    # Make the test client the host, then leave the lobby.
    with client.session_transaction() as sess:
        sess["room_id"] = room["id"]
        sess["player_id"] = host["id"]

    response = client.get("/leave")

    players = quiz_app.db.execute(
        "SELECT id, name, join_order FROM players WHERE room_id = ? ORDER BY join_order",
        room["id"]
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")
    assert [player["id"] for player in players] == [bob_id, cara_id]
    assert [player["join_order"] for player in players] == [0, 1]


def test_last_vote_moves_round_to_results_and_updates_score(client):
    # Create a room and host player through the normal route.
    client.post("/create-room", data={
        "room_name": "QuizRoom",
        "host_name": "Alice",
        "rounds": "1"
    })

    room = quiz_app.db.execute("SELECT * FROM rooms")[0]
    host = quiz_app.db.execute("SELECT * FROM players WHERE room_id = ?", room["id"])[0]

    # Add three more players so the round has enough voters.
    bob_id = quiz_app.db.execute(
        "INSERT INTO players (room_id, name, join_order, reconnect_token) VALUES (?, ?, ?, ?)",
        room["id"], "Bob", 1, "token_bob"
    )
    cara_id = quiz_app.db.execute(
        "INSERT INTO players (room_id, name, join_order, reconnect_token) VALUES (?, ?, ?, ?)",
        room["id"], "Cara", 2, "token_cara"
    )
    dave_id = quiz_app.db.execute(
        "INSERT INTO players (room_id, name, join_order, reconnect_token) VALUES (?, ?, ?, ?)",
        room["id"], "Dave", 3, "token_dave"
    )

    # Simulate an active voting round led by the host.
    quiz_app.db.execute("UPDATE rooms SET status = ? WHERE id = ?",
                        quiz_app.STATUS_IN_SESSION, room["id"])
    round_id = quiz_app.db.execute(
        "INSERT INTO rounds (room_id, leader_id, round_number, question, phase) VALUES (?, ?, ?, ?, ?)",
        room["id"], host["id"], 1, "Best answer?", quiz_app.PHASE_VOTING
    )

    # Insert answers for the non-leader players.
    bob_answer = quiz_app.db.execute(
        "INSERT INTO answers (round_id, player_id, answer) VALUES (?, ?, ?)",
        round_id, bob_id, "Bob answer"
    )
    cara_answer = quiz_app.db.execute(
        "INSERT INTO answers (round_id, player_id, answer) VALUES (?, ?, ?)",
        round_id, cara_id, "Cara answer"
    )
    dave_answer = quiz_app.db.execute(
        "INSERT INTO answers (round_id, player_id, answer) VALUES (?, ?, ?)",
        round_id, dave_id, "Dave answer"
    )

    # Add the first three votes so only one vote remains.
    quiz_app.db.execute(
        "INSERT INTO votes (round_id, voter_id, answer_id) VALUES (?, ?, ?)",
        round_id, host["id"], bob_answer
    )
    quiz_app.db.execute(
        "INSERT INTO votes (round_id, voter_id, answer_id) VALUES (?, ?, ?)",
        round_id, cara_id, bob_answer
    )
    quiz_app.db.execute(
        "INSERT INTO votes (round_id, voter_id, answer_id) VALUES (?, ?, ?)",
        round_id, dave_id, cara_answer
    )

    # Set the final voter session and submit the last vote.
    with client.session_transaction() as sess:
        sess["room_id"] = room["id"]
        sess["player_id"] = bob_id

    response = client.post("/submit-vote", data={"answer_id": cara_answer})

    # Verify that the round moves to Results after the final vote.
    current_round = quiz_app.db.execute("SELECT * FROM rounds WHERE id = ?", round_id)[0]
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/game")
    assert current_round["phase"] == quiz_app.PHASE_RESULTS

    # Verify that Bob receives a point for having the highest vote total.
    bob = quiz_app.db.execute("SELECT * FROM players WHERE id = ?", bob_id)[0]
    assert bob["score"] == 1


def test_next_round_creates_new_round_with_next_leader(client):
    # Create a room and host player through the normal route.
    client.post("/create-room", data={
        "room_name": "QuizRoom",
        "host_name": "Alice",
        "rounds": "2"
    })

    room = quiz_app.db.execute("SELECT * FROM rooms")[0]
    host = quiz_app.db.execute("SELECT * FROM players WHERE room_id = ?", room["id"])[0]

    # Add more players so leader rotation can be tested.
    bob_id = quiz_app.db.execute(
        "INSERT INTO players (room_id, name, join_order, reconnect_token) VALUES (?, ?, ?, ?)",
        room["id"], "Bob", 1, "token_bob"
    )
    quiz_app.db.execute(
        "INSERT INTO players (room_id, name, join_order, reconnect_token) VALUES (?, ?, ?, ?)",
        room["id"], "Cara", 2, "token_cara"
    )
    quiz_app.db.execute(
        "INSERT INTO players (room_id, name, join_order, reconnect_token) VALUES (?, ?, ?, ?)",
        room["id"], "Dave", 3, "token_dave"
    )

    # Simulate a finished round led by the host.
    quiz_app.db.execute("UPDATE rooms SET status = ? WHERE id = ?",
                        quiz_app.STATUS_IN_SESSION, room["id"])
    round_id = quiz_app.db.execute(
        "INSERT INTO rounds (room_id, leader_id, round_number, question, phase) VALUES (?, ?, ?, ?, ?)",
        room["id"], host["id"], 1, "Test question", quiz_app.PHASE_RESULTS
    )

    # Set the leader session and submit the next-round request.
    with client.session_transaction() as sess:
        sess["room_id"] = room["id"]
        sess["player_id"] = host["id"]

    response = client.post("/next-round")

    # Verify that a new round is created with the next player in join order.
    rounds = quiz_app.db.execute(
        "SELECT * FROM rounds WHERE room_id = ? ORDER BY round_number",
        room["id"]
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/game")
    assert len(rounds) == 2
    assert rounds[1]["round_number"] == 2
    assert rounds[1]["leader_id"] == bob_id


def test_leave_during_active_game_cancels_room(client):
    # Create a room and host player through the normal route.
    client.post("/create-room", data={
        "room_name": "QuizRoom",
        "host_name": "Alice",
        "rounds": "1"
    })

    room = quiz_app.db.execute("SELECT * FROM rooms")[0]

    # Simulate a game already in session.
    quiz_app.db.execute(
        "UPDATE rooms SET status = ? WHERE id = ?",
        quiz_app.STATUS_IN_SESSION, room["id"]
    )

    # Leave the room during the active session.
    response = client.get("/leave")

    # Verify that the room is marked as Cancelled.
    updated_room = quiz_app.db.execute("SELECT * FROM rooms WHERE id = ?", room["id"])[0]

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")
    assert updated_room["status"] == quiz_app.STATUS_CANCELLED


def test_start_game_twice_creates_only_one_round(client):
    # Create a room and host player through the normal route.
    client.post("/create-room", data={
        "room_name": "QuizRoom",
        "host_name": "Alice",
        "rounds": "1"
    })

    room = quiz_app.db.execute("SELECT * FROM rooms")[0]

    # Add enough players for the host to start the game.
    for i, name in enumerate(["Bob", "Cara", "Dave"], start=1):
        quiz_app.db.execute(
            "INSERT INTO players (room_id, name, join_order, reconnect_token) VALUES (?, ?, ?, ?)",
            room["id"], name, i, f"token_{i}"
        )

    # Submit the start-game request twice to simulate a repeated POST.
    first_response = client.post("/start-game")
    second_response = client.post("/start-game")

    # Verify that only one first round exists in the database.
    rounds = quiz_app.db.execute("SELECT * FROM rounds WHERE room_id = ?", room["id"])

    assert first_response.status_code == 302
    assert second_response.status_code == 302
    assert len(rounds) == 1
    assert rounds[0]["round_number"] == 1


def test_join_room_redirects_if_player_already_in_room(client):
    # Create a room so the test client already has an active room session.
    client.post("/create-room", data={
        "room_name": "QuizRoom",
        "host_name": "Alice",
        "rounds": "1"
    })

    # Try to join another room while already assigned to the first one.
    response = client.post("/join-room", data={
        "room_code": "ABC123",
        "player_name": "Bob"
    })

    # Verify that the player is redirected back to the existing lobby.
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/lobby")

    # Verify that no second player was created from the blocked join attempt.
    players = quiz_app.db.execute("SELECT * FROM players WHERE name = ?", "Bob")
    assert len(players) == 0
