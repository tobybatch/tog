import argparse
from collections.abc import Iterable
import json
import os
from pathlib import Path

from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama
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

DEFAULT_GENERATED_ONTOLOGY_FILENAME = "generated-ontologies/generated_ontology.ttl"


class ConceptClass(BaseModel):
    name: str = Field(description="PascalCase name of the class, e.g. 'TemperatureSensor' or 'VisaApplication'")
    parent_class: Optional[str] = Field(None, description="Parent class name, e.g. 'Sensor' or 'Application'. Do NOT set to self or owl:Thing/Thing/Entity.")
    description: str = Field(description="Clear definition of the concept/class")


class NamedIndividual(BaseModel):
    name: str = Field(description="PascalCase identifier for a specific instance/individual, e.g. 'UKVCAS' or 'UnitedKingdom'")
    instance_of: str = Field(description="Class name of which this individual is an instance, e.g. 'Service' or 'Country'")
    description: str = Field(description="Definition or description of the specific individual")


class ObjectProperty(BaseModel):
    name: str = Field(description="camelCase relation between classes/individuals, e.g. 'hasSensor' or 'requiresEvidence'")
    domain: str = Field(description="Source class name, e.g. 'Person'")
    range: str = Field(description="Target class name, e.g. 'Passport'. NEVER use primitive datatypes like boolean, string, integer, or Boolean here.")
    description: str = Field(description="Description of the relationship")


class DataProperty(BaseModel):
    name: str = Field(description="camelCase attribute name, e.g. 'temperatureValue', 'canWork', or 'serialNumber'")
    domain: str = Field(description="Class that owns this attribute, e.g. 'Person'")
    data_type: str = Field(
        description="Primitive data type: string, float, integer, boolean, date, or dateTime"
    )
    description: str = Field(description="Description of the data attribute")


class OntologySchema(BaseModel):
    classes: List[ConceptClass] = Field(default_factory=list)
    individuals: List[NamedIndividual] = Field(default_factory=list)
    object_properties: List[ObjectProperty] = Field(default_factory=list)
    data_properties: List[DataProperty] = Field(default_factory=list)


ONTOLOGY_SYSTEM_PROMPT = (
    "You are an expert ontology engineer building a formal OWL 2 ontology.\n"
    "Extract domain concepts, class hierarchies (subClassOf), named individuals, object properties, "
    "and datatype properties from the text according to strict ontological principles:\n\n"
    "1. CLASSES vs INDIVIDUALS:\n"
    "- A Class (ConceptClass) represents a category or concept (e.g., 'VisaApplication', 'Evidence', 'Fee', 'Service', 'Country').\n"
    "- A NamedIndividual represents a specific, singular real-world entity, service, location, or organization instance (e.g., 'UKVCAS' is an instance of 'Service', 'UnitedKingdom' or 'UK' is an instance of 'Country'). Do NOT create classes for unique entities.\n\n"
    "2. OBJECT vs DATA PROPERTIES:\n"
    "- ObjectProperty: Relates a Class/Individual to another Class/Individual (e.g., 'hasApplicant', 'requiresEvidence').\n"
    "- DataProperty: Relates a Class/Individual to a primitive literal value (e.g., 'age' -> integer, 'canWork' -> boolean, 'decisionDate' -> date).\n"
    "- NEVER use primitive types like 'Boolean', 'String', 'Integer', or 'Date' as the range of an ObjectProperty. Use DataProperty instead.\n\n"
    "3. TAXONOMY & HIERARCHY:\n"
    "- Avoid creating redundant generic meta-classes like 'Thing', 'Object', or 'Entity' (owl:Thing is already the implicit root).\n"
    "- Never make a class a subclass of itself (e.g., 'Commitment' cannot have parent_class 'Commitment').\n"
    "- Ensure every class referenced in domains, ranges, parent classes, or individual types is well-defined with a clear description."
)


