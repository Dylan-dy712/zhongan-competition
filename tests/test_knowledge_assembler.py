"""Knowledge assembler contract tests (T19 消费侧).

The assembler loads the compiled contracts/knowledge/entries.jsonl produced by
tools/build_knowledge_jsonl.py; tests assert the two hard gates and the
selection semantics documented in docs/medical/knowledge-manifest.md.
"""

import unittest

from services.api.app.contracts.knowledge import DiseaseCode
from services.api.app.knowledge_assembler import (
    KnowledgeAssembler,
    PackExcludedError,
    UnknownDiseaseError,
)


class KnowledgeAssemblerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.assembler = KnowledgeAssembler()

    def test_loads_all_compiled_entries(self) -> None:
        self.assertGreaterEqual(self.assembler.entries_total, 599)

    def test_five_disease_packs_and_ty_resolved(self) -> None:
        for code in (
            DiseaseCode.fx,
            DiseaseCode.fy,
            DiseaseCode.gx,
            DiseaseCode.yz,
            DiseaseCode.tn,
            DiseaseCode.ty,
        ):
            scope = self.assembler.pack_scope(code)
            self.assertTrue(scope.pack_id.startswith("KP-"))
            self.assertGreater(scope.entries_total, 0)

    def test_unknown_disease_raises(self) -> None:
        class UnknownCode:
            value = "ZZ"

        with self.assertRaises(UnknownDiseaseError):
            self.assembler.pack_scope(UnknownCode())  # type: ignore[arg-type]

    def test_pack_scope_carries_exclusions(self) -> None:
        scope = self.assembler.pack_scope(DiseaseCode.tn)
        self.assertIsNotNone(scope.exclusions)
        self.assertIn("1型糖尿病", scope.exclusions or "")

    def test_exclusion_keyword_scan_routes_to_human(self) -> None:
        with self.assertRaises(PackExcludedError):
            self.assembler.check_exclusions(DiseaseCode.tn, "患者本次住院诊断含1型糖尿病相关记录")

    def test_purpose_filter_returns_medication_entries(self) -> None:
        entries = self.assembler.entries_for(
            DiseaseCode.gx, purpose="用药疑点标签"
        )
        self.assertGreaterEqual(len(entries), 8)
        # S4 用药规则是主槽位；S2 术语/S7 随访条目可合法携带同一用途
        self.assertTrue(any(e.slot == "S4" for e in entries))
        self.assertTrue(all(e.slot in {"S2", "S4", "S7"} for e in entries))

    def test_patient_visible_blocks_all_drafts(self) -> None:
        selection = self.assembler.select(
            DiseaseCode.fx, slots=("S9",), patient_visible=True
        )
        self.assertEqual(selection.allowed, [])
        self.assertGreater(len(selection.blocked), 0)
        self.assertTrue(all(e.status != "approved" for e in selection.blocked))
        internal = self.assembler.select(
            DiseaseCode.fx, slots=("S9",), patient_visible=False
        )
        self.assertEqual(
            len(selection.allowed) + len(selection.blocked),
            len(internal.allowed),
        )

    def test_patient_visible_gates_knowingly(self) -> None:
        # TN S9 含至少一条数值待审条目（如吸收热阈值），证明阻断逻辑真实生效
        selection = self.assembler.select(
            DiseaseCode.tn, slots=("S9",), patient_visible=True
        )
        allowed_ids = {e.entry_id for e in selection.allowed}
        internal = self.assembler.select(
            DiseaseCode.tn, slots=("S9",), patient_visible=False
        )
        leaked = [
            e
            for e in internal.allowed
            if e.numeric_pending_review and e.status != "approved" and e.entry_id in allowed_ids
        ]
        self.assertEqual(
            leaked,
            [],
            "no numeric-pending draft entry may survive patient_visible=True",
        )

    def test_knowledge_version_stable_shape(self) -> None:
        self.assertRegex(
            self.assembler.knowledge_version, r"^knowledge:sha256:[0-9a-f]{64}$"
        )

    def test_folded_yaml_scope_is_parsed(self) -> None:
        scope = self.assembler.pack_scope(DiseaseCode.fx)
        self.assertIn("成人常见四肢闭合骨折", scope.scope or "")
        self.assertNotEqual(scope.scope, ">-")


if __name__ == "__main__":
    unittest.main()
