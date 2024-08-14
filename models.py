from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(255), unique=True, nullable=False)
    hash = Column(String(255), nullable=False)
    total_points = Column(Integer, default=0)
    correct_result = Column(Integer, default=0)
    correct_goal_diff = Column(Integer, default=0)
    correct_tendency = Column(Integer, default=0)
    predictions = relationship("Prediction", back_populates="user")

class Match(Base):
    __tablename__ = 'matches'

    id = Column(Integer, primary_key=True)
    matchday = Column(Integer)
    team1_id = Column(Integer, ForeignKey('teams.id'), nullable=False)
    team2_id = Column(Integer, ForeignKey('teams.id'), nullable=False)
    team1_score = Column(Integer)
    team2_score = Column(Integer)
    matchDateTime = Column(DateTime)
    matchIsFinished = Column(Integer)
    location = Column(String(255))
    lastUpdateDateTime = Column(DateTime)
    predictions_evaluated = Column(Integer, default=0)
    evaluation_Date = Column(DateTime)

    # Define explicit relationship names
    team1 = relationship("Team", foreign_keys=[team1_id], backref="matches_as_team1")
    team2 = relationship("Team", foreign_keys=[team2_id], backref="matches_as_team2")

    @property
    def formatted_matchDate(self):
        date = self.matchDateTime
        weekday_names = ["Mo.", "Di.", "Mi.", "Do.", "Fr.", "Sa.", "So."]
        match_time_readable = f"{weekday_names[date.weekday()]} {date.strftime('%d.%m.%y')}"
        return match_time_readable
    
    @property
    def formatted_matchDateTime(self):
        date = self.matchDateTime
        weekday_names = ["Mo.", "Di.", "Mi.", "Do.", "Fr.", "Sa.", "So."]
        match_time_readable = f"{weekday_names[date.weekday()]} {date.strftime('%d.%m.%y %H:%M')}"
        return match_time_readable
    
    @property
    def formatted_groupname(self):
        matchday = self.matchday
        if matchday < 4:
            team_group_name = self.teamGroupName
            return team_group_name[0].replace("Gruppe ", "") if team_group_name else '-'
        else:
            return '-'

    @property
    def time(self):
        return self.matchDateTime.strftime('%H:%M')

    @property
    def is_underway(self):
        current_datetime = datetime.now()
        match_start_time = self.matchDateTime
        if match_start_time <= current_datetime and not self.matchIsFinished:
            return True
        else:
            return False
        
    @property
    def formatted_matchday(self):
        matchday = self.matchday
        if matchday <=3:
            return f"{matchday}. Spieltag"
        elif matchday == 4:
            return "Achtelfinale"
        elif matchday == 5:
            return "Viertelfinale"
        elif matchday == 6:
            return "Halbfinale"
        elif matchday == 7:
            return "Finale"
        
    @property
    def formatted_matchday_short(self):
        if self.matchday <=3:
            return f"{self.matchday}. Sp."
        elif self.matchday == 4:
            return "AF"
        elif self.matchday == 5:
            return "VF"
        elif self.matchday == 6:
            return "HF"
        elif self.matchday == 7:
            return "F"

class Team(Base):
    __tablename__ = 'teams'

    id = Column(Integer, primary_key=True)
    teamName = Column(String(255))
    shortName = Column(String(255))
    teamIconUrl = Column(String(255))
    teamIconPath = Column(String(255))
    teamGroupName = Column(String, default='None')
    points = Column(Integer, default=0)
    opponentGoals = Column(Integer, default=0)
    goals = Column(Integer, default=0)
    matches = Column(Integer, default=0)
    won = Column(Integer, default=0)
    lost = Column(Integer, default=0)
    draw = Column(Integer, default=0)
    goalDiff = Column(Integer, default=0)
    teamRank = Column(Integer)
    lastUpdateTime = Column(DateTime)

class Prediction(Base):
    __tablename__ = 'predictions'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    matchday = Column(Integer, nullable=False)
    match_id = Column(Integer, nullable=False)
    team1_score = Column(Integer, nullable=False)
    team2_score = Column(Integer, nullable=False)
    goal_diff = Column(Integer, nullable=False)
    winner = Column(Integer, nullable=False)
    prediction_date = Column(DateTime)
    points = Column(Integer, default=0)
    user = relationship("User", back_populates="predictions")
