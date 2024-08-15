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

default_db_name = os.getenv("DB_DATABASE_FCH2024")

def get_db_session(db_name=None):
    # SQLAlchemy database URI
    SQLALCHEMY_DATABASE_URI = get_sqlalchemy_database_uri(db_name)

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
    return session_db()


# Centralized function to get the SQLAlchemy database URI
def get_sqlalchemy_database_uri(db_name=None):
    # Set default database name if no db_name is specified
    if db_name is None:
        db_name = default_db_name

    # Here are the database names of the archives
    elif db_name.lower() == "euro2024":
        db_name = os.getenv('DB_DATABASE_EURO2024')
    return 'mysql+mysqlconnector://{username}:{password}@{hostname}/{databasename}'.format(
        username=os.getenv('DB_USERNAME'),
        password=os.getenv('DB_PASSWORD'),
        hostname=os.getenv('DB_HOSTNAME'),
        databasename=db_name
    )

