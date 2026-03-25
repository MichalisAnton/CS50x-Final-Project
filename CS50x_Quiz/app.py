import os
from cs50 import SQL
from flask import Flask, flash, redirect, render_template, request, session, jsonify, make_response
from flask_session import Session
from helpers import restore_session, get_room, get_current_round, generate_unique_room_code, get_room_by_code, get_player, clear_session_and_cookies, generate_unique_reconnect_token
from secrets import token_hex

# Configure application
app = Flask(__name__)

# Access quiz database and generate room codes
db = SQL("sqlite:///quiz.db")
db.execute("PRAGMA foreign_keys = ON")

# Use an environment secret key when available; otherwise, generate one locally
secret = os.environ.get("SECRET_KEY")
if not secret:
    secret = token_hex(32)
# Configure server-side sessions for the Flask app.
app.config["SECRET_KEY"] = secret
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Useful global constants, game-state phases, and room statuses
STATUS_LOBBY = "Lobby"
STATUS_IN_SESSION = "In Session"
STATUS_FINISHED = "Finished"
STATUS_CANCELLED = "Cancelled"

PHASE_QUESTION = "Question"
PHASE_ANSWERING = "Answering"
PHASE_VOTING = "Voting"
PHASE_SCORING = "Scoring"  # Temporary phase used to prevent duplicate end-of-round scoring.
PHASE_RESULTS = "Results"
PHASE_ADVANCING = "Advancing"


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/rules")
def rules():
    # Rules page
    return render_template("rules.html")


@app.route("/rooms")
def rooms():
    return render_template("rooms.html")


@app.route("/create-room", methods=["GET", "POST"])
# Room creation page
def create_room():
    if restore_session(db):
        return redirect("/lobby")
    if request.method == "POST":
        room_name = request.form.get("room_name", "").strip()
        host_name = request.form.get("host_name", "").strip()
        round_number = request.form.get("rounds")
        #  Cast and validate the rounds input
        try:
            round_number = int(round_number)
        except (TypeError, ValueError):
            flash("Please choose between 1 and 4 rounds")
            return redirect(request.url)
        # Validate user input
        if not room_name or not host_name:
            flash("Please fill both fields")
            return redirect(request.url)
        if round_number not in range(1, 5):
            flash("Please choose between 1 and 4 rounds")
            return redirect(request.url)
        # Server side validation to protect database, html validation also applied in create_room.html
        if len(room_name) < 4:
            flash("Please choose a room name with at least 4 characters")
            return redirect(request.url)
        if len(host_name) < 3:
            flash("Please choose a host name with at least than 3 characters")
            return redirect(request.url)

        # Generate a new room code
        # In helpers, there is a While loop that returns True in the extreme case of duplicates
        room_code = generate_unique_room_code(db)

        # Generate token
        reconnect_token = generate_unique_reconnect_token(db)

        # Save the room and the host_player and unique  into the database
        room_id = db.execute(
            "INSERT INTO rooms (room_code, room_name, rounds) VALUES (?, ?, ?)", room_code, room_name, round_number)
        player_id = db.execute(
            "INSERT INTO players (room_id, name, join_order, reconnect_token) VALUES (?, ?, 0, ?)", room_id, host_name, reconnect_token)

        # Save and start sessions for room and players
        session["player_id"] = player_id
        session["room_id"] = room_id

        resp = make_response(redirect("/lobby"))
        resp.set_cookie("reconnect_token", reconnect_token,
                        max_age=60*60*24, httponly=True, samesite="Lax")
        return resp

    return render_template("create_room.html")


