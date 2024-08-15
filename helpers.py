from flask import flash, redirect, session
from sqlalchemy import func, text, desc, case, or_, and_
from sqlalchemy.orm import joinedload
import time
from functools import wraps
import requests
import uuid
import os
from PIL import Image
from datetime import datetime, timedelta
from models import User, Match, Team, Prediction
from collections import defaultdict
from config import app
import logging

logging.basicConfig(
    filename='app.log',  # Log file name
    filemode='a',        # Append mode; use 'w' for overwrite mode
    level=logging.INFO,  # Log level
    format='%(asctime)s - %(levelname)s - %(message)s'  # Log format
)# Prepare API requests
league = "bl1"      # bl1 for 1. Bundesliga
league_id = 4741
season = "2024"     # 2023 for 2023/2024 season

# Tournament info
games_group_stage = 3

# urls for openliga queries
url_matchdata = f"https://api.openligadb.de/getmatchdata/{league}/{season}"
url_table = f"https://api.openligadb.de/getbltable/{league}/{season}"
url_teams = f"https://api.openligadb.de/getavailableteams/{league}/{season}"

# Folder paths
local_folder_path = os.path.join(".", "static", league, season)
img_folder =  os.path.join(local_folder_path, "team-logos")

# Dummy team info
dummy_team_id = 5251


def timer(func):
    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        elapsed_time = end_time - start_time
        print(f"Elapsed time for {func.__name__}: {elapsed_time:.4f} seconds")
        return result
    return wrapper


def get_matches_db(db_session):
        return db_session.query(Match).all()


def get_teams(db_session):
    return db_session.query(Team).all()


