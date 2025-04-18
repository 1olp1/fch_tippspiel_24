from flask import flash, redirect, render_template, request, session, url_for
import time
import os
from sqlalchemy import func, desc
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import OperationalError
from werkzeug.security import check_password_hash, generate_password_hash
from helpers import login_required, get_league_table, get_valid_matches, convert_iso_datetime_to_human_readable, get_insights, process_predictions, update_live_matches_and_scores, find_closest_in_time_match, update_matches_and_scores, find_matchday_to_display_tippen, delete_user_and_predictions, get_matches_by_gameround, get_game_rounds, get_current_game_round, get_filtered_predictions_by_date, find_closest_in_time_match_from_selection, get_vote_counts
from models import User, Prediction, Match, UserVote
from config import app, get_db_session
import csv



@app.after_request
def after_request(response):
    """Ensure responses aren't cached"""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response


@app.route("/archive", methods=["GET"])
@login_required
def archive():
    return render_template("apology.html")

@app.route("/", methods=["GET", "POST"])
@login_required
def home():
    user_id = session.get("user_id")  # Get the user ID from the session or request
    poll_id = '14_10'  # ID for this specific poll (can be dynamic)
    user_voted = False
        
    try: 
        with get_db_session() as db_session:
            # Get votes for poll
            votes = get_vote_counts(db_session, poll_id)

            try:
                # Check if vote exists for the user
                existing_vote = db_session.query(UserVote).filter_by(user_id=session["user_id"], poll_id=poll_id).first()
                if existing_vote:
                    user_voted = True
            except Exception as e:
                app.logger.error(f"Error getting vote for poll {poll_id} and user {user_id}: {e}")

            # Handle form submission if user hasn't voted yet
            if request.method == "POST" and not user_voted:
                selected_vote = request.form.get("vote")
                
                if selected_vote == "1":
                    votes[0] += 1  # Increment the "Ja" votes
                elif selected_vote == "0":
                    votes[1] += 1  # Increment the "Nein" votes               

                # Record the vote in the database
                new_vote = UserVote(user_id=user_id, poll_id=poll_id, vote=int(selected_vote))
                db_session.add(new_vote)
                db_session.commit()

                user_voted = True  # Mark the user as voted

            insights = get_insights(db_session)
        
        return render_template("home.html", insights=insights, votes=votes, user_voted=user_voted)

    except OperationalError as e:
        app.logger.error(f"Database connection error: {e}")
        return "Database connection error, please try again later.", 500
    
@app.route("/rangliste/gesamt", methods=["GET"])
@login_required
def rangliste_gesamt():
    try:
        with get_db_session() as db_session:
            # Hole die Spielrunden
            game_rounds = get_game_rounds()  # Liefert eine Liste von 5 Tupeln
            num_rounds = len(game_rounds)

            # Dictionaries zur Speicherung der Punkte:
            # round_points: { Runde (1-indexed): { user_id: Punkte in dieser Runde } }
            # total_points: { user_id: Summe aller Punkte über alle Runden }
            round_points = {}
            total_points = {}

            # Für jede Spielrunde (Index 0 bis num_rounds-1)
            for round_index in range(num_rounds):
                # Hole alle Vorhersagen für diese Runde
                predictions = get_filtered_predictions_by_date(db_session, round_index)
                points_this_round = {}
                for pred in predictions:
                    points_this_round[pred.user_id] = points_this_round.get(pred.user_id, 0) + pred.points
                # Runde als 1-indexierte Zahl speichern
                round_points[round_index + 1] = points_this_round

                # Addiere zu den Gesamtpunkten
                for user_id, pts in points_this_round.items():
                    total_points[user_id] = total_points.get(user_id, 0) + pts

            # Hole alle Nutzer (alternativ nur die, die in mindestens einer Runde getippt haben)
            users = db_session.query(User).all()
            # Sortiere die Nutzer absteigend nach ihren Gesamtpunkten (default 0, wenn kein Tipp)
            sorted_users = sorted(users, key=lambda u: total_points.get(u.id, 0), reverse=True)

            # Für jede Runde: Ermittle den Höchstwert, um diesen im Template hervorzuheben
            max_round_scores = {}
            for round_num, points_dict in round_points.items():
                if points_dict:
                    max_round_scores[round_num] = max(points_dict.values())
                else:
                    max_round_scores[round_num] = 0

            # Optional: Gesamthöchste Punktzahl (kann zur Hervorhebung der Gesamtspitze genutzt werden)
            overall_top = max(total_points.values(), default=0)

            # Current round
            current_round = get_current_game_round()

            # Letzter Update-Zeitpunkt der Matches (optional)
            last_update = db_session.query(func.max(Match.evaluation_Date)).scalar()
            last_update = convert_iso_datetime_to_human_readable(last_update) if last_update else None

            return render_template("rangliste_gesamt.html",
                                   users=sorted_users,
                                   round_points=round_points,
                                   total_points=total_points,
                                   max_round_scores=max_round_scores,
                                   overall_top=overall_top,
                                   num_rounds=num_rounds,
                                   user_id=session["user_id"],
                                   current_round=current_round,
                                   last_update=last_update)
    except OperationalError as e:
        app.logger.error(f"Database connection error: {e}")
        return "Database connection error, please try again later.", 500


