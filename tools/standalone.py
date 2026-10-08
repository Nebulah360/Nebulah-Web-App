"""Optional Windows executable entry point; the bridge remains local."""
import os
import subprocess
import sys
from pathlib import Path


def main():
    root = Path(sys.executable).resolve().parent
    if len(sys.argv) > 1 and sys.argv[1] == '--bridge-child':
        sys.path.insert(0, str(root / 'bridge'))
        import server
        sys.argv = [sys.argv[0], *sys.argv[2:]]
        server.main()
        return 0
    if not getattr(sys, 'frozen', False):
        raise SystemExit('Build the standalone app before running this entry point.')
    env = os.environ.copy()
    env['NEBULAH_STANDALONE_EXE'] = sys.executable
    try:
        return subprocess.call(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                                '-File', str(root / 'tools' / 'start-local.ps1'), *sys.argv[1:]],
                               cwd=root, env=env)
    except FileNotFoundError as error:
        raise SystemExit('Windows PowerShell is required for Xbox 360 Neighborhood.') from error
    except KeyboardInterrupt:
        return 0


if __name__ == '__main__':
    sys.exit(main())