def extract_ontology_from_text(text: str) -> OntologySchema:
    llm = ChatOllama(
        model=os.getenv("OLLAMA_MODEL", "llama3.1"),
        base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        temperature=0,
    )
    structured_llm = llm.with_structured_output(
        OntologySchema, method="json_schema"
    )

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", ONTOLOGY_SYSTEM_PROMPT),
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

    declared_classes = set()
    declared_individuals = set()

    def ensure_class_declared(raw_name: str):
        c_name = clean_identifier(raw_name)
        if not c_name or c_name.lower() in {"thing", "owlthing"}:
            return
        c_uri = EX[c_name]
        if c_uri not in declared_classes and c_uri not in declared_individuals:
            g.add((c_uri, RDF.type, OWL.Class))
            g.add((c_uri, RDFS.label, Literal(raw_name.strip())))
            g.add((c_uri, RDFS.comment, Literal(f"A class representing {raw_name.strip()}.")))
            declared_classes.add(c_uri)

    # 1. Add Classes
    for cls in extracted.classes:
        class_name = clean_identifier(cls.name)
        if not class_name:
            continue
        class_uri = EX[class_name]

        g.add((class_uri, RDF.type, OWL.Class))
        g.add((class_uri, RDFS.label, Literal(cls.name)))
        g.add((class_uri, RDFS.comment, Literal(cls.description)))
        declared_classes.add(class_uri)

        if cls.parent_class:
            parent_name = clean_identifier(cls.parent_class)
            # Avoid self-loops and redundant owl:Thing/Thing loops
            if parent_name and parent_name != class_name and parent_name.lower() not in {"thing", "owlthing"}:
                parent_uri = EX[parent_name]
                ensure_class_declared(cls.parent_class)
                g.add((class_uri, RDFS.subClassOf, parent_uri))

    # 2. Add Named Individuals (Instances)
    for ind in extracted.individuals:
        ind_name = clean_identifier(ind.name)
        if not ind_name:
            continue
        ind_uri = EX[ind_name]

        g.add((ind_uri, RDF.type, OWL.NamedIndividual))
        if ind.instance_of:
            instance_of_name = clean_identifier(ind.instance_of)
            if instance_of_name:
                ensure_class_declared(ind.instance_of)
                g.add((ind_uri, RDF.type, EX[instance_of_name]))
        g.add((ind_uri, RDFS.label, Literal(ind.name)))
        g.add((ind_uri, RDFS.comment, Literal(ind.description)))
        declared_individuals.add(ind_uri)

    # 3. Add Object Properties (Class-to-Class relations)
    for prop in extracted.object_properties:
        prop_name = clean_identifier(prop.name)
        if not prop_name:
            continue
        prop_name = prop_name[0].lower() + prop_name[1:] if prop_name else prop_name
        prop_uri = EX[prop_name]

        g.add((prop_uri, RDF.type, OWL.ObjectProperty))
        g.add((prop_uri, RDFS.label, Literal(prop.name)))
        g.add((prop_uri, RDFS.comment, Literal(prop.description)))

        if prop.domain:
            domain_name = clean_identifier(prop.domain)
            if domain_name:
                ensure_class_declared(prop.domain)
                g.add((prop_uri, RDFS.domain, EX[domain_name]))
        if prop.range:
            range_name = clean_identifier(prop.range)
            if range_name:
                ensure_class_declared(prop.range)
                g.add((prop_uri, RDFS.range, EX[range_name]))

    # 4. Add Data Properties (Class-to-Literal attributes)
    for dprop in extracted.data_properties:
        dprop_name = clean_identifier(dprop.name)
        if not dprop_name:
            continue
        dprop_name = (
            dprop_name[0].lower() + dprop_name[1:] if dprop_name else dprop_name
        )
        dprop_uri = EX[dprop_name]

        g.add((dprop_uri, RDF.type, OWL.DatatypeProperty))
        g.add((dprop_uri, RDFS.label, Literal(dprop.name)))
        g.add((dprop_uri, RDFS.comment, Literal(dprop.description)))

        if dprop.domain:
            domain_name = clean_identifier(dprop.domain)
            if domain_name:
                ensure_class_declared(dprop.domain)
                g.add((dprop_uri, RDFS.domain, EX[domain_name]))

        # Assign XSD Range (e.g., xsd:float, xsd:string)
        raw_type = dprop.data_type.lower().strip()
        xsd_range = XSD_TYPE_MAP.get(raw_type, XSD.string)
        g.add((dprop_uri, RDFS.range, xsd_range))

    g.serialize(destination=output_filepath, format="turtle")
    print(f"Ontology saved to {output_filepath}")