@app.route("/rangliste", methods=["GET", "POST"])
@login_required
def rangliste():
    start_time = time.time()
    try:
        with get_db_session() as db_session:
            game_rounds_list = get_game_rounds()

            # Determine game round to display based on session or default to closest in time game round
            if request.method == "GET":
                game_round_to_display = int(request.args.get('matchday', get_current_game_round()))
                session['matchday_to_display'] = game_round_to_display
            else:
                game_round_to_display = session.get('matchday_to_display')
                    
            # Determine next and previous matchdays
            current_matchday = game_round_to_display
            next_matchday = game_round_to_display + 1 if current_matchday + 1 <= len(game_rounds_list) else None
            prev_matchday = game_round_to_display - 1 if current_matchday > 0 else None

            # Get last update time for display
            last_update = db_session.query(func.max(Match.evaluation_Date)).scalar()
            last_update = convert_iso_datetime_to_human_readable(last_update) if last_update else None

            # Update live matches for live scoring
            update_live_matches_and_scores(db_session)
            
            # Fetch all users sorted by multiple criteria
            users = db_session.query(User).options(
                joinedload(User.predictions)  # Ensures predictions are loaded with users
            ).order_by(
                desc(User.total_points),
                desc(User.correct_result),
                desc(User.correct_goal_diff),
                desc(User.correct_tendency)
            ).all()

            # Fetch matches and predictions for the current matchday
            filtered_matches = get_matches_by_gameround(db_session, game_round_to_display - 1)
            filtered_predictions = get_filtered_predictions_by_date(db_session, game_round_to_display - 1)

            # Calculate user points for the matchday
            user_points_matchday = {user.id: 0 for user in users}
            for prediction in filtered_predictions:
                user_points_matchday[prediction.user_id] += prediction.points

            # Determine top users to highlight in the html
            max_points = max(user_points_matchday.values(), default=0)
            top_users = [user_id for user_id, points in user_points_matchday.items() if points == max_points and max_points != 0]

            # Get index of closest in time match to set the default match to display (esp. important for mobile view)
            match_ids = [match.id for match in filtered_matches]
            index_of_closest_in_time_match = match_ids.index(find_closest_in_time_match_from_selection(filtered_matches).id) + 1 # +1 because loop index in jinja starts at 1
            
            # Needed for the in-table pagination 
            no_filtered_matches = len(match_ids)

            end_time = time.time()
            elapsed_time = end_time - start_time
            print("Match to display: ", index_of_closest_in_time_match)
            print(f"Elapsed time for Rangliste: {elapsed_time:.4f} seconds")
                        
            return render_template("rangliste.html",
                                matches=filtered_matches,
                                prev_matchday=prev_matchday,
                                next_matchday=next_matchday,
                                current_matchday=current_matchday,
                                matchdays=[1,2,3,4,5],
                                users=users,
                                user_id=session["user_id"],
                                last_update=last_update,
                                top_users=top_users,
                                user_points_matchday=user_points_matchday,
                                index_of_closest_in_time_match=index_of_closest_in_time_match,
                                no_matches=no_filtered_matches
                                )
        
    except OperationalError as e:
        app.logger.error(f"Database connection error: {e}")
        return "Database connection error, please try again later.", 500
        

