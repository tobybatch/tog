# TOG

Toby's Ontology Generator 

## Install dependencies

```bash
uv sync
```

## Run the web app

Install the JavaScript dependencies alongside the Python dependencies:

```bash
npm install
npm install --prefix frontend
npm run dev
```

Open `http://localhost:5173/`. Vite serves the frontend and proxies `/api`
requests to Flask on port 5000. Flask's page routes redirect to Vite when
running in debug mode. Port 5173 must be available.

To serve the frontend directly from Flask without Vite:

```bash
npm run build --prefix frontend
uv run flask --app backend run --port 5000
```

The build writes the frontend into `backend/static/`. Open
`http://localhost:5000/`; Flask serves the built page and assets. If the build
is missing, Flask returns a setup page with HTTP status 503.

## Run the generator

Put source documents in a directory and run the generator with the folder as input. The Turtle output file is optional, and defaults to `generated-ontologies/generated_ontology.ttl`. The generator also writes a visualizer-compatible `graph.json` beside it:

```bash
uv run main.py <input_file_or_folder> [output_file]
uv run validate.py <input_file>
```

The generator uses a local Ollama instance at `http://localhost:11434` by default
and the `llama3.1` model. Ensure Ollama is running and the model is available
(`ollama pull llama3.1`). Override these settings with `OLLAMA_BASE_URL` and
`OLLAMA_MODEL` if needed.

e.g. Process all documents in `inputs/` into one ontology:

```bash
uv run main.py inputs generated_ontology.ttl
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
  - The output defaults to `base_ontology.ttl` and replaces any existing output file
