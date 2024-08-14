from flask import Flask
from flask_session import Session
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.pool import QueuePool
from datetime import timedelta
import os

app = Flask(__name__)

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)  # Keep users logged in for 30 days
app.config["SESSION_FILE_THRESHOLD"] = 100  # Limits the number of session files before they are pruned
app.config["DEBUG"] = True
Session(app)

# SQLAlchemy database URI
SQLALCHEMY_DATABASE_URI = 'mysql+mysqlconnector://{username}:{password}@{hostname}/{databasename}'.format(
    username=os.getenv('DB_USERNAME'),
    password=os.getenv('DB_PASSWORD'),
    hostname=os.getenv('DB_HOSTNAME'),
    databasename=os.getenv('DB_DATABASE')
)

app.config["SQLALCHEMY_DATABASE_URI"] = SQLALCHEMY_DATABASE_URI
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Create SQLAlchemy engine and session
engine = create_engine(
    SQLALCHEMY_DATABASE_URI,
    poolclass=QueuePool,
    pool_recycle=280,  # Recycle connections after 280 seconds
    pool_pre_ping=True  # Enable connection testing
)
SessionFactory = sessionmaker(bind=engine)
session_db = scoped_session(SessionFactory)

def get_db_session():
    return session_db()

