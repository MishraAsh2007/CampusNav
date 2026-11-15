"""Single service for the CampusNav map, routing engine, and Data API."""

from backend.main import app as data_app

from .api import create_app

app = create_app(data_app=data_app)
