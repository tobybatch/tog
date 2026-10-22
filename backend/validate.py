from rdflib import Graph


def main():
    if len(sys.argv) < 2:
        print("Usage: python main.py <filename>")
        return

    filename = sys.argv[1]

    g = Graph()
    g.parse(filename, format="turtle")
    print(f"Base ontology loaded successfully with {len(g)} triples.")

if __name__ == "__main__":
    main()
