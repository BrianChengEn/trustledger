"""Generate/check offline JSON compatibility fixtures; runtime data lives in SQLite."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.adapters.synthetic_dataset import main  # noqa: E402

if __name__ == "__main__":
    main()
