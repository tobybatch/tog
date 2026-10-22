import json
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


def test_visualizer_graph_matches_ontology_graph_shape(tmp_path):
    schema = main.OntologySchema(
        classes=[
            main.ConceptClass(
                name="Visa",
                parent_class="Permit",
                description="Permission to enter a country",
            )
        ],
        individuals=[
            main.NamedIndividual(
                name="UKVCAS",
                instance_of="Visa",
                description="An application service",
            )
        ],
        object_properties=[
            main.ObjectProperty(
                name="requiresEvidence",
                domain="Visa",
                range="Document",
                description="Evidence required for an application",
            )
        ],
        data_properties=[
            main.DataProperty(
                name="validDays",
                domain="Visa",
                data_type="integer",
                description="Validity period",
            )
        ],
    )
    output = tmp_path / "graph.json"

    main.build_visualizer_graph(
        schema, "http://example.org/digitaltwin#", str(output)
    )

    graph = json.loads(output.read_text(encoding="utf-8"))
    entities = {entity["label"]: entity for entity in graph["entities"]}
    relationships = {
        (rel["type"], rel["from"], rel["to"]) for rel in graph["relationships"]
    }
    assert graph["domain"] == "digitaltwin"
    assert graph["schema_version"]
    assert {"Visa", "Permit", "UKVCAS", "Document"} == set(entities)
    assert entities["Visa"]["properties"]["dataProperties"][0]["name"] == "validDays"
    assert (
        "subClassOf",
        entities["Visa"]["id"],
        entities["Permit"]["id"],
    ) in relationships
    assert (
        "instanceOf",
        entities["UKVCAS"]["id"],
        entities["Visa"]["id"],
    ) in relationships
    assert (
        "requiresEvidence",
        entities["Visa"]["id"],
        entities["Document"]["id"],
    ) in relationships
    assert all(
        {"id", "canonical_key", "label", "aliases", "type", "properties", "metadata"}
        <= entity.keys()
        for entity in graph["entities"]
    )
    assert all(
        {"id", "type", "from", "to", "properties", "metadata"} <= rel.keys()
        for rel in graph["relationships"]
    )


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
        patch("main.build_visualizer_graph") as build_graph,
    ):
        main.main()

    extract.assert_called_once_with("Visa")
    assert (
        build.call_args.kwargs["output_filepath"]
        == main.DEFAULT_GENERATED_ONTOLOGY_FILENAME
    )
    assert build_graph.call_args.kwargs["output_filepath"].endswith(
        "generated-ontologies/graph.json"
    )


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


def test_named_individuals_and_primitive_range_conversion(tmp_path):
    schema = main.OntologySchema(
        classes=[main.ConceptClass(name="Service", description="A public service")],
        individuals=[
            main.NamedIndividual(
                name="UKVCAS",
                instance_of="Service",
                description="UK Visa and Citizenship Application Services",
            )
        ],
        object_properties=[
            main.ObjectProperty(
                name="canBringDependants",
                domain="Person",
                range="Boolean",
                description="Whether a person can bring dependants",
            ),
            main.ObjectProperty(
                name="appliesFor",
                domain="Person",
                range="Visa",
                description="Person applies for a visa",
            ),
        ],
    )

    merged = main.merge_ontologies([schema])
    assert len(merged.individuals) == 1
    assert merged.individuals[0].name == "UKVCAS"

    # canBringDependants should be converted to data_properties with boolean type
    assert any(
        dp.name == "canBringDependants" and dp.data_type == "boolean"
        for dp in merged.data_properties
    )
    # appliesFor should remain an object_property
    assert any(op.name == "appliesFor" for op in merged.object_properties)

    output = tmp_path / "ontology.ttl"
    main.build_turtle_file(merged, "http://example.org/digitaltwin#", str(output))

    graph = Graph().parse(output, format="turtle")
    ex = Namespace("http://example.org/digitaltwin#")

    # Check UKVCAS individual
    ukvcas_uri = ex[main.clean_identifier("UKVCAS")]
    assert (ukvcas_uri, RDF.type, OWL.NamedIndividual) in graph
    assert (ukvcas_uri, RDF.type, ex.Service) in graph
    assert (ukvcas_uri, RDFS.label, None) in graph
    assert (ukvcas_uri, RDFS.comment, None) in graph

    # Check Person and Visa were auto-declared with labels & comments
    assert (ex.Person, RDF.type, OWL.Class) in graph
    assert (ex.Person, RDFS.label, None) in graph
    assert (ex.Visa, RDF.type, OWL.Class) in graph
    assert (ex.Visa, RDFS.label, None) in graph

    # Check canBringDependants has xsd:boolean range
    assert (ex.canbringdependants, RDF.type, OWL.DatatypeProperty) in graph
    assert (ex.canbringdependants, RDFS.range, XSD.boolean) in graph


def test_circular_and_self_parent_classes_are_sanitized(tmp_path):
    schema = main.OntologySchema(
        classes=[
            main.ConceptClass(
                name="Commitment",
                parent_class="Commitment",
                description="An ongoing commitment",
            ),
            main.ConceptClass(
                name="Ancestry",
                parent_class="Thing",
                description="Ancestry claim",
            ),
        ]
    )

    merged = main.merge_ontologies([schema])
    assert merged.classes[0].parent_class is None
    assert merged.classes[1].parent_class is None

    output = tmp_path / "cycle.ttl"
    main.build_turtle_file(merged, "http://example.org/digitaltwin#", str(output))

    graph = Graph().parse(output, format="turtle")
    ex = Namespace("http://example.org/digitaltwin#")

    assert (ex.Commitment, RDF.type, OWL.Class) in graph
    assert (ex.Commitment, RDFS.subClassOf, ex.Commitment) not in graph
    assert (ex.Ancestry, RDFS.subClassOf, ex.Thing) not in graph


def test_text_extraction_uses_configured_local_ollama(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.local:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5:7b")
    schema = main.OntologySchema()
    with (
        patch("main.ChatOllama") as chat_ollama,
        patch("main.ChatPromptTemplate.from_messages") as from_messages,
    ):
        structured_llm = chat_ollama.return_value.with_structured_output.return_value
        chain = from_messages.return_value.__or__.return_value
        chain.invoke.return_value = schema

        result = main.extract_ontology_from_text("Visa requirements")

    chat_ollama.assert_called_once_with(
        model="qwen2.5:7b",
        base_url="http://ollama.local:11434",
        temperature=0,
    )
    chat_ollama.return_value.with_structured_output.assert_called_once_with(
        main.OntologySchema, method="json_schema"
    )
    from_messages.return_value.__or__.assert_called_once_with(structured_llm)
    chain.invoke.assert_called_once_with({"document": "Visa requirements"})
    assert result is schema
