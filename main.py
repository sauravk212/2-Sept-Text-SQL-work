import ast
import json
import re

from functools import lru_cache
from typing import Annotated, TypedDict
from table_extraction_3 import normalize_retrieved_tables
from dotenv import load_dotenv

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from constants import *
from db import execute_sql
from schema_store_retrival_2 import retrieve_tables

load_dotenv()


# ============================================================
# CONFIG (falls back if not defined in constants.py)
# ============================================================

MAX_RETRIES = globals().get("MAX_RETRIES", 2)
DEBUG_FORCE_BAD_SQL = globals().get("DEBUG_FORCE_BAD_SQL", False)
TOP_K_TABLES = globals().get("TOP_K_TABLES", 5)
MAX_QUESTIONS = globals().get("MAX_QUESTIONS", 50)

REPAIR_PROMPT = (
    "The previous query failed.\n\n"
    "SQL:\n{sql}\n\n"
    "Database error:\n{error}\n\n"
    "Rewrite the query so it runs against the schema above. "
    "Return only the corrected SQL, no explanation and no code fences."
)


# ============================================================
# STATE
# ============================================================


class State(TypedDict):

    question: str
    schema: str
    messages: Annotated[list, add_messages]
    sql: str
    result: str
    error: str
    retries: int


# ============================================================
# LLM
# ============================================================

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)


# ============================================================
# HELPERS
# ============================================================

FENCE_OPEN = re.compile(r"^\s*```(?:sql)?\s*", re.IGNORECASE)
FENCE_CLOSE = re.compile(r"\s*```\s*$")
TABLE_NAME = re.compile(r"table:\s*(\w+)", re.IGNORECASE)


def strip_code_fences(text: str) -> str:
    """Remove ```sql ... ``` wrappers the model sometimes adds."""
    text = FENCE_OPEN.sub("", text.strip())
    text = FENCE_CLOSE.sub("", text)
    return text.strip()


@lru_cache(maxsize=8)
def load_table_blocks(schema_file: str):
    """Parse schema.txt once into {table_name: block} instead of on every call."""
    with open(schema_file, "r", encoding="utf-8") as f:
        schema_text = f.read()

    blocks = {}

    for block in re.split(r"\n(?=table:\s)", schema_text):
        match = TABLE_NAME.search(block)
        if match:
            blocks[match.group(1).lower()] = block.strip()

    return blocks


def get_relevant_schema(schema_file, retrieved_tables):
    """Map retrieved table names back to their blocks in schema.txt."""
    blocks = load_table_blocks(schema_file)

    wanted = {str(table).lower().strip() for table in retrieved_tables}

    relevant = [block for name, block in blocks.items() if name in wanted]

    # Retrieval miss: better to send everything than an empty schema.
    if not relevant:
        print("WARNING: no retrieved table matched schema.txt, using full schema")
        relevant = list(blocks.values())

    return "\n\n".join(relevant)


# ============================================================
# NODES
# ============================================================


def retrieve_schema_node(state: State):

    question = state["question"]

    retrieved_tables = retrieve_tables(query=question, top_k=TOP_K_TABLES)
    retrieved_tables = normalize_retrieved_tables(retrieved_tables)
    print("\nRETRIEVED TABLES:")
    print(retrieved_tables)

    relevant_schema = get_relevant_schema(
        f"{DATABASE_NAME}_schema.txt",
        retrieved_tables,
    )

    # print("\nRETRIEVED SCHEMA:")
    # print(relevant_schema)

    return {
        "schema": relevant_schema,
        "messages": [
            SystemMessage(content=SYSTEM_PROMPT.format(schema=relevant_schema)),
            HumanMessage(content=question),
        ],
    }


def generate_sql_node(state: State):
    """Generates the first query and every repaired query after it."""

    if DEBUG_FORCE_BAD_SQL and state["retries"] == 0 and not state.get("error"):
        bad = AIMessage(content="SELECT wrong_column FROM wrong_table;")
        return {"sql": "SELECT wrong_column FROM wrong_table;", "messages": [bad]}

    new_messages = []

    # Only true on a retry: feed the failure back so the model can repair it.
    if state.get("error"):
        new_messages.append(
            HumanMessage(
                content=REPAIR_PROMPT.format(
                    sql=state.get("sql", ""),
                    error=state["error"],
                )
            )
        )

    response = llm.invoke(state["messages"] + new_messages)

    new_messages.append(response)

    sql = strip_code_fences(response.content)

    print("\nGENERATED SQL:")
    print(sql)

    # print("\nEXPECTED SQL:")
    # print(expected_sql)

    return {
        "sql": sql,
        "messages": new_messages,
        "retries": state["retries"] + (1 if state.get("error") else 0),
    }


