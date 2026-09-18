import asyncio


async def minimal_test():
    print("1. Внутри асинхронной функции.")
    await asyncio.sleep(0.1)  # Это простейшая await-операция
    print("3. Асинхронная операция успешно завершена!")

if __name__ == "__main__":
    print("0. Запускаем тест...")
    asyncio.run(minimal_test())
    print("4. Тест окончен.")