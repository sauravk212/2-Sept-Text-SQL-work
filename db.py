import sqlite3


def get_sample_rows(db_path, table_name, limit=5):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute(f'SELECT * FROM "{table_name}" LIMIT {limit}')
    rows = cursor.fetchall()

    conn.close()

    return rows
def get_schema(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    schema = {}

    # Get all tables
    cursor.execute("""
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
        AND name NOT LIKE 'sqlite_%';
    """)

    tables = cursor.fetchall()

    for (table_name,) in tables:

        # Get columns
        cursor.execute(f'PRAGMA table_info("{table_name}")')

        columns = cursor.fetchall()

        schema[table_name] = {"columns": [], "foreign_keys": []}

        for column in columns:

            schema[table_name]["columns"].append(
                {"name": column[1], "type": column[2]}
                # {"name": column[1], "type": column[2], "primary_key": bool(column[5])}
            )

        # Get foreign keys
        cursor.execute(f'PRAGMA foreign_key_list("{table_name}")')

        foreign_keys = cursor.fetchall()

        for fk in foreign_keys:

            schema[table_name]["foreign_keys"].append(
                {"column": fk[3], "references_table": fk[2], "references_column": fk[4]}
            )

    conn.close()

    return schema


def execute_sql(db_path, sql):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute(sql)

    result = cursor.fetchall()

    conn.close()

    return result


def format_schema(schema_data):

    tables = schema_data["table_names_original"]
    columns = schema_data["column_names_original"]
    column_types = schema_data["column_types"]
    primary_keys = schema_data["primary_keys"]
    foreign_keys = schema_data["foreign_keys"]

    output = []

    output.append("DATABASE SCHEMA\n")

    # -------------------------
    # Tables and columns
    # -------------------------

    for table_index, table_name in enumerate(tables):

        output.append(f"Table: {table_name}")

        output.append("Columns:")

        for column_index, (table_id, column_name) in enumerate(columns):

            if table_id == table_index:

                column_type = column_types[column_index]

                output.append(f"  - {column_name} ({column_type})")

        # Primary keys
        table_primary_keys = []

        for pk_index in primary_keys:

            table_id, column_name = columns[pk_index]

            if table_id == table_index:
                table_primary_keys.append(column_name)

        if table_primary_keys:

            output.append("Primary Key:")

            for pk in table_primary_keys:
                output.append(f"  - {pk}")

        output.append("")

    # -------------------------
    # Relationships
    # -------------------------

    output.append("Relationships:")
    # print("foreign_keys", foreign_keys)
    for source_column, target_column in foreign_keys:

        source_table_id, source_column_name = columns[source_column]

        target_table_id, target_column_name = columns[target_column]

        source_table = tables[source_table_id]
        target_table = tables[target_table_id]

        output.append(
            f"  - {source_table}.{source_column_name} "
            f"→ {target_table}.{target_column_name}"
        )

    return "\n".join(output)
