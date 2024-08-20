# Football Game Prediction Website
#### Description:   A website where users can guess the outcome of football matches.

## Overview
The website allows users to predict the outcome of Bundesliga, DFB-Pokal and UEFA Conference League matches from the Club 1. FC Heidenheim 1846. The users get points based on how correct their prediction was. In the "Rangliste"-Route they can view their current ranking among all the other users. The website is built using **Flask (and Jinja)**, **Bootstrap tables** and an **API** called [**OpenLigaDB**](https://github.com/OpenLigaDB) for fetching match and team data and a **mysql** server for storing this data. The website is hosted on [**pythonanywhere**](https://salatic.pythonanywhere.com/), where an access key is needed to register.

This Flask application is built upon the [**project**](https://github.com/1olp1/fch_tippspiel_23_local_version) I did as a final project for the CS50 Course. There are some differences to that earlier version, mainly:
- This version is **web-hosted** and in use by friends.
- **mysql** database instead of SQLite, using SQLAlchemy for database interactions.
- More modern **design**, including icons for the submenues.
- Support for **mobile** devices.

## Routes
In the following section the different routes will be presented with screenshots from the desktop view.
### Not logged in
There are three routes when the user is not logged in:
1. **Log In**: The user is prompted to login or register.

    ![Screenshot_Home](/static/images_readme/login.png)
2. **Registrieren** (register): Here the user can set up an account. Password has to be repeated for security and a access code needs to be entered.

    ![Screenshot_Home](/static/images_readme/register.png)

5. **Regeln** (rules): The rules are displayed in this route. For screenshot see down below in the logged in routes.

### Logged in
The website consists of multiple routes when logged in:
1. **Home**: Shows statistics about the users predictions (e. g. current rank, total points, points per game etc.)

    ![Screenshot_Home](/static/images_readme/statistik.png)
2. **Tippen** (making predictions): Here you can input the final scores for matches that have not already had a kickoff (otherwise it is greyed out). By clicking the "Speichern"-Button you can save your predictions. When that button is pressed, the server double checks if the input is valid (e. g. "are there scores for both teams?" "are these scores numeric?" "is the game already underway?") and then stores it if it is. This page is also optimised for mobile viewing.

    ![Screenshot_tippen](/static/images_readme/tippen.png)

3. **Rangliste** (rankings): This is the page where users can see their rank based on the total points they got awarded. They can also see an overview of all predictions from all users and the points for each prediction. The rankings are made using multiple SQL queries and formatting the data in python for making them displayable by jinja. There also exists an extra mobile view.

    ![Screenshot_Home](/static/images_readme/rangliste.png)

4. **Regeln** (rules): The rules are displayed in this route.

    ![Screenshot_Home](/static/images_readme/regeln.png)

### Routes Under Construction

As of August 2024, two routes are still under development:

1. **Rangliste - Übersicht**:
This route will display rankings, showing only the total points for each "round" rather than individual game scores. Each round spans two months. This is reflected in the pagination on the "rangliste" route, where the season is divided into five sections, each covering two months (see screenshot above for reference).


2. **Archiv**:
The tables for past and finished seasons will be displayed here.

### HTML for sites that are under construction
Here's a screenshot of routes that are still in development:
    ![Screenshot_Home](/static/images_readme/construction.png)

## Database
The sqlite database used for this website consists of four tables:
- users
- teams
- predictions
- matches


### users
The users table holds all information relevant to the individual. These include e. g. a unique ID, the username and the hashed password. This table also holds information about the predictions that have already been rated. For example the total points, the amount of correct results etc. are stored here. This is also done in order to make it easier to create the rankings table.

### teams
The teams table holds all team related information. It is filled using the OpenLiga API. Besides basic team info like the name, the short name or an ID, this table also holds the path to the team icon image, so that the icon is more easily integrated into the html template. It also holds the date of the last update for the updating routine and for showing the user how recent the data is (see screenshot).

### predictions
The predictions table holds all predictions of all users. It references the user id from the users table. Each prediction gets its own unique ID. It also holds a points column, that is only filled when the prediction is evaluated. The points are later used for calculating the total points per user.

### matches
This table holds all the information about the matchups of the 1. FC Heidenheim 1846. Additionally, it has a column that stores, whether the match has been already used for evaluating the predictions or not. This way, when updating the user scores (for more details on updating procedures, see below), not all matches have to be regarded again. This table also references the team IDs of the teams table.

## Updating match and team data
As of August 24, the update mechanism functions on demand and triggers under the following conditions:
- When the user logs in.
- When the user navigates to the "rangliste" route.

An update occurs when the data retrieved from the API differs from the data stored in the MySQL database. In such cases, the local data is updated to reflect the changes.

### Logging in
When logging in, the server checks for new match updates via the API. If updates are found, the user scores are also updated accordingly.

### "Rangliste" route
When accessing the "rangliste" page, the server verifies if there are any ongoing matches and updates them if necessary. Subsequently, the user scores are refreshed, enabling real-time scoring.


### Differences to older version
In the older version, the updates where only loaded if they were needed. For that, an "is_update_needed" function was called. But that function was so slow overall because of making several API queries, that it was much faster by just calling the matchdata from the API and check if it differs from the local save.

## OpenLiga API use
Generally, the API is free to use and maintained by its community, where everyone can partake. To use the API, you need a valid **URL** and use that to get a response in **JSON format**. To automate this in Python, I wrote this function:

```
def get_openliga_json(url):
    try:
        response.raise_for_status()

        return response.json()

    except (KeyError, IndexError, requests.RequestException, ValueError):
        return None
```

By providing a valid URL, this function will return a list of dictionaries based on the content of the API response. In order to construct the URL, one can tinker on this [page](https://api.openligadb.de/index.html).

Here are some examples for common URLs used for this project:
```
url_matchdata = f"https://api.openligadb.de/getmatchdata/{league}/{season}/{team}"
url_table = f"https://api.openligadb.de/getbltable/{league}/{season}"
url_teams = f"https://api.openligadb.de/getavailableteams/{league}/{season}"
```
There also exist some URLs to retrieve update times, which is helpful for checking whether updates are needed or not. By making the URLs dynamic (by using f-strings), this project can be more easily adapted to other leagues or use cases.

## Initialising the website
To initialise a new season, one has to perform several steps. Here is a quick rundown:
1. Make sure that environment variables are set according to the mysql database credentials in config.py
2. Initialise the database to create the tables based on models.py
3. Set the variable names in the beginning of app.py according to the team you want and the leagues the game should cover.
4. Insert the teams into the team database. For that, uncomment "insert_teams_to_db" in helpers.py. Matches will be updated automatically after.