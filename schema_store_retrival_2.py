import re
import uuid
from qdrant_client import QdrantClient
from qdrant_client import models
from qdrant_client.models import (
    PointStruct,
    VectorParams,
    Distance,
    SparseVectorParams,
    SparseVector,
    Modifier,
)
from openai import OpenAI
from dotenv import load_dotenv
from constants import *
from fastembed import SparseTextEmbedding

load_dotenv()

qdrant = QdrantClient(url=QDRANT_URL)
openai_client = OpenAI()
bm25_model = SparseTextEmbedding(model_name="Qdrant/bm25")


with open(f"{SCHEMA_FILE}.txt", "r", encoding="utf-8") as f:
    schema_text = f.read()


def insert_payload():
    tables = re.split(r"\n(?=table:\s)", schema_text)
    print(f"Found {len(tables)} tables")

    if not qdrant.collection_exists(COLLECTION_NAME):

        qdrant.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config={"dense": VectorParams(size=1536, distance=Distance.COSINE)},
            sparse_vectors_config={"bm25": SparseVectorParams(modifier=Modifier.IDF)},
        )
        print("Collection created")

    else:
        print("Collection already exists")

    points = []

    for table_block in tables:

        table_match = re.search(r"table:\s*(\w+)", table_block)
        reference_table_match = re.search(
            r"references_table:\s*(\[[^\n]*\])", table_block
        )
        if not table_match:
            continue

        table_name = table_match.group(1)

        text = table_block.strip()

        max_chars = 4000

        chunks = [text[i : i + max_chars] for i in range(0, len(text), max_chars)]

        print(f"{table_name}: {len(chunks)} chunk(s)")

        dense_response = openai_client.embeddings.create(
            model=EMBEDDING_MODEL, input=chunks
        )

        dense_embeddings = [item.embedding for item in dense_response.data]

        sparse_embeddings = list(bm25_model.embed(chunks))
        # print("sparse_embeddings", s  parse_embeddings)

        for chunk_index, (chunk, dense_embedding, sparse_embedding) in enumerate(
            zip(chunks, dense_embeddings, sparse_embeddings)
        ):

            point = PointStruct(
                id=str(uuid.uuid4()),
                vector={
                    "dense": dense_embedding,
                    "bm25": SparseVector(
                        indices=sparse_embedding.indices.tolist(),
                        values=sparse_embedding.values.tolist(),
                    ),
                },
                payload={
                    "database_name": DATABASE_NAME,
                    "table_name": table_name,
                    "references_table": (
                        reference_table_match.group(1)
                        if reference_table_match
                        else None
                    ),
                    "chunk_index": chunk_index,
                    "chunk_id": f"{table_name}_{chunk_index}",
                    "text": chunk,
                },
            )

            points.append(point)

    # INSERT POINTS INTO QDRANT
    qdrant.upsert(collection_name=COLLECTION_NAME, points=points)
    print(f"\nInserted {len(points)} chunks " f"into '{COLLECTION_NAME}'")


def retrieve_tables(query, top_k=10):

    # =========================
    # DENSE QUERY EMBEDDING
    # =========================

    dense_response = openai_client.embeddings.create(model=EMBEDDING_MODEL, input=query)

    dense_vector = dense_response.data[0].embedding

    # =========================
    # BM25 QUERY EMBEDDING
    # =========================

    sparse_embedding = list(bm25_model.embed([query]))[0]

    sparse_vector = SparseVector(
        indices=sparse_embedding.indices.tolist(),
        values=sparse_embedding.values.tolist(),
    )
    # qdrant.scroll(
    #     collection_name=COLLECTION_NAME,
    #     scroll_filter=models.Filter(
    #         should=[
    #             models.FieldCondition(
    #                 key="database_name", match=models.MatchValue(value=DATABASE_NAME)
    #             ),
    #         ],
    #     ),
    # )
    # return results
    results = qdrant.query_points(
        collection_name=COLLECTION_NAME,
        prefetch=[
            models.Prefetch(
                # The same query, embedded for the dense retriever.
                query=dense_vector,
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="database_name",
                            match=models.MatchValue(value=DATABASE_NAME),
                        )
                    ]
                ),
                using="dense",
                limit=100,
            ),
            models.Prefetch(
                # The same query, embedded for the sparse retriever.
                query=sparse_vector,
                using="bm25",
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="database_name",
                            match=models.MatchValue(value=DATABASE_NAME),
                        )
                    ]
                ),
                limit=100,
            ),
        ],
        query=models.FusionQuery(fusion=models.Fusion.RRF),
        limit=top_k,
        with_payload=True,
    )

    retrieved_tables = []

    for result in results.points:

        table_name = result.payload["table_name"]
        references_table = result.payload.get("references_table", None)

        if table_name not in retrieved_tables:
            retrieved_tables.append(table_name)
        if references_table and references_table not in retrieved_tables:
            retrieved_tables.append(references_table)
        if len(retrieved_tables) >= top_k:
            break

    return set(retrieved_tables)
    # return results


if __name__ == "__main__":
    insert_payload()
