from app.connectors.registry import CONNECTORS


class SearchManager:

    async def search(self):

        print("Registered Connectors:")

        for name in CONNECTORS:

            print(name)