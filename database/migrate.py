"""Apply checked-in, versioned database migrations."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sqlalchemy.exc import SQLAlchemyError
from apps.api.config import ConfigurationError,load_settings
from apps.api.db import make_engine,migrate
from apps.api.migrations import MigrationError,VERSIONS

def main():
    engine=None
    try:
        settings=load_settings()
        engine=make_engine(settings.database_url)
        migrate(engine)
    except ConfigurationError:
        print('MIGRATION_CONFIG_INVALID: check the selected environment and database settings.',file=sys.stderr)
        return 2
    except MigrationError:
        print('MIGRATION_HISTORY_UNSUPPORTED: use a compatible application version; do not change version markers manually.',file=sys.stderr)
        return 2
    except (SQLAlchemyError,OSError):
        print('MIGRATION_DATABASE_ERROR: verify connectivity, schema state and backup before retrying.',file=sys.stderr)
        return 2
    finally:
        if engine is not None: engine.dispose()
    print('Migrations '+', '.join(VERSIONS)+' applied (or already present).')
    return 0

if __name__=='__main__':
    raise SystemExit(main())