@app.route("/tippen", methods=["GET", "POST"])
@login_required
def tippen():
    try:
        with get_db_session() as db_session:
            # Determine matchday_to_display based on session or default to current matchday
            if request.method == "GET":
                game_round_to_display = int(request.args.get('matchday', get_current_game_round()))
                session['matchday_to_display'] = game_round_to_display
            else:
                game_round_to_display = session.get('matchday_to_display')

            # Get matches for the gameround that should be displayed
            matches_game_round = get_matches_by_gameround(db_session, game_round_to_display - 1)

            # Filter valid matches for predictions
            valid_matches = get_valid_matches(matches_game_round)
            
            # Determine next and previous matchdays
            game_rounds_list = get_game_rounds()
            current_matchday = game_round_to_display
            next_matchday = game_round_to_display + 1 if current_matchday + 1 <= len(game_rounds_list) else None
            prev_matchday = game_round_to_display - 1 if current_matchday > 0 else None

            if request.method == "POST":
                process_predictions(valid_matches, session, db_session, request)

            # Fetch all predictions for the current user
            predictions = db_session.query(Prediction).filter_by(user_id=session["user_id"]).all()

            # Get time of last match update
            last_update = db_session.query(func.max(Match.lastUpdateDateTime)).scalar()

            # Format last update time for display
            if last_update:
                last_update = convert_iso_datetime_to_human_readable(last_update)

            return render_template('tippen.html', matches=matches_game_round, matchdays=[1,2,3,4,5], current_matchday=current_matchday,
                                next_matchday=next_matchday, prev_matchday=prev_matchday, last_update=last_update,
                                predictions=predictions, valid_matches=valid_matches, matches_by_date=None)
        
    except OperationalError as e:
        app.logger.error(f"Database connection error: {e}")
        return "Database connection error, please try again later.", 500
    

@app.route("/gruppen")
@login_required
def gruppen():
    try:
        with get_db_session() as db_session:
            table_data = get_league_table(db_session)
            groups = {}

            for team in table_data:
                if team.teamGroupName not in groups:
                    groups[team.teamGroupName] = []

                groups[team.teamGroupName].append(team)

            try:
                del groups["None"]  # To remove the placeholder team
            except KeyError:
                pass

            groups = dict(sorted(groups.items()))

            last_update = table_data[0].lastUpdateTime
            if last_update:
                last_update = convert_iso_datetime_to_human_readable(last_update)
            else:
                last_update = None

            return render_template("gruppen.html", groups=groups, table_data=table_data, last_update=last_update)
    except OperationalError as e:
        app.logger.error(f"Database connection error: {e}")
        return "Database connection error, please try again later.", 500


@app.route("/regeln")
def regeln():
    return render_template("regeln.html")


@app.route("/statistik")
@login_required
def statistik():
    try:
        with get_db_session() as db_session:
            return render_template("statistik.html", insights=get_insights(db_session))
        
    except OperationalError as e:
        app.logger.error(f"Database connection error: {e}")
        return "Database connection error, please try again later.", 500