@app.route("/join-room", methods=["GET", "POST"])
# Join room page as long as they have a code
def join_room():
    # Prevent players with an active room session from joining a second room
    if restore_session(db):
        return redirect("/lobby")
    if request.method == "POST":
        room_code = request.form.get("room_code", "").strip().upper()
        player_name = request.form.get("player_name", "").strip()
        # Validate user input
        if not room_code or not player_name:
            flash("Please fill both fields")
            return redirect(request.url)
        # Server side validation to protect database, html validation also applied in create_room.html
        if len(room_code) != 6:
            flash("The room code must be 6 characters")
            return redirect(request.url)
        if len(player_name) < 3:
            flash("Please enter a name longer than 3 characters")
            return redirect(request.url)

        # Check room exists and if it's still in lobby
        room = get_room_by_code(db, room_code)
        if not room:
            flash("Room not found")
            return render_template("join_room.html")
        if room["status"] != STATUS_LOBBY:
            flash("This room is already in session, so you cannot join now")
            return render_template("join_room.html")

        # Get the join_order variable
        room_id = room["id"]
        player_count = db.execute(
            "SELECT COUNT(*) AS count FROM players WHERE room_id = ?", room_id)
        join_order = player_count[0]["count"]

        # Generate a reconnect token
        reconnect_token = generate_unique_reconnect_token(db)

        # Save and start session and token for joining player
        player_id = db.execute(
            "INSERT INTO players (room_id, name, join_order, reconnect_token) VALUES (?, ?, ?, ?)", room_id, player_name, join_order, reconnect_token)

        session["player_id"] = player_id
        session["room_id"] = room_id

        resp = make_response(redirect("/lobby"))
        resp.set_cookie("reconnect_token", reconnect_token,
                        max_age=60*60*24, httponly=True, samesite="Lax")
        return resp

    return render_template("join_room.html")


@app.route("/lobby")
# Lobby page until status changes and get into the game session
def lobby():
    # Check for cookies of existing players GUARD
    if not restore_session(db):
        flash("You are not in a room")
        return redirect("/rooms")

    # Query the database for the room
    room = get_room(db, session["room_id"])
    # Query the database for the player
    player = get_player(db, session["player_id"])

    if not room or not player:
        flash("Room or player could not be found")
        return redirect("/rooms")
    if room["status"] != STATUS_LOBBY:
        return redirect("/game")

    # Identify who is the host of the group by their join order
    host = db.execute(
        "SELECT name FROM players WHERE room_id = ? AND join_order = 0", room["id"])[0]

    is_host = player["join_order"] == 0

    return render_template("lobby.html", room=room, player=player, is_host=is_host, host=host)


@app.route("/lobby-state")
def lobby_state():
    # Make sure the room exists in session
    if not restore_session(db):
        return jsonify({"error": "no_room"}), 400

    # Return all players and the current room status as JSON.
    players = db.execute("SELECT * FROM players WHERE room_id = ?", session["room_id"])
    room = get_room(db, session["room_id"])
    return jsonify({
        "status": room["status"],
        "players": players
    })


@app.route("/start-game", methods=["POST"])
def start_game():
    # Check for cookies of existing players after game start GUARD
    if not restore_session(db):
        flash("You are not authorized to access that room")
        return redirect("/rooms")

    # Get all the players with this room_id, ordering them by join_order
    players = db.execute(
        "SELECT * FROM players WHERE room_id = ? ORDER BY join_order", session["room_id"])

    # First position is always the host and only host can request to start the game
    if players[0]["id"] != session["player_id"]:
        flash("Only the host can start the session")
        return redirect("/lobby")
    if len(players) < 4:
        flash("Too soon! You need at least 4 players to play the quiz")
        return redirect("/lobby")

    # Change the room status to In Session only if the room is still in the Lobby.
    updated = db.execute("UPDATE rooms SET status = ? WHERE id = ? AND status = ?",
                         STATUS_IN_SESSION, session["room_id"], STATUS_LOBBY)

    # If the query did not update anything because another POST already changed the room to In Session, redirect safely.
    if updated == 0:
        return redirect("/game")

    db.execute("INSERT INTO rounds (room_id, leader_id, round_number) VALUES (?, ?, ?)",
               session["room_id"], session["player_id"], 1)
    return redirect("/game")