def execute_sql_node(state: State):

    try:
        result = execute_sql(DB_PATH, state["sql"])
        return {"result": str(result), "error": ""}

    except Exception as e:
        print(f"\nSQL ERROR: {e}")
        return {"result": "", "error": str(e)}


def route_after_execute(state: State):

    if not state.get("error"):
        return END

    if state["retries"] >= MAX_RETRIES:
        return END

    return "generate_sql"


# ============================================================
# LANGGRAPH
# ============================================================

graph_builder = StateGraph(State)

graph_builder.add_node("retrieve_schema", retrieve_schema_node)
graph_builder.add_node("generate_sql", generate_sql_node)
graph_builder.add_node("execute_sql", execute_sql_node)

graph_builder.add_edge(START, "retrieve_schema")
graph_builder.add_edge("retrieve_schema", "generate_sql")
graph_builder.add_edge("generate_sql", "execute_sql")

graph_builder.add_conditional_edges(
    "execute_sql",
    route_after_execute,
    {"generate_sql": "generate_sql", END: END},
)

graph = graph_builder.compile()


def safe_parse_generated_rows(raw_value):
    if raw_value is None:
        return []
    value = str(raw_value).strip()
    if not value or value.lower() in {"null", "none"}:
        return []
    try:
        parsed = ast.literal_eval(value)
        if isinstance(parsed, list):
            return parsed
        return [parsed]
    except (ValueError, SyntaxError):
        print("Bad generated result:", repr(raw_value))
        return []


def run_question(question: str):
    return graph.invoke(
        {
            "question": question,
            "schema": "",
            "messages": [],
            "sql": "",
            "result": "",
            "error": "",
            "retries": 0,
        }
    )


# ============================================================
# EVALUATION
# ============================================================

if __name__ == "__main__":

    try:
        graph.get_graph().draw_png("langgraph.png")
    except Exception as error:
        print(f"(skipped graph render: {error})")

    with open("train_spider.json", "r", encoding="utf-8") as file:
        spider_data = json.load(file)

    questions = [item for item in spider_data if item["db_id"] == DATABASE_NAME]

    if MAX_QUESTIONS:
        questions = questions[:MAX_QUESTIONS]

    print(f"Number of {DATABASE_NAME} questions: {len(questions)}")

    correct_count = 0
    failed_count = 0
    failed_questions = []

    for index, item in enumerate(questions, start=1):

        question = item["question"]
        expected_sql = item["query"]

        print("\n" + "=" * 70)
        print(f"QUESTION {index}/{len(questions)}")
        print("=" * 70)
        print(question)

        generated_sql = ""

        try:
            result = run_question(question)

            generated_sql = result.get("sql", "")
            generated_result = result.get("result", "")
            error = result.get("error", "")

            expected_result = execute_sql(DB_PATH, expected_sql)

            print("\nGENERATED RESULT:")
            print(generated_result)

            print("\nEXPECTED RESULT:")
            print(expected_result)

            if error:
                failed_count += 1
                failed_questions.append(
                    {
                        "question": question,
                        "generated_sql": generated_sql,
                        "expected_sql": expected_sql,
                        "retries": result.get("retries", 0),
                        "error": error,
                    }
                )
                print("\nSQL ERROR (gave up after retries)")
                continue

            try:
                generated_rows = safe_parse_generated_rows(generated_result)
            except Exception:
                failed_count += 1
                failed_questions.append(
                    {
                        "question": question,
                        "generated_sql": generated_sql,
                        "expected_sql": expected_sql,
                        "generated_result": generated_result,
                        "expected_result": expected_result,
                        "error": "Could not parse generated result",
                    }
                )
                print("\nRESULT PARSING ERROR")
                continue

            if generated_rows == expected_result:
                correct_count += 1
                print("\nCORRECT")
            else:
                failed_count += 1
                failed_questions.append(
                    {
                        "question": question,
                        "generated_sql": generated_sql,
                        "expected_sql": expected_sql,
                        "generated_result": generated_rows,
                        "expected_result": expected_result,
                    }
                )
                print("\nINCORRECT")

        except Exception as error:
            failed_count += 1
            failed_questions.append(
                {
                    "question": question,
                    "generated_sql": generated_sql,
                    "expected_sql": expected_sql,
                    "error": str(error),
                }
            )
            print("\nERROR:")
            print(error)

    total = len(questions)
    accuracy = correct_count / total * 100 if total else 0

    print("\n" + "=" * 70)
    print("TEXT-TO-SQL EVALUATION")
    print("=" * 70)
    print(f"Total questions : {total}")
    print(f"Correct         : {correct_count}")
    print(f"Failed          : {failed_count}")
    print(f"Accuracy        : {accuracy:.2f}%")

    output_file = f"failed_questions_{DATABASE_NAME}.json"

    with open(output_file, "w", encoding="utf-8") as file:
        json.dump(failed_questions, file, indent=4, default=str)

    print(f"\nSaved failed questions to {output_file}")
