# TOG

Toby's Ontology Generator 

## Install dependencies

```bash
uv sync
```

## Run with Docker

Build and start the app with:

```bash
docker build -t tog .
docker run --rm \
  -v ./inputs/single:/app/inputs \
  -v ./outputs:/app/outputs \
  --add-host host.docker.internal:host-gateway \
  -e OLLAMA_BASE_URL=http://host.docker.internal:11434 \
  tog inputs outputs/generated-ontologies/generated_ontology.ttl
```

## Run Native

```bash
uv run backend/main.py <input_file_or_folder> [output_file]
uv run backend/validate.py <input_file>
```

## Notes

The generator uses a local Ollama instance at `http://localhost:11434` by default
and the `llama3.1` model. Ensure Ollama is running and the model is available
(`ollama pull llama3.1`). Override these settings with `OLLAMA_BASE_URL` and
`OLLAMA_MODEL` if needed.

```bash
brew install ollama
ollama pull llama3.1
ollama serve
```

e.g. Process all documents in `inputs/` into one ontology:

```bash
uv run main.py inputs/multiple outputs/generated-ontologies/generated_ontology.ttl
```

## Notes

  - Supports  `.md`, `.txt`, and `.pdf`
  - Does not recurse into sub folders
  - Unsupported files are reported and skipped
  - The output file is excluded if it is inside the input folder.
  - Documents are split into chunks, and classes, object properties, and data properties are merged across all chunks
  - Writes a Turtle ontology and a visualizer-compatible `graph.json` in the output directory. The JSON graph contains class and individual nodes, hierarchy and property relationships, and datatype properties on their domain classes.
  - Classes are deduplicated by sanitised name
  - Properties are sanitised name and domain
  - The output defaults to `outputs/generated-ontologies/generated_ontology.ttl` and replaces any existing output file
