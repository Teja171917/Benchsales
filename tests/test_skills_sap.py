"""SAP lexicon (Nov 13 2026): the curated skill list had "sap" as
its only SAP term, so a SAP IS-U/ABAP resume (Yogeeta's, added to
RSATECH that day) extracted 13 generic skills — crm, jira, sql —
and none of her actual specialty, leaving her invisible to SAP
matching. The lexicon now carries the SAP/ERP module vocabulary;
these tests pin the extraction against text taken from that resume.
"""
import unittest

from app import skills

RESUME_SNIPPET = (
    "SAP ISU Analyst with 5+ years of experience in implementing SAP "
    "solutions. 12 + years of Experience in SAP ABAP. Technical skills "
    "of working in ABAP for RICEFW objects, Idocs, good understanding "
    "of using LSMW for conversion process. BDC's to automate any "
    "transaction input in SAP. Skills Technology: SAP, FICA, Fieldnet, "
    "M5, ISU, Device management, MDMS SAP, IEE, Smart Meter, COUPA, "
    "ABAP, BAPI, BADI, IDocs, Module pool, Enhancements, User Exit, "
    "REST API, Oracle SQL, Service Now, Charm, Jira, HP ALM. "
    "Regression test AMI SAP and IEE for Device creation. Verify "
    "Inbound and Outbound messages in ECC. Well versed with ISU SAP "
    "Data models. Worked on meter-to-cash lifecycle processes."
)


class SapExtractionTests(unittest.TestCase):
    def test_isu_abap_resume_extracts_her_specialty(self):
        found = set(skills.extract_skills(RESUME_SNIPPET))
        for want in ("abap", "sap abap", "sap is-u", "fica", "idoc",
                     "lsmw", "bdc", "bapi", "badi", "ricefw",
                     "module pool", "smart meter", "ami",
                     "device management", "mdms", "meter-to-cash",
                     "coupa", "hp alm", "fieldnet", "sap ecc"):
            self.assertIn(want, found, f"missing skill: {want}")
        # the generic skills the old lexicon DID catch still extract
        for want in ("sap", "jira", "sql", "rest api"):
            self.assertIn(want, found)

    def test_alias_canonicals_all_exist_in_skills(self):
        for alias, canonical in skills.ALIASES.items():
            self.assertIn(canonical, skills.SKILLS,
                          f"alias {alias!r} -> {canonical!r} not in SKILLS")

    def test_sap_terms_appear_exactly_once(self):
        # (the pre-existing lexicon already repeats a couple of
        # general terms across sections — harmless for extraction;
        # the SAP block must not add new duplicates)
        for term in ("abap", "sap is-u", "fica", "idoc", "lsmw",
                     "coupa", "hp alm", "sap ecc", "s/4hana"):
            self.assertEqual(skills.SKILLS.count(term), 1, term)


if __name__ == "__main__":
    unittest.main()
