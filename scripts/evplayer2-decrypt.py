"""EVPlayer2 experimental CLI: python scripts/evplayer2-decrypt.py --help."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from evplayer_unlocker.cli import main

if __name__ == "__main__":
    sys.argv.insert(1, "export-player2")
    raise SystemExit(main())
