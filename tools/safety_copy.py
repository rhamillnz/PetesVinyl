"""Make a safety copy of Pete's library. Run by Update_PetesVinyl.bat after every update.

If this is the first time the new version runs, it also moves the library from the old place (inside the
program folder) to its permanent home first, so nothing is left behind.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from petesvinyl import config, library  # noqa: E402

if __name__ == "__main__":
    if library.migrate_legacy():
        print(f"Moved your library to its permanent home: {config.DATA_DIR}")
    copy = library.safety_copy(sys.argv[1] if len(sys.argv) > 1 else "manual")
    info = library.current_summary()
    print(f"Your library: {info['records']} records, kept safely in {config.DATA_DIR}")
    if copy:
        print(f"Safety copy saved: {copy.name}")
