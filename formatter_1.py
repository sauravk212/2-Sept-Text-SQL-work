import json
from pathlib import Path
from constants import *
from db import get_sample_rows, get_schema


def create_schema_file():
    with open(f"{SCHEMA_FILE}.json", "w", encoding="utf-8") as file:
        json.dump(get_schema(DB_PATH), file, indent=2)

    print("Schema saved to schema.json")


def format_table(table_name, table_definition):

    columns = table_definition.get("columns", [])
    foreign_keys = table_definition.get("foreign_keys", [])
    references_table = [foreign_key["references_table"] for foreign_key in foreign_keys]
    print("references_table", references_table)
    primary_keys = set(table_definition.get("primary_keys", []))

    foreign_key_map = {
        item["column"]: f'{item["references_table"]}.{item["references_column"]}'
        for item in foreign_keys
    }

    lines = [
        f"table: {table_name}",
        f"references_table: {references_table}",
        "columns:",
    ]

    for column in columns:
        name = column["name"]
        data_type = column["type"]
        constraints = []

        if name in primary_keys:
            constraints.append("PK")

        if name in foreign_key_map:
            constraints.append(f"FK -> {foreign_key_map[name]}")

        suffix = f", {', '.join(constraints)}" if constraints else ""
        lines.append(f"  - {name} ({data_type}{suffix})")

    sample_rows = get_sample_rows(DB_PATH, table_name, limit=5)
    lines.append("sample_rows:")

    if sample_rows:
        for row in sample_rows:
            lines.append(f"  - {json.dumps(row, separators=(', ', ': '))}")
    else:
        lines.append("  []")

    return "\n".join(lines)


def main():

    create_schema_file()

    INPUT_FILE = Path(f"{DATABASE_NAME}_schema.json")
    OUTPUT_FILE = Path(f"{DATABASE_NAME}_schema.txt")

    with INPUT_FILE.open("r", encoding="utf-8") as file:
        schema = json.load(file)

    output = []

    for table_name, table_definition in schema.items():
        output.append(format_table(table_name, table_definition))

    OUTPUT_FILE.write_text(
        "\n\n".join(output) + "\n",
        encoding="utf-8",
    )

    print(f"Created {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
