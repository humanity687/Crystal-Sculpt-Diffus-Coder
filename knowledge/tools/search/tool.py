# Copyright (C) 2026 humanity687
# This file is part of FranxAgent.
# FranxAgent is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or any later version.
# FranxAgent is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Affero General Public License for more details.
# You should have received a copy of the GNU Affero General Public License along with FranxAgent.  If not, see <https://www.gnu.org/licenses/>.

"""
Network Search Tool
Use DuckDuckGo search engine to search internet information
"""

import concurrent.futures
from ddgs import DDGS

_SEARCH_TIMEOUT = 15  # seconds
_MAX_QUERY_LENGTH = 500


def execute(query: str, max_results: int = 5) -> str:
    """
    Search information on the internet

    Args:
        query: Search keyword
        max_results: Maximum number of returned results (default 5)

    Returns:
        Search result list in Markdown format
    """
    if len(query) > _MAX_QUERY_LENGTH:
        query = query[:_MAX_QUERY_LENGTH]

    def _do_search():
        try:
            with DDGS() as ddgs:
                return list(ddgs.text(query, max_results=max_results))
        except Exception as e:
            return f"Search failed: {str(e)}"

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_do_search)
            results = future.result(timeout=_SEARCH_TIMEOUT)
    except concurrent.futures.TimeoutError:
        return f"Search timed out after {_SEARCH_TIMEOUT}s for query '{query[:100]}...'"

    if isinstance(results, str):
        return results

    if not results:
        return f"No search results found for '{query}'."

    output = f"🔍 Search results about '{query}':\n\n"
    for i, r in enumerate(results, 1):
        title = r.get("title", "No title")
        href = r.get("href", "")
        body = r.get("body", "")[:1000]
        output += f"{i}. **{title}**\n"
        output += f"   {body}...\n"
        output += f"   🔗 {href}\n\n"

    return output
