import os
import asyncio
from memory import connect, remember

DATA_FOLDER = "data"


async def main():
    await connect()

    for file_name in sorted(os.listdir(DATA_FOLDER)):
        path = os.path.join(DATA_FOLDER, file_name)
        with open(path, "r") as f:
            text = f.read()

        # Keep the source name so answers can say where a fact came from
        await remember("Source: " + file_name + "\n\n" + text)
        print("Loaded", file_name)

    print("Done. Try: python ask.py \"What depends on the Northwind walkthrough?\"")


asyncio.run(main())
