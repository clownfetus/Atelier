"""Build the standing idle decoder from checksum-pinned inputs with .NET SDK 10.0.402."""
import argparse
from pathlib import Path

# Retained for callers that used the original bundle extraction helper.
from dotnet_bundle import extract_assemblies
from pinned_dotnet import build


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tools', type=Path, required=True)
    parser.add_argument('--output', type=Path, help='Fresh output folder; defaults to Tools/AtelierAnimation')
    parser.add_argument('--dotnet', default='dotnet')
    args = parser.parse_args()
    output = args.output or args.tools.resolve() / 'AtelierAnimation'
    build('AtelierAnimation', args.tools.resolve(), output, args.dotnet)


if __name__ == '__main__':
    main()
