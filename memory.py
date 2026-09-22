import os
import cognee
from dotenv import load_dotenv

load_dotenv()

DATASET = os.getenv("COGNEE_DATASET", "blast_radius")


async def connect():
    url = os.getenv("COGNEE_URL")
    api_key = os.getenv("COGNEE_API_KEY")
    if url and api_key:
        await cognee.serve(url=url, api_key=api_key)
        print("Connected to Cognee Cloud")
    else:
        print("No Cloud key found, using local Cognee")


async def remember(text):
    await cognee.remember(text, dataset_name=DATASET)


async def recall(question):
    results = await cognee.recall(question, datasets=[DATASET])
    lines = []
    for result in results:
        lines.append(str(result))
    return "\n".join(lines)
