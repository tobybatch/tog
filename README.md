# TOG

Toby's Ontology Generator 

## Install dependencies

```bash
uv sync
```

## Run the generator

Put source documents in a directory and run the generator with the folder as input. The output file is optional, and defaults to `base_ontology.ttl`:

```bash
uv run main.py <input_file_or_folder> [output_file]
uv run validate.py <input_file>
```

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
  - Writes a single Turtle file.
  - Classes are deduplicated by sanitised name
  - Properties are sanitised name and domain
  - The output defaults to `base_ontology.ttl` and replaces any existing output file
