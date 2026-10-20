import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class ProductionDeployGateTests(unittest.TestCase):
    def test_release_deploy_runs_production_preflight_before_backup_or_build(self):
        script = (ROOT / "scripts" / "deploy_web_release.sh").read_text(encoding="utf-8")
        preflight = 'check_production_env.py" --mode production --env-file "$DEPLOY_WORKTREE/.env"'
        self.assertIn(preflight, script)
        self.assertNotIn('check_production_env.py" --mode testing', script)
        self.assertLess(script.index(preflight), script.index('mkdir -p "$BACKUP_ROOT"'))
        self.assertLess(script.index(preflight), script.index('"${COMPOSE[@]}" build --pull "$SERVICE"'))

if __name__ == "__main__":
    unittest.main()
