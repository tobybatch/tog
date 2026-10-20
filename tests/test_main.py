from pathlib import Path
from unittest.mock import patch

import pytest
from langchain_core.documents import Document
from rdflib import Graph, Namespace, OWL, RDF, RDFS, XSD

import main


def test_merge_retains_all_property_types_and_enriches_classes():
    first = main.OntologySchema(
        classes=[main.ConceptClass(name="Visa", description="Visa")],
        object_properties=[
            main.ObjectProperty(
                name="hasHolder", domain="Visa", range="Person",
                description="Visa holder",
            )
        ],
        data_properties=[
            main.DataProperty(
                name="validDays", domain="Visa", data_type="integer",
                description="Validity in days",
            )
        ],
    )
    second = first.model_copy(deep=True)
    second.classes[0].parent_class = "Permit"
    second.classes[0].description = "Permission to enter the country"
    second.data_properties.append(
        main.DataProperty(
            name="validDays", domain="Permit", data_type="integer",
            description="Permit validity",
        )
    )

    merged = main.merge_ontologies([first, second])

    assert len(merged.classes) == 1
    assert merged.classes[0].parent_class == "Permit"
    assert merged.classes[0].description == "Permission to enter the country"
    assert len(merged.object_properties) == 1
    assert len(merged.data_properties) == 2


def test_folder_writes_one_combined_graph(tmp_path, monkeypatch):
    def extract(text):
        return main.OntologySchema(
            classes=[main.ConceptClass(name=text, description=text)],
            object_properties=[
                main.ObjectProperty(
                    name="hasHolder", domain=text, range="Person",
                    description="Holder",
                )
            ],
            data_properties=[
                main.DataProperty(
                    name="validDays", domain=text, data_type="integer",
                    description="Validity",
                )
            ],
        )

    folder = tmp_path
    (folder / "a.md").write_text("Visa", encoding="utf-8")
    (folder / "b.TXT").write_text("Permit", encoding="utf-8")
    (folder / "ignored.bin").write_bytes(b"\xff")
    nested = folder / "nested"
    nested.mkdir()
    (nested / "ignored.md").write_text("Nested")
    output = folder / "combined.ttl"
    output.write_text("old output")
    monkeypatch.setattr("sys.argv", ["main.py", str(folder), str(output)])
    with patch("main.extract_ontology_from_text", side_effect=extract) as llm:
        main.main()

    assert llm.call_count == 2
    graph = Graph().parse(output, format="turtle")
    ex = Namespace("http://example.org/digitaltwin#")
    for name in ("Visa", "Permit"):
        assert (ex[name], RDF.type, OWL.Class) in graph
        assert (ex.hasholder, RDFS.domain, ex[name]) in graph
        assert (ex.validdays, RDFS.domain, ex[name]) in graph
    assert (ex.validdays, RDFS.range, XSD.integer) in graph
    assert len(list(graph.subjects(RDF.type, OWL.Ontology))) == 1


def test_text_is_chunked_before_extraction(tmp_path):
    path = tmp_path / "long.md"
    path.write_text("Visa requirements. " * 500, encoding="utf-8")
    with patch(
        "main.extract_ontology_from_text",
        return_value=main.OntologySchema(),
    ) as extract:
        main.extract_ontology_from_file(path)

    assert extract.call_count > 1
    assert all(
        len(call.args[0]) <= 2500 for call in extract.call_args_list
    )


def test_pdf_merges_chunk_results():
    with (
        patch(
            "main.load_and_chunk_pdf",
            return_value=[Document(page_content="Visa"),
                          Document(page_content="Permit")],
        ),
        patch(
            "main.extract_ontology_from_text",
            side_effect=lambda text: main.OntologySchema(
                classes=[main.ConceptClass(name=text, description=text)]
            ),
        ),
    ):
        result = main.extract_ontology_from_file(Path("example.pdf"))

    assert [cls.name for cls in result.classes] == ["Visa", "Permit"]


@pytest.mark.parametrize("source_kind", ["directory", "missing"])
def test_invalid_inputs_do_not_write_output(tmp_path, monkeypatch, source_kind):
    source = tmp_path if source_kind == "directory" else tmp_path / "missing"
    output = tmp_path / "output.ttl"
    monkeypatch.setattr("sys.argv", ["main.py", str(source), str(output)])

    with pytest.raises(SystemExit) as error:
        main.main()

    assert error.value.code == 2
    assert not output.exists()


def test_single_file_and_default_output_remain_supported(tmp_path, monkeypatch):
    source = tmp_path / "input.txt"
    source.write_text("Visa", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["main.py", str(source)])
    with (
        patch(
            "main.extract_ontology_from_text",
            return_value=main.OntologySchema(),
        ) as extract,
        patch("main.build_turtle_file") as build,
    ):
        main.main()

    extract.assert_called_once_with("Visa")
    assert build.call_args.kwargs["output_filepath"] == "base_ontology.ttl"


def test_extraction_failure_preserves_existing_output(tmp_path, monkeypatch):
    (tmp_path / "a.md").write_text("Visa", encoding="utf-8")
    (tmp_path / "b.md").write_text("Permit", encoding="utf-8")
    output = tmp_path / "output.ttl"
    output.write_text("existing ontology")
    monkeypatch.setattr(
        "sys.argv", ["main.py", str(tmp_path), str(output)]
    )

    with (
        patch(
            "main.extract_ontology_from_text",
            side_effect=[main.OntologySchema(), RuntimeError("API failed")],
        ),
        pytest.raises(RuntimeError, match="API failed"),
    ):
        main.main()

    assert output.read_text() == "existing ontology"