def build_visualizer_graph(
    extracted: OntologySchema, base_uri: str, output_filepath: str
) -> None:
    """Write the extracted ontology in the visualizer's OntologyGraph JSON shape."""
    entities: dict[str, dict] = {}
    relationships: list[dict] = []
    entity_ids: dict[tuple[str, str], str] = {}

    def add_entity(name: str, kind: str, description: str = "") -> str | None:
        key = clean_identifier(name)
        if not key:
            return None
        entity_id = f"{kind.lower()}:{key}"
        entity_ids[(kind, key)] = entity_id
        entities.setdefault(
            entity_id,
            {
                "id": entity_id,
                "canonical_key": f"{base_uri}{key}",
                "label": name.strip(),
                "aliases": [],
                "type": kind,
                "description": description or None,
                "properties": {},
                "metadata": {},
            },
        )
        if description and not entities[entity_id]["description"]:
            entities[entity_id]["description"] = description
        return entity_id

    def add_relationship(
        relationship_type: str,
        source_id: str | None,
        target_id: str | None,
        description: str = "",
    ) -> None:
        if source_id is None or target_id is None:
            return
        relationships.append(
            {
                "id": f"relationship:{len(relationships) + 1}",
                "type": relationship_type,
                "from": source_id,
                "to": target_id,
                "properties": {"description": description} if description else {},
                "metadata": {},
            }
        )

    class_ids: dict[str, str] = {}
    for concept in extracted.classes:
        entity_id = add_entity(concept.name, "Class", concept.description)
        if entity_id is not None:
            class_ids[clean_identifier(concept.name)] = entity_id

    for individual in extracted.individuals:
        add_entity(individual.name, "Individual", individual.description)

    for concept in extracted.classes:
        source_id = class_ids.get(clean_identifier(concept.name))
        if concept.parent_class:
            parent_key = clean_identifier(concept.parent_class)
            parent_id = class_ids.get(parent_key) or add_entity(concept.parent_class, "Class")
            add_relationship("subClassOf", source_id, parent_id)

    for individual in extracted.individuals:
        individual_id = entity_ids.get(("Individual", clean_identifier(individual.name)))
        class_key = clean_identifier(individual.instance_of)
        class_id = class_ids.get(class_key) or add_entity(
            individual.instance_of, "Class"
        )
        add_relationship("instanceOf", individual_id, class_id)

    for prop in extracted.object_properties:
        domain_key = clean_identifier(prop.domain)
        range_key = clean_identifier(prop.range)
        domain_id = class_ids.get(domain_key) or add_entity(prop.domain, "Class")
        range_id = class_ids.get(range_key) or add_entity(prop.range, "Class")
        add_relationship(prop.name, domain_id, range_id, prop.description)

    for prop in extracted.data_properties:
        domain_key = clean_identifier(prop.domain)
        domain_id = class_ids.get(domain_key) or add_entity(prop.domain, "Class")
        if domain_id is not None:
            entities[domain_id]["properties"].setdefault("dataProperties", []).append(
                {
                    "name": prop.name,
                    "data_type": prop.data_type,
                    "description": prop.description,
                }
            )

    graph_data = {
        "domain": "digitaltwin",
        "schema_version": "1.0",
        "entities": list(entities.values()),
        "relationships": relationships,
    }
    output_path = Path(output_filepath)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(graph_data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Visualizer graph saved to {output_filepath}")


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


PRIMITIVE_TYPE_MAP = {
    "string": "string",
    "str": "string",
    "text": "string",
    "float": "float",
    "double": "double",
    "integer": "integer",
    "int": "integer",
    "number": "integer",
    "boolean": "boolean",
    "bool": "boolean",
    "datetime": "datetime",
    "date": "date",
}


def merge_ontologies(ontologies: Iterable[OntologySchema]) -> OntologySchema:
    merged_classes = {}
    merged_individuals = {}
    merged_object_properties = {}
    merged_data_properties = {}

    for extracted in ontologies:
        # Merge Classes (Deduplicate by sanitized name)
        for cls in extracted.classes:
            key = clean_identifier(cls.name)
            if not key:
                continue

            # Sanitise parent_class: prevent self-loops and redundant generic roots
            parent_key = clean_identifier(cls.parent_class) if cls.parent_class else None
            if parent_key and (parent_key == key or parent_key.lower() in {"thing", "owlthing"}):
                cls.parent_class = None

            if key not in merged_classes:
                merged_classes[key] = cls
            else:
                existing = merged_classes[key]
                if not existing.parent_class and cls.parent_class:
                    existing.parent_class = cls.parent_class
                if len(cls.description) > len(existing.description):
                    existing.description = cls.description

        # Merge Individuals (Deduplicate by sanitized name)
        for ind in extracted.individuals:
            key = clean_identifier(ind.name)
            if not key:
                continue
            if key not in merged_individuals:
                merged_individuals[key] = ind
            else:
                existing = merged_individuals[key]
                if not existing.instance_of and ind.instance_of:
                    existing.instance_of = ind.instance_of
                if len(ind.description) > len(existing.description):
                    existing.description = ind.description

        # Merge Properties (Deduplicate by sanitized name + domain)
        for prop in extracted.object_properties:
            if not prop.name or not prop.domain:
                continue

            # Check if range is actually a primitive datatype (e.g., Boolean, String, Integer)
            range_lower = prop.range.lower().strip() if prop.range else ""
            if range_lower in PRIMITIVE_TYPE_MAP:
                data_prop = DataProperty(
                    name=prop.name,
                    domain=prop.domain,
                    data_type=PRIMITIVE_TYPE_MAP[range_lower],
                    description=prop.description,
                )
                prop_key = f"{clean_identifier(data_prop.domain)}_{clean_identifier(data_prop.name)}"
                if prop_key not in merged_data_properties:
                    merged_data_properties[prop_key] = data_prop
                continue

            prop_key = f"{clean_identifier(prop.domain)}_{clean_identifier(prop.name)}"
            if prop_key not in merged_object_properties:
                merged_object_properties[prop_key] = prop

        for prop in extracted.data_properties:
            if not prop.name or not prop.domain:
                continue
            prop_key = f"{clean_identifier(prop.domain)}_{clean_identifier(prop.name)}"
            if prop_key not in merged_data_properties:
                merged_data_properties[prop_key] = prop

    return OntologySchema(
        classes=list(merged_classes.values()),
        individuals=list(merged_individuals.values()),
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
    parser.add_argument("output_filename", nargs="?", default=DEFAULT_GENERATED_ONTOLOGY_FILENAME)
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
    graph_output_path = output_path.with_name("graph.json")
    build_visualizer_graph(
        extracted=extracted_data,
        base_uri="http://example.org/digitaltwin#",
        output_filepath=str(graph_output_path),
    )


if __name__ == "__main__":
    main()
