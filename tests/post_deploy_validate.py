"""Post-deploy health checks — run immediately after bot restart."""
import subprocess
import sys


def check_bot_process():
    """Verify bot.py is running."""
    result = subprocess.run(['pgrep', '-f', 'python bot.py'], capture_output=True, text=True)
    assert result.returncode == 0, "bot.py process not found"
    print(f"  bot.py running as PID {result.stdout.strip()}")


def check_bot_log_no_crash():
    """Check last 20 lines of bot log for crash indicators."""
    try:
        with open('/tmp/bot_latest.log', 'r') as f:
            lines = f.readlines()[-20:]
        crash_indicators = ['Traceback', 'CRITICAL', 'Fatal', 'MemoryError']
        for line in lines:
            for indicator in crash_indicators:
                if indicator in line:
                    print(f"  CRASH INDICATOR: {line.strip()}")
                    raise AssertionError(f"Crash indicator found in bot log: {indicator}")
        print("  No crash indicators in last 20 log lines")
    except FileNotFoundError:
        print("  WARNING: /tmp/bot_latest.log not found (first start?)")


def check_ram():
    """Verify >500MB RAM free."""
    result = subprocess.run(['free', '-m'], capture_output=True, text=True)
    for line in result.stdout.split('\n'):
        if line.startswith('Mem:'):
            parts = line.split()
            available = int(parts[-1])  # last column = available
            assert available > 500, f"RAM too low: {available}MB available (need >500MB)"
            print(f"  RAM OK: {available}MB available")
            return
    raise AssertionError("Could not parse free -m output")


def main():
    print("POST-DEPLOY VALIDATION")
    print("=====================")
    checks = [check_bot_process, check_bot_log_no_crash, check_ram]
    failed = 0
    for check in checks:
        try:
            print(f"\n{check.__doc__}")
            check()
        except (AssertionError, Exception) as e:
            print(f"  FAIL: {e}")
            failed += 1

    print(f"\n{'='*40}")
    if failed:
        print(f"POST-DEPLOY VALIDATION FAILED ({failed} checks failed)")
        sys.exit(1)
    else:
        print("POST-DEPLOY VALIDATION PASSED")


if __name__ == '__main__':
    main()