def login_required(f):
    """
    Decorate routes to require login.

    https://flask.palletsprojects.com/en/latest/patterns/viewdecorators/
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("user_id") is None:
            return redirect("/login")
        return f(*args, **kwargs)

    return decorated_function


def make_image_filepath(team):
    img_file_name = team['shortName'] + os.path.splitext(team['teamIconUrl'])[1]
    img_file_path = os.path.join(img_folder, img_file_name)

    return img_file_path


def get_openliga_json(url):
    try:
        response = requests.get(url)
        response.raise_for_status()

        return response.json()
    
    except (KeyError, IndexError, requests.RequestException, ValueError):
        return None
    

def get_league_table(db_session):        
    return db_session.query(Team).order_by(Team.teamRank.asc()).all()


def insert_teams_to_db(db_session):
    print("Inserting teams to db")
    try:
        teams = get_openliga_json(url_teams)
        if teams:
            for team in teams:
                team = Team(
                    id = team["teamId"],
                    teamName = team["teamName"],
                    shortName = team["shortName"],
                    teamIconUrl = team["teamIconUrl"],
                    teamIconPath = make_image_filepath(team),
                    teamGroupName = team["teamGroupName"]
                )
                db_session.add(team)

            # Insert dummy team for open matchups after the group stage where teams are yet undetermined
            dummy_team = Team(
                id = dummy_team_id,
                teamName = '-',
                shortName = '-',
                teamIconPath = os.path.join(img_folder,"dummy-teamlogo.png")
            )

            db_session.add(dummy_team)

            # Download and resize team icon images
            print("Downloading and resizing team icon images...")
            download_and_resize_logos(teams)
            
            db_session.query(Team).update({Team.lastUpdateTime: get_current_datetime_str()})
        db_session.commit()
    except Exception as e:
            print(f"Updating inserting teams failed: {e}")
               

def update_league_table(db_session):
    table = get_openliga_json(url_table)
    if table:
        for teamRank, team in enumerate(table, start=1):

            db_session.query(Team).filter_by(id=team["teamInfoId"]).update({
                Team.points: team["points"],
                Team.opponentGoals: team["opponentGoals"],
                Team.goals: team["goals"],
                Team.matches: team["matches"],
                Team.won: team["won"],
                Team.lost: team["lost"],
                Team.draw: team["draw"],
                Team.goalDiff: team["goalDiff"],
                Team.teamRank: teamRank
            })
        # Update lastUpdateTime for all teams
        db_session.query(Team).update({Team.lastUpdateTime: get_current_datetime_str()})

        # Commit the session to persist data
        db_session.commit()


def insert_or_update_matches_to_db(db_session):
    # Query openliga API with link from above
    matchdata = get_openliga_json(url_matchdata)

    if matchdata:
        for match in matchdata:           
            team1_score, team2_score = get_scores(match)

            match_entry = Match(
                id=match["matchID"],
                matchday=match["group"]["groupOrderID"],
                team1_id=match["team1"]["teamId"],
                team2_id=match["team2"]["teamId"],
                team1_score=team1_score,
                team2_score=team2_score,
                matchDateTime=match["matchDateTime"],
                matchIsFinished=match["matchIsFinished"],
                #location=match["location"]["locationCity"],        # only worked for euro2024
                lastUpdateDateTime=match["lastUpdateDateTime"]
            )
            
            db_session.merge(match_entry)  # Use merge to insert or update

    db_session.commit()


def get_scores(match_API):

    if match_API["matchResults"]:
        if len(match_API["matchResults"]) == match_API["matchResults"][-1]["resultOrderID"]:
            team1_score = match_API["matchResults"][-1]["pointsTeam1"]
            team2_score = match_API["matchResults"][-1]["pointsTeam2"]

        else:
            team1_score = match_API["matchResults"][1]["pointsTeam1"]
            team2_score = match_API["matchResults"][1]["pointsTeam2"]
    else:
        team1_score, team2_score = None, None

    return team1_score, team2_score


def update_user_scores(db_session):
    start_time = time.time()
    
    # Award points for the predictions in the prediction table
    award_predictions(db_session)

    # Award users based on the points for each prediction
    award_users(db_session)
    
    end_time = time.time()
    elapsed_time = end_time - start_time
    print(f"Elapsed time for update_user_scores: {elapsed_time:.4f} seconds")


def award_predictions(db_session):
    # Get matches that need to be evaluated
    current_time = datetime.now()
    matches_to_evaluate = db_session.query(Match).filter(
        Match.predictions_evaluated == 0,
        or_(
            Match.matchIsFinished == 1,
            and_(
                Match.matchDateTime <= current_time,
                Match.matchIsFinished == 0
            )
        )
    ).all()

    predictions_awarded = False

    for match in matches_to_evaluate:
        if match.team1_score is not None:
            # Calculate match outcome parameters
            team1_score = match.team1_score
            team2_score = match.team2_score
            goal_diff = team1_score - team2_score
            winner = 1 if team1_score > team2_score else 2 if team1_score < team2_score else 0

            # Update predictions in bulk
            db_session.query(Prediction).filter(Prediction.match_id == match.id).update({
                Prediction.points: case(
                    ((Prediction.team1_score == team1_score) & (Prediction.team2_score == team2_score), 4),
                    ((Prediction.goal_diff == goal_diff) & (winner != 0), 3),
                    (((Prediction.winner == winner) | ((Prediction.goal_diff == goal_diff) & (winner == 0))), 2),
                    else_=0
                )
            }, synchronize_session=False)

            # Update match evaluation status
            if match.matchIsFinished == 1:
                match.predictions_evaluated = 1
            match.evaluation_Date = get_current_datetime_as_object()

            predictions_awarded = True

    if predictions_awarded:
        # Commit changes for match predictions
        db_session.commit()
        

def award_users(db_session):
    # Update total points in the users table in bulk # chatGPT
    user_predictions = db_session.query(
        Prediction.user_id,
        func.sum(Prediction.points).label('total_points'),
        func.count(case((Prediction.points == 4, 1))).label('correct_result'),
        func.count(case((Prediction.points == 3, 1))).label('correct_goal_diff'),
        func.count(case((Prediction.points == 2, 1))).label('correct_tendency')
    ).group_by(Prediction.user_id).all()

    for user_prediction in user_predictions:
        db_session.query(User).filter(User.id == user_prediction.user_id).update({
            User.total_points: user_prediction.total_points,
            User.correct_result: user_prediction.correct_result,
            User.correct_goal_diff: user_prediction.correct_goal_diff,
            User.correct_tendency: user_prediction.correct_tendency
        }, synchronize_session=False)

    # Commit all changes to the database
    db_session.commit()


def get_valid_matches(matches):
    return [match for match in matches
            if match.matchIsFinished == 0 and get_current_datetime_as_object() < match.matchDateTime]


def process_predictions(valid_matches, session, db_session, request):
    prediction_added = False
    error_message = "Keine Änderungen oder Tipps fehlerhaft"
    success_message = "Tipp(s) erfolgreich gespeichert"
    
    # Iterate through valid matches and process predictions
    for match in valid_matches:
        match_id = match.id

        # Retrieve user input for team scores
        team1_score = request.form.get(f'team1Score_{match_id}')
        team2_score = request.form.get(f'team2Score_{match_id}')

        # Retrieve or create prediction entry
        prediction = db_session.query(Prediction).filter_by(user_id=session["user_id"], match_id=match_id).first()

        # If prediction existed, but input fields were posted empty, then delete the prediction
        if prediction and not team1_score and not team2_score:
            db_session.delete(prediction)
            prediction_added = True
            continue

        # Validate and convert scores to integers
        if team1_score and team2_score and team1_score.isdigit() and team2_score.isdigit():
            team1_score = int(team1_score)
            team2_score = int(team2_score)
        else:
            continue

        # Determine winner based on scores
        winner = 1 if team1_score > team2_score else 2 if team1_score < team2_score else 0

        if winner == 0 and match.matchday > games_group_stage:
            error_message = "Kein Unentschieden bei KO-Spielen möglich"
            continue

        if prediction:
            # Update existing prediction if changed
            if team1_score != prediction.team1_score or team2_score != prediction.team2_score:
                prediction.team1_score = team1_score
                prediction.team2_score = team2_score
                prediction.goal_diff = team1_score - team2_score
                prediction.winner = winner
                prediction.prediction_date = get_current_datetime_as_object()
                prediction_added = True
        else:
            # Create new prediction if none exists
            new_prediction = Prediction(
                user_id=session["user_id"],
                matchday=match.matchday,
                match_id=match_id,
                team1_score=team1_score,
                team2_score=team2_score,
                goal_diff=team1_score - team2_score,
                winner=winner,
                prediction_date=get_current_datetime_as_object()
            )
            db_session.add(new_prediction)
            prediction_added = True

    # Commit changes if predictions were added
    if prediction_added:
        db_session.commit()
        flash(success_message, "success")
    else:
        flash(error_message, "error")


def delete_user_and_predictions(user_id, db_session):
    # Delete predictions from the user
    db_session.query(Prediction).filter_by(user_id=user_id).delete()

    # Delete the user
    db_session.query(User).filter_by(id=user_id).delete()

    db_session.commit()


def update_match_score_for_live_scores(db_session, match_API):
    match = match_API

    print("live match to update: ", match["matchID"])

    team1_score, team2_score = get_scores(match)

    print("Live scores: ", team1_score, ":", team2_score)
    match_entry = Match(
        id=match["matchID"],
        team1_score=team1_score,
        team2_score=team2_score,
        lastUpdateDateTime=match["lastUpdateDateTime"]
    )
    
    db_session.merge(match_entry)  # Use merge to insert or update

    db_session.commit()


def download_and_resize_logos(teams):
    os.makedirs(img_folder, exist_ok=True)

    if not os.listdir(img_folder):
        for _, team in enumerate(teams):
            try:
                img_url = team.get('teamIconUrl')
                if not img_url:
                    continue

                response = requests.get(
                    img_url,
                    cookies={"session": str(uuid.uuid4())},
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.102 Safari/537.36",
                             "Referer": "https://www.google.com/",
                             "Accept-Language": "en-US,en;q=0.9",
                             "Cache-Control": "no-cache",
                             "Upgrade-Insecure-Requests": "1",},
                )       ### Header from chatGPT to mimic a real computer
                response.raise_for_status()

                img_file_path = make_image_filepath(team)

                with open(img_file_path, 'wb') as f:
                    f.write(response.content)

                resize_image(img_file_path)

            except (KeyError, IndexError, requests.RequestException, ValueError) as e:
                continue


def get_insights(db_session):
    user_id = session["user_id"]

    # Predictions rated
    predictions_rated = db_session.query(func.count(Prediction.id).label('predictions_rated'))\
        .join(Match, Match.id == Prediction.match_id)\
        .filter(Prediction.user_id == user_id, Match.matchIsFinished == 1)\
        .scalar()

    # Prediction count
    prediction_count = db_session.query(func.count(Prediction.id).label('prediction_count'))\
        .filter(Prediction.user_id == user_id)\
        .scalar()

    # Finished matches
    finished_matches = db_session.query(func.count(Match.id).label('completed_matches'))\
        .filter(Match.matchIsFinished == 1)\
        .scalar()

    # Total points of the user
    total_points_user = db_session.query(User.total_points).filter(User.id == user_id).scalar()

    # User rank
    subquery = db_session.query(
        User.id,
        func.row_number().over(
            order_by=[
                desc(User.total_points),
                desc(User.correct_result),
                desc(User.correct_goal_diff),
                desc(User.correct_tendency)
            ]
        ).label('rank')
    ).subquery()
    rank = db_session.query(subquery.c.rank).filter(subquery.c.id == user_id).scalar()

    # Base statistics for the user
    base_stats = db_session.query(User.correct_result, User.correct_goal_diff, User.correct_tendency)\
        .filter(User.id == user_id).first()

    # Number of users
    no_users = db_session.query(func.count(User.id).label('no_users')).scalar()

    # Store the statistics in the insights dictionary
    insights = {}

    # If there have been predictions, count how many were made
    if predictions_rated:
        insights["predictions_rated"] = predictions_rated
    else:
        insights["predictions_rated"] = 0

    # Create useful statistics and store in insights dict    
    insights["total_games_predicted"] = prediction_count
    insights["missed_games"] = finished_matches - predictions_rated    
    insights["total_points"] = total_points_user
    insights["username"] = db_session.query(User.username).filter(User.id == user_id).scalar()
    insights["no_users"] = no_users
    insights["rank"] = rank
    insights["corr_result"] = base_stats.correct_result
    insights["corr_goal_diff"] = base_stats.correct_goal_diff
    insights["corr_tendency"] = base_stats.correct_tendency
    insights["wrong_predictions"] = insights["predictions_rated"] - insights["corr_result"] - insights["corr_goal_diff"] - insights["corr_tendency"]

    # Differentiate if predictions have been rated to avoid dividing by 0 for the percentage
    if insights["predictions_rated"] != 0:
        insights["corr_result_p"] = round((base_stats.correct_result / insights["predictions_rated"])*100)
        insights["corr_goal_diff_p"] = round(base_stats.correct_goal_diff / insights["predictions_rated"]*100)
        insights["corr_tendency_p"] = round(base_stats.correct_tendency / insights["predictions_rated"]*100)
        insights["wrong_predictions_p"] = round(insights["wrong_predictions"] / insights["predictions_rated"]*100) 
        insights["points_per_tip"] = round(total_points_user / insights["predictions_rated"], 2)
    else:
        insights["corr_result_p"] = 0
        insights["corr_goal_diff_p"] = 0
        insights["corr_tendency_p"] = 0
        insights["wrong_predictions_p"] = 0
        insights["points_per_tip"] = 0

    return insights


def is_update_needed_league_table(db_session):
    # Check if teams table is empty and insert teams if needed
    if not db_session.query(Team).first():
        print("Teams table is empty, inserting teams first...")
        insert_teams_to_db(db_session)
        print("Inserting done.")

    # Get current matchday from API and DB
    current_matchday_API = get_current_matchday_openliga()
    current_match_db = find_closest_in_time_kickoff_match_db(db_session)

    current_matchday_db = current_match_db.matchday if current_match_db else None

    # Compare matchdays and if they're the same, check for update times
    if current_matchday_API > current_matchday_db:
        return True

    if current_matchday_API == current_matchday_db:
        # Get last update times
        lastUpdateTime_openliga = normalize_datetime(get_last_online_change(current_matchday_API))
        last_update_time_db = normalize_datetime(current_match_db.team1.lastUpdateTime) if current_match_db else None

        # Print for debugging
        print(f"\tLast update time openliga: {lastUpdateTime_openliga}")
        print(f"\tLast update time db: {last_update_time_db}")

        # Update if online data is more recent
        if lastUpdateTime_openliga and last_update_time_db:
            return lastUpdateTime_openliga > last_update_time_db

        # Update if there are no comparable update times
        return True

    return False


def is_update_needed_matches(db_session):
    ''' Deprecated incomplete function. Actually faster to just update. Maybe useful with big datasets.'''
    # Get current matchday from API and DB
    current_matchday_API = get_current_matchday_openliga()
    current_match_db = find_closest_in_time_kickoff_match_db(db_session)
    current_matchday_db = current_match_db.matchday if current_match_db else None

    # Print to enable debugging for comparison of matchdays
    print("\tCurrent matchday local: ", current_matchday_db)
    print("\tCurrent matchday API: ", current_matchday_API)

    # Compare matchdays and if they're the same, check for update times
    if current_matchday_API > current_matchday_db:
        return True

    if current_matchday_API == current_matchday_db:
        return check_if_update_needed_for_current_matchday(db_session, current_matchday_API)


    return False


def check_if_update_needed_for_current_matchday(db_session, current_matchday_API):

    # Get last update times
    lastUpdateTime_openliga = normalize_datetime(get_last_online_change(current_matchday_API))
    last_updated_match = get_most_recently_updated_match_by_matchday(db_session, current_matchday_API)
    last_update_time_db = normalize_datetime(last_updated_match.lastUpdateDateTime) if last_updated_match else None

    # Print for debugging
    print(f"\tLast update time openliga: {lastUpdateTime_openliga}")
    print(f"\tLast update time db: {last_update_time_db}")

    # Update if online data is more recent or if there are no comparable update times
    if lastUpdateTime_openliga and last_update_time_db:
        return lastUpdateTime_openliga > last_update_time_db

    return True


def update_match_if_needed(db_session, unfinished_match):
    # Get match data from openliga
    matchdata_openliga = get_matchdata_openliga(unfinished_match.id)

    # Get last update times from openliga and db
    last_update_time_openliga = normalize_datetime(matchdata_openliga["lastUpdateDateTime"])
    last_update_time_db = normalize_datetime(unfinished_match.lastUpdateDateTime)

    if not last_update_time_db or last_update_time_openliga > last_update_time_db:
        update_match_in_db(matchdata_openliga, unfinished_match, db_session)


def update_match_in_db(matchdata_API, match_db, db_session):
    """ Deprecated function, needs updating for use """
    print("Updating match: ", matchdata_API["matchID"])

    # Prepare update dictionary
    update_data = {
        Match.matchDateTime: matchdata_API["matchDateTime"],
        Match.matchIsFinished: matchdata_API["matchIsFinished"],
        Match.lastUpdateDateTime: matchdata_API["lastUpdateDateTime"],
        Match.team1_id: matchdata_API["team1"]["teamId"],
        Match.team2_id: matchdata_API["team2"]["teamId"]
    }

    # Conditionally update team scores based on match finished status
    if matchdata_API["matchIsFinished"]:
        update_data[Match.team1_score] = matchdata_API["matchResults"][1]["pointsTeam1"]
        update_data[Match.team2_score] = matchdata_API["matchResults"][1]["pointsTeam2"]
    elif match_db.is_underway:
        update_data[Match.team1_score] = matchdata_API["matchResults"][-1]["pointsTeam1"]
        update_data[Match.team2_score] = matchdata_API["matchResults"][-1]["pointsTeam2"]

    db_session.query(Match).filter_by(id=matchdata_API["matchID"]).update(update_data)

    # Commit the session to persist data
    db_session.commit()


@timer
def update_matches_and_scores(db_session):
    print("Updating matches and user scores...")

    try:
        #insert_teams_to_db(db_session)
        insert_or_update_matches_to_db(db_session)
        update_user_scores(db_session)
    
    except:
        insert_teams_to_db(db_session)
        insert_or_update_matches_to_db(db_session)
        update_user_scores(db_session)

    print("Matches and user scores updated.")


@timer
def update_live_matches_and_scores(db_session):
    print("Updating live matches and user scores...")

    live_matches = find_live_matches(db_session)
    game_updated = False

    for match in live_matches:
        match_data = get_matchdata_openliga(match.id)
        if match_data:
            update_match_score_for_live_scores(db_session, match_data)
            if match_data["matchIsFinished"] == 1:
                update_matches_and_scores(db_session)       # In order to also update other matchups that may depend
            game_updated = True                             # on the live match that has ended, like in a tournament
                                                            # TODO add routine for league table
    if game_updated:
        update_user_scores(db_session)
    print("Updating live matches and user scores finished.")


def get_matchdata_openliga(id):
    url = f"https://api.openligadb.de/getmatchdata/{id}"

    matchdata = get_openliga_json(url)

    return matchdata


def get_last_online_change(matchday):
    # Make url to get last online change
    url = f"https://api.openligadb.de/getlastchangedate/{league}/{season}/{matchday}"

    # Query API and convert to correct format
    # (to ensure that the datetime module works correctly)
    online_change = add_up_decimals_to_6(get_openliga_json(url))

    return online_change

def get_current_matchday_openliga():
    # Openliga DB API
    url = f"https://api.openligadb.de/getcurrentgroup/{league}"

    # Query API
    current_matchday = get_openliga_json(url)

    if current_matchday:
        return current_matchday["groupOrderID"]

    return None


def resize_image(image_path, max_size=(100, 100)):
    """ For faster load times of the page, it is useful to lower the resolution of the pictures """
    if image_path.lower().endswith(('.jpg', '.jpeg', '.png')):
        # Open the image
        with Image.open(image_path) as f:
            # Resize the image while maintaining the aspect ratio
            f.thumbnail(max_size)

            # Save the resized image to the output folder
            f.save(image_path)


def add_up_decimals_to_6(date_string):
    # Format dates of the API to make them usable with the datetime module. Intended to use with ISO formatted dates
    split_string = date_string.split('.')

    pre_decimals = split_string[0]
    decimals = split_string[1]

    while len(decimals) < 6:
        decimals += "0"
        
    return f"{pre_decimals}.{decimals}"


def get_current_datetime_str():
    # Format the current date and time as a string in the desired format
    return datetime.now().isoformat()


def get_current_datetime_as_object():
    # Format the current date and time as a string in the desired format
    return datetime.now()


def convert_iso_datetime_to_human_readable(iso_string_or_datetime_obj):
    if isinstance(iso_string_or_datetime_obj, str):
        date = datetime.fromisoformat(iso_string_or_datetime_obj)
    else: 
        date = iso_string_or_datetime_obj

    weekday_names = ["Mo.", "Di.", "Mi.", "Do.", "Fr.", "Sa.", "So."]

    # Format the datetime object into a more readable format
    match_time_readable = f"{weekday_names[date.weekday()]} {date.strftime('%d.%m.%Y %H:%M')}"
    return match_time_readable


# With help from chatgpt
def normalize_datetime(input_dt):
    # Define possible datetime string formats
    datetime_formats = [
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
    ]

    if isinstance(input_dt, str):
        dt = None
        for fmt in datetime_formats:
            try:
                dt = datetime.strptime(input_dt, fmt)
                break
            except ValueError:
                continue
        if dt is None:
            raise ValueError(f"Time data '{input_dt}' does not match any expected format")
    elif isinstance(input_dt, datetime):
        dt = input_dt
    else:
        raise ValueError("Input must be a datetime string or a datetime object")

    # Remove microseconds
    dt_without_microseconds = dt.replace(microsecond=0)
    return dt_without_microseconds


def find_closest_in_time_kickoff_match_db(db_session):
    # Query to find the match closest in time, adding 140 minutes to matchDateTime
    current_time = datetime.now()
    # Query with help from chatgpt
    query = db_session.query(Match).options(
        joinedload(Match.team1),
        joinedload(Match.team2)
    ).order_by(
        func.abs(func.timestampdiff(text('SECOND'), Match.matchDateTime, current_time))
    ).first()

    return query


def find_live_matches(db_session):
    current_time = datetime.now()
    # Fetch matches that are underway
    live_matches = db_session.query(Match).filter(
        Match.matchDateTime <= current_time,
        Match.matchIsFinished == 0
    ).all()
    
    return live_matches


def find_closest_in_time_matchday_db(db_session):
    return find_closest_in_time_kickoff_match_db(db_session).matchday


def find_closest_in_time_match_db_matchday(db_session, matchday):
    # Get current match from db based on which match is closest in time
    current_datetime = datetime.now()
    # Add 140 minutes to current_datetime
    target_datetime = current_datetime + timedelta(minutes=140)
    
    current_matchday_data_db = db_session.query(
        Match.matchday,
        Match.id,
    ).filter(
        Match.matchday == matchday
    ).order_by(
        func.abs(func.timestampdiff(text('SECOND'), Match.matchDateTime, target_datetime))
    ).first()           # Query by chatgpt

    return current_matchday_data_db


def find_next_matchday_db(db_session):
    # Get current datetime
    current_datetime = datetime.now()

    # Subquery to find the minimum positive time difference
    subquery = db_session.query(
        func.min(Match.matchDateTime - current_datetime).label('min_diff')
    ).filter(
        Match.matchDateTime > current_datetime
    ).scalar_subquery()

    # Query to retrieve the closest future match
    next_matchday_db = db_session.query(
        Match.matchday
    ).filter(
        Match.matchDateTime == current_datetime + subquery  # Adjust to use the subquery result
    ).first()

    return next_matchday_db.matchday


def find_matchday_to_display_tippen(db_session):
    match = find_next_match_db(db_session)

    if match:
        return match.matchday
    
    else:
        # If no unfinished match is found, return the last finished match
        last_matchday  = db_session.query(
            Match.matchday
        ).filter(
            Match.matchIsFinished == 1
        ).order_by(
            Match.matchDateTime.desc()
        ).first()

        if last_matchday is None:
            # Handle the case where there are no finished matches
            raise ValueError("No matches found, neither unfinished nor finished.")

        return last_matchday.matchday
    

def find_next_match_db(db_session):
    query = db_session.query(
        Match
        ).filter(
            Match.matchIsFinished == 0
        ).first()
    return query


def get_most_recently_updated_match_by_matchday(db_session, matchday):
    most_recent_match = db_session.query(Match).filter_by(matchday=matchday).order_by(desc(Match.lastUpdateDateTime)).first()
    return most_recent_match


def group_matches_by_date(matches):
    matches_by_date = defaultdict(list)
    for match in matches:
        match_date = match.formatted_matchDate
        matches_by_date[match_date].append(match)
    return matches_by_date