@app.route("/game")
def game():
    # Validation checks for users in the room
    if not restore_session(db):
        flash("You need to join a room first")
        return redirect("/lobby")
    # Query for the room that is starting the game
    room = get_room(db, session["room_id"])
    # Checks the state of the room
    if room["status"] == STATUS_FINISHED:
        return redirect("/results")
    if room["status"] == STATUS_LOBBY:
        flash("The host has yet to start the quiz, wait like everyone else")
        return redirect("/lobby")
    if room["status"] == STATUS_CANCELLED:
        flash("A player left, so the session was cancelled.")
        return redirect("/leave")

    # Pass the key session and database values to game.html
    current_round = get_current_round(db, session["room_id"])
    is_leader = current_round["leader_id"] == session["player_id"]
    players = db.execute(
        "SELECT * FROM players WHERE room_id = ? ORDER BY join_order", session["room_id"])
    answers = db.execute(
        "SELECT * FROM answers WHERE round_id = ?", current_round["id"])
    answer_count = len(answers)
    has_answered = bool(db.execute(
        "SELECT id FROM answers WHERE round_id = ? AND player_id = ?", current_round["id"], session["player_id"]))
    has_voted = bool(db.execute(
        "SELECT id FROM votes WHERE round_id = ? AND voter_id = ?", current_round["id"], session["player_id"]))
    vote_count = len(db.execute("SELECT id FROM votes WHERE round_id = ?", current_round["id"]))
    results = []
    vote_answers = answers
    if current_round["phase"] == PHASE_VOTING:
        # Keep the backend self-vote guard, but also hide the current player's
        # own answer so the UI never offers an invalid choice.
        vote_answers = [
            answer for answer in answers
            if answer["player_id"] != session["player_id"]
        ]
    if current_round["phase"] == PHASE_RESULTS:
        # LEFT JOIN keeps answers that received no votes in the results.
        # GROUP BY ensures one row per submitted answer with the correct vote total.
        results = db.execute("""
            SELECT answers.player_id, answers.answer, COUNT(votes.id) AS vote_count, players.name
            FROM answers
            LEFT JOIN votes ON votes.answer_id = answers.id
            JOIN players ON players.id = answers.player_id
            WHERE answers.round_id = ?
            GROUP BY answers.id, answers.player_id, answers.answer, players.name
            ORDER BY vote_count DESC
        """, current_round["id"])
    return render_template("game.html", room=room, round=current_round, is_leader=is_leader,
                           players=players, answer_count=answer_count, has_answered=has_answered,
                           answers=answers, vote_answers=vote_answers, has_voted=has_voted, results=results, vote_count=vote_count)


@app.route("/submit-question", methods=["POST"])
# Once question has been sent to players, save their answers in the database
def submit_question():
    # Validation checks
    if not restore_session(db):
        flash("You need to be in a room to do that")
        return redirect("/lobby")

    # Get all the information from this round
    current_round = get_current_round(db, session["room_id"])

    # Make sure submission happens only from the leader of this round
    if current_round["leader_id"] != session["player_id"]:
        flash("I'm sorry but only the leader of this round can ask the question, you'll get your turn")
        return redirect("/game")

    # Don't accept questions if the status is not Question
    if current_round["phase"] != PHASE_QUESTION:
        flash("We are not asking you a question at the moment")
        return redirect("/game")

    # Receive the question that was asked
    question = request.form.get("leader_question", "").strip()
    # Make sure question is not empty
    if not question:
        flash("Please enter a question")
        return redirect("/game")

    # Update the question and phase only if the round is still in the Question phase
    # This guards against timing windows from simultaneous question POSTs
    updated = db.execute("UPDATE rounds SET question = ?, phase = ? WHERE id = ? AND phase = ?",
                         question, PHASE_ANSWERING, current_round["id"], PHASE_QUESTION)

    if updated == 0:
        return redirect("/game")

    return redirect("/game")


# Polling game to sync all clients
@app.route("/game-state")
def game_state():
    # Validation checks
    if not restore_session(db):
        return jsonify({"error": "no_session"}), 400

    # Query the database about what's in the database in the current round
    current_round = get_current_round(db, session["room_id"])
    # Useful QOL and frontend variables
    answer_count = db.execute(
        "SELECT COUNT(*) AS count FROM answers WHERE round_id = ?", current_round["id"])[0]["count"]
    vote_count = db.execute(
        "SELECT COUNT(*) AS count FROM votes WHERE round_id = ?", current_round["id"])[0]["count"]
    room = get_room(db, session["room_id"])

    # Return the data client side to handle what shows on the page,
    return jsonify({
        "phase": current_round["phase"],
        "question": current_round["question"],
        "round_number": current_round["round_number"],
        "leader_id": current_round["leader_id"],
        "answer_count": answer_count,
        "vote_count": vote_count,
        "room_status": room["status"]
    })


