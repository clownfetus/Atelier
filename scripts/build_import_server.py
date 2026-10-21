"""Build the persistent import server from the same pinned mesh inputs as the idle decoder."""
import argparse
from pathlib import Path

from pinned_dotnet import build


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tools', type=Path, required=True)
    parser.add_argument('--output', type=Path, help='Fresh output folder; defaults to Tools/AtelierImport')
    parser.add_argument('--dotnet', default='dotnet')
    args = parser.parse_args()
    output = args.output or args.tools.resolve() / 'AtelierImport'
    build('AtelierImport', args.tools.resolve(), output, args.dotnet)


if __name__ == '__main__':
    main()
