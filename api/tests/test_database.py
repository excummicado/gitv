from sqlalchemy import create_engine, inspect, text

from app.database import drop_removed_columns


def test_emails_are_dropped_from_an_old_database():
    old = create_engine("sqlite://")
    with old.begin() as conn:
        conn.execute(
            text("CREATE TABLE user (email VARCHAR(255) NOT NULL, nickname VARCHAR(32) NOT NULL, id CHAR(32))")
        )
        conn.execute(text("CREATE UNIQUE INDEX ix_user_email ON user (email)"))
        conn.execute(text("INSERT INTO user VALUES ('a@example.com', 'nick', '1')"))
    drop_removed_columns(old)
    assert [c["name"] for c in inspect(old).get_columns("user")] == ["nickname", "id"]
    with old.connect() as conn:
        assert conn.execute(text("SELECT nickname FROM user")).scalar() == "nick"
    drop_removed_columns(old)  # nothing left to drop: no error


def test_suggestion_tables_are_dropped():
    from app.database import drop_removed_tables

    old = create_engine("sqlite://")
    with old.begin() as conn:
        conn.execute(text("CREATE TABLE playerprofile (player_id VARCHAR PRIMARY KEY, real_name VARCHAR)"))
        conn.execute(text("CREATE TABLE playersuggestion (id INTEGER PRIMARY KEY)"))
    drop_removed_tables(old)
    assert not {"playerprofile", "playersuggestion"} & set(inspect(old).get_table_names())
    drop_removed_tables(old)  # already gone: no error