@app.route("/submit-answer", methods=["POST"])
def submit_answer():
    # Validation checks
    if not restore_session(db):
        flash("You must be in a room to submit an answer")
        return redirect("/lobby")

    # Make sure the session is in 'Answering' phase
    current_round = get_current_round(db, session["room_id"])
    if current_round["phase"] != PHASE_ANSWERING:
        flash("It is not time to submit an answer yet")
        return redirect("/game")

    # Guard to make sure the leader who asked the question cannot submit an answer
    if current_round["leader_id"] == session["player_id"]:
        flash("You asked the question, you don't get to answer it too!")
        return redirect("/game")

    # Guard against double submission of answers
    already_answered = db.execute(
        "SELECT id FROM answers WHERE round_id = ? AND player_id = ?", current_round["id"], session["player_id"])
    if already_answered:
        return redirect("/game")

    # Get the answer from the clients
    answer = request.form.get("answer", "").strip()
    if not answer:
        return redirect("/game")
    # Try to save the answer, but redirect safely if another simultaneous POST already insterted it
    try:
        db.execute(
            "INSERT INTO answers (round_id, player_id, answer) VALUES (?, ?, ?)", current_round["id"], session["player_id"], answer)
    except RuntimeError:
        return redirect("/game")

    # Check that all the players have answered before moving to the next phase
    answer_count = db.execute(
        "SELECT COUNT(*) AS count FROM answers WHERE round_id = ?", current_round["id"])[0]["count"]
    player_count = db.execute(
        "SELECT COUNT(*) AS count FROM players WHERE room_id = ?", session["room_id"])[0]["count"]

    # Checks that everyone but the leader has answered
    # Move to Voting only if the round is still in the Answering phase.
    if answer_count == player_count - 1:
        db.execute("UPDATE rounds SET phase = ? WHERE id = ? AND phase = ?",
                   PHASE_VOTING, current_round["id"], PHASE_ANSWERING)
    return redirect("/game")


@app.route("/submit-vote", methods=["POST"])
def submit_vote():
    # Validation checks
    if not restore_session(db):
        flash("You must be in a room to vote")
        return redirect("/lobby")

    # Make sure the game is in 'Voting' phase
    current_round = get_current_round(db, session["room_id"])
    if current_round["phase"] != PHASE_VOTING:
        flash("Your vote matters... but polls are not open yet")
        return redirect("/game")

    # Check that a player cannot vote again on the same round
    already_voted = db.execute(
        "SELECT id FROM votes WHERE round_id = ? AND voter_id = ?", current_round["id"], session["player_id"])
    if already_voted:
        return redirect("/game")

    answer_id = request.form.get("answer_id")
    if not answer_id:
        return redirect("/game")

    # Guard against malicious string input into database
    try:
        answer_id = int(answer_id)
    except (ValueError, TypeError):
        return redirect("/game")

    # Don't accept votes for rounds that are not the current
    valid_answer = db.execute(
        "SELECT id, player_id FROM answers WHERE id = ? AND round_id = ?", answer_id, current_round["id"])
    if not valid_answer:
        flash("Invalid vote.")
        return redirect("/game")

    # Guard from voting for own answer
    if valid_answer[0]["player_id"] == session["player_id"]:
        flash("You can't vote for yourself!")
        return redirect("/game")

    # Try to save the vote, but redirect safely if another simultaneous POST already inserted it
    try:
        db.execute("INSERT INTO votes(round_id, voter_id, answer_id) VALUES(?, ?, ?)",
                   current_round["id"], session["player_id"], answer_id)
    except RuntimeError:
        return redirect("/game")

    # Check that all the players have voted before moving to the next phase
    vote_count = db.execute(
        "SELECT COUNT(*) AS count FROM votes WHERE round_id = ?", current_round["id"])[0]["count"]
    player_count = db.execute(
        "SELECT COUNT(*) AS count FROM players WHERE room_id = ?", session["room_id"])[0]["count"]

    if vote_count == player_count:
        # Claim the scoring step so only one POST can award points
        claimed = db.execute("UPDATE rounds SET phase = ? WHERE id = ? AND phase = ?",
                             PHASE_SCORING, current_round["id"], PHASE_VOTING)

        # If another POST already moved the round into scoring, redirect safely
        if claimed == 0:
            return redirect("/game")

        # Join the votes and answers tables for players in the current round, grouped by player_id.
        results = db.execute("""
            SELECT answers.player_id, COUNT(votes.id) AS vote_count
            FROM answers
            JOIN votes ON votes.answer_id = answers.id
            WHERE answers.round_id = ?
            GROUP BY answers.player_id
        """, current_round["id"])

        # Loop through each result and find the highest possible vote tally in the round
        max_votes = 0
        for r in results:
            if r["vote_count"] > max_votes:
                max_votes = r["vote_count"]

        for r in results:
            if r["vote_count"] == max_votes:
                db.execute("UPDATE players SET score = score + 1 WHERE id = ?", r["player_id"])

        db.execute("UPDATE rounds SET phase = ? WHERE id = ?", PHASE_RESULTS, current_round["id"])

    return redirect("/game")


