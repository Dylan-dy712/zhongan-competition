"""Pure-assembly tests for the authoritative quality export (no database)."""
import unittest
from datetime import date
from uuid import uuid5, NAMESPACE_URL, uuid4

from services.api.app.quality_export import (
    assemble_records, draft_policy, entity_uuid, normalized_entity_name,
)
from services.api.app.quality_profiles import MetricPolicy


def row(**over):
    base = {
        "entity_id": "h-1", "display_name": "合成市第一医院",
        "encounter_id": str(uuid5(uuid4(), "encounter:primary")),
        "subject_ref": "psd-1", "observed_date": date(2026, 10, 1),
        "total_minor": 12000, "evidence_ids": ["11111111-1111-1111-1111-111111111111"],
    }
    base.update(over)
    return base


class TestEntityIdentity(unittest.TestCase):
    def test_normalized_and_stable(self):
        self.assertEqual(normalized_entity_name(" 合成市第一医院 "), "合成市第一医院")
        self.assertEqual(entity_uuid("hospital", "A院"), entity_uuid("hospital", "a院"))
        self.assertNotEqual(entity_uuid("hospital", "A院"), entity_uuid("doctor", "A院"))


class TestDraftPolicy(unittest.TestCase):
    def test_draft_is_not_frozen_and_has_no_placeholder_review(self):
        policy = draft_policy(date(2026, 1, 1), date(2026, 2, 1), min_sample_size=5, max_missing_rate=0.2)
        self.assertEqual(policy.status, "draft")
        with self.assertRaises(Exception):
            MetricPolicy(**{**policy.model_dump(mode="json"), "status": "frozen"})


class TestAssembleRecords(unittest.TestCase):
    def test_exports_only_cost_level_and_records_proxy_limitations(self):
        entities, records, limitations = assemble_records([row()])
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].total_cost_minor.value, 12000)
        self.assertEqual([a.metrics for a in records[0].attributions], [["cost_level"]])
        self.assertEqual(records[0].disease_group.value, "TY")
        self.assertTrue(any("代理" in x for x in limitations))
        self.assertTrue(any("仅导出费用水平" in x for x in limitations))

    def test_row_without_total_or_evidence_is_dropped(self):
        _, records, _ = assemble_records([row(total_minor=None)])
        self.assertEqual(records, [])
        _, records2, _ = assemble_records([row(evidence_ids=[])])
        self.assertEqual(records2, [])

    def test_subject_ref_passes_through_as_already_pseudonymized(self):
        # The hash-to-pseudonym step lives in export_quality_input (SQL stage);
        # assemble_records must pass the private ref through untouched.
        _, records, _ = assemble_records([row()])
        self.assertEqual(records[0].subject_ref, "psd-1")


if __name__ == "__main__":
    unittest.main()
