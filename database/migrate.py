"""Apply checked-in, versioned database migrations."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from apps.api.db import make_engine,migrate
if __name__=='__main__':
    migrate(make_engine())
    print('Migration 0001 applied (or already present).')
