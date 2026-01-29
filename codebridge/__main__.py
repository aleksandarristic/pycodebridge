"""Module entrypoint for running the bridge as `python -m codebridge`."""

import asyncio

from cmd.bridge import main


if __name__ == "__main__":
    asyncio.run(main())
