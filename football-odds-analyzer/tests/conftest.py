import os
import sys
import tempfile
from pathlib import Path

# Base de données / cache isolés pour les tests (avant tout import de config)
_TMP = tempfile.mkdtemp(prefix="foa-tests-")
os.environ["DATA_DIR"] = _TMP
os.environ["SCHEDULER_ENABLED"] = "0"
os.environ["ANALYZE_AFTER_SCRAPE"] = "0"
os.environ.setdefault("API_FOOTBALL_KEY", "test-key")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FIXTURES = Path(__file__).parent / "fixtures"


def reset_db():
    from database import Base, engine

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
