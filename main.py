import argparse
from collections.abc import Iterable
from pathlib import Path

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from rdflib import Graph, Literal, Namespace, RDF, RDFS, OWL, URIRef, XSD
import re
from typing import List, Optional
from pydantic import BaseModel, Field
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter


XSD_TYPE_MAP = {
    "string": XSD.string,
    "float": XSD.float,
    "double": XSD.double,
    "integer": XSD.integer,
    "int": XSD.integer,
    "boolean": XSD.boolean,
    "datetime": XSD.dateTime,
    "date": XSD.date,
}


class ConceptClass(BaseModel):
    name: str = Field(description="PascalCase name of the class, e.g. 'TemperatureSensor'")
    parent_class: Optional[str] = Field(None, description="Parent class name, e.g. 'Sensor'")
    description: str = Field(description="Definition of the concept")


class ObjectProperty(BaseModel):
    name: str = Field(description="camelCase relation between classes, e.g. 'hasSensor'")
    domain: str = Field(description="Source class name, e.g. 'DigitalTwin'")
    range: str = Field(description="Target class name, e.g. 'Sensor'")
    description: str = Field(description="Description of the relationship")


class DataProperty(BaseModel):
    name: str = Field(description="camelCase attribute name, e.g. 'temperatureValue' or 'serialNumber'")
    domain: str = Field(description="Class that owns this attribute, e.g. 'TemperatureSensor'")
    data_type: str = Field(
        description="Primitive data type: string, float, integer, boolean, or dateTime"
    )
    description: str = Field(description="Description of the data attribute")


class OntologySchema(BaseModel):
    classes: List[ConceptClass] = Field(default_factory=list)
    object_properties: List[ObjectProperty] = Field(default_factory=list)
    data_properties: List[DataProperty] = Field(default_factory=list)


def extract_ontology_from_text(text: str) -> OntologySchema:
    llm = ChatOpenAI(model="gpt-4o", temperature=0)
    structured_llm = llm.with_structured_output(OntologySchema)

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You are an expert ontology engineer. Extract domain concepts, class hierarchies (subClassOf), and object properties from the text into a formal ontology model.",
            ),
            ("human", "{document}"),
        ]
    )

    chain = prompt | structured_llm
    return chain.invoke({"document": text})


def clean_identifier(name: str) -> str:
    """Sanitise strings into valid URI local names."""
    return re.sub(r"[^a-zA-Z0-9_]", "", name.strip().title().replace(" ", ""))


def build_turtle_file(extracted: OntologySchema, base_uri: str, output_filepath: str):
    g = Graph()

    EX = Namespace(base_uri)
    g.bind("ex", EX)
    g.bind("owl", OWL)
    g.bind("rdfs", RDFS)
    g.bind("xsd", XSD)

    # Ontology metadata
    g.add((URIRef(base_uri), RDF.type, OWL.Ontology))

    # 1. Add Classes
    for cls in extracted.classes:
        class_name = clean_identifier(cls.name)
        class_uri = EX[class_name]

        g.add((class_uri, RDF.type, OWL.Class))
        g.add((class_uri, RDFS.label, Literal(cls.name)))
        g.add((class_uri, RDFS.comment, Literal(cls.description)))

        if cls.parent_class:
            g.add((class_uri, RDFS.subClassOf, EX[clean_identifier(cls.parent_class)]))

    # 2. Add Object Properties (Class-to-Class relations)
    for prop in extracted.object_properties:
        prop_name = clean_identifier(prop.name)
        prop_name = prop_name[0].lower() + prop_name[1:] if prop_name else prop_name
        prop_uri = EX[prop_name]

        g.add((prop_uri, RDF.type, OWL.ObjectProperty))
        g.add((prop_uri, RDFS.label, Literal(prop.name)))
        g.add((prop_uri, RDFS.comment, Literal(prop.description)))

        if prop.domain:
            g.add((prop_uri, RDFS.domain, EX[clean_identifier(prop.domain)]))
        if prop.range:
            g.add((prop_uri, RDFS.range, EX[clean_identifier(prop.range)]))

    # 3. Add Data Properties (Class-to-Literal attributes)
    for dprop in extracted.data_properties:
        dprop_name = clean_identifier(dprop.name)
        dprop_name = (
            dprop_name[0].lower() + dprop_name[1:] if dprop_name else dprop_name
        )
        dprop_uri = EX[dprop_name]

        g.add((dprop_uri, RDF.type, OWL.DatatypeProperty))
        g.add((dprop_uri, RDFS.label, Literal(dprop.name)))
        g.add((dprop_uri, RDFS.comment, Literal(dprop.description)))

        if dprop.domain:
            g.add((dprop_uri, RDFS.domain, EX[clean_identifier(dprop.domain)]))

        # Assign XSD Range (e.g., xsd:float, xsd:string)
        raw_type = dprop.data_type.lower().strip()
        xsd_range = XSD_TYPE_MAP.get(raw_type, XSD.string)
        g.add((dprop_uri, RDFS.range, xsd_range))

    g.serialize(destination=output_filepath, format="turtle")
    print(f"Ontology saved to {output_filepath}")


