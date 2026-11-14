# Clickwise index for DeepSeek Harness

A self-published plugin index and data-only bundle from Clickwise. The `clickwise-mcp` bundle connects DSH to the public Clickwise MCP server for affiliate programs, deals, and tracked links, without an API key.

Links returned by these tools are affiliate links: if someone buys through them, the publisher who shares them may receive a commission from the store.

Future index URL: https://softdevfz.github.io/dsh-plugin-index/index.json

After publication, enable **Plugins → Experimental plugins → Custom plugin indexes**, then use **Discover → Add index source → URL** with the URL above. Select `clickwise-mcp` and version `0.1.0`, review its Git source, confirm installation, and enable the installed bundle.

`index.json` lives only at the repository root. A future GitHub Pages publication from the root (`/`) can serve the URL above directly, without a duplicate under `docs/`. This local repository does not configure or publish Pages.

The bundle contains configuration and display text only. `tools/check_index.py` is a repository maintenance tool outside the bundle; run `python3 tools/check_index.py` for offline checks of the index and its pinned local Git manifest. It is a purpose-built check for this Git index, with conservative npm-name, URL, and SemVer syntax checks; it does not replace the DSH format validator or runtime installation checks.

Publisher: Clickwise. Contact: affiliates@clickwise.net.

License: MIT; see LICENSE.
