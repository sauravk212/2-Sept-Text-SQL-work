import re
import json
from constants import DATABASE_NAME
from schema_store_retrival_2 import retrieve_tables


def normalize_retrieved_tables(retrieved_tables):
    """
    Convert retrieved table output into a clean set of table names.

    Handles cases like:
        "player"
        ["player"]
        ["park", "team"]
        []
    """

    tables = set()

    def add_table(value):

        if isinstance(value, list):
            for item in value:
                add_table(item)

        elif isinstance(value, str):

            value = value.strip()

            if not value:
                return

            # Handle string representation of a list:
            # "['park', 'team']"
            if value.startswith("[") and value.endswith("]"):

                try:
                    parsed = json.loads(value.replace("'", '"'))
                    add_table(parsed)
                    return

                except Exception:
                    pass

            tables.add(value.lower())

    for table in retrieved_tables:
        add_table(table)

    return tables


def extract_tables_from_sql(sql):
    """
    Extract table names appearing after FROM or JOIN.
    Handles subqueries, JOINs, UNION, INTERSECT, etc.
    """

    pattern = r"""
        \bFROM\s+([A-Za-z_][A-Za-z0-9_]*)
        |
        \bJOIN\s+([A-Za-z_][A-Za-z0-9_]*)
    """

    matches = re.findall(pattern, sql, flags=re.IGNORECASE | re.VERBOSE)

    tables = set()

    for match in matches:
        table = match[0] or match[1]
        tables.add(table.lower())

    return tables

if __name__ == "__main__":
    with open("train_spider.json", "r", encoding="utf-8") as f:
        spider_data = json.load(f)

    database_data = [item for item in spider_data if item["db_id"] == DATABASE_NAME]

    print(f"Found {len(database_data)} {DATABASE_NAME} examples")

    # =========================
    # EVALUATION
    # =========================

    TOP_K = 5

    passed = 0
    failed = 0

    failures = []


    for item in database_data:

        question = item["question"]
        gold_sql = item["query"]

        # Expected tables from gold SQL
        expected_tables = extract_tables_from_sql(gold_sql)

        # Retrieved tables
        retrieved_tables = retrieve_tables(query=question, top_k=TOP_K)
        retrieved_tables = normalize_retrieved_tables(retrieved_tables)

        # retrieved_tables = {table.lower() for table in retrieved_tables}

        # Check whether ALL expected tables were retrieved
        if expected_tables.issubset(retrieved_tables):

            passed += 1

        else:

            failed += 1

            failures.append(
                {
                    "question": question,
                    "expected": sorted(expected_tables),
                    "retrieved": sorted(retrieved_tables),
                    "sql": gold_sql,
                }
            )


    # =========================
    # FINAL RESULT
    # =========================

    total = len(database_data)

    print("\n" + "=" * 50)
    print("TABLE RETRIEVAL EVALUATION")
    print("=" * 50)

    print(f"Total questions : {total}")
    print(f"Passed          : {passed}")
    print(f"Failed          : {failed}")

    print(f"Pass rate       : {passed / total * 100:.2f}%")
    print(f"Fail rate       : {failed / total * 100:.2f}%")
    with open(f"{DATABASE_NAME}_retrieval_failures.json", "w", encoding="utf-8") as f:
        json.dump(failures, f, indent=2)
