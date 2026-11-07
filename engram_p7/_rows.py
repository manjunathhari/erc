"""P7 reads rows by column name. It is given the engine's own connection, so it must not change that connection's row_factory:
the engine and the other layers expect plain tuples. Each query gets its own cursor with named columns instead."""
import sqlite3


class NamedRows:
    def __init__(self, db: sqlite3.Connection):
        self.connection = db

    def execute(self, sql, params=()):
        cursor = self.connection.cursor()
        cursor.row_factory = sqlite3.Row
        return cursor.execute(sql, params)

    def executescript(self, script):
        return self.connection.executescript(script)