def load_and_chunk_pdf(
    pdf_path: str, chunk_size: int = 2500, chunk_overlap: int = 300
):
    loader = PyPDFLoader(pdf_path)
    documents = loader.load()

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    return text_splitter.split_documents(documents)


def merge_ontologies(ontologies: Iterable[OntologySchema]) -> OntologySchema:
    merged_classes = {}
    merged_object_properties = {}
    merged_data_properties = {}

    for extracted in ontologies:
        # Merge Classes (Deduplicate by sanitized name)
        for cls in extracted.classes:
            key = clean_identifier(cls.name)
            if key not in merged_classes:
                merged_classes[key] = cls
            else:
                # Retain parent_class or longer description if available
                existing = merged_classes[key]
                if not existing.parent_class and cls.parent_class:
                    existing.parent_class = cls.parent_class
                if len(cls.description) > len(existing.description):
                    existing.description = cls.description

        # Merge Properties (Deduplicate by sanitized name + domain)
        for prop in extracted.object_properties:
            prop_key = f"{clean_identifier(prop.domain)}_{clean_identifier(prop.name)}"
            if prop_key not in merged_object_properties:
                merged_object_properties[prop_key] = prop

        for prop in extracted.data_properties:
            prop_key = f"{clean_identifier(prop.domain)}_{clean_identifier(prop.name)}"
            if prop_key not in merged_data_properties:
                merged_data_properties[prop_key] = prop

    return OntologySchema(
        classes=list(merged_classes.values()),
        object_properties=list(merged_object_properties.values()),
        data_properties=list(merged_data_properties.values()),
    )


def extract_ontology_from_pdf(pdf_path: str) -> OntologySchema:
    chunks = load_and_chunk_pdf(pdf_path)
    print(f"Loaded '{pdf_path}' split into {len(chunks)} chunks.")

    def extract_chunks():
        for i, chunk in enumerate(chunks):
            print(f"Extracting concepts from chunk {i+1}/{len(chunks)}...")
            yield extract_ontology_from_text(chunk.page_content)

    return merge_ontologies(extract_chunks())


def extract_ontology_from_file(path: Path) -> OntologySchema:
    print(f"Processing '{path}'...")
    if path.suffix.lower() == ".pdf":
        return extract_ontology_from_pdf(str(path))

    content = path.read_text(encoding="utf-8")
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=2500,
        chunk_overlap=300,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    chunks = splitter.split_text(content)
    print(f"Loaded '{path}' split into {len(chunks)} chunks.")
    return merge_ontologies(extract_ontology_from_text(chunk) for chunk in chunks)


def main():
    parser = argparse.ArgumentParser(
        description="Extract an ontology from a file or folder into one Turtle file."
    )
    parser.add_argument("input_path", type=Path, help="Input file or folder")
    parser.add_argument("output_filename", nargs="?", default="base_ontology.ttl")
    args = parser.parse_args()

    if not args.input_path.exists():
        parser.error(f"The path {args.input_path} does not exist.")

    output_path = Path(args.output_filename).resolve()
    if args.input_path.is_dir():
        files = []
        for path in sorted(args.input_path.iterdir()):
            if not path.is_file() or path.resolve() == output_path:
                continue
            if path.suffix.lower() not in {".txt", ".md", ".pdf"}:
                print(f"Skipping unsupported file: {path}")
                continue
            files.append(path)
        if not files:
            parser.error(f"No supported documents found in {args.input_path}.")
    else:
        if args.input_path.resolve() == output_path:
            parser.error("The output file must not overwrite the input file.")
        files = [args.input_path]

    extracted_data = merge_ontologies(
        extract_ontology_from_file(path) for path in files
    )
    build_turtle_file(
        extracted=extracted_data,
        base_uri="http://example.org/digitaltwin#",
        output_filepath=args.output_filename,
    )


if __name__ == "__main__":
    main()
