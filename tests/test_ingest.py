from fedsight.ingest import gao_document, pack, split_long, walk_sections


def test_split_long_keeps_sentences_whole():
    para = " ".join(f"This is sentence number {i} about disaster funding." for i in range(60))
    pieces = split_long(para, limit=300)
    assert len(pieces) > 5
    assert all(len(p) <= 450 for p in pieces)
    assert all(p.endswith(".") for p in pieces)


def test_pack_merges_small_leftover_and_respects_limit():
    paras = ["Short opening paragraph about FEMA staffing levels in 2017.", "x " * 400]
    passages = pack(paras, limit=500)
    assert all(len(p) < 1100 for p in passages)
    assert "FEMA staffing" in passages[0]


def test_pack_collapses_whitespace():
    assert pack(["Thank you for the   opportunity\nto discuss this."]) == ["Thank you for the opportunity to discuss this."]


def test_walk_sections_builds_paths_and_skips_staff_credits():
    tree = [{"section_title": "Letter", "paragraphs": ["Intro."], "subsections": [
        {"section_title": "Background", "paragraphs": ["Some background."], "subsections": []},
        {"section_title": "GAO Contacts and Staff Acknowledgments", "paragraphs": ["Call us."], "subsections": []},
    ]}]
    got = dict(walk_sections(tree))
    assert list(got) == ["Letter", "Letter > Background"]


def test_gao_document_ids_and_highlights_first():
    report = {
        "id": "GAO-19-999", "title": "Disaster Aid:  Better Data Needed", "url": "https://www.gao.gov/products/GAO-19-999",
        "published_date": "2019-05-01T00:00:00",
        "highlight": [{"section_title": "What GAO Found", "paragraphs": ["FEMA data were incomplete."]}],
        "report": [{"section_title": "Letter", "paragraphs": ["Body text here that is long enough to matter."],
                    "subsections": []}],
    }
    doc, passages = gao_document(report)
    assert doc["doc_id"] == "GAO-19-999" and doc["date"] == "2019-05-01"
    assert doc["title"] == "GAO-19-999: Disaster Aid: Better Data Needed"
    assert passages[0]["section"] == "Highlights > What GAO Found"
    assert [p["id"] for p in passages] == ["GAO-19-999-001", "GAO-19-999-002"]
    assert all(p["source"] == "gao" and p["page"] is None for p in passages)


def test_table_appendices_are_dropped_but_methodology_is_kept():
    tree = [
        {"section_title": "Letter", "paragraphs": ["Findings."], "subsections": []},
        {"section_title": "Appendix I: Objectives, Scope, and Methodology", "paragraphs": ["We interviewed officials."],
         "subsections": []},
        {"section_title": "Appendix II: Program Fact Sheets", "paragraphs": ["Row after row of numbers."],
         "subsections": [{"section_title": "Sheet A", "paragraphs": ["More rows."], "subsections": []}]},
        {"section_title": "Appendix III: Comments from the Department of Homeland Security",
         "paragraphs": ["DHS concurred."], "subsections": []},
    ]
    assert [s for s, _ in walk_sections(tree)] == [
        "Letter", "Appendix I: Objectives, Scope, and Methodology",
        "Appendix III: Comments from the Department of Homeland Security"]
