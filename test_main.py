import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from langchain_core.documents import Document
from rdflib import Graph, Namespace, OWL, RDF, RDFS, XSD

import main


class OntologyTests(unittest.TestCase):
    def test_merge_retains_all_property_types_and_enriches_classes(self):
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
        self.assertEqual(len(merged.classes), 1)
        self.assertEqual(merged.classes[0].parent_class, "Permit")
        self.assertEqual(
            merged.classes[0].description, "Permission to enter the country"
        )
        self.assertEqual(len(merged.object_properties), 1)
        self.assertEqual(len(merged.data_properties), 2)

    def test_folder_writes_one_combined_graph(self):
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

        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "a.md").write_text("Visa", encoding="utf-8")
            (folder / "b.TXT").write_text("Permit", encoding="utf-8")
            (folder / "ignored.bin").write_bytes(b"\xff")
            (folder / "nested").mkdir()
            (folder / "nested" / "ignored.md").write_text("Nested")
            output = folder / "combined.ttl"
            output.write_text("old output")
            with (
                patch("sys.argv", ["main.py", str(folder), str(output)]),
                patch("main.extract_ontology_from_text", side_effect=extract) as llm,
            ):
                main.main()
            self.assertEqual(llm.call_count, 2)
            graph = Graph().parse(output, format="turtle")
            ex = Namespace("http://example.org/digitaltwin#")
            for name in ("Visa", "Permit"):
                self.assertIn((ex[name], RDF.type, OWL.Class), graph)
                self.assertIn((ex.hasholder, RDFS.domain, ex[name]), graph)
                self.assertIn((ex.validdays, RDFS.domain, ex[name]), graph)
            self.assertIn((ex.validdays, RDFS.range, XSD.integer), graph)
            self.assertEqual(len(list(graph.subjects(RDF.type, OWL.Ontology))), 1)

    def test_text_is_chunked_before_extraction(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "long.md"
            path.write_text("Visa requirements. " * 500, encoding="utf-8")
            with patch(
                "main.extract_ontology_from_text",
                return_value=main.OntologySchema(),
            ) as extract:
                main.extract_ontology_from_file(path)
            self.assertGreater(extract.call_count, 1)
            self.assertTrue(
                all(len(call.args[0]) <= 2500 for call in extract.call_args_list)
            )

    def test_pdf_merges_chunk_results(self):
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
        self.assertEqual([cls.name for cls in result.classes], ["Visa", "Permit"])

    def test_invalid_inputs_do_not_write_output(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            output = folder / "output.ttl"
            for source in (folder, folder / "missing"):
                with (
                    self.subTest(source=source),
                    patch("sys.argv", ["main.py", str(source), str(output)]),
                    self.assertRaises(SystemExit) as error,
                ):
                    main.main()
                self.assertEqual(error.exception.code, 2)
                self.assertFalse(output.exists())

    def test_single_file_and_default_output_remain_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.txt"
            source.write_text("Visa", encoding="utf-8")
            with (
                patch("sys.argv", ["main.py", str(source)]),
                patch("main.extract_ontology_from_text",
                      return_value=main.OntologySchema()) as extract,
                patch("main.build_turtle_file") as build,
            ):
                main.main()
            extract.assert_called_once_with("Visa")
            self.assertEqual(
                build.call_args.kwargs["output_filepath"], "base_ontology.ttl"
            )

    def test_extraction_failure_preserves_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "a.md").write_text("Visa", encoding="utf-8")
            (folder / "b.md").write_text("Permit", encoding="utf-8")
            output = folder / "output.ttl"
            output.write_text("existing ontology")
            with (
                patch("sys.argv", ["main.py", str(folder), str(output)]),
                patch("main.extract_ontology_from_text",
                      side_effect=[main.OntologySchema(), RuntimeError("API failed")]),
                self.assertRaisesRegex(RuntimeError, "API failed"),
            ):
                main.main()
            self.assertEqual(output.read_text(), "existing ontology")


if __name__ == "__main__":
    unittest.main()
