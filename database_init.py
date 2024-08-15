from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Base
from config import get_sqlalchemy_database_uri

SQLALCHEMY_DATABASE_URI = get_sqlalchemy_database_uri()

engine = create_engine(SQLALCHEMY_DATABASE_URI)
Session = sessionmaker(bind=engine)
session = Session()

# Create all tables
Base.metadata.create_all(engine)
