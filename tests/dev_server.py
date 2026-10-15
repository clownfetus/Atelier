"""Run the real Bottle interface with isolated application data."""
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8767)
    args = parser.parse_args()
    if not os.environ.get('ATELIER_DATA_DIR'):
        parser.error('Set ATELIER_DATA_DIR to an isolated development directory.')
    from atelier.web import routes
    from atelier.web.app import app, _ThreadedServer
    try:
        app.run(host='127.0.0.1', port=args.port, server=_ThreadedServer, quiet=True)
    finally:
        while not routes.shutdown(5):
            pass


if __name__ == '__main__':
    main()
