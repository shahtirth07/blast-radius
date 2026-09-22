import sys
import asyncio
from memory import connect, recall


async def main():
    question = sys.argv[1]
    await connect()
    answer = await recall(question)
    print(answer)


asyncio.run(main())
