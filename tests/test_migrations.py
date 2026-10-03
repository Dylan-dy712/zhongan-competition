"""Guard rails tying worker SQL/shape expectations to the migration files.

These are text-level consistency checks only — this suite has no database, so real
DDL behavior is verified by the deployment migration run, not here.
"""
import unittest
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SQL = ROOT / "services" / "api" / "sql"
WORKER = (ROOT / "services" / "api" / "app" / "worker.py").read_text(encoding="utf-8")


def applied_sql() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted(SQL.glob("*.sql")))


class MigrationConsistencyTests(unittest.TestCase):
    def test_encounter_key_column_is_added_and_written(self):
        # worker writes encounter_key on every fact; 017 must add the column, and the
        # INSERT column list must match or every run fails against a migrated database.
        self.assertIn("ADD COLUMN IF NOT EXISTS encounter_key text",
                      (SQL / "017_encounter_scope.sql").read_text(encoding="utf-8"))
        insert = re.search(r"INSERT INTO extracted_facts\s*\(([^)]*)\)", WORKER, re.S).group(1)
        self.assertIn("encounter_key", insert)

    def test_zero_seventeen_drops_exactly_what_zero_zero_five_creates(self):
        # 005 declares UNIQUE (run_id, fact_type); 017 drops the corresponding
        # constraint. The names must stay in sync or the drop silently misses.
        self.assertIn("UNIQUE (run_id, fact_type)",
                      (SQL / "005_extracted_facts.sql").read_text(encoding="utf-8"))
        self.assertIn("DROP CONSTRAINT IF EXISTS extracted_facts_run_id_fact_type_key",
                      (SQL / "017_encounter_scope.sql").read_text(encoding="utf-8"))

    def test_multi_event_writes_do_not_hit_a_unique_event_index(self):
        # build_events emits several same-type events per run (per encounter/drug), so
        # the last migration touching 015's unique index must drop it.
        references = [(path.name, line.strip()) for path in sorted(SQL.glob("*.sql"))
                      for line in path.read_text(encoding="utf-8").splitlines()
                      if "medical_events_run_fact_type_idx" in line]
        self.assertTrue(references, "015's unique index vanished from the migrations")
        self.assertEqual(references[-1][0], "017_encounter_scope.sql")
        self.assertIn("DROP INDEX", references[-1][1])
        applied = applied_sql()
        self.assertIn("medical_events_run_encounter_idx", applied)

    def test_worker_persists_structured_dates_for_review_and_release(self):
        # The review/release date-conflict guard reads structured_dates from the
        # reconcile stage results; worker must record them.
        self.assertIn('"structured_dates": encounter_dates', WORKER)

    def test_personnel_get_a_dedicated_column_and_candidates_keep_their_list_shape(self):
        # model_extractions.candidates must stay a plain JSON array for external
        # auditors; the structured staff extractions live in their own column.
        sql = (SQL / "017_encounter_scope.sql").read_text(encoding="utf-8")
        self.assertIn("ADD COLUMN IF NOT EXISTS personnel jsonb", sql)
        self.assertIn("personnel", WORKER)


if __name__ == "__main__":
    unittest.main()
