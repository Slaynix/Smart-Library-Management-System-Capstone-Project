"""Production WSGI entrypoint for SmartLib.
Gunicorn: gunicorn wsgi:application --workers 2 --bind 0.0.0.0:$PORT
"""
from app import app as application  # noqa: F401

if __name__ == "__main__":
    application.run()
