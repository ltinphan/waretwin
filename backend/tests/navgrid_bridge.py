"""Test-only JSON bridge for byte-for-byte TypeScript/Python grid comparison."""
import json
import sys
from app.sim.navgrid import build_nav_grid

if __name__ == '__main__':
    cases = json.load(sys.stdin)
    print(json.dumps([list(build_nav_grid(case['layout'], case['floor']).cells) for case in cases]))