@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""
    try:
        with get_db_session() as db_session:
            # User reached route via POST (as by submitting a form via POST)
            if request.method == "POST":
                username = request.form.get("username")
                password = request.form.get("password")

                # Ensure username and password were submitted
                if not username or not password:
                    flash("Benutzername/Passwort fehlt", "error")
                    return redirect("/login")
                
                # Forget any user_id
                session.clear()

                # Query database for username
                user = db_session.query(User).filter_by(username=username).first()

                # Check if user exists and password is correct
                if not user or not check_password_hash(user.hash, password):
                    flash("Benutzername/Passwort falsch", 'error')
                    return redirect("/login")

                # Remember which user has logged in
                session["user_id"] = user.id
                session["username"] = user.username
                
                session.permanent = True  # Make the session permanent (user can stay logged in for longer times)

                update_matches_and_scores(db_session)   # TODO updating tables?

                # Redirect user to home page
                return redirect("/")

            # User reached route via GET (as by clicking a link or via redirect)
            else:
                return render_template("login.html")
            
    except OperationalError as e:
        app.logger.error(f"Database connection error: {e}")
        return "Database connection error, please try again later.", 500
    

@app.route("/logout")
@login_required
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()
    
    # Message for logging out successfully
    flash("Erfolgreich ausgeloggt!", 'success')

    # Redirect user to login form
    return redirect("/")


@app.route("/account", methods=["GET", "POST"])
@login_required
def account():  
    return render_template("account_index.html")


@app.route("/account/delete", methods=["GET", "POST"])
@login_required
def delete_account():
    if request.method == "POST":
        confirm_delete = request.form.get('confirm_delete')
        if confirm_delete == 'yes':
            try:
                with get_db_session() as db_session:
                    delete_user_and_predictions(session["user_id"], db_session)
                    session.clear()
                    flash('Account erfolgreich gelöscht.', 'success')
                    return redirect("/")

            except OperationalError as e:
                app.logger.error(f"Database connection error: {e}")
                return "Database connection error, please try again later.", 500
            
        else:
            flash('Zum Löschen Haken bei Checkbox setzen.', 'warning')
            return redirect(url_for('delete_account'))
        
    else:
        return render_template("account_delete.html")


@app.route("/account/change_password", methods=["GET", "POST"])
@login_required
def change_password():
    try:
        with get_db_session() as db_session:
            # User reached route via POST (as by submitting a form via POST)
            if request.method == "POST":
                current_password = request.form.get("current_password")
                new_password = request.form.get("password")
                password_confirmation = request.form.get("password_confirmation")

                # Ensure inputs are not empty
                if not current_password or not new_password or not password_confirmation:
                    flash("Feld(er) leer", "error")
                    return redirect("/account/change_password")

                # Query database for username
                user = db_session.query(User).filter_by(username=session["username"]).first()

                # Check if user exists and password is correct
                if not user or not check_password_hash(user.hash, current_password):
                    flash("Ungültiges Passwort", 'error')
                    return redirect("/account/change_password")
                
                if new_password != password_confirmation:
                    flash("Passwörter stimmen nicht überein", 'error')
                    return redirect("/account/change_password")

                # Hash the password
                hashed_pw = generate_password_hash(new_password)

                # Update the user's password in the database
                user.hash = hashed_pw
                db_session.commit()

                flash('Passwort erfolgreich geändert.', 'success')
                return redirect("/account")

            # User reached route via GET (as by clicking a link or via redirect)
            else:
                return render_template("account_change_pw.html")
            
    except OperationalError as e:
        app.logger.error(f"Database connection error: {e}")
        return "Database connection error, please try again later.", 500


@app.route("/account/change_username", methods=["GET", "POST"])
def change_username():
    try:
        with get_db_session() as db_session:
            # User reached route via POST (as by submitting a form via POST)
            if request.method == "POST":
                new_username = request.form.get("new_username")
                password_confirmation = request.form.get("password_confirmation")

                # Ensure inputs are not empty
                if not new_username or not password_confirmation:
                    flash("Feld(er) leer", "error")
                    return redirect("/account/change_username")

                # Query database for username
                user = db_session.query(User).filter_by(username=session["username"]).first()

                # Check if user exists and password is correct
                if not user or not check_password_hash(user.hash, password_confirmation):
                    flash("Ungültiges Passwort", 'error')
                    return redirect("/account/change_username")
                
                # Prevent username from being the same as current username
                if new_username == session["username"]:
                    flash("Benutzername ungültig", 'error')
                    return redirect("/account/change_username")
                
                # Check if username already exists
                existing_user = db_session.query(User).filter_by(username=new_username).first()
                if existing_user:
                    flash("Benutzername bereits vergeben", 'error')
                    return redirect("/account/change_username")
                
                if len(new_username) > 15:
                    flash("Benutzername ist zu lang", 'error')
                    return redirect("/account/change_username")

                # Update the user's username in the database
                user.username = new_username
                db_session.commit()
                session["username"] = new_username

                flash('Benutzernamen erfolgreich geändert.', 'success')
                return redirect("/account")

            # User reached route via GET (as by clicking a link or via redirect)
            else:
                return render_template("account_change_username.html")
                
    except OperationalError as e:
        app.logger.error(f"Database connection error: {e}")
        return "Database connection error, please try again later.", 500


