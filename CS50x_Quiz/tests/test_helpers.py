from helpers import (generate_room_code, generate_unique_room_code,
                     generate_unique_reconnect_token, get_room)
from string import ascii_uppercase, digits
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class FakeDB:
    # Fake object that responds with an empty list to db.execute
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def execute(self, query, *params):
        self.calls.append((query, params))
        return self.responses.pop(0)


def test_generate_room_code_has_valid_format():
    # Test that the function is 6 digits and has digits and ascii uppercase values
    code = generate_room_code()
    allowed = set(ascii_uppercase + digits)

    assert len(code) == 6
    assert all(char in allowed for char in code)


def test_generate_unique_room_code_returns_first_code_if_unused(monkeypatch):
    # Generate a unique room code and check its uniqueness in the database
    monkeypatch.setattr("helpers.generate_room_code", lambda: "ABC123")
    db = FakeDB([[]])

    code = generate_unique_room_code(db)

    assert code == "ABC123"
    assert len(db.calls) == 1


def test_generate_unique_room_code_retries_if_first_code_is_taken(monkeypatch):
    # Test that the function retries when the first generated code already exists
    codes = iter(["ABC123", "XYZ999"])
    monkeypatch.setattr("helpers.generate_room_code", lambda: next(codes))

    db = FakeDB([
        [{"id": 1}],
        []
    ])

    code = generate_unique_room_code(db)

    assert code == "XYZ999"
    assert len(db.calls) == 2


def test_generate_unique_reconnect_token_returns_first_token_if_unused(monkeypatch):
    # Generate a unique reconnect token and check the database if it's free
    monkeypatch.setattr("helpers.generate_reconnect_token", lambda: "token_1")
    db = FakeDB([[]])

    token = generate_unique_reconnect_token(db)

    assert token == "token_1"
    assert len(db.calls) == 1


def test_generate_unique_reconnect_token_retries_if_first_token_is_taken(monkeypatch):
    # If token is already assigned, then reassign a new one
    tokens = iter(["token_1", "token_2"])
    monkeypatch.setattr("helpers.generate_reconnect_token", lambda: next(tokens))

    db = FakeDB([
        [{"id": 1}],
        []
    ])

    token = generate_unique_reconnect_token(db)

    assert token == "token_2"
    assert len(db.calls) == 2


def test_get_room_returns_room_when_found():
    # Create fake DB data and check that get_player returns the matching player
    db = FakeDB([[{"id": 1, "room_name": "Quiz Room"}]])

    room = get_room(db, 1)

    assert room == {"id": 1, "room_name": "Quiz Room"}


def test_get_room_returns_none_when_missing():
    # If not in database, room returns none
    db = FakeDB([[]])

    room = get_room(db, 999)

    assert room is None
