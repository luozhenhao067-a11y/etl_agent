"""Application-level database package (merged from the review folder 建表/db/).

``session.py`` holds the DATABASE_URL-only engine factory (psycopg 3 dialect
enforced); ``guards.py`` mirrors the Spec 10.2 immutability rules as ORM
events on top of the database triggers from migration 0001.
"""