@app.route("/register", methods=["GET", "POST"])
def register():
    try:
        with get_db_session() as db_session:
            if request.method == "POST":
                username = request.form.get("username")
                password = request.form.get("password")
                password_repetition = request.form.get("confirmation")
                access_code = request.form.get("accesscode")

                if not username:
                    flash("Kein Benutzername angegeben", 'error')
                    return redirect("/register")

                if not access_code or access_code != os.getenv('ACCESSCODE_TIPPSPIEL'):
                    flash("Zugangscode fehlt/ungültig", "error")
                    return redirect("/register")

                # Check if username already exists
                existing_user = db_session.query(User).filter_by(username=username).first()
                if existing_user:
                    flash("Benutzername bereits vergeben", 'error')
                    return redirect("/register")

                # Check if passwords are entered and if they match
                if not password or not password_repetition or password != password_repetition:
                    flash("Passwörter fehlen oder stimmen nicht überein", 'error')
                    return redirect("/register")
                
                if len(username) > 15:
                    flash("Benutzername ist zu lang", 'error')
                    return redirect("/register")

                # Hash the password
                hashed_pw = generate_password_hash(password)

                # Create a new User object
                new_user = User(username=username, hash=hashed_pw)

                # Add new user to session and commit to database
                db_session.add(new_user)
                db_session.commit()

                # Show success message
                flash("Erfolgreich registriert!", 'success')

                return redirect("/")

            else:
                return render_template("register.html")
            
    except OperationalError as e:
        app.logger.error(f"Database connection error: {e}")
        return "Database connection error, please try again later.", 500


@app.route("/accesscode", methods=["POST"])
def accesscode():
    accesscode = request.form["accesscode"]
    
    # Validate the access code here
    
    if validate_accesscode(accesscode):
        return redirect(url_for("success"))  # Redirect to a success page
    else:
        return "Invalid Access Code", 400  # Return an error message
    

def validate_accesscode(accesscode):
    # Implement your access code validation logic here
    return accesscode == os.getenv("ACCESSCODE_TIPPSPIEL")


@app.route("/italian_brain_rot")
def italian_brain_rot():
    # Der Pfad zum Bildordner im static-Verzeichnis
    images_folder = os.path.join(app.static_folder, "italian_brain_rot")
    images = []

    image_names = {
        1: "Brr Brr Patapim",
        2: "Trallalero Trallala",
        3: "Bombardino Crocodilo",
        4: "Trippi Troppi",
        5: "Tung Tung Tung Tung Tung Sahur",
        6: "Lirili Larila",
        7: "Schimpansini Bananini",
        8: "Brri Brri bigus dicus debicus dedicus",
        9: "La vaca saturno saturnia"
    }

    # Lese alle unterstützten Bild-Dateien (png, jpg, jpeg, gif)
    try:
        for filename in os.listdir(images_folder):
            if filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
                # Der URL-Pfad muss relativ zum static-Ordner angegeben werden
                image_url = url_for('static', filename=f'italian_brain_rot/{filename}')
                images.append(image_url)
    except Exception as e:
        app.logger.error(f"Fehler beim Auslesen der Bilder für Italian Brain Rot: {e}")
    
    return render_template("italian_brain_rot.html", images=images, image_names=image_names)