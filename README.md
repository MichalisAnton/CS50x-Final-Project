# CS50x Quiz Game
#### Description: A multiplayer web application Quiz party game


CS50x Quiz Game is a multiplayer browser-based party game built with Flask, SQLite, Python, HTML, CSS, JavaScript, Bootstrap, and Jinja. One player creates a room and shares a unique room code so friends can join the same session. The group then plays through a series of rounds where the current leader asks a question, the other players submit answers, and everyone votes for the best response.

The game is inspired by party games such as Cards Against Humanity, but instead of using pre-written cards, players create their own questions and answers. After each round, leadership rotates in join order so every player gets a turn to lead.

The goal of this project was to build something more interactive than a standard CRUD-style web app by combining session management, multiplayer game flow, voting logic, and round-based states and transitions into a single application. I also wanted to practise server-side validation and safer database handling throughout the project.

## Features
- Room creation with a unique 6-character code
- Allowing players to join rooms via their unique 6-character codes
- Host-controlled lobby before the game starts
- Rotating leader system based on join order
- Multi-phased game system: question, answering, voting, and results
- Automatic score tracking
- Session restoration using reconnect tokens
- Final results page showing winner(s)
- Test coverage with pytest

## Getting Started

### Prerequisites
- Python 3.x
- pip

### Installation
1. Download/clone the repo and navigate in the project folder
2. Install dependencies:
```bash
   pip install -r requirements.txt
```

### Running the App
```bash
flask run
```
Then open your browser at `http://127.0.0.1:5000`.

## How the Game Works
1. A player creates a room and becomes the host.
2. Other players join the room using the room code.
3. Once enough players have joined, the host starts the game.
4. The current leader submits a question.
5. The other players submit their answers.
6. All players vote for the best answer, except their own.
7. The player with the winning answer receives a point.
8. Leadership rotates to the next player.
9. After the selected number of rounds, the final results are displayed.

## Project Structure
- "app.py" contains Flask routes and the main game logic.
- "helpers.py" contains helper functions for session recovery, database lookups, and token/code generation.
- "quiz.db" stores rooms, players, rounds, answers, and votes.
- "templates/" contains the HTML pages, using Jinja to render the layout and JavaScript for interactivity.
- "static/" contains "styles.css", JavaScript scripts, and the favicon.
- "tests/" contains pytest tests for helper functions, the database, and app behaviours.

## Design Decisions
Using Flask allowed a clear route-based structure to switch between pages and game states in the quiz. SQLite was utilised to keep the server-side logic safe, and any game-state or database changes were made with strict SQL conditionals and guards.

One important design decision was using frequent polling endpoints to update all clients in the room for changes in routes and game states without needing WebSockets, which would have been overkill for the scope of this project. Another design choice was using reconnect tokens stored in cookies and on the server so that players can reconnect to their session should they refresh or disconnect by accident.

I also separated helper logic into "helpers.py" to keep the route handlers in "app.py" more focused and readable, while adding very thorough comments in both "app.py" and "helpers.py" to explain the process.

## Challenges
One of the biggest challenges was making sure that multiplayer state stayed consistent across all players, while also thinking ahead for ways a players may missuse the game, whether intentionally or accidentally. Because several users can interact with the same room at nearly the same time, I had to think carefully about duplicate submissions, duplicate votes, round progression, and player permissions.

Another challenge was handling players leaving a room. If a player leaves during the lobby, the room can continue safely, but if someone leaves during an active game, the session is cancelled to avoid corrupting the game state.

Handling multiplayer POST requests with polling created many security sensitivities, therefore I had to be very thorough in isolating changes based on the database in order to guard against malicious injections.

## Future Improvements
- Replace polling with WebSockets for real-time updates
- Add user accounts and saved profiles
- Add custom question categories
- Improve mobile responsiveness
- Store past game history and statistics