@app.route("/next-round", methods=["POST"])
def next_round():
    # Validation checks
    if not restore_session(db):
        flash("Please wait for the current round to finish")
        return redirect("/lobby")

    # Get the current round data from database
    current_round = get_current_round(db, session["room_id"])
    if current_round["leader_id"] != session["player_id"]:
        flash("Only the leader can start the next round")
        return redirect("/game")
    if current_round["phase"] != PHASE_RESULTS:
        flash("You might be the leader but can't do anything you want! Round has yet to finish")
        return redirect("/game")

    # Claim the round progression so only one POST can advance the game.
    claimed = db.execute("UPDATE rounds SET phase = ? WHERE id = ? AND phase = ?",
                         PHASE_ADVANCING, current_round["id"], PHASE_RESULTS)

    # If another POST already started advancing the round, redirect safely
    if claimed == 0:
        return redirect("/game")

    room = get_room(db, session["room_id"])
    players = db.execute(
        "SELECT * FROM players WHERE room_id = ? ORDER BY join_order", session["room_id"])
    player_count = len(players)

    # A full round = every player has asked once, so game ends after rounds * player_count questions
    if current_round["round_number"] == room["rounds"] * player_count:
        db.execute("UPDATE rooms SET status = ? WHERE id = ?", STATUS_FINISHED, session["room_id"])
        return redirect("/results")

    # Find the current leader's full player object from the players list
    current_leader = next(p for p in players if p["id"] == current_round["leader_id"])
    # Get their position in the join order (0, 1, 2, 3...)
    current_order = current_leader["join_order"]
    # Calculate the next position, wrapping back to 0 if we've reached the end
    next_order = (current_order + 1) % player_count
    # Get the player at that next position — players is ordered by join-order so index matches
    next_leader = players[next_order]
    # Insert a new round with the next leader and increment the round number by 1
    db.execute("INSERT INTO rounds (room_id, leader_id, round_number) VALUES (?, ?, ?)",
               session["room_id"], next_leader["id"], current_round["round_number"] + 1)
    return redirect("/game")


@app.route("/results", methods=["GET"])
def results():
    if not restore_session(db):
        flash("You must finish a game before viewing results")
        return redirect("/")
    room = get_room(db, session["room_id"])
    if not room["status"] == STATUS_FINISHED:
        flash("The game is still in progress")
        return redirect("/game")
    players = db.execute(
        "SELECT * FROM players WHERE room_id = ? ORDER BY score DESC, name ASC", session["room_id"])

    # Handle the possibility that more than one player is tied for the top score
    top_score = players[0]["score"]
    winners = [player for player in players if player["score"] == top_score]

    session.clear()
    resp = make_response(render_template("results.html", players=players, winners=winners))
    resp.delete_cookie("reconnect_token")
    return resp


@app.route("/leave")
# Handle players leaving the room while the game is in the Lobby, In Session, or Finished
def leave():
    # Restore the player's session before checking room state
    if not restore_session(db):
        return clear_session_and_cookies()

    # Getting leaving player-rows
    player = get_player(db, session["player_id"])

    # Get the room and clear the local session if either no longer exists
    room = get_room(db, session["room_id"])
    if not room or not player:
        return clear_session_and_cookies()

    # Cleanup for Finished or Cancelled rooms
    if room["status"] in [STATUS_FINISHED, STATUS_CANCELLED]:
        return clear_session_and_cookies()

    # If a player leaves the lobby, delete him from the database and lobby
    elif room["status"] == STATUS_LOBBY:
        leaving_order = player["join_order"]
        db.execute("DELETE FROM players WHERE id = ?", session["player_id"])

        # Correct the join-order values for the room in the Lobby in case the leader or any early joiners leave
        db.execute("UPDATE players SET join_order = join_order - 1 WHERE room_id = ? AND join_order > ?",
                   session["room_id"], leaving_order)

        player_count = db.execute(
            "SELECT COUNT(*) AS count FROM players WHERE room_id = ?", session["room_id"])[0]["count"]
        # If all the players leave the room, delete the room
        if player_count == 0:
            db.execute("DELETE FROM rooms WHERE id = ?", session["room_id"])
        return clear_session_and_cookies()

    # If a player leaves during an ongoing session, cancel the room for everyone and clear
    elif room["status"] == STATUS_IN_SESSION:
        db.execute("UPDATE rooms SET status = ? WHERE id = ?", STATUS_CANCELLED, session["room_id"])
        return clear_session_and_cookies()
