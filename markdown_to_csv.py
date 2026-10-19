import argparse
import re

import pandas as pd
from pathlib import Path


def markdown_to_ndtp_csv(md_filepath: str, output_csv_path: str):
    with open(md_filepath, "r", encoding="utf-8") as f:
        md_text = f.read()
    sections = re.split(r"\n(?=#{1,3}\s)", md_text)

    data = []

    for section in sections:
        section = section.strip()
        if not section:
            continue

        lines = section.split("\n")
        header_line = lines[0]
        title = re.sub(r"^#{1,3}\s*", "", header_line).strip()
        description = "\n".join(lines[1:]).strip() if len(lines) > 1 else title

        if title:
            data.append({"Title": title, "Description": description})

    df = pd.DataFrame(data)
    df.to_csv(output_csv_path, index=False, encoding="utf-8")
    print(
        f"Successfully converted '{md_filepath}' to '{output_csv_path}' with {len(df)} sections."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Extract an ontology from a file or folder into one Turtle file."
    )
    parser.add_argument("input_path", type=Path, help="Input file or folder")
    parser.add_argument("output_filename", nargs="?", default="base_ontology.ttl")
    args = parser.parse_args()

    if not args.input_path.exists():
        parser.error(f"The path {args.input_path} does not exist.")

    markdown_to_ndtp_csv(args.input_path, args.output_filename)
